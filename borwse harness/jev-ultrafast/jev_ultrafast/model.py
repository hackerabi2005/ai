"""Experiential Labs Jev makes choices; an optional OpenAI-compatible model writes field values."""

import json
import math
import os
import time

import httpx

from .questions import NEXT_ACTION, TARGET, TEXT_VALUE

DEFAULT_JEV_URL = "https://api.experientiallabs.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-latest"
DEFAULT_TEXT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TEXT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
MAX_CHOICE_CRITERIA = 64

CLIENT = httpx.Client(http2=True, timeout=httpx.Timeout(30.0, connect=10.0))
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.TransportError:
            if attempt < 2:
                time.sleep(0.35 * 2**attempt)
                continue
            raise RuntimeError("Model connection failed; no action executed.") from None
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in _RETRYABLE_STATUS and attempt < 2:
            time.sleep(0.35 * 2**attempt)
            continue
        if response.is_error:
            detail = response.text.strip().replace("\n", " ")[:240]
            suffix = f" ({detail})" if detail else ""
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}{suffix}; no action executed.")
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def _target_criteria(candidates):
    return {
        index: {
            "element": f"[{index}] {a['label']}",
            "current_value": a.get("current_value", a.get("value", "")),
            **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
        }
        for index, a in candidates.items()
    }


def _add_target_questions(questions, operation, candidates, goal):
    """Add 2..64 choice question(s) for an operation; singletons need no choice head."""
    if len(candidates) < 2:
        return
    instructions = {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]}
    criteria = _target_criteria(candidates)
    prefix = operation.lower() + "_target"
    if len(criteria) <= MAX_CHOICE_CRITERIA:
        questions[prefix] = {"type": "choice", "criteria": criteria, "instructions": instructions}
        return
    items = list(criteria.items())
    chunk_size = MAX_CHOICE_CRITERIA - 1
    for i in range(0, len(items), chunk_size):
        chunk = dict(items[i : i + chunk_size])
        chunk["NONE"] = "None of these elements; choose a real index only if it is the right target."
        questions[f"{prefix}_{i // chunk_size + 1}"] = {
            "type": "choice",
            "criteria": chunk,
            "instructions": instructions,
        }


def _resolve_target(operation, candidates, questions, answers):
    if len(candidates) == 1:
        only = next(iter(candidates))
        return only, {only: 1.0}, 1.0
    prefix = operation.lower() + "_target"
    if prefix in questions:
        answer = validate_choice(answers.get(prefix, {}), candidates)
        return answer["choice"], answer["probabilities"], answer["confidence"]
    chunk_keys = [k for k in questions if k.startswith(prefix + "_")]
    all_probs = {}
    selected = []
    for key in chunk_keys:
        criteria = questions[key]["criteria"]
        answer = validate_choice(answers.get(key, {}), criteria)
        probs = {idx: p for idx, p in answer["probabilities"].items() if idx != "NONE"}
        all_probs.update(probs)
        if answer["choice"] != "NONE":
            selected.append((answer["choice"], probs[answer["choice"]], answer["confidence"]))
    if selected:
        best_target, _, best_conf = max(selected, key=lambda item: (item[1], item[2]))
    else:
        best_target = max(all_probs, key=all_probs.get)
        best_conf = all_probs[best_target]
    return best_target, all_probs, best_conf


def choose(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        _add_target_questions(questions, operation, candidates, goal)
    api_key = os.environ.get("EXPERIENTIAL_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise ValueError("Missing EXPERIENTIAL_API_KEY; no action executed.")
    api_url = os.environ.get("EXPERIENTIAL_API_URL", DEFAULT_JEV_URL)
    body = {
        "model": os.environ.get("EXPERIENTIAL_MODEL") or os.environ.get("TYPESAFE_MODEL") or DEFAULT_JEV_MODEL,
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    result = post_json(api_url, api_key, body)
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_probabilities = {}
    target_confidence = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target, target_probabilities, target_confidence = _resolve_target(
            operation, targets[operation], questions, result["answers"]
        )
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_probabilities[index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_probabilities,
        "target_confidence": target_confidence,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def _text_reasoning_kwargs(base):
    """Build provider-specific reasoning toggle without duplicating chat request logic."""
    mode = os.environ.get("TEXT_MODEL_REASONING", "none" if "integrate.api.nvidia.com" in base else "")
    if "integrate.api.nvidia.com" in base:
        return {"chat_template_kwargs": {"enable_thinking": mode.lower() not in {"", "none", "false", "off"}}}
    if "api.deepseek.com/" in base:
        return {"thinking": {"type": "disabled"}}
    if mode == "none":
        return {"reasoning": {"enabled": False}}
    return {"reasoning": {"effort": "low"}}


def field_text(context):
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor.")
    base = (os.environ.get("TEXT_MODEL_BASE_URL") or DEFAULT_TEXT_BASE_URL).rstrip("/")
    model = os.environ.get("TEXT_MODEL") or DEFAULT_TEXT_MODEL
    reasoning = _text_reasoning_kwargs(base)
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
    )
    try:
        raw = str(result["choices"][0]["message"]["content"]).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if len(lines) >= 2 and lines[-1].strip().startswith("```"):
                raw = "\n".join(lines[1:-1]).strip()
        output = json.loads(raw)
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }
