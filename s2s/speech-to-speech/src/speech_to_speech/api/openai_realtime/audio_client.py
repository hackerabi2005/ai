"""Native Python microphone/speaker client used by the ``talk`` and ``local`` commands.

The browser demo has separate browser-native WebSocket and WebRTC clients under
``demo/``. Those clients share the Realtime protocol with this module, but not
its OpenAI Python SDK, ``sounddevice``, or process-signal implementation.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import multiprocessing
import signal
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field
from importlib import import_module
from ipaddress import ip_address
from queue import Empty, Queue
from threading import Event
from typing import Any, NoReturn, Optional
from urllib.parse import urlsplit, urlunsplit

from jsonschema import SchemaError, ValidationError
from jsonschema.validators import validator_for
from openai import AsyncOpenAI
from rich.cells import cell_len
from rich.console import Console
from websockets.exceptions import ConnectionClosed

from speech_to_speech.api.openai_realtime._audio_worker import (
    _PLAYBACK_START_BUFFER_MS,
    _PLAYBACK_TAIL_HOLD_S,
    AudioWorkerConfig,
    PlaybackBuffer,
    _AudioItem,
    _open_audio_streams,
    _PlaybackCommands,
    _PlaybackTruncation,
    _run_audio_worker,
    _stream_clock_offset,
)
from speech_to_speech.api.openai_realtime.tool_followup import (
    TOOL_FOLLOWUP_COVERED,
    TOOL_FOLLOWUP_METADATA_KEY,
    TOOL_FOLLOWUP_WAIT,
    TOOL_INPUT_METADATA_KEY,
    tool_call_ids,
)
from speech_to_speech.api.openai_realtime.voice_controls import VoiceSelection, arrow_steps, has_terminal_arrows
from speech_to_speech.pipeline.transcript_logging import log_exception

logger = logging.getLogger(__name__)

_AssistantTranscriptStream = tuple[str | None, str | None, int | None, int | None]
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]
_TOOL_CREATE_ID_METADATA_KEY = "s2s_local_tool_create_id"


@dataclass(frozen=True)
class ToolResult:
    """A local tool output with a per-call follow-up response policy."""

    output: Any
    create_response: bool = True


@dataclass
class RealtimeAudioClientConfig:
    """Configuration for the packaged microphone/speaker Realtime client."""

    url: str = "ws://127.0.0.1:8765/v1/realtime"
    model: str = "local"
    api_key: Optional[str] = None
    send_rate: int = 16000
    recv_rate: int = 16000
    playback_buffer_ms: float = _PLAYBACK_START_BUFFER_MS
    chunk_size: int = 1024
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    instructions: Optional[str] = None
    voice: Optional[str] = None
    voice_choices: list[str] = field(default_factory=list)
    print_json: bool = False
    verbose: bool = False
    block_mic_during_playback: bool = False
    vad_threshold: Optional[float] = None
    interrupt_response: bool = True
    echo_cancellation: bool = False
    log_transcripts: bool = False
    connection_retry_timeout_s: float = 30.0
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_executor: ToolExecutor | None = None
    tool_response_create: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.playback_buffer_ms < float("inf"):
            raise ValueError("playback_buffer_ms must be a finite non-negative number")
        if self.vad_threshold is not None and not 0 <= self.vad_threshold <= 1:
            raise ValueError("vad_threshold must be a number between 0 and 1")
        if self.echo_cancellation and self.block_mic_during_playback:
            raise ValueError("Echo cancellation cannot be combined with blocking the microphone during playback")
        if any(not isinstance(voice, str) or not voice.strip() for voice in self.voice_choices):
            raise ValueError("voice_choices must contain non-empty voice names")
        self.voice_choices = list(dict.fromkeys(self.voice_choices))
        if self.voice_choices:
            if self.voice and self.voice not in self.voice_choices:
                self.voice_choices.insert(0, self.voice)
            self.voice = self.voice or self.voice_choices[0]

    @property
    def conversation_only(self) -> bool:
        """Use the clean display unless diagnostics or raw events were requested."""
        return not (self.verbose or self.print_json)


def load_realtime_tool_module(module_name: str) -> tuple[list[dict[str, Any]], ToolExecutor, bool]:
    """Load the explicit tool contract used by the ``talk`` and ``local`` CLIs."""

    if not module_name or not module_name.strip():
        raise ValueError("Tool module name must not be empty")
    module = import_module(module_name)
    try:
        tools = list(module.TOOLS)
    except AttributeError as exc:
        raise ValueError(f"Tool module {module_name!r} must define TOOLS") from exc
    executor = getattr(module, "execute_tool", None)
    if not callable(executor):
        raise ValueError(f"Tool module {module_name!r} must define callable execute_tool(name, arguments)")
    create_response = getattr(module, "CREATE_RESPONSE", True)
    if not isinstance(create_response, bool):
        raise ValueError(f"Tool module {module_name!r} CREATE_RESPONSE must be a boolean")
    _validate_tool_config(tools, executor)
    return tools, executor, create_response


def _validate_tool_config(tools: list[dict[str, Any]], executor: ToolExecutor | None) -> dict[str, Any]:
    if tools and executor is None:
        raise ValueError("A tool_executor is required when tools are configured")
    if tools and not callable(executor):
        raise ValueError("tool_executor must be callable")
    validators: dict[str, Any] = {}
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError("Each local client tool must be a function tool definition")
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Each local client tool must have a non-empty name")
        if name in validators:
            raise ValueError(f"Duplicate local client tool name: {name}")
        parameters = tool.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(f"Tool {name!r} parameters must be a JSON Schema object")
        validator_class = validator_for(parameters)
        try:
            validator_class.check_schema(parameters)
        except SchemaError as exc:
            raise ValueError(f"Tool {name!r} parameters are not a valid JSON Schema: {exc}") from exc
        validators[name] = validator_class(parameters)
    return validators


def normalize_realtime_url(url: str) -> tuple[str, str]:
    """Convert a full Realtime endpoint into the base URLs expected by the SDK."""

    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"ws", "wss", "http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an absolute ws://, wss://, http://, or https:// URL")
    if parsed.query or parsed.fragment:
        raise ValueError("--url must not include a query string or fragment")

    path = parsed.path.rstrip("/")
    if not path.endswith("/realtime"):
        raise ValueError("--url must be the full Realtime endpoint ending in /realtime")

    sdk_path = path[: -len("/realtime")]
    websocket_scheme = "wss" if parsed.scheme in {"wss", "https"} else "ws"
    http_scheme = "https" if websocket_scheme == "wss" else "http"
    websocket_base_url = urlunsplit((websocket_scheme, parsed.netloc, sdk_path, "", ""))
    base_url = urlunsplit((http_scheme, parsed.netloc, sdk_path, "", ""))
    return base_url, websocket_base_url


def _make_client(config: RealtimeAudioClientConfig) -> AsyncOpenAI:
    base_url, websocket_base_url = normalize_realtime_url(config.url)
    client_kwargs: dict[str, Any] = {
        "base_url": base_url,
        "websocket_base_url": websocket_base_url,
    }
    api_key = config.api_key
    if api_key is None:
        hostname = urlsplit(config.url.strip()).hostname
        try:
            is_loopback = hostname == "localhost" or (hostname is not None and ip_address(hostname).is_loopback)
        except ValueError:
            is_loopback = False
        if is_loopback:
            api_key = "local"
    # Omitting the key for non-loopback endpoints lets the SDK read OPENAI_API_KEY.
    if api_key is not None:
        client_kwargs["api_key"] = api_key
    return AsyncOpenAI(**client_kwargs)


def build_session_update(config: RealtimeAudioClientConfig) -> dict[str, Any]:
    """Build the Realtime session update used by local and standalone clients."""

    _validate_tool_config(config.tools, config.tool_executor)

    def maybe_pcm_format(rate: int) -> Optional[dict[str, Any]]:
        # The OpenAI SDK models only validate explicit PCM formats at 24 kHz.
        # Omitting the format selects this server's native 16 kHz pipeline rate.
        if rate == 16000:
            return None
        if rate == 24000:
            return {"type": "audio/pcm", "rate": 24000}
        raise ValueError(
            f"Unsupported rate {rate}. Use 16000 for the local pipeline default "
            "or 24000 for the OpenAI Realtime PCM schema."
        )

    turn_detection: dict[str, Any] = {"type": "server_vad", "interrupt_response": config.interrupt_response}
    if config.vad_threshold is not None:
        turn_detection["threshold"] = config.vad_threshold
    input_config: dict[str, Any] = {"turn_detection": turn_detection}
    output_config: dict[str, Any] = {}

    input_format = maybe_pcm_format(config.send_rate)
    output_format = maybe_pcm_format(config.recv_rate)
    if input_format is not None:
        input_config["format"] = input_format
    if output_format is not None:
        output_config["format"] = output_format
    if config.voice:
        output_config["voice"] = config.voice

    session: dict[str, Any] = {
        "type": "realtime",
        "extensions": ["speech_to_speech.input_audio_transcription.snapshot"],
        "audio": {
            "input": input_config,
            "output": output_config,
        },
    }
    if config.instructions:
        session["instructions"] = config.instructions
    if config.tools:
        session["tools"] = config.tools
        session["tool_choice"] = "auto"
    return {"type": "session.update", "session": session}


# Retrieve requests the client sends to learn what an interrupted reply left in history.
_HEARD_TEXT_EVENT_PREFIX = "heard_text_"
# Assistant lines remembered for comparison with their heard text.
_ASSISTANT_LINE_HISTORY = 32


class _AssistantLineGuard(logging.Handler):
    """Note that log output followed the last assistant line."""

    def __init__(self, renderer: _FriendlyEventRenderer) -> None:
        super().__init__()
        self._renderer = renderer

    def emit(self, record: logging.LogRecord) -> None:
        self._renderer.last_assistant_line = None


def _heard_text_event_id(item_id: str) -> str:
    return f"{_HEARD_TEXT_EVENT_PREFIX}{item_id}"


def _assistant_item_text(item: Any) -> str:
    """Join an assistant item's transcript or text parts the way they streamed."""
    parts = (getattr(part, "transcript", None) or getattr(part, "text", None) for part in item.content or [])
    return " ".join(part.strip() for part in parts if part and part.strip())


