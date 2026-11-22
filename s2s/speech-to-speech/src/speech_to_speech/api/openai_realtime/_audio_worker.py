"""Lightweight audio device worker module for spawned playback/capture isolation.

Kept free of ``openai``, ``jsonschema``, ``websockets``, and ``rich`` imports so
Windows ``multiprocessing("spawn")`` starts the audio device process rapidly.
"""

from __future__ import annotations

import logging
import multiprocessing
import signal
import sys
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Empty, Full
from threading import Lock, Thread
from typing import Any, Optional

from speech_to_speech.api.openai_realtime.echo_canceller import EchoCanceller

logger = logging.getLogger(__name__)

_PLAYBACK_START_BUFFER_MS = 0.0
_PLAYBACK_TAIL_HOLD_S = 0.30

_AudioItem = tuple[str, int]
# Assistant audio cut off by an interruption: (item_id, content_index, played ms).
_PlaybackTruncation = tuple[str, int, int]


@dataclass(frozen=True)
class AudioWorkerConfig:
    """Minimal hardware audio settings pickled across the spawn boundary."""

    send_rate: int = 16000
    recv_rate: int = 16000
    chunk_size: int = 1024
    playback_buffer_ms: float = _PLAYBACK_START_BUFFER_MS
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    echo_cancellation: bool = True
    block_mic_during_playback: bool = False


class PlaybackBuffer:
    """Thread-safe audio state shared by the Realtime loop and sounddevice callbacks.

    Audio appended with its assistant item is tracked through playback. When
    ``clear()`` discards an item's unplayed audio, ``on_interrupted`` receives
    how much of that item played so the server can truncate its history.
    """

    def __init__(
        self,
        recv_rate: int,
        startup_buffer_ms: float = _PLAYBACK_START_BUFFER_MS,
        on_interrupted: Callable[[list[_PlaybackTruncation]], None] | None = None,
    ) -> None:
        if recv_rate <= 0:
            raise ValueError("recv_rate must be positive")
        if not 0 <= startup_buffer_ms < float("inf"):
            raise ValueError("startup_buffer_ms must be a finite non-negative number")
        self.recv_rate = recv_rate
        self._startup_buffer_bytes = int(recv_rate * 2 * startup_buffer_ms / 1000)
        self._startup_buffer_bytes -= self._startup_buffer_bytes % 2
        self._audio = bytearray()
        self._lock = Lock()
        self._active_until = 0.0
        self._playing = False
        self._input_complete = False
        self._on_interrupted = on_interrupted
        # Queued bytes per item, in playback order, and bytes already played.
        self._queued_items: deque[list[Any]] = deque()
        self._played_bytes: dict[_AudioItem, int] = {}

    def clear(self) -> None:
        with self._lock:
            self._active_until = 0.0
            self._audio.clear()
            self._playing = False
            self._input_complete = False
            interrupted = dict.fromkeys(item for item, _ in self._queued_items if item is not None)
            truncations = [
                (
                    item_id,
                    content_index,
                    self._played_bytes.get((item_id, content_index), 0) * 1000 // (2 * self.recv_rate),
                )
                for item_id, content_index in interrupted
            ]
            self._queued_items.clear()
            self._played_bytes.clear()
        if truncations and self._on_interrupted is not None:
            self._on_interrupted(truncations)

    def append(self, audio: bytes, item: _AudioItem | None = None) -> None:
        if not audio:
            return
        with self._lock:
            if self._input_complete and not self._audio:
                self._playing = False
            self._input_complete = False
            self._audio.extend(audio)
            if self._queued_items and self._queued_items[-1][0] == item:
                self._queued_items[-1][1] += len(audio)
            else:
                # Audio items arrive one after another, so an item that is
                # neither queued nor receiving this audio has finished playing.
                queued = {entry[0] for entry in self._queued_items}
                self._played_bytes = {key: n for key, n in self._played_bytes.items() if key in queued or key == item}
                self._queued_items.append([item, len(audio)])
            self._active_until = time.monotonic() + max(0.15, len(audio) / (2 * self.recv_rate))

    def finish(self) -> None:
        """Allow a completed short response to play before reaching the startup target."""
        with self._lock:
            self._input_complete = True

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._audio) or time.monotonic() < self._active_until

    def write(self, outdata: Any) -> None:
        needed = len(outdata)
        with self._lock:
            if not self._playing:
                ready = len(self._audio) >= self._startup_buffer_bytes
                if not ready and not (self._input_complete and self._audio):
                    outdata[:] = b"\x00" * needed
                    return
                self._playing = True
            available = min(needed, len(self._audio))
            if available:
                outdata[:available] = self._audio[:available]
                del self._audio[:available]
                self._mark_played(available)
                self._active_until = max(
                    self._active_until,
                    time.monotonic() + max(_PLAYBACK_TAIL_HOLD_S, available / (2 * self.recv_rate)),
                )
            if available < needed:
                outdata[available:] = b"\x00" * (needed - available)
                self._playing = False
            if not self._audio and self._input_complete:
                self._playing = False

    def _mark_played(self, played: int) -> None:
        """Attribute bytes just rendered to their queued items; caller holds the lock."""
        while played and self._queued_items:
            entry = self._queued_items[0]
            count = min(played, entry[1])
            entry[1] -= count
            played -= count
            if entry[0] is not None:
                self._played_bytes[entry[0]] = self._played_bytes.get(entry[0], 0) + count
            if entry[1] == 0:
                self._queued_items.popleft()

    @property
    def buffered_bytes(self) -> int:
        with self._lock:
            return len(self._audio)


