"""Offline unit tests for jarvis_tools.py and jarvis_s2s.yaml validation."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jarvis_tools  # noqa: E402
from speech_to_speech.api.openai_realtime.audio_client import _validate_tool_config  # noqa: E402
from speech_to_speech.config import load_config, resolve_config, validate_config  # noqa: E402
from speech_to_speech.configured_runtime import build_configured_client  # noqa: E402
from speech_to_speech.LLM.chat_completions_language_model import ChatCompletionsApiModelHandler  # noqa: E402


def test_tools_schema_is_valid():
    validators = _validate_tool_config(jarvis_tools.TOOLS, jarvis_tools.execute_tool)
    assert set(validators) == {"browser_task", "browser_confirm", "browser_control", "read_page"}
    validators["browser_task"].validate({"goal": "Find flights"})
    validators["browser_task"].validate({"goal": "Find flights", "url": None})


def test_jarvis_s2s_yaml_validates_with_thinking_off():
    yaml_path = Path(__file__).resolve().parent.parent / "config" / "jarvis_s2s.yaml"
    doc = load_config(yaml_path)
    validate_config(doc)
    resolved = resolve_config(doc, environ={"NVIDIA_API_KEY": "test-nv-key"}, include_client=True)
    llm_cfg = resolved.pipelines["jarvis"].stages["llm"].selection.config
    assert llm_cfg["model_name"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert llm_cfg["disable_thinking"] is True
    assert (
        ChatCompletionsApiModelHandler._build_extra_body(
            llm_cfg["base_url"], llm_cfg["disable_thinking"], llm_cfg.get("reasoning_effort")
        )
        == {"chat_template_kwargs": {"enable_thinking": False}}
    )
    assert llm_cfg["gen_kwargs"]["max_tokens"] == 1024

    vad_opts = resolved.pipelines["jarvis"].stages["vad"].settings
    assert vad_opts["smart_turn"] is False
    assert vad_opts["min_speech_ms"] == 192
    assert vad_opts["min_silence_ms"] == 64

    stt_cfg = resolved.pipelines["jarvis"].stages["stt"].selection.config
    assert stt_cfg["use_grpc"] is True
    assert stt_cfg["streaming"] is True
    assert stt_cfg["word_time_offsets"] is False

    client = build_configured_client(resolved, local=True)
    assert client.echo_cancellation is True
    assert client.playback_buffer_ms == 64.0
    assert client.chunk_size == 512
    assert {t["name"] for t in client.tools} == {"browser_task", "browser_confirm", "browser_control", "read_page"}


@pytest.mark.asyncio
async def test_execute_tool_forwards_auth_header_and_payload(monkeypatch):
    seen: list[tuple[str, str, str | None, dict | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
            seen.append(("POST", self.path, self.headers.get("Authorization"), body))
            resp = json.dumps({"status": "done", "steps": 2}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization"), None))
            resp = json.dumps({"ok": True, "result": {"page": {"title": "Home"}}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("JARVIS_API_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("JARVIS_API_TOKEN", "tok-123")

        r1 = await jarvis_tools.execute_tool("browser_task", {"goal": "Open flights", "url": None})
        assert r1.output["status"] == "done"
        r2 = await jarvis_tools.execute_tool("read_page", {})
        assert r2.output["ok"] is True

        assert seen[0] == ("POST", "/task", "Bearer tok-123", {"goal": "Open flights"})
        assert seen[1] == ("GET", "/read_page", "Bearer tok-123", None)
    finally:
        server.shutdown()
        server.server_close()
