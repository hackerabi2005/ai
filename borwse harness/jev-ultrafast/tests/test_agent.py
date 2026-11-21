"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import json
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import model
from jev_ultrafast.browser import StalePage, browser_operation, fingerprint


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []
    p = page()
    p["actions"].append({"id": "e4", "kind": "fill", "label": "Filter", "role": "textbox", "value": "", "node": 30})

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1", "3"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(0, {
        "id": "toggle", "kind": "click", "label": "Free cancellation", "node": 30,
        "role": "checkbox", "checked": "true", "selected": False,
    })

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    p = page()
    a.state = {
        "browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p)),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "history": [],
        "decisions": [],
        "status": "predicted",
        "started_at": time.perf_counter(),
        "record": False,
        "text_calls": [],
    }
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    for _ in range(5):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import jev_ultrafast.browser as browser

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation({"operation": "act", "session": "test", "action": {
            "id": "e1", "kind": "select", "node": 1, "value": "Design",
        }})
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize("changed", ["Departure", "Where from?", "Where to?", "year"])
def test_flight_verification_rejects_wrong_trip(changed):
    from examples.flights import verify

    actual = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }
    assert verify(actual)["passed"]
    if changed == "year":
        actual["text"] = actual["text"].replace("2026", "2027")
    else:
        next(a for a in actual["actions"] if a["label"] == changed)["value"] = "wrong"
    assert not verify(actual)["passed"]


@pytest.mark.parametrize(
    "content", ["Thinking: Zurich", '{"text":null}', '{"text":"Zurich","extra":true}', '{"text":123}']
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()


def test_choose_uses_experiential_endpoint_and_key(monkeypatch):
    calls = []

    def post(url, key, body):
        calls.append((url, key, body))
        return {
            "model": body["model"],
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "WAIT"),
            },
        }

    monkeypatch.setenv("EXPERIENTIAL_API_KEY", "xpl_test")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("EXPERIENTIAL_MODEL", raising=False)
    monkeypatch.delenv("TYPESAFE_MODEL", raising=False)
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert d["choice"] == "wait"
    assert calls[0][0] == "https://api.experientiallabs.ai/v1/systemone"
    assert calls[0][1] == "xpl_test"
    assert calls[0][2]["model"] == "jev-latest"


