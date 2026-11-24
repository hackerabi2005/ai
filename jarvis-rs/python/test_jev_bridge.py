"""Offline unit tests for jev_bridge.py using a fake Agent."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jev_bridge import BridgeSession, serve_stdio  # noqa: E402

from jev_ultrafast.browser import StalePage  # noqa: E402


def _fake_page(url="https://example.test", title="Example", text="Hello", fp="fp1"):
    return {
        "url": url,
        "title": title,
        "text": text,
        "fingerprint": fp,
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Where from?", "role": "combobox", "value": "", "node": 1},
            {"id": "e2", "kind": "click", "label": "Submit order", "role": "button", "value": "", "node": 2},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }


class FakeAgent:
    def __init__(self, url: str, goal: str, *, background: bool = True) -> None:
        self.init_args = (url, goal, background)
        self.screenshots = False
        self.pending_text = "cached"
        self.closed = False
        self.browser = Mock()
        self.browser.evaluate = Mock(return_value="complete")
        self.browser.observe = Mock(return_value=_fake_page(url=url, fp="fp2"))
        self.state = {
            "goal": goal,
            "plan": [goal],
            "plan_index": 0,
            "page": _fake_page(url=url),
            "decision": None,
            "history": [],
            "status": "ready",
            "decisions": [],
            "text_calls": [],
            "elapsed_ms": 0,
            "started_at": None,
        }

    def command(self, name: str, body=None):
        if name == "predict":
            self.state["decision"] = {
                "choice": "e2",
                "operation": "CLICK",
                "target": "2",
                "confidence": 0.98,
            }
            self.state["decisions"].append({"choice": "e2"})
            self.state["status"] = "predicted"
            return None
        if name == "act":
            if body.get("fingerprint") == "stale":
                raise StalePage("changed")
            self.state["decision"] = None
            self.state["history"].append({"step": 1, "action": "Submit order", "kind": "click"})
            self.state["status"] = "ready"
            return {k: v for k, v in self.state.items()}
        raise ValueError(name)

    def close(self) -> None:
        self.closed = True


def test_bridge_open_reuse_predict_act_and_stale_recovery():
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)

    r1, exit1 = session.handle({"cmd": "open", "goal": "Find flights", "url": "https://flights.test"})
    assert not exit1 and r1["ok"] is True
    assert session.agent.init_args == ("https://flights.test", "Find flights", False)

    # Second open without URL reuses the existing tab and clears history/goal.
    session.agent.state["history"].append({"step": 1})
    r2, _ = session.handle({"cmd": "open", "goal": "Second goal"})
    assert r2["ok"] is True
    assert session.agent.state["goal"] == "Second goal"
    assert session.agent.state["history"] == []
    assert session.agent.pending_text is None

    # Predict exposes action label/kind before act runs.
    pred, _ = session.handle({"cmd": "predict"})
    assert pred["ok"] is True
    assert pred["kind"] == "click"
    assert pred["action_label"] == "Submit order"
    assert pred["fingerprint"] == "fp2"

    # Stale act recovers cleanly without dropping bridge state.
    stale_act, _ = session.handle({"cmd": "act", "fingerprint": "stale"})
    assert stale_act["ok"] is True and stale_act["stale"] is True and stale_act["executed"] is False
    assert session.agent.state["decision"] is None

    # Normal act executes and advances history.
    session.handle({"cmd": "predict"})
    ok_act, _ = session.handle({"cmd": "act", "fingerprint": "fp2"})
    assert ok_act["ok"] is True and ok_act["stale"] is False and ok_act["executed"] is True
    assert ok_act["history_len"] == 1

    # Read page returns indexed elements without screenshots.
    rp, _ = session.handle({"cmd": "read_page"})
    assert rp["ok"] is True
    assert len(rp["elements"]) == 2

    # Control scroll uses fast scrollBy (no mouseWheel) when window scrolls, and falls back to mouseWheel otherwise.
    session.agent.browser.observe.reset_mock()
    session.agent.browser.call.reset_mock()
    session.agent.browser.evaluate.return_value = True
    ctrl, _ = session.handle({"cmd": "control", "action": "scroll_down"})
    assert ctrl["ok"] is True
    assert session.agent.browser.observe.call_count == 0
    assert session.agent.browser.call.call_count == 0
    assert session.agent.state["page"]["fingerprint"] == ""
    session.agent.browser.evaluate.return_value = [560, 390, -700]
    ctrl2, _ = session.handle({"cmd": "control", "action": "scroll_up"})
    assert ctrl2["ok"] is True
    assert session.agent.browser.call.call_count == 1
    closed, _ = session.handle({"cmd": "control", "action": "close_tab"})
    assert closed["ok"] is True and closed["closed"] is True
    assert session.agent is None


def test_open_with_skip_observe_navigates_without_dom_snapshot():
    class ObserveCapableAgent(FakeAgent):
        def __init__(self, url: str, goal: str, *, background: bool = True, observe: bool = True) -> None:
            super().__init__(url, goal, background=background)
            self.observe_arg = observe
            if not observe:
                self.browser.observe.reset_mock()

    session = BridgeSession(agent_cls=ObserveCapableAgent, default_background=False)
    r1, _ = session.handle({"cmd": "open", "goal": "Open YouTube", "url": "https://www.youtube.com", "skip_observe": True})
    assert r1["ok"] is True
    assert session.agent.observe_arg is False
    assert session.agent.browser.observe.call_count == 0

    session.agent.browser.evaluate.reset_mock()
    session.agent.browser.evaluate.side_effect = [
        [1000.0, "https://www.youtube.com/"],  # pre-navigate [timeOrigin, href]
        ["complete", "https://www.youtube.com/", "YouTube", 1000.0],  # stale old page ignored
        ["interactive", "https://en.wikipedia.org/", "Wikipedia", 2000.0],  # committed new page
    ]
    r2, _ = session.handle({"cmd": "open", "goal": "Open Wikipedia", "url": "https://en.wikipedia.org", "skip_observe": True})
    assert r2["ok"] is True
    assert r2["page"]["url"] == "https://en.wikipedia.org/"
    assert r2["page"]["title"] == "Wikipedia"
    assert session.agent.browser.observe.call_count == 0
    assert session.agent.browser.evaluate.call_count == 3

    # new_tab=True leaves the prior Chrome tab open and attaches a new tab.
    first_agent = session.agent
    r3, _ = session.handle(
        {"cmd": "open", "goal": "Open Hugging Face", "url": "https://huggingface.co", "skip_observe": True, "new_tab": True}
    )
    assert r3["ok"] is True
    assert session.agent is not first_agent
    assert first_agent.closed is False


def test_direct_media_controls_skip_observe_and_dispatch_click_when_needed():
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Open YouTube", "url": "https://www.youtube.com"})
    session.agent.browser.observe.reset_mock()
    session.agent.browser.evaluate.return_value = {"ok": True}

    r_pause, _ = session.handle({"cmd": "control", "action": "pause_video"})
    assert r_pause["ok"] is True
    assert session.agent.browser.observe.call_count == 0

    r_vol, _ = session.handle({"cmd": "control", "action": "volume:35"})
    assert r_vol["ok"] is True
    assert session.agent.browser.observe.call_count == 0

    session.agent.browser.call.reset_mock()
    session.agent.browser.evaluate.return_value = {"ok": True, "click": [400, 300]}
    r_skip, _ = session.handle({"cmd": "control", "action": "skip_ad"})
    assert r_skip["ok"] is True
    click_calls = [c for c in session.agent.browser.call.call_args_list if c.args and c.args[0] == "Input.dispatchMouseEvent"]
    assert len(click_calls) == 2

    # open_settings wakes faded player bar via mouseMoved before clicking settings button.
    session.agent.browser.call.reset_mock()
    session.agent.browser.evaluate.side_effect = [{"ok": False, "hover": [250, 200]}, {"ok": True, "click": [500, 420]}]
    r_set, _ = session.handle({"cmd": "control", "action": "open_settings"})
    assert r_set["ok"] is True
    mouse_types = [c.kwargs.get("type") for c in session.agent.browser.call.call_args_list if c.args and c.args[0] == "Input.dispatchMouseEvent"]
    assert mouse_types == ["mouseMoved", "mousePressed", "mouseReleased"]


def test_chrome_disconnect_clears_agent_and_reports_chrome_not_ready():
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Browse", "url": "https://example.test"})
    session.agent.browser.observe.side_effect = RuntimeError("Target closed")
    resp, should_exit = session.handle({"cmd": "read_page"})
    assert not should_exit
    assert resp["ok"] is False
    assert resp["code"] == "chrome_not_ready"
    assert session.agent is None


def test_warm_browser_invokes_ensure_daemon(monkeypatch):
    import jev_bridge

    called = []
    monkeypatch.setattr(jev_bridge, "ensure_daemon", lambda: called.append(True))
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    resp, should_exit = session.handle({"cmd": "warm_browser"})
    assert not should_exit
    assert resp == {"ok": True}
    assert called == [True]


def test_serve_stdio_closes_on_eof():
    inp = io.StringIO('{"id": 1, "cmd": "ping"}\n{"id": 2, "cmd": "close"}\n')
    out = io.StringIO()
    serve_stdio(inp, out)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(lines) == 2
    assert lines[0]["id"] == 1 and lines[0]["ok"] is True
    assert lines[1]["id"] == 2 and lines[1]["ok"] is True


def test_close_agent_detaches_instead_of_killing_last_chrome_tab(monkeypatch):
    import jev_bridge

    cdp_calls = []
    monkeypatch.setattr(jev_bridge, "cdp", lambda m, **kw: cdp_calls.append((m, kw)) or {})
    monkeypatch.setattr(
        jev_bridge,
        "_list_page_targets",
        lambda *, prefer_real=False: [{"targetId": "only-tab", "type": "page", "url": "https://www.google.com"}],
    )

    session = BridgeSession(default_background=False)
    fake_agent = FakeAgent("https://www.google.com", "Keep alive")
    fake_agent.browser.target = "only-tab"
    fake_agent.browser.session = "sess-only"
    session.agent = fake_agent
    session._owns_tab = True

    session.close_agent()
    assert session.agent is None
    assert fake_agent.closed is False
    assert ("Target.detachFromTarget", {"sessionId": "sess-only"}) in cdp_calls
    assert not any(m == "Target.closeTarget" for m, _ in cdp_calls)


def test_match_click_resolves_exact_fuzzy_and_select_labels_and_rejects_ambiguous():
    from jev_bridge import _match_clickable_action

    actions = [
        {"id": "e1", "kind": "click", "role": "button", "label": "Accept Cookies", "node": 1},
        {"id": "e2", "kind": "click", "role": "checkbox", "label": "Free cancellation before Dec 18", "node": 2},
        {"id": "e3", "kind": "select", "role": "combobox", "label": "Sort by → Price low to high", "node": 3},
        {"id": "e4", "kind": "click", "role": "link", "label": "Docs", "node": 4},
        {"id": "e5", "kind": "click", "role": "button", "label": "Buy now", "node": 5},
        {"id": "e6", "kind": "click", "role": "link", "label": "Ramayana | Official Trailer", "node": 6},
    ]
    assert _match_clickable_action(actions, "Accept Cookies button")[0]["id"] == "e1"
    assert _match_clickable_action(actions, "accept cokies")[0]["id"] == "e1"
    assert _match_clickable_action(actions, "free cancellation")[0]["id"] == "e2"
    assert _match_clickable_action(actions, "Price low to high")[0]["id"] == "e3"
    assert _match_clickable_action(actions, "docs")[0]["id"] == "e4"
    assert _match_clickable_action(actions, "ramayana video")[0]["id"] == "e6"
    assert _match_clickable_action(actions, "nonexistent element") is None

    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Browse", "url": "https://shop.test"})
    hit, _ = session.handle({"cmd": "match_click", "target": "Submit order"})
    assert hit["ok"] is True and hit["matched"] is True and hit["choice"] == "e2"
    assert session.agent.state["decision"]["choice"] == "e2"
    miss, _ = session.handle({"cmd": "match_click", "target": "Not on screen"})
    assert miss["ok"] is True and miss["matched"] is False


def test_short_tab_label_strips_emoji_and_symbols():
    from jev_bridge import _short_tab_label

    assert _short_tab_label("chrome://newtab", "🐴 New Tab") == "New Tab"
    assert _short_tab_label("https://www.youtube.com/", "🐴 YouTube") == "YouTube"
    assert _short_tab_label("https://www.youtube.com/watch?v=1", "🐴🔥") == "youtube.com"
    assert (
        _short_tab_label("https://huggingface.co", "Hugging Face – The AI community building the future.")
        == "Hugging Face The AI community building the future"
    )


def test_act_converts_null_field_text_error_into_clean_blocked_status():
    class NullTextAgent(FakeAgent):
        def command(self, name: str, body=None):
            if name == "act":
                raise ValueError("Text helper returned no valid field value; nothing typed.")
            return super().command(name, body)

    session = BridgeSession(agent_cls=NullTextAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Select Anthropic", "url": "https://huggingface.co"})
    session.handle({"cmd": "predict"})
    res, _ = session.handle({"cmd": "act", "fingerprint": "fp2"})
    assert res["ok"] is True
    assert res["status"] == "blocked"
    assert res["executed"] is False
    assert session.agent.state["decision"] is None


def test_ctrl_shortcuts_dispatch_with_ctrl_modifier():
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Browse", "url": "https://huggingface.co"})
    session.agent.browser.call.reset_mock()

    res, _ = session.handle({"cmd": "control", "action": "press_ctrl_k"})
    assert res["ok"] is True
    key_calls = [c for c in session.agent.browser.call.call_args_list if c.args and c.args[0] == "Input.dispatchKeyEvent"]
    assert len(key_calls) == 2
    assert key_calls[0].kwargs["key"] == "k"
    assert key_calls[0].kwargs["modifiers"] == 2
    assert key_calls[1].kwargs["type"] == "keyUp"
    assert key_calls[1].kwargs["modifiers"] == 2


def test_list_tabs_and_close_dialog_controls():
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Browse", "url": "https://www.youtube.com"})

    lt, _ = session.handle({"cmd": "control", "action": "list_tabs"})
    assert lt["ok"] is True
    assert lt["message"] == "1 tab open: Example."

    # close_dialog clicks visible dialog Close button when found, otherwise falls back to Escape.
    session.agent.browser.call.reset_mock()
    session.agent.browser.evaluate.return_value = {"click": [420, 80]}
    cd1, _ = session.handle({"cmd": "control", "action": "close_dialog"})
    assert cd1["ok"] is True
    click_calls = [c for c in session.agent.browser.call.call_args_list if c.args and c.args[0] == "Input.dispatchMouseEvent"]
    assert len(click_calls) == 2

    session.agent.browser.call.reset_mock()
    session.agent.browser.evaluate.return_value = {"click": None}
    cd2, _ = session.handle({"cmd": "control", "action": "close_dialog"})
    assert cd2["ok"] is True
    key_calls = [c for c in session.agent.browser.call.call_args_list if c.args and c.args[0] == "Input.dispatchKeyEvent"]
    assert len(key_calls) == 2 and key_calls[0].kwargs["key"] == "Escape"


def test_collect_iframe_refs_resolves_oopifs_by_url_and_same_process_by_frame_id():
    from jev_bridge import _collect_iframe_refs

    browser = Mock()
    browser.session = "top-sess"
    browser.call.return_value = {
        "frameTree": {
            "frame": {"id": "main", "url": "https://host.test/"},
            "childFrames": [
                {"frame": {"id": "f-oo", "url": "https://player.example/embed"}},
                {"frame": {"id": "f-same", "url": "https://host.test/help"}},
                {"frame": {"id": "f-blank", "url": "about:blank"}},
            ],
        }
    }
    browser._attach_oopif_sessions.return_value = {"https://player.example/embed": ["sid-oo-1"]}

    refs = _collect_iframe_refs(browser)
    assert refs == [
        {"frame_id": None, "session_id": "sid-oo-1"},
        {"frame_id": "f-same"},
    ]


def test_match_click_resets_history_so_unlimited_voice_clicks_never_hit_budget():
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Browse", "url": "https://shop.test"})
    session.agent.state["history"] = [{"step": i} for i in range(60)]
    session.agent.state["decisions"] = [{"choice": "e2"} for _ in range(120)]

    hit, _ = session.handle({"cmd": "match_click", "target": "Submit order"})
    assert hit["ok"] is True and hit["matched"] is True
    assert session.agent.state["history"] == []
    assert session.agent.state["decisions"] == []


def test_close_tab_never_retries_and_closes_a_second_tab_when_fallback_vanishes(monkeypatch):
    import jev_bridge

    closed_targets = []
    monkeypatch.setattr(
        jev_bridge,
        "cdp",
        lambda m, **kw: closed_targets.append(kw.get("targetId")) if m == "Target.closeTarget" else {},
    )
    monkeypatch.setattr(
        jev_bridge,
        "_list_page_targets",
        lambda *, prefer_real=False: [
            {"targetId": "tab-cur", "type": "page", "url": "https://youtube.com", "title": "YouTube"},
            {"targetId": "tab-ok", "type": "page", "url": "https://wiki.test", "title": "Wiki"},
            {"targetId": "tab-gone", "type": "page", "url": "https://gone.test", "title": "Gone"},
        ],
    )

    session = BridgeSession(default_background=False)
    fake_agent = FakeAgent("https://youtube.com", "Watch")
    fake_agent.browser.target = "tab-cur"
    fake_agent.browser.session = "sess-cur"

    def fake_switch(tid, activate=True):
        if tid == "tab-gone":
            raise RuntimeError("No target with given id")
        fake_agent.browser.target = tid

    fake_agent.browser.switch_to_target = fake_switch
    fake_agent.browser.evaluate.return_value = ["https://wiki.test", "Wiki"]
    session.agent = fake_agent

    res, _ = session.handle({"cmd": "control", "action": "close_tab"})
    assert res["ok"] is True and res["closed"] is True
    assert closed_targets == ["tab-cur"]
    assert fake_agent.browser.target == "tab-ok"
    assert res["message"] == "Closed the tab. Now on Wiki."


def test_act_treats_concurrent_control_invalidation_as_stale_retry():
    class StrictStateAgent(FakeAgent):
        def command(self, name: str, body=None):
            if name == "act" and self.state.get("decision") is None:
                raise ValueError("Observe and choose before acting")
            return super().command(name, body)

    session = BridgeSession(agent_cls=StrictStateAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Watch video", "url": "https://www.youtube.com"})
    session.handle({"cmd": "predict"})
    # Concurrent media control invalidates decision while task is between predict and act.
    session.agent.browser.evaluate.return_value = {"ok": True}
    ctrl, _ = session.handle({"cmd": "control", "action": "pause_video"})
    assert ctrl["ok"] is True
    assert session.agent.state["decision"] is None

    act_res, _ = session.handle({"cmd": "act", "fingerprint": "fp2"})
    assert act_res["ok"] is True
    assert act_res["stale"] is True
    assert act_res["executed"] is False
    assert act_res["status"] == "ready"


def test_match_clickable_action_resolves_appearance_radio_buttons_and_act_recovers_from_nav_timeout():
    from jev_bridge import _match_clickable_action

    wiki_actions = [
        {"id": "e1", "kind": "click", "role": "radio", "label": "Small", "node": 1},
        {"id": "e2", "kind": "click", "role": "radio", "label": "Large", "node": 2},
        {"id": "e3", "kind": "click", "role": "radio", "label": "Dark", "node": 3},
        {"id": "e4", "kind": "click", "role": "radio", "label": "Wide", "node": 4},
    ]
    assert _match_clickable_action(wiki_actions, "text large")[0]["id"] == "e2"
    assert _match_clickable_action(wiki_actions, "set color dark")[0]["id"] == "e3"
    assert _match_clickable_action(wiki_actions, "width wide")[0]["id"] == "e4"

    class NavTimeoutAfterClickAgent(FakeAgent):
        def command(self, name: str, body=None):
            if name == "act":
                self.state["decision"] = None
                self.state["history"].append({"step": 1, "action": "YouTube", "kind": "click"})
                raise RuntimeError("Runtime.evaluate timed out after 5s waiting for the daemon")
            return super().command(name, body)

    session = BridgeSession(agent_cls=NavTimeoutAfterClickAgent, default_background=False)
    session.handle({"cmd": "open", "goal": "Select YouTube", "url": "https://www.google.com"})
    session.handle({"cmd": "predict"})
    session.agent.browser.evaluate.return_value = ["https://www.youtube.com/", "YouTube"]
    act_res, _ = session.handle({"cmd": "act", "fingerprint": "fp2"})
    assert act_res["ok"] is True
    assert act_res["executed"] is True
    assert act_res["stale"] is False
    assert session.agent is not None


def test_press_enter_dispatches_char_cr_and_warm_browser_returns_attached_url(monkeypatch):
    import jev_bridge

    cdp_calls = []

    class FakeBrowser:
        def call(self, method, **params):
            cdp_calls.append((method, params))
            return {}

        def evaluate(self, _js):
            return ["https://www.youtube.com/", "YouTube"]

        def close(self):
            pass

    browser = FakeBrowser()
    # _dispatch_key for press_enter sends rawKeyDown, char("\r"), keyUp.
    jev_bridge._dispatch_key(browser, "press_enter")
    assert ("Input.dispatchKeyEvent", {"type": "char", "text": "\r", "unmodifiedText": "\r"}) in cdp_calls

    # warm_browser returns existing active tab URL when a tab is attached.
    monkeypatch.setattr(jev_bridge, "ensure_daemon", lambda: None)
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    attached = FakeAgent("https://www.youtube.com/", "warm", background=False)
    attached.browser = browser
    attached.state["page"] = {"url": "https://www.youtube.com/", "title": "YouTube"}
    monkeypatch.setattr(session, "_try_attach_existing_tab", lambda **_kw: setattr(session, "agent", attached))
    resp, should_exit = session.handle({"cmd": "warm_browser"})
    assert not should_exit
    assert resp == {"ok": True, "url": "https://www.youtube.com/"}


def test_ensure_chrome_running_launches_chrome_even_when_other_browser_is_open(monkeypatch):
    import browser_harness.admin as bh_admin
    import browser_harness.daemon as bh_daemon
    import jev_bridge

    launched = []
    live_checks = [False, False, True]

    def fake_port_live(_profile):
        return live_checks.pop(0) if live_checks else True

    monkeypatch.setattr(bh_admin, "daemon_alive", lambda *a, **kw: False)
    monkeypatch.setattr(bh_admin, "_launch_browser", lambda: launched.append(True))
    monkeypatch.setattr(bh_daemon, "PROFILES", [Path("C:/Fake/Chrome/User Data")])
    monkeypatch.setattr(bh_daemon, "remote_debugging_toggle_profiles", lambda: [Path("C:/Fake/Chrome/User Data")])
    monkeypatch.setattr(bh_daemon, "_devtools_port_live", fake_port_live)
    # Even if another browser (e.g., Brave) is running, target browser chrome.exe is NOT running.
    monkeypatch.setattr(jev_bridge, "_is_target_browser_running", lambda _profile: False)

    jev_bridge._ensure_chrome_running()
    assert launched == [True]


def test_switch_tab_includes_chrome_new_tab_page(monkeypatch):
    import jev_bridge

    targets = [
        {"targetId": "t-ntp", "type": "page", "url": "chrome://new-tab-page/", "title": "New Tab"},
        {"targetId": "t-yt", "type": "page", "url": "https://www.youtube.com/", "title": "YouTube"},
    ]
    monkeypatch.setattr(jev_bridge, "cdp", lambda method, **kw: {"targetInfos": targets} if method == "Target.getTargets" else {})
    switched = []
    session = BridgeSession(agent_cls=FakeAgent, default_background=False)
    agent = FakeAgent("chrome://new-tab-page/", "New Tab", background=False)
    agent.browser.target = "t-ntp"
    agent.browser.switch_to_target = lambda tid, activate=True: switched.append(tid)
    agent.browser.evaluate.return_value = ["https://www.youtube.com/", "YouTube"]
    session.agent = agent

    res, _ = session.handle({"cmd": "control", "action": "switch_tab_next"})
    assert res["ok"] is True
    assert switched == ["t-yt"]
    assert res["message"] == "Switched to YouTube."


