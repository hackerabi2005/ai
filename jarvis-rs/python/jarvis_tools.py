"""Realtime client tool module bridging s2s Nemotron tool calls to the Rust broker API."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx2
from speech_to_speech.api.openai_realtime.audio_client import ToolResult

_HTTP_CLIENT = httpx2.Client()

TOOLS = [
    {
        "type": "function",
        "name": "browser_task",
        "description": (
            "Run a natural-language web browsing or video-player task in Chrome (search, navigate, fill forms, "
            "click buttons/links, pause/mute/volume, settings, captions, fullscreen). "
            "Blocks until done, blocked, stopped, or needing confirmation on a risky action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Clear natural-language goal describing what to achieve on the web.",
                },
                "url": {
                    "type": ["string", "null"],
                    "description": "Optional starting URL (omit to continue in the current open tab).",
                },
                "new_tab": {
                    "type": "boolean",
                    "description": "Set true to open the task in a new browser tab instead of reusing the current tab.",
                },
            },
            "required": ["goal"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "browser_confirm",
        "description": (
            "Approve or reject a pending risky browser action (such as pay, buy, submit, send, delete, confirm) "
            "after asking the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "approve": {
                    "type": "boolean",
                    "description": "True only if the user explicitly approved the pending action; false to cancel.",
                }
            },
            "required": ["approve"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "browser_control",
        "description": "Control the browser or stop the running browser task.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "stop",
                        "back",
                        "forward",
                        "reload",
                        "scroll_up",
                        "scroll_down",
                        "scroll_top",
                        "scroll_bottom",
                        "zoom_in",
                        "zoom_out",
                        "zoom_reset",
                        "switch_tab_next",
                        "switch_tab_prev",
                        "list_tabs",
                        "close_tab",
                        "close_dialog",
                        "press_escape",
                        "press_enter",
                        "press_tab",
                        "press_ctrl_k",
                        "press_ctrl_f",
                        "play_video",
                        "pause_video",
                        "mute_video",
                        "unmute_video",
                        "volume_up",
                        "volume_down",
                        "seek_forward",
                        "seek_back",
                        "skip_ad",
                        "fullscreen",
                        "open_settings",
                        "toggle_captions",
                        "speed_up",
                        "speed_down",
                        "next_track",
                        "prev_track",
                    ],
                    "description": "The control action to execute.",
                }
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "read_page",
        "description": "Read the current browser tab URL, title, visible text, and interactive elements.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def _request_sync(method: str, path: str, body: dict[str, Any] | None, timeout_s: float) -> dict[str, Any]:
    base_url = os.environ.get("JARVIS_API_URL", "").rstrip("/")
    token = os.environ.get("JARVIS_API_TOKEN", "")
    if not base_url or not token:
        return {"code": "not_configured", "error": "Jarvis loopback API is not configured."}

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = _HTTP_CLIENT.request(
            method,
            f"{base_url}{path}",
            json=body if body is not None else None,
            headers=headers,
            timeout=timeout_s,
        )
        if resp.status_code >= 400:
            try:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
            return {"code": f"http_{resp.status_code}", "error": resp.text or f"HTTP {resp.status_code}"}
        return resp.json()
    except Exception as exc:
        return {"code": "connection_failed", "error": f"Failed reaching Jarvis browser broker: {exc}"}


async def execute_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
    if name == "browser_task":
        payload: dict[str, Any] = {"goal": str(arguments["goal"])}
        url = arguments.get("url")
        if isinstance(url, str) and url.strip():
            payload["url"] = url.strip()
        if arguments.get("new_tab") is True:
            payload["new_tab"] = True
        res = await asyncio.to_thread(_request_sync, "POST", "/task", payload, 180.0)
        return ToolResult(res, create_response=True)

    if name == "browser_confirm":
        res = await asyncio.to_thread(
            _request_sync, "POST", "/confirm", {"approve": bool(arguments["approve"])}, 180.0
        )
        return ToolResult(res, create_response=True)

    if name == "browser_control":
        res = await asyncio.to_thread(
            _request_sync, "POST", "/control", {"action": str(arguments["action"])}, 15.0
        )
        return ToolResult(res, create_response=True)

    if name == "read_page":
        res = await asyncio.to_thread(_request_sync, "GET", "/read_page", None, 15.0)
        return ToolResult(res, create_response=True)

    raise ValueError(f"Unknown tool: {name}")