def test_missing_jev_credential_raises_clear_error(monkeypatch):
    monkeypatch.delenv("EXPERIENTIAL_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="EXPERIENTIAL_API_KEY"):
        model.choose(page(), "Find a book", [])


def test_field_text_defaults_to_nvidia_nemotron_without_thinking(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "nvapi_test")
    monkeypatch.delenv("TEXT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("TEXT_MODEL", raising=False)
    monkeypatch.delenv("TEXT_MODEL_REASONING", raising=False)
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    value, meta = model.field_text({"goal": "Fly from Zurich"})
    assert value == "Zurich"
    assert meta["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    url, key, body = post.call_args.args
    assert url == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert key == "nvapi_test"
    assert body["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning" not in body


def test_single_target_omits_one_choice_question(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "jev-latest",
            "answers": {"operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT")},
        }

    monkeypatch.setenv("EXPERIENTIAL_API_KEY", "xpl_test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert "type_text_target" not in calls[0]["questions"]
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert d["probabilities"] == {"e1": 1.0}


def test_over_64_targets_chunked_into_valid_choice_heads(monkeypatch):
    p = {
        "url": "https://example.test/",
        "title": "Many",
        "text": "Many",
        "scroll": {"y": 0},
        "actions": [
            {"id": f"e{i}", "kind": "click", "label": f"Item {i}", "role": "button", "value": "", "node": i}
            for i in range(1, 71)
        ],
    }
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        q = body["questions"]
        return {
            "model": "jev-latest",
            "answers": {
                "operation": choice(q["operation"]["criteria"], "CLICK"),
                "click_target_1": choice(q["click_target_1"]["criteria"], "NONE"),
                "click_target_2": choice(q["click_target_2"]["criteria"], "68"),
            },
        }

    monkeypatch.setenv("EXPERIENTIAL_API_KEY", "xpl_test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Pick item 68", [])
    q = calls[0]["questions"]
    assert all(2 <= len(head["criteria"]) <= 64 for head in q.values())
    assert set(q) == {"operation", "click_target_1", "click_target_2"}
    assert d["target"] == "68" and d["choice"] == "e68"


def test_hover_reveal_wakes_video_controls_before_observe_and_click(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp_calls = []

    def fake_cdp(method, **params):
        cdp_calls.append((method, params))
        if method == "Runtime.evaluate":
            return {"result": {"value": [280, 220]}}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "browser_operation", Mock(side_effect=[p, {"executed": "e3"}]))
    monkeypatch.setattr(browser.time, "sleep", lambda _s: None)

    b = browser.Browser.__new__(browser.Browser)
    b.session = "sess-1"
    b.fresh = Mock(return_value=True)

    observed = b.observe(screenshot=False)
    assert observed["fingerprint"] == p["fingerprint"]
    assert (
        "Input.dispatchMouseEvent",
        {"session_id": "sess-1", "type": "mouseMoved", "x": 280, "y": 220, "pointerType": "mouse"},
    ) in cdp_calls

    cdp_calls.clear()
    b.act(p["actions"][2], p)
    assert (
        "Input.dispatchMouseEvent",
        {"session_id": "sess-1", "type": "mouseMoved", "x": 281, "y": 220, "pointerType": "mouse"},
    ) in cdp_calls


def test_hover_reveal_skips_mouse_move_when_no_video_or_menu_open(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp_calls = []

    def fake_cdp(method, **params):
        cdp_calls.append((method, params))
        return {"result": {"value": None}}

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "browser_operation", Mock(return_value=p))

    b = browser.Browser.__new__(browser.Browser)
    b.session = "sess-2"
    b.observe(screenshot=False)
    assert all(method == "Runtime.evaluate" for method, _ in cdp_calls)


def test_hover_skips_when_controls_visible_or_menu_delta_opened(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp_calls = []
    states = iter([
        {"hover": None, "menuOpen": False, "controls": 4},  # observe 1 -> already visible -> no mouseMove
        {"hover": None, "menuOpen": False, "controls": 3},  # act() wake -> 3 controls before click
        {"hover": None, "menuOpen": False, "controls": 7},  # observe 2 -> count grew after click -> menuOpen=True
    ])

    def fake_cdp(method, **params):
        cdp_calls.append((method, params))
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if "new Promise" in expr:
                return {"result": {"value": None}}
            return {"result": {"value": next(states)}}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "browser_operation", Mock(return_value=p))
    monkeypatch.setattr(browser.time, "sleep", lambda _s: None)

    b = browser.Browser.__new__(browser.Browser)
    b.session = "sess-3"
    b.fresh = Mock(return_value=True)
    b.observe(screenshot=False)
    assert not any(m == "Input.dispatchMouseEvent" for m, _ in cdp_calls)

    b.act(p["actions"][2], p)
    assert b._last_click_was_player is True
    assert b._player_menu_open is False

    b.observe(screenshot=False)
    assert b._player_menu_open is True


def test_cross_origin_iframe_snapshot_and_offset_click(monkeypatch):
    import jev_ultrafast.browser as browser

    top_page = page()
    top_page["iframes"] = [
        {
            "src": "https://player.example/embed",
            "name": "vid",
            "id": "p",
            "rect": {"x": 100.0, "y": 50.0, "w": 600.0, "h": 340.0},
        }
    ]
    frame_page = {
        "url": "https://player.example/embed",
        "title": "Player",
        "text": "Embed Play",
        "scroll": {"y": 0, "height": 340},
        "page_key": ["k2"],
        "guards": {"7": ["g7"]},
        "actions": [
            {
                "id": "e1",
                "kind": "click",
                "role": "button",
                "label": "Play embed",
                "value": "",
                "node": 7,
                "rect": {"x": 20, "y": 30, "w": 40, "h": 20},
            },
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }

    calls = []

    def fake_cdp(method, session_id=None, **params):
        calls.append((method, session_id, params))
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if session_id == "oo-sess":
                if "c.pageKey()" in expr:
                    return {"result": {"value": [["k2"], ["g7"]]}}
                if "const e=window.__jevFast" in expr:
                    return {"result": {"value": {"x": 40.0, "y": 40.0}}}
                return {"result": {"value": frame_page}}
            if "new Promise" in expr:
                return {"result": {"value": None}}
            return {"result": {"value": {"hover": None, "menuOpen": False, "controls": 1}}}
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {"id": "root"},
                    "childFrames": [{"frame": {"id": "cf1", "url": "https://player.example/embed", "name": "vid"}}],
                }
            }
        if method == "DOM.enable":
            return {}
        if method == "DOM.getFrameOwner":
            return {"backendNodeId": 99}
        if method == "DOM.getBoxModel":
            return {"model": {"content": [120, 60, 720, 60, 720, 400, 120, 400]}}
        if method == "Target.getTargets":
            return {"targetInfos": [{"targetId": "t-oo", "type": "iframe", "url": "https://player.example/embed"}]}
        if method == "Target.attachToTarget":
            return {"sessionId": "oo-sess"}
        return {}

    orig_op = browser.browser_operation
    monkeypatch.setattr(browser, "cdp", fake_cdp)

    def fake_top_observe(req):
        if req["operation"] == "observe":
            return deepcopy(top_page)
        return orig_op(req)

    monkeypatch.setattr(browser, "browser_operation", fake_top_observe)

    b = browser.Browser.__new__(browser.Browser)
    b.session = "top-sess"
    observed = b.observe(screenshot=False)

    embed_btn = next(a for a in observed["actions"] if a["label"] == "Play embed")
    assert embed_btn["node"] == "f1:7"
    assert embed_btn["rect"]["x"] == 140.0 and embed_btn["rect"]["y"] == 90.0
    assert observed["guards"]["f1:7"] == ["g7"]

    calls.clear()
    b.act(embed_btn, observed)
    clicks = [(sid, p) for m, sid, p in calls if m == "Input.dispatchMouseEvent"]
    # Evaluate ran inside OOPIF session ('oo-sess'), clicks landed on top session ('top-sess') at (40+120, 40+60).
    assert ("Runtime.evaluate", "oo-sess") in [(m, sid) for m, sid, _ in calls]
    assert clicks[0][0] == "top-sess"
    assert clicks[0][1]["x"] == 160.0 and clicks[0][1]["y"] == 100.0


def test_video_ops_with_autoplay_fallback_and_slider_drag_fallback(monkeypatch):
    import jev_ultrafast.browser as browser

    # 1. Video play() blocked -> falls back to real CDP click at video center.
    calls = []
    play_script_hits = []

    def fake_video_cdp(method, session_id=None, **params):
        calls.append((method, params))
        if method == "Runtime.evaluate":
            expr = params["expression"]
            if "playbackRate" in expr and "paused" in expr:
                return {
                    "result": {
                        "value": {
                            "paused": True,
                            "muted": False,
                            "volume": 1.0,
                            "currentTime": 2.0,
                            "duration": 100.0,
                            "playbackRate": 1.0,
                            "x": 300.0,
                            "y": 200.0,
                        }
                    }
                }
            if "v.play()" in expr:
                play_script_hits.append(True)
                return {"result": {"value": False}}
            if "v.volume =" in expr:
                play_script_hits.append(expr)
                return {"result": {"value": None}}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_video_cdp)
    browser_operation(
        {
            "operation": "act",
            "session": "s",
            "action": {"id": "e1", "kind": "click", "role": "button", "node": 5, "video_op": "toggle_play"},
        }
    )
    assert play_script_hits == [True]
    assert any(m == "Input.dispatchMouseEvent" and p["x"] == 300.0 and p["y"] == 200.0 for m, p in calls)

    play_script_hits.clear()
    browser_operation(
        {
            "operation": "act",
            "session": "s",
            "action": {"id": "e2", "kind": "fill", "role": "slider", "node": 5, "video_op": "volume"},
            "text": "35%",
        }
    )
    assert any("v.volume = 0.35" in item for item in play_script_hits if isinstance(item, str))

    # 2. Custom [role="slider"] where Arrow keys don't update aria-valuenow -> falls back to real mouse step-drag.
    drag_calls = []

    def fake_slider_cdp(method, session_id=None, **params):
        drag_calls.append((method, params))
        if method == "Runtime.evaluate":
            expr = params["expression"]
            if "input_type" in expr:
                return {
                    "result": {
                        "value": {
                            "tag": "DIV",
                            "input_type": "",
                            "has_aria_now": True,
                            "cur": 20.0,
                            "min": 0.0,
                            "max": 100.0,
                            "step": 5.0,
                            "rect": {"x": 100.0, "y": 400.0, "w": 200.0, "h": 20.0},
                        }
                    }
                }
            if "getAttribute('aria-valuenow')" in expr:
                return {"result": {"value": 20.0}}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_slider_cdp)
    browser_operation(
        {
            "operation": "act",
            "session": "s",
            "action": {"id": "e3", "kind": "fill", "role": "slider", "node": 9},
            "text": "75%",
        }
    )
    drag_events = [p for m, p in drag_calls if m == "Input.dispatchMouseEvent"]
    assert drag_events[0]["type"] == "mousePressed" and drag_events[0]["x"] == 140.0  # 100 + 0.2 * 200
    assert drag_events[-1]["type"] == "mouseReleased" and drag_events[-1]["x"] == 250.0  # 100 + 0.75 * 200


def test_same_process_iframe_caches_named_isolated_world(monkeypatch):
    import jev_ultrafast.browser as browser

    top_page = page()
    top_page["iframes"] = [
        {
            "src": "https://example.test/frame",
            "name": "f",
            "id": "f",
            "rect": {"x": 10.0, "y": 20.0, "w": 300.0, "h": 200.0},
        }
    ]
    frame_page = {
        "url": "https://example.test/frame",
        "title": "Frame",
        "text": "Inside",
        "scroll": {"y": 0, "height": 200},
        "page_key": ["fk"],
        "guards": {"3": ["fg3"]},
        "actions": [
            {
                "id": "e1",
                "kind": "click",
                "role": "button",
                "label": "Frame OK",
                "value": "",
                "node": 3,
                "rect": {"x": 5, "y": 5, "w": 20, "h": 10},
            },
        ],
    }
    world_calls = []

    def fake_cdp(method, session_id=None, **params):
        if method == "Page.createIsolatedWorld":
            world_calls.append(params)
            return {"executionContextId": 42}
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if params.get("contextId") == 42:
                if "c.pageKey()" in expr:
                    return {"result": {"value": [["fk"], ["fg3"]]}}
                if "const e=window.__jevFast" in expr:
                    return {"result": {"value": {"x": 15.0, "y": 10.0}}}
                return {"result": {"value": frame_page}}
            return {"result": {"value": {"hover": None, "menuOpen": False, "controls": 1}}}
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {"id": "root"},
                    "childFrames": [{"frame": {"id": "sf1", "url": "https://example.test/frame", "name": "f"}}],
                }
            }
        if method == "Target.getTargets":
            return {"targetInfos": []}
        return {}

    orig_op = browser.browser_operation
    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(
        browser,
        "browser_operation",
        lambda req: deepcopy(top_page) if req["operation"] == "observe" else orig_op(req),
    )

    b = browser.Browser.__new__(browser.Browser)
    b.session = "top-sess"
    observed = b.observe(screenshot=False)
    btn = next(a for a in observed["actions"] if a["label"] == "Frame OK")
    b.act(btn, observed)

    assert len(world_calls) == 1
    assert world_calls[0]["worldName"] == "__jevFast"
    assert world_calls[0]["grantUniversalAccess"] is True


def test_scroll_and_press_enter_do_not_crash_observe_after_input(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp_calls = []

    def fake_cdp(method, session_id=None, **params):
        cdp_calls.append((method, params))
        if method == "Runtime.evaluate":
            return {"result": {"value": True}}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "browser_operation", Mock(return_value=p))

    b = browser.Browser.__new__(browser.Browser)
    b.session = "sess-scroll"
    b.fresh = Mock(return_value=True)
    b._last_page_has_media = False

    # Scroll and press_enter have no 'node' key; observe() must not crash on after_input.
    b.act({"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560}, p)
    assert b.after_input is None
    b.after_input = {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560}
    observed = b.observe(screenshot=False)
    assert observed["fingerprint"] == p["fingerprint"]

    key_calls = []
    monkeypatch.setattr(browser, "cdp", lambda m, **kw: key_calls.append((m, kw)) or {})
    res = browser_operation(
        {
            "operation": "act",
            "session": "sess-enter",
            "action": {"id": "press_enter", "kind": "press_enter", "label": "Press Enter"},
        }
    )
    assert res == {"executed": "press_enter"}
    assert [kw["type"] for m, kw in key_calls if m == "Input.dispatchKeyEvent"] == ["rawKeyDown", "char", "keyUp"]


def test_click_follows_opened_target_blank_tab(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    switched = []

    def fake_cdp(method, session_id=None, **params):
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    {"targetId": "tab-1", "type": "page", "url": "https://booking.test/search"},
                    {"targetId": "tab-2", "type": "page", "url": "https://booking.test/hotel", "openerId": "tab-1"},
                ]
            }
        if method == "Runtime.evaluate":
            return {"result": {"value": ["complete", "https://booking.test/hotel"]}}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "browser_operation", Mock(return_value={"executed": "e3", "opens_new_tab": True}))

    b = browser.Browser.__new__(browser.Browser)
    b.session = "sess-1"
    b.target = "tab-1"
    b._background = False
    b._last_page_has_media = False
    b.fresh = Mock(return_value=True)
    b.switch_to_target = lambda tid, activate=True: switched.append((tid, activate))

    b.act(p["actions"][2], p)
    assert switched == [("tab-2", True)]


def test_post_json_retries_transient_transport_error_and_fenced_text(monkeypatch):
    import httpx

    attempts = []

    class FakeResp:
        def __init__(self, code, data):
            self.status_code = code
            self.is_error = code >= 400
            self.text = ""
            self._data = data

        def json(self):
            return self._data

    def fake_post(url, json=None, headers=None):
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("Server disconnected")
        if len(attempts) == 2:
            return FakeResp(502, {})
        return FakeResp(200, {"ok": True})

    monkeypatch.setattr(model.CLIENT, "post", fake_post)
    monkeypatch.setattr(model.time, "sleep", lambda _s: None)
    assert model.post_json("https://api.test", "k", {}) == {"ok": True}
    assert len(attempts) == 3

    monkeypatch.setenv("TEXT_MODEL_API_KEY", "nvapi_test")
    monkeypatch.setattr(
        model,
        "post_json",
        Mock(return_value={"choices": [{"message": {"content": '```json\n{"text": "Paris"}\n```'}}]}),
    )
    val, _ = model.field_text({"goal": "Find hotels in Paris"})
    assert val == "Paris"