class _FriendlyEventRenderer:
    def __init__(self, *, conversation_only: bool = False, console: Console | None = None) -> None:
        self.conversation_only = conversation_only
        self.console = console or Console(highlight=False, markup=False, soft_wrap=True)
        self.ready_announced = False
        # Input transcription events can arrive out of order across items.
        self.user_transcript_by_item: dict[str | None, str] = {}
        self.user_snapshot_by_item: dict[str | None, str] = {}
        self.live_user_width = 0
        self.saw_user_speech = False
        self.live_assistant_stream: _AssistantTranscriptStream | None = None
        self.streamed_assistant_transcripts: set[_AssistantTranscriptStream] = set()
        self.status = ""
        self.status_visible = False
        self.live_assistant_text = ""
        self.assistant_text_by_item: dict[str, str] = {}
        # (item id, terminal rows) of an assistant line when it is the last output.
        self.last_assistant_line: tuple[str, int] | None = None

    def print_conversation(self, text: str, *, style: str, end: str = "\n") -> None:
        self.last_assistant_line = None
        self._clear_status()
        if self.conversation_only:
            self.console.print(text, style=style, end=end, markup=False, emoji=False, highlight=False, soft_wrap=True)
        else:
            print(text, end=end, flush=True)
        if end == "\n":
            self._draw_status()

    def show_status(self, text: str) -> None:
        """Keep one status line below the conversation, rewritten in place on a terminal."""
        if not (self.conversation_only and self.console.is_terminal):
            self.print_conversation(text, style="cyan")
            return
        # A wrapped line could not be cleared in place.
        self.status = text[: max(1, self.console.width - 1)]
        self._draw_status()

    def clear_status(self) -> None:
        self._clear_status()
        self.status = ""

    def _clear_status(self) -> None:
        if self.status_visible:
            self.console.file.write("\r\x1b[2K")
            self.console.file.flush()
            self.status_visible = False

    def _draw_status(self) -> None:
        # Wait for a streamed assistant line to finish before taking the cursor line.
        if not self.status or self.live_assistant_stream is not None:
            return
        self._clear_status()
        self.console.print(self.status, style="cyan", end="", markup=False, highlight=False, soft_wrap=True)
        self.status_visible = True

    def announce_ready(self) -> None:
        if self.conversation_only and not self.ready_announced:
            self.print_conversation("Ready — start speaking.", style="cyan")
            self.ready_announced = True

    def render_live_user_text(self, text: str, *, final: bool = False) -> None:
        line = f"USER: {text}"
        if self.conversation_only:
            if final:
                self.print_conversation(line, style="yellow")
            return
        padded = line + (" " * max(0, self.live_user_width - len(line)))
        if final:
            print(f"\r{padded}", flush=True)
            self.live_user_width = 0
            return
        print(f"\r{padded}", end="", flush=True)
        self.live_user_width = len(line)

    def clear_live_user_text(self) -> None:
        if self.live_user_width == 0:
            return
        print("\r" + (" " * self.live_user_width) + "\r", end="", flush=True)
        self.live_user_width = 0

    @staticmethod
    def _assistant_stream_key(event: Any) -> _AssistantTranscriptStream:
        return (
            getattr(event, "response_id", None),
            getattr(event, "item_id", None),
            getattr(event, "output_index", None),
            getattr(event, "content_index", None),
        )

    def render_assistant_text_delta(self, event: Any) -> None:
        delta = event.delta or ""
        if not delta:
            return
        self.clear_live_user_text()
        stream_key = self._assistant_stream_key(event)
        if self.live_assistant_stream != stream_key:
            self.finish_live_assistant_text()
            delta = delta.lstrip()
            if not delta:
                return
            self.print_conversation("ASSISTANT: ", style="green", end="")
            self.live_assistant_stream = stream_key
            self.live_assistant_text = ""
        self.streamed_assistant_transcripts.add(stream_key)
        self.print_conversation(delta, style="green", end="")
        self.live_assistant_text += delta

    def render_assistant_text_done(self, event: Any) -> None:
        stream_key = self._assistant_stream_key(event)
        if self.live_assistant_stream == stream_key:
            self.finish_live_assistant_text()
        if stream_key in self.streamed_assistant_transcripts:
            self.streamed_assistant_transcripts.remove(stream_key)
            return
        self.clear_live_user_text()
        self.finish_live_assistant_text()
        transcript = event.transcript or ""
        self.print_conversation(f"ASSISTANT: {transcript}", style="green")
        self._remember_assistant_line(getattr(event, "item_id", None), transcript)

    def finish_live_assistant_text(self) -> None:
        if self.live_assistant_stream is not None:
            item_id = self.live_assistant_stream[1]
            self.live_assistant_stream = None
            self.print_conversation("", style="green")
            self._remember_assistant_line(item_id, self.live_assistant_text)
            self.live_assistant_text = ""

    def _remember_assistant_line(self, item_id: str | None, text: str) -> None:
        if item_id is None:
            return
        self.assistant_text_by_item.pop(item_id, None)
        self.assistant_text_by_item[item_id] = text
        while len(self.assistant_text_by_item) > _ASSISTANT_LINE_HISTORY:
            self.assistant_text_by_item.pop(next(iter(self.assistant_text_by_item)))
        width = max(1, self.console.width)
        rows = sum(max(1, -(-cell_len(row.expandtabs(8)) // width)) for row in f"ASSISTANT: {text}".split("\n"))
        self.last_assistant_line = (item_id, rows)

    def render_heard_assistant_text(self, item_id: str, heard: str) -> None:
        """Show the part of an interrupted reply that the model history kept.

        The reply's line is redrawn in place while it is still the last line on
        a terminal; otherwise the heard text is printed as a new line.
        """
        shown = self.assistant_text_by_item.get(item_id)
        if shown is not None and " ".join(shown.split()) == " ".join(heard.split()):
            return
        self.clear_live_user_text()
        self.finish_live_assistant_text()
        last = self.last_assistant_line
        if self.conversation_only and self.console.is_terminal and last is not None and last[0] == item_id:
            self._clear_status()
            self.console.file.write(f"\x1b[{last[1]}F\x1b[J")
            self.console.file.flush()
        self.assistant_text_by_item.pop(item_id, None)
        line = f"ASSISTANT: {heard} [interrupted]" if heard else "ASSISTANT: [interrupted, nothing heard]"
        self.print_conversation(line, style="green")

    def reset_assistant_text(self) -> None:
        self.finish_live_assistant_text()
        self.streamed_assistant_transcripts.clear()

    def finish_assistant_response(self, response_id: str | None) -> None:
        self.finish_live_assistant_text()
        self.streamed_assistant_transcripts = {
            stream_key for stream_key in self.streamed_assistant_transcripts if stream_key[0] != response_id
        }


def handle_server_event(
    event: Any,
    *,
    playback: PlaybackBuffer | _PlaybackCommands,
    renderer: _FriendlyEventRenderer,
    print_json: bool,
    interrupt_response: bool = True,
) -> None:
    """Apply one Realtime lifecycle event to local playback and console state."""

    if print_json:
        renderer.finish_live_assistant_text()
        renderer.last_assistant_line = None
        try:
            print(f"EVENT: {event.model_dump_json()}", flush=True)
        except Exception:
            print(f"EVENT: {event}", flush=True)

    if renderer.conversation_only and event.type in {
        "speech_to_speech.input_audio_transcription.snapshot",
        "conversation.item.input_audio_transcription.delta",
    }:
        # Only the final transcript belongs in this display. Hidden partials must
        # not end an assistant line or leave drafts in redirected terminal output.
        return

    if event.type == "session.created":
        renderer.finish_live_assistant_text()
        if not renderer.conversation_only:
            print("Connected.", flush=True)
    elif event.type == "session.updated":
        if renderer.conversation_only:
            renderer.announce_ready()
        else:
            renderer.finish_live_assistant_text()
            print(f"EVENT: {event.type}", flush=True)
    elif event.type == "input_audio_buffer.speech_started":
        renderer.finish_live_assistant_text()
        # Without barge-in the server keeps the response, so its queued audio must keep playing.
        if interrupt_response:
            playback.clear()
        if renderer.saw_user_speech and not renderer.conversation_only:
            print("", flush=True)
        renderer.saw_user_speech = True
    elif event.type == "input_audio_buffer.speech_stopped":
        return
    elif event.type == "speech_to_speech.input_audio_transcription.snapshot":
        renderer.finish_live_assistant_text()
        item_id = getattr(event, "item_id", None)
        transcript = getattr(event, "transcript", "") or ""
        renderer.user_snapshot_by_item[item_id] = transcript
        display_text = transcript.strip()
        if display_text:
            renderer.render_live_user_text(display_text)
    elif event.type == "conversation.item.input_audio_transcription.delta":
        renderer.finish_live_assistant_text()
        item_id = getattr(event, "item_id", None)
        transcript = renderer.user_transcript_by_item.get(item_id, "") + (event.delta or "")
        renderer.user_transcript_by_item[item_id] = transcript
        snapshot = renderer.user_snapshot_by_item.get(item_id)
        display_text = (snapshot if snapshot is not None else transcript).strip()
        if display_text:
            renderer.render_live_user_text(display_text)
    elif event.type == "conversation.item.input_audio_transcription.completed":
        renderer.finish_live_assistant_text()
        item_id = getattr(event, "item_id", None)
        cleaned = (event.transcript or "").strip()
        if cleaned:
            renderer.render_live_user_text(cleaned, final=True)
        else:
            renderer.clear_live_user_text()
        renderer.user_transcript_by_item.pop(item_id, None)
        renderer.user_snapshot_by_item.pop(item_id, None)
    elif event.type == "conversation.item.input_audio_transcription.failed":
        renderer.clear_live_user_text()
        renderer.finish_live_assistant_text()
        item_id = getattr(event, "item_id", None)
        renderer.user_transcript_by_item.pop(item_id, None)
        renderer.user_snapshot_by_item.pop(item_id, None)
        error = getattr(event, "error", None)
        err_type = getattr(error, "type", "transcription_error") if error else "transcription_error"
        err_msg = (
            getattr(error, "message", "Input audio transcription failed")
            if error
            else "Input audio transcription failed"
        )
        renderer.print_conversation(f"ERROR: {err_type}: {err_msg}", style="red")
    elif event.type == "response.created":
        renderer.clear_live_user_text()
        renderer.finish_live_assistant_text()
        if not renderer.conversation_only:
            print("ASSISTANT: <response started>", flush=True)
    elif event.type in {"response.output_item.added", "response.output_item.done"}:
        return
    elif event.type == "response.output_audio.delta":
        item_id = getattr(event, "item_id", None)
        item = (item_id, getattr(event, "content_index", 0)) if item_id is not None else None
        playback.append(base64.b64decode(event.delta), item)
    elif event.type == "response.output_audio.done":
        playback.finish()
        renderer.finish_live_assistant_text()
        if not renderer.conversation_only:
            print("ASSISTANT: <audio done>", flush=True)
    elif event.type == "response.output_audio_transcript.delta":
        renderer.render_assistant_text_delta(event)
    elif event.type == "response.output_audio_transcript.done":
        renderer.render_assistant_text_done(event)
    elif event.type == "response.function_call_arguments.done":
        if not renderer.conversation_only:
            renderer.finish_live_assistant_text()
            print(
                f"TOOL: {event.name} call_id={event.call_id} arguments={event.arguments}",
                flush=True,
            )
    elif event.type == "response.done":
        renderer.finish_assistant_response(getattr(event.response, "id", None))
        if event.response.status == "cancelled":
            playback.clear()
        else:
            playback.finish()
        if not renderer.conversation_only:
            print(f"ASSISTANT: <response {event.response.status}>", flush=True)
        elif event.response.status not in {"completed", "cancelled"}:
            renderer.print_conversation(f"ERROR: response {event.response.status}", style="red")
    elif event.type == "output_audio_buffer.cleared":
        playback.clear()
    elif event.type == "conversation.item.retrieved":
        item = event.item
        # Only a cut item carries heard text; a reply still generating or one
        # that played to the end keeps the transcript already shown.
        if getattr(item, "role", None) == "assistant" and item.id is not None and item.status == "incomplete":
            renderer.render_heard_assistant_text(item.id, _assistant_item_text(item))
    elif (
        event.type == "error"
        and event.error.type == "conversation_item_not_found"
        and (getattr(event.error, "event_id", None) or "").startswith(_HEARD_TEXT_EVENT_PREFIX)
    ):
        # The interrupted reply was removed from history: none of it was heard.
        renderer.render_heard_assistant_text(event.error.event_id.removeprefix(_HEARD_TEXT_EVENT_PREFIX), "")
    elif event.type == "error":
        renderer.clear_live_user_text()
        renderer.finish_live_assistant_text()
        renderer.print_conversation(f"ERROR: {event.error.type}: {event.error.message}", style="red")
    else:
        if not renderer.conversation_only:
            renderer.clear_live_user_text()
            renderer.finish_live_assistant_text()
            print(f"EVENT: {event.type}", flush=True)


@dataclass(frozen=True)
class _ToolExecutionResult:
    call_id: str
    output: str
    create_response: bool


@dataclass
class _ToolResponseBatch:
    """Execution and delivery state scoped to one Realtime response."""

    call_ids: set[str] = field(default_factory=set)
    execution_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    output_indices: dict[str, int] = field(default_factory=dict)
    authoritative_call_ids: set[str] = field(default_factory=set)
    ordered_call_ids: list[str] = field(default_factory=list)
    delivered_call_ids: set[str] = field(default_factory=set)
    results: dict[str, _ToolExecutionResult] = field(default_factory=dict)
    pending_deliveries: int = 0
    completed: bool = False
    successful: bool = False
    cancelled: bool = False
    create_response: bool = False


class _ToolCoordinatorError(RuntimeError):
    """Raised when the server rejects a tool follow-up response permanently."""


class _ToolCallCoordinator:
    """Execute declared tools without blocking event reception or racing responses."""

    def __init__(
        self,
        conn: Any,
        config: RealtimeAudioClientConfig,
        report: Callable[[str], None] | None = None,
    ) -> None:
        self._conn = conn
        self._report = report or (lambda line: print(line, flush=True))
        self._executor = config.tool_executor
        self._tool_validators = _validate_tool_config(config.tools, self._executor)
        self._default_create_response = config.tool_response_create
        self._active_response_id: str | None = None
        self._pending_tool_flushes = 0
        self._pending_create_id: str | None = None
        self._pending_create_saw_response = False
        self._waiting_for_response_after_collision = False
        # Keep results in history while speech can still reopen.
        self._user_turn_open = False
        self._user_turn_item_id: str | None = None
        self._queued_tool_results: dict[str, set[str]] = {}
        self._pending_create_call_ids: set[str] = set()
        self._pending_create_marked_call_ids: set[str] = set()
        self._answered_tool_call_ids: set[str] = set()
        self._next_create_sequence = 0
        self._tool_batches: dict[str, _ToolResponseBatch] = {}
        self._tool_batch_order: list[str] = []
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._delivery_lock = asyncio.Lock()
        self._follow_up_lock = asyncio.Lock()
        self._failure: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._closing = False

    def handle_event(self, event: Any) -> None:
        if self._closing:
            return
        if event.type == "response.created":
            response = event.response
            self._active_response_id = getattr(response, "id", None)
            metadata = getattr(response, "metadata", None)
            create_id = metadata.get(_TOOL_CREATE_ID_METADATA_KEY) if isinstance(metadata, Mapping) else None
            if create_id and create_id == self._pending_create_id:
                self._pending_create_id = None
                self._pending_create_saw_response = False
                self._consume_tool_results(self._pending_create_call_ids)
                self._pending_create_call_ids.clear()
                self._pending_create_marked_call_ids.clear()
            elif self._pending_create_id is not None:
                self._pending_create_saw_response = True
        elif event.type == "response.output_item.added":
            item = getattr(event, "item", None)
            if getattr(item, "type", None) == "function_call":
                response_id = getattr(event, "response_id", None) or self._active_response_id
                output_index = getattr(event, "output_index", None)
                call_id = getattr(item, "call_id", None)
                if (
                    isinstance(response_id, str)
                    and response_id
                    and isinstance(output_index, int)
                    and isinstance(call_id, str)
                    and call_id
                ):
                    self._register_call_order(response_id, call_id, output_index)
        elif event.type == "response.function_call_arguments.done":
            response_id = getattr(event, "response_id", None) or self._active_response_id
            if isinstance(response_id, str) and response_id:
                self._schedule_call(response_id, event)
        elif event.type == "response.done":
            self._handle_response_done(event.response)
        elif event.type == "error":
            self._handle_error(event.error)
        elif event.type == "input_audio_buffer.speech_started":
            self._user_turn_open = True
            self._user_turn_item_id = getattr(event, "item_id", None)
        elif event.type == "input_audio_buffer.committed":
            if self._user_turn_open and self._user_turn_item_id in (None, getattr(event, "item_id", None)):
                self._user_turn_open = False
                self._kick_follow_up()
        elif event.type == "conversation.item.input_audio_transcription.completed":
            if self._waiting_for_response_after_collision:
                self._waiting_for_response_after_collision = False
                self._kick_follow_up()

    async def _execute_tool(self, call_id: str, name: Any, raw_arguments: Any) -> _ToolExecutionResult:
        display_name = name if isinstance(name, str) and name else "<unnamed>"
        create_response = self._default_create_response
        try:
            if not isinstance(name, str) or name not in self._tool_validators:
                raise ValueError(f"unknown tool {display_name!r}")
            if not isinstance(raw_arguments, str):
                raise ValueError("arguments must be a JSON string")
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(f"arguments are not valid JSON: {exc.msg}") from exc
            if not isinstance(arguments, dict):
                raise ValueError("arguments must decode to a JSON object")
            try:
                self._tool_validators[name].validate(arguments)
            except ValidationError as exc:
                raise ValueError(f"arguments do not match the declared schema: {exc.message}") from exc

            assert self._executor is not None
            pending_result = self._executor(name, arguments)
            if not inspect.isawaitable(pending_result):
                raise TypeError("tool_executor must return an awaitable")
            result = await pending_result
            if isinstance(result, ToolResult):
                if not isinstance(result.create_response, bool):
                    raise TypeError("ToolResult.create_response must be a boolean")
                create_response = result.create_response
                result = result.output
            if isinstance(result, str):
                output = result
            else:
                try:
                    output = json.dumps(result)
                except (TypeError, ValueError) as exc:
                    raise ValueError("tool result is not JSON serializable") from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            log_exception(logger, f"Local tool {display_name} failed", exc, level=logging.DEBUG)
            self._report(f"TOOL ERROR: {display_name} call_id={call_id}: {message}")
            output = json.dumps({"error": message})
            create_response = True
        return _ToolExecutionResult(call_id=call_id, output=output, create_response=create_response)

    def _handle_response_done(self, response: Any) -> None:
        response_id = getattr(response, "id", None)
        if response_id == self._active_response_id:
            self._active_response_id = None
        self._waiting_for_response_after_collision = False
        status = getattr(response, "status", None)
        metadata = getattr(response, "metadata", None)
        if status == "completed" and getattr(response, "output", None) and isinstance(metadata, Mapping):
            self._answered_tool_call_ids.update(tool_call_ids(metadata.get(TOOL_INPUT_METADATA_KEY)))
            self._consume_tool_results(self._answered_tool_call_ids)
            outstanding = set().union(*(batch.call_ids for batch in self._tool_batches.values()))
            self._answered_tool_call_ids.intersection_update(outstanding)
        if isinstance(response_id, str) and response_id and status == "completed":
            output = getattr(response, "output", None) or []
            calls = [
                (output_index, item)
                for output_index, item in enumerate(output)
                if getattr(item, "type", None) == "function_call"
            ]
            batch = self._tool_batches.get(response_id)
            if calls and batch is None:
                batch = self._batch(response_id)
            for output_index, call in calls:
                call_id = getattr(call, "call_id", None)
                if isinstance(call_id, str) and call_id:
                    self._register_call_order(response_id, call_id, output_index, kick=False)
                self._schedule_call(response_id, call)
            if batch is not None:
                batch.completed = True
                batch.successful = True
                self._kick_delivery()
        elif isinstance(response_id, str) and response_id:
            batch = self._tool_batches.get(response_id)
            if batch is not None:
                self._cancel_batch(response_id, batch)
        self._kick_follow_up()

    def _batch(self, response_id: str) -> _ToolResponseBatch:
        batch = self._tool_batches.get(response_id)
        if batch is None:
            batch = _ToolResponseBatch()
            self._tool_batches[response_id] = batch
            self._tool_batch_order.append(response_id)
        return batch

    def _register_call_order(
        self,
        response_id: str,
        call_id: str,
        output_index: int,
        *,
        kick: bool = True,
    ) -> None:
        batch = self._batch(response_id)
        if call_id in batch.delivered_call_ids:
            return
        batch.output_indices[call_id] = output_index
        batch.authoritative_call_ids.add(call_id)
        batch.ordered_call_ids = sorted(
            batch.authoritative_call_ids,
            key=batch.output_indices.__getitem__,
        )
        if kick:
            self._kick_delivery()

    def _schedule_call(self, response_id: str, call: Any) -> None:
        call_id = getattr(call, "call_id", None)
        if not isinstance(call_id, str) or not call_id:
            self._report("TOOL ERROR: received a call without call_id; cannot return an output")
            return
        batch = self._batch(response_id)
        if call_id in batch.call_ids:
            return
        batch.call_ids.add(call_id)
        output_index = getattr(call, "output_index", None)
        if isinstance(output_index, int):
            batch.output_indices.setdefault(call_id, output_index)
        batch.pending_deliveries += 1
        self._pending_tool_flushes += 1

        async def execute() -> None:
            result = await self._execute_tool(
                call_id,
                getattr(call, "name", None),
                getattr(call, "arguments", None),
            )
            if not batch.cancelled:
                batch.results[call_id] = result
                self._kick_delivery()

        execution = asyncio.create_task(execute())
        batch.execution_tasks.add(execution)
        execution.add_done_callback(batch.execution_tasks.discard)
        self._track(execution, report_errors=True)

    def _kick_delivery(self) -> None:
        task = asyncio.create_task(self._deliver_ready_results())
        self._track(task, report_errors=True)

    async def _deliver_ready_results(self) -> None:
        async with self._delivery_lock:
            while self._tool_batch_order:
                response_id = self._tool_batch_order[0]
                batch = self._tool_batches.get(response_id)
                if batch is None or batch.cancelled:
                    self._tool_batch_order.pop(0)
                    continue
                if batch.ordered_call_ids:
                    call_id = batch.ordered_call_ids[0]
                    result = batch.results.get(call_id)
                    if result is None:
                        return
                    await self._conn.send(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": result.call_id,
                                "output": result.output,
                            },
                        }
                    )
                    # response.done can cancel the batch while send() is
                    # suspended on transport backpressure. _cancel_batch()
                    # already releases its counters, so do not account for the
                    # same delivery a second time when the send resumes.
                    if batch.cancelled:
                        return
                    batch.ordered_call_ids.pop(0)
                    batch.authoritative_call_ids.discard(call_id)
                    batch.delivered_call_ids.add(call_id)
                    batch.results.pop(call_id, None)
                    batch.pending_deliveries -= 1
                    self._pending_tool_flushes -= 1
                    batch.create_response = batch.create_response or result.create_response
                    continue
                if batch.completed and batch.pending_deliveries == 0:
                    self._finalize_batch_if_ready(response_id, batch)
                    continue
                return

    def _finalize_batch_if_ready(self, response_id: str, batch: _ToolResponseBatch) -> None:
        if not batch.completed or batch.pending_deliveries > 0:
            return
        if self._tool_batches.get(response_id) is batch:
            self._tool_batches.pop(response_id, None)
        if response_id in self._tool_batch_order:
            self._tool_batch_order.remove(response_id)
        if batch.successful and not batch.cancelled and batch.create_response:
            remaining = batch.delivered_call_ids - self._answered_tool_call_ids
            self._answered_tool_call_ids.difference_update(batch.delivered_call_ids)
            if remaining:
                self._queued_tool_results[response_id] = remaining
        self._kick_follow_up()

    def _consume_tool_results(self, call_ids: set[str]) -> None:
        for response_id, pending in list(self._queued_tool_results.items()):
            pending.difference_update(call_ids)
            if not pending:
                del self._queued_tool_results[response_id]

    def _cancel_batch(self, response_id: str, batch: _ToolResponseBatch) -> None:
        batch.cancelled = True
        self._pending_tool_flushes -= batch.pending_deliveries
        batch.pending_deliveries = 0
        self._tool_batches.pop(response_id, None)
        if response_id in self._tool_batch_order:
            self._tool_batch_order.remove(response_id)
        for task in tuple(batch.execution_tasks):
            task.cancel()
        self._kick_delivery()

    def _handle_error(self, error: Any) -> None:
        if getattr(error, "event_id", None) != self._pending_create_id:
            return
        is_collision = "conversation_already_has_active_response" in {
            getattr(error, "type", None),
            getattr(error, "code", None),
        }
        if self._pending_create_id is None:
            return
        rejected_create_id = self._pending_create_id
        self._pending_create_id = None

        if TOOL_FOLLOWUP_COVERED in {getattr(error, "type", None), getattr(error, "code", None)}:
            self._consume_tool_results(self._pending_create_marked_call_ids)
            self._pending_create_call_ids.clear()
            self._pending_create_marked_call_ids.clear()
            self._pending_create_saw_response = False
            self._kick_follow_up()
            return
        self._pending_create_call_ids.clear()
        self._pending_create_marked_call_ids.clear()
        if TOOL_FOLLOWUP_WAIT in {getattr(error, "type", None), getattr(error, "code", None)}:
            self._pending_create_saw_response = False
            self._user_turn_open = True
            return
        if not is_collision:
            self._pending_create_saw_response = False
            self._closing = True
            message = getattr(error, "message", None) or "unknown error"
            error_type = getattr(error, "type", None) or "unknown_error"
            code = getattr(error, "code", None)
            detail = f"{error_type}/{code}" if code else error_type
            if not self._failure.done():
                self._failure.set_exception(
                    _ToolCoordinatorError(
                        f"Tool follow-up response.create {rejected_create_id!r} was rejected ({detail}): {message}"
                    )
                )
            return

        response_already_finished = self._pending_create_saw_response and self._active_response_id is None
        self._waiting_for_response_after_collision = not self._pending_create_saw_response
        self._pending_create_saw_response = False
        if response_already_finished:
            self._kick_follow_up()

    def _kick_follow_up(self) -> None:
        task = asyncio.create_task(self._maybe_send_follow_up())
        self._track(task, report_errors=True)

    async def _maybe_send_follow_up(self) -> None:
        async with self._follow_up_lock:
            if (
                self._closing
                or self._pending_tool_flushes > 0
                or not self._queued_tool_results
                or self._active_response_id is not None
                or self._pending_create_id is not None
                or self._waiting_for_response_after_collision
                or self._user_turn_open
            ):
                return
            pending_call_ids = set().union(*self._queued_tool_results.values())
            call_ids: set[str] = set()
            for call_id in sorted(pending_call_ids):
                candidate = call_ids | {call_id}
                if len(json.dumps(sorted(candidate), separators=(",", ":"))) > 512:
                    break
                call_ids = candidate
            metadata = {_TOOL_CREATE_ID_METADATA_KEY: f"tool_{self._next_create_sequence + 1}"}
            # Omit the marker when no provider call IDs fit within its budget.
            if call_ids:
                metadata[TOOL_FOLLOWUP_METADATA_KEY] = json.dumps(sorted(call_ids), separators=(",", ":"))
            # Acceptance covers the full snapshot; an already-answered rejection covers only marked IDs.
            self._pending_create_call_ids = pending_call_ids
            self._pending_create_marked_call_ids = call_ids
            self._next_create_sequence += 1
            create_id = f"tool_{self._next_create_sequence}"
            self._pending_create_id = create_id
            self._pending_create_saw_response = False
            try:
                await self._conn.send(
                    {
                        "event_id": create_id,
                        "type": "response.create",
                        "response": {"metadata": metadata},
                    }
                )
            except BaseException:
                self._pending_create_id = None
                self._pending_create_call_ids.clear()
                self._pending_create_marked_call_ids.clear()
                self._pending_create_saw_response = False
                raise

    def _track(self, task: asyncio.Task[Any], *, report_errors: bool = False) -> None:
        self._background_tasks.add(task)

        def done(completed: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(completed)
            if report_errors and not completed.cancelled():
                exception = completed.exception()
                if exception is not None and not self._failure.done():
                    self._failure.set_exception(exception)

        task.add_done_callback(done)

    async def wait_for_failure(self) -> None:
        await asyncio.shield(self._failure)

    async def close(self) -> None:
        self._closing = True
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if not self._failure.done():
            self._failure.cancel()


async def _wait_for_stop(stop_event: Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(stop_event.wait, 0.1)


class _AudioWorker:
    """Keep device callbacks independent of model and tool code's Python GIL."""

    def __init__(self, config: RealtimeAudioClientConfig) -> None:
        context = multiprocessing.get_context("spawn")
        self.mic_queue = context.Queue(maxsize=128)
        self.truncations = context.Queue()
        self._commands = context.Queue()
        # Pending playback can be discarded when the worker exits.
        self._commands._ignore_epipe = True  # type: ignore[attr-defined]
        self._stop = context.Event()
        self._ready = context.Event()
        self.playback = _PlaybackCommands(self._commands)
        self._errors, self._error_sender = context.Pipe(duplex=False)
        # Keep executors and their state in the parent; the worker only needs
        # hardware settings and audio, not models, tools or network credentials.
        worker_config = AudioWorkerConfig(
            send_rate=config.send_rate,
            recv_rate=config.recv_rate,
            chunk_size=config.chunk_size,
            playback_buffer_ms=config.playback_buffer_ms,
            input_device=config.input_device,
            output_device=config.output_device,
            echo_cancellation=config.echo_cancellation,
            block_mic_during_playback=config.block_mic_during_playback,
        )
        self._process = context.Process(
            target=_run_audio_worker,
            args=(
                worker_config,
                self.mic_queue,
                self._commands,
                self._stop,
                self._error_sender,
                self._ready,
                self.truncations,
            ),
            name="realtime-audio",
        )

    def __enter__(self) -> _AudioWorker:
        try:
            self._process.start()
        except Exception:
            self.__exit__(None, None, None)
            raise
        # Only the child writes microphone PCM. Keeping this duplicate open would
        # leave a read of a partial queue message blocked if the child dies.
        self.mic_queue._writer.close()  # type: ignore[attr-defined]
        self.truncations._writer.close()  # type: ignore[attr-defined]
        # Only the child reads playback. Close our duplicate so its exit also
        # releases the queue feeder when it is blocked writing pending audio.
        self._commands._reader.close()  # type: ignore[attr-defined]
        self._error_sender.close()
        return self

    async def wait_for_failure(self) -> NoReturn:
        while self._process.is_alive():
            await asyncio.sleep(0.1)
        message = "Audio process stopped unexpectedly"
        try:
            if self._errors.poll():
                message = self._errors.recv()
        except (EOFError, OSError):
            pass
        logger.error("Local audio process failed: %s", message)
        raise RuntimeError(message)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self._stop.set()
        if self._process.pid is not None:
            self._process.join(timeout=5)
            if self._process.is_alive():
                logger.warning("Stopping an unresponsive local audio process")
                self._process.terminate()
                self._process.join(timeout=5)
        self._commands.cancel_join_thread()
        self._commands.close()
        self.mic_queue.close()
        self.truncations.close()
        self._errors.close()
        self._error_sender.close()


async def _run_audio_session(
    conn: Any,
    config: RealtimeAudioClientConfig,
    stop_event: Event,
) -> None:
    worker = _AudioWorker(config) if config.echo_cancellation else None
    mic_queue: Any = worker.mic_queue if worker is not None else Queue(maxsize=128)
    truncations: Any = worker.truncations if worker is not None else Queue()
    playback: PlaybackBuffer | _PlaybackCommands
    audio_context: AbstractContextManager[Any]
    if worker is None:
        playback = PlaybackBuffer(config.recv_rate, config.playback_buffer_ms, truncations.put_nowait)
        audio_context = _open_audio_streams(config, playback, mic_queue)
    else:
        playback = worker.playback
        audio_context = worker
    renderer = _FriendlyEventRenderer(conversation_only=config.conversation_only)
    tool_calls = _ToolCallCoordinator(conn, config, lambda line: renderer.print_conversation(line, style="red"))
    # Log records reach the same terminal, so an assistant line they follow is
    # no longer the last output and must not be redrawn in place.
    output_guard = _AssistantLineGuard(renderer)
    logging.getLogger().addHandler(output_guard)

    voices = VoiceSelection(conn, config, renderer.show_status) if len(config.voice_choices) > 1 else None

    async def select_voices() -> None:
        assert voices is not None
        try:
            keys = arrow_steps()
            try:
                async for step in keys:
                    await voices.select(step)
            finally:
                await keys.aclose()
        except (OSError, ValueError, NotImplementedError):
            logger.debug("Terminal arrow controls unavailable", exc_info=True)
        # No terminal or stdin EOF must not disconnect a working audio session.
        await _wait_for_stop(stop_event)

    async def send_audio() -> None:
        while not stop_event.is_set():
            try:
                chunk = await asyncio.to_thread(mic_queue.get, True, 0.1)
            except Empty:
                continue
            except (EOFError, OSError):
                if worker is None:
                    raise
                await worker.wait_for_failure()
            await conn.send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }
            )

    async def send_truncations() -> None:
        """Tell the server how much interrupted assistant audio actually played."""
        while not stop_event.is_set():
            try:
                interrupted = await asyncio.to_thread(truncations.get, True, 0.1)
            except Empty:
                continue
            except (EOFError, OSError):
                if worker is None:
                    raise
                await worker.wait_for_failure()
            for item_id, content_index, audio_end_ms in interrupted:
                await conn.send(
                    {
                        "type": "conversation.item.truncate",
                        "item_id": item_id,
                        "content_index": content_index,
                        "audio_end_ms": audio_end_ms,
                    }
                )
                # The answer carries the heard text the model history kept.
                await conn.send(
                    {
                        "type": "conversation.item.retrieve",
                        "event_id": _heard_text_event_id(item_id),
                        "item_id": item_id,
                    }
                )

    async def receive_events() -> None:
        while worker is not None and not worker._ready.is_set():
            await asyncio.sleep(0.01)
        while not stop_event.is_set():
            event = await conn.recv()
            tool_calls.handle_event(event)
            if voices is not None:
                await voices.handle_event(event)
            handle_server_event(
                event,
                playback=playback,
                renderer=renderer,
                print_json=config.print_json,
                interrupt_response=config.interrupt_response,
            )

    streams = ExitStack()
    tasks: set[asyncio.Task[Any]] = set()
    try:
        streams.enter_context(audio_context)
        tasks = {
            asyncio.create_task(send_audio()),
            asyncio.create_task(send_truncations()),
            asyncio.create_task(receive_events()),
            asyncio.create_task(_wait_for_stop(stop_event)),
            asyncio.create_task(tool_calls.wait_for_failure()),
        }
        if voices is not None:
            voices.announce()
            if has_terminal_arrows():
                renderer.print_conversation(
                    "Use ←/→ or ↑/↓ to change voice; changes apply between replies. Ctrl+C stops.", style="cyan"
                )
                tasks.add(asyncio.create_task(select_voices()))

        if worker is not None:
            tasks.add(asyncio.create_task(worker.wait_for_failure()))

        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        server_closed = False
        for task in done:
            if task.cancelled() or task.exception() is None:
                continue
            if not isinstance(task.exception(), ConnectionClosed):
                raise task.exception()  # type: ignore[misc]
            server_closed = True
        # Shutdown closes the local server too; only report an unrequested close.
        if server_closed and not stop_event.is_set():
            renderer.clear_live_user_text()
            renderer.finish_live_assistant_text()
            renderer.print_conversation("Server closed the connection.", style="red")
        stop_event.set()
    except asyncio.CancelledError:
        stop_event.set()
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await tool_calls.close()
        finally:
            logging.getLogger().removeHandler(output_guard)
            streams.close()
            renderer.clear_live_user_text()
            renderer.reset_assistant_text()
            renderer.clear_status()


async def listen_and_play_realtime(
    config: RealtimeAudioClientConfig,
    *,
    stop_event: Event | None = None,
) -> None:
    """Connect microphone/speaker audio to a Realtime server over WebSocket."""

    owned_stop_event = stop_event is None
    stop_event = stop_event or Event()
    client = _make_client(config)
    connected = False
    retry_started = time.monotonic()

    try:
        while not stop_event.is_set():
            try:
                async with client.realtime.connect(model=config.model) as conn:
                    connected = True
                    await conn.send(build_session_update(config))  # type: ignore[arg-type]
                    await _run_audio_session(
                        conn,
                        config,
                        stop_event,
                    )
                    return
            except asyncio.CancelledError:
                raise
            except _ToolCoordinatorError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    return
                if connected or time.monotonic() - retry_started >= config.connection_retry_timeout_s:
                    raise
                logger.debug("Realtime loopback server is not ready yet: %s", exc)
                await asyncio.sleep(0.1)
    finally:
        if owned_stop_event:
            stop_event.set()
        await client.close()


def run_realtime_audio_client(config: RealtimeAudioClientConfig) -> None:
    """Run the audio client until SIGINT, SIGTERM, disconnect, or an error."""

    from speech_to_speech.pipeline.console import conversation_output

    if not config.conversation_only:
        logging.basicConfig(level=logging.INFO)
    stop_event = Event()
    previous_handlers: dict[signal.Signals, Any] = {}

    def request_shutdown(_sig: int, _frame: Any) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, request_shutdown)

    try:
        with conversation_output(config.conversation_only):
            asyncio.run(listen_and_play_realtime(config, stop_event=stop_event))
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


class RealtimeAudioClient:
    """ThreadManager handler that embeds the packaged client for ``local``."""

    def __init__(self, stop_event: Event, config: RealtimeAudioClientConfig) -> None:
        self.stop_event = stop_event
        self.config = config

    def run(self) -> None:
        try:
            asyncio.run(
                listen_and_play_realtime(
                    self.config,
                    stop_event=self.stop_event,
                )
            )
        except Exception:
            logger.exception("Local Realtime audio client stopped unexpectedly")
            self.stop_event.set()