def _stream_clock_offset(stream: Any) -> float:
    """Map a PortAudio stream's time base to the common monotonic clock."""
    estimates = []
    for _ in range(5):
        before = time.monotonic()
        stream_time = stream.time
        after = time.monotonic()
        estimates.append((after - before, (before + after) / 2 - stream_time))
    # Use the shortest read so thread scheduling cannot skew the clock mapping.
    return min(estimates)[1]


@contextmanager
def _open_audio_streams(config: Any, playback: PlaybackBuffer, mic_queue: Any) -> Iterator[None]:
    import sounddevice as sd

    input_device, output_device = config.input_device, config.output_device
    stream_options: dict[str, Any] = {}
    if config.echo_cancellation and sys.platform == "win32":
        host_apis = sd.query_hostapis()
        wasapi = next((index for index, api in enumerate(host_apis) if api["name"] == "Windows WASAPI"), None)
        if wasapi is None:
            raise ValueError("Echo cancellation on Windows requires WASAPI audio devices")
        if input_device is None:
            input_device = host_apis[wasapi]["default_input_device"]
        if output_device is None:
            output_device = host_apis[wasapi]["default_output_device"]
        for device, kind in ((input_device, "input"), (output_device, "output")):
            if sd.query_devices(device, kind)["hostapi"] != wasapi:
                raise ValueError(
                    "Echo cancellation on Windows requires WASAPI input and output devices; "
                    "leave --input-device and --output-device unset or select WASAPI devices"
                )
        # MME has no capture timestamps. WASAPI supplies them, while shared-mode
        # conversion keeps the device's mix format compatible with 16 kHz PCM.
        stream_options["extra_settings"] = sd.WasapiSettings(auto_convert=True)

    echo_canceller = EchoCanceller(config.send_rate, config.recv_rate) if config.echo_cancellation else None

    input_clock_offset = output_clock_offset = 0.0

    def callback_recv(outdata: Any, _frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning("Speaker status: %s", status)
        playback.write(outdata)
        if echo_canceller is not None:
            echo_canceller.render(bytes(outdata), time_info.outputBufferDacTime + output_clock_offset)

    def callback_send(indata: Any, _frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning("Microphone status: %s", status)
        if (
            config.block_mic_during_playback or (echo_canceller is not None and echo_canceller._failed)
        ) and playback.is_active():
            return
        chunk = bytes(indata)
        if echo_canceller is not None:
            chunk = echo_canceller.capture(
                chunk,
                time_info.inputBufferAdcTime + input_clock_offset,
                lost_input=bool(status and status.input_overflow),
            )
            if not chunk:
                return
        try:
            mic_queue.put_nowait(chunk)
        except Full:
            logger.debug("Dropping local microphone chunk because the send queue is full")

    opened_streams: list[Any] = []
    started_streams: list[Any] = []
    try:
        input_stream = sd.RawInputStream(
            samplerate=config.send_rate,
            channels=1,
            dtype="int16",
            blocksize=config.chunk_size,
            callback=callback_send,
            device=input_device,
            **stream_options,
        )
        opened_streams.append(input_stream)
        output_stream = sd.RawOutputStream(
            samplerate=config.recv_rate,
            channels=1,
            dtype="int16",
            blocksize=config.chunk_size,
            callback=callback_recv,
            device=output_device,
            **stream_options,
        )
        opened_streams.append(output_stream)

        if echo_canceller is not None:
            input_clock_offset = _stream_clock_offset(input_stream)
            output_clock_offset = _stream_clock_offset(output_stream)

        for stream in opened_streams:
            stream.start()
            started_streams.append(stream)

        yield
    finally:
        for stream in reversed(started_streams):
            try:
                stream.stop()
            except Exception:
                logger.exception("Failed to stop local audio stream")
        for stream in reversed(opened_streams):
            try:
                stream.close()
            except Exception:
                logger.exception("Failed to close local audio stream")


class _PlaybackCommands:
    """Forward playback changes to the process that owns the audio device."""

    def __init__(self, commands: Any) -> None:
        self._commands = commands

    def append(self, audio: bytes, item: _AudioItem | None = None) -> None:
        if audio:
            self._commands.put_nowait(("append", audio, item))

    def clear(self) -> None:
        self._commands.put_nowait(("clear", b"", None))

    def finish(self) -> None:
        self._commands.put_nowait(("finish", b"", None))


def _run_audio_worker(
    config: AudioWorkerConfig,
    mic_queue: Any,
    commands: Any,
    stop_event: Any,
    errors: Any,
    ready: Any,
    truncations: Any,
) -> None:
    # The parent handles Ctrl-C and requests orderly stream shutdown.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if stop_event.is_set():
        mic_queue.cancel_join_thread()
        truncations.cancel_join_thread()
        errors.close()
        return
    playback = PlaybackBuffer(config.recv_rate, config.playback_buffer_ms, truncations.put_nowait)

    def receive_playback() -> None:
        while not stop_event.is_set():
            try:
                command, audio, item = commands.get(timeout=0.1)
            except Empty:
                continue
            if command == "append":
                playback.append(audio, item)
            elif command == "clear":
                playback.clear()
            elif command == "finish":
                playback.finish()

    receiver = Thread(target=receive_playback, daemon=True)
    receiver.start()
    try:
        with _open_audio_streams(config, playback, mic_queue):
            ready.set()
            parent = multiprocessing.parent_process()
            while not stop_event.wait(0.1):
                if parent is not None and not parent.is_alive():
                    break
    except Exception as exc:
        errors.send(str(exc))
        raise
    finally:
        stop_event.set()
        receiver.join(timeout=1)
        # The parent stops consuming microphone audio during shutdown.
        mic_queue.cancel_join_thread()
        truncations.cancel_join_thread()
        errors.close()
