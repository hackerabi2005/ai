"""NVIDIA NIM Riva ASR handler supporting NVCF HTTP and Riva gRPC."""

from __future__ import annotations

import io
import logging
import math
import os
import wave
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any, Iterator, Optional

import httpx2
import numpy as np

from speech_to_speech.pipeline.console import console
from speech_to_speech.pipeline.handler_types import STTIn, STTOut
from speech_to_speech.pipeline.messages import PartialTranscription, Transcription, TranscriptionFailure
from speech_to_speech.STT.base_stt_handler import BaseSTTHandler

logger = logging.getLogger(__name__)

PIPELINE_SAMPLE_RATE = 16000
DEFAULT_HTTP_URL = ""


def _join_transcripts(prefix: str, text: str) -> str:
    prefix = prefix.strip()
    text = text.strip()
    if not prefix:
        return text
    if not text:
        return prefix
    return f"{prefix} {text}"


@dataclass
class _RivaUtteranceStream:
    """Per-utterance gRPC streaming state linking VAD chunks to process()."""

    generation: int
    language_code: str
    turn_id: str | None = None
    turn_revision: int | None = None
    audio_q: Queue[bytes | None] = field(default_factory=Queue)
    done: Event = field(default_factory=Event)
    cancelled: Event = field(default_factory=Event)
    opened_at_s: float = field(default_factory=perf_counter)
    boundary_at_s: float | None = None
    completed_at_s: float | None = None
    prefix: str = ""
    final_text: str | None = None
    error: str | None = None


def _to_pcm16_bytes(audio: np.ndarray) -> bytes:
    waveform = np.asarray(audio).squeeze()
    if waveform.ndim != 1:
        raise ValueError(f"Riva STT audio must be mono, got shape {waveform.shape}")
    if np.issubdtype(waveform.dtype, np.floating):
        pcm = np.round(np.clip(waveform, -1.0, 1.0) * 32767.0).astype("<i2")
    else:
        pcm = np.clip(waveform, -32768, 32767).astype("<i2")
    return pcm.tobytes()


def _encode_wav(pcm_bytes: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(PIPELINE_SAMPLE_RATE)
        wav.writeframes(pcm_bytes)
    return output.getvalue()


class RivaSTTHandler(BaseSTTHandler):
    """Speech-to-Text handler for NVIDIA NIM Parakeet CTC 1.1B ASR via NVCF HTTP or Riva gRPC."""

    def setup(
        self,
        server: str = "grpc.nvcf.nvidia.com:443",
        use_ssl: bool = True,
        function_id: str = "1598d209-5e27-4d3c-8079-4751568b1081",
        api_key: Optional[str] = None,
        language_code: str = "en-US",
        word_time_offsets: bool = True,
        http_url: Optional[str] = DEFAULT_HTTP_URL,
        use_grpc: bool = False,
        timeout: float = 60.0,
        streaming: bool = True,
        gen_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Riva STT timeout must be finite and > 0")
        if not language_code or not language_code.strip():
            raise ValueError("Riva STT language_code must not be empty")

        self.server = server
        self.use_ssl = use_ssl
        self.function_id = function_id
        self.api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY")
        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY environment variable is required for Riva STT.")
        self.language_code = language_code.strip()
        self.start_language = self.language_code.split("-", 1)[0].lower()
        self.last_language = self.start_language
        self.word_time_offsets = word_time_offsets
        self.http_url = http_url.strip() if http_url else ""
        self.use_grpc = bool(use_grpc or not self.http_url)
        self.streaming = bool(self.use_grpc and streaming)
        self.timeout = float(timeout)
        self.gen_kwargs = gen_kwargs or {}
        self._http_client: httpx2.Client | None = None
        self._auth: Any = None
        self._asr_service: Any = None
        self._streaming_capable = False
        self._grpc_backoff_until_s: float = 0.0
        self._stream_lock = Lock()
        self._session_generation = 0
        self._active_turn_id: str | None = None
        self._active_turn_revision: int | None = None
        self._current_stream: _RivaUtteranceStream | None = None
        self._pending_commits: dict[tuple[int, str | None, int | None], _RivaUtteranceStream] = {}
        self._cancelled_commit_keys: list[tuple[str | None, int | None]] = []
        self._committed_prefixes: dict[str, str] = {}

        if self.use_grpc:
            self._init_grpc()
        else:
            self._http_client = self._make_http_client()

        self.warmup()

    def _make_http_client(self) -> httpx2.Client:
        http_read = min(self.timeout, 8.0)
        timeout = httpx2.Timeout(
            http_read,
            connect=min(self.timeout, 5.0),
            write=min(self.timeout, 8.0),
            pool=min(self.timeout, 5.0),
        )
        return httpx2.Client(timeout=timeout)

    def _init_grpc(self) -> None:
        import riva.client

        self._auth = riva.client.Auth(
            use_ssl=self.use_ssl,
            uri=self.server,
            metadata_args=[
                ["function-id", self.function_id],
                ["authorization", f"Bearer {self.api_key}"],
            ],
            options=[
                ("grpc.keepalive_time_ms", 20000),
                ("grpc.keepalive_timeout_ms", 5000),
                ("grpc.keepalive_permit_without_calls", 1),
            ],
        )
        self._asr_service = riva.client.ASRService(self._auth)
        self._streaming_capable = bool(
            self.streaming
            and hasattr(self._asr_service, "streaming_response_generator")
            and hasattr(riva.client, "StreamingRecognitionConfig")
        )

    def _reset_grpc(self) -> None:
        auth = getattr(self, "_auth", None)
        channel = getattr(auth, "channel", None)
        if channel is not None and hasattr(channel, "close"):
            try:
                channel.close()
            except Exception:
                pass
        self._init_grpc()

    def _streaming_ready(self) -> bool:
        return bool(self._streaming_capable and self._asr_service is not None)

    def start_turn(self, turn_id: str | None, turn_revision: int | None) -> None:
        if not self._streaming_ready():
            return
        with self._stream_lock:
            self._active_turn_id = turn_id
            self._active_turn_revision = turn_revision
            if self._current_stream is not None and not self._current_stream.cancelled.is_set():
                self._current_stream.turn_id = turn_id
                self._current_stream.turn_revision = turn_revision

    def append_audio(self, audio: bytes) -> None:
        if not self._streaming_ready() or not audio or self.stop_event.is_set():
            return
        worker_stream: _RivaUtteranceStream | None = None
        with self._stream_lock:
            stream = self._current_stream
            if stream is None or stream.cancelled.is_set():
                stream = _RivaUtteranceStream(
                    generation=self._session_generation,
                    language_code=self.language_code,
                    turn_id=self._active_turn_id,
                    turn_revision=self._active_turn_revision,
                )
                worker_stream = stream
                self._current_stream = stream
            stream.audio_q.put(audio)
        if worker_stream is not None:
            Thread(
                target=self._stream_worker,
                args=(worker_stream,),
                name="riva-stt-stream",
                daemon=True,
            ).start()

    def commit_boundary(self, turn_id: str | None, turn_revision: int | None) -> None:
        if not self._streaming_ready():
            return
        with self._stream_lock:
            stream = self._current_stream
            self._current_stream = None
            self._active_turn_id = None
            self._active_turn_revision = None
            if stream is None or stream.cancelled.is_set():
                return
            stream.turn_id = turn_id
            stream.turn_revision = turn_revision
            stream.boundary_at_s = perf_counter()
            if turn_id is not None:
                stream.prefix = self._committed_prefixes.get(turn_id, "")
            key = (turn_id, turn_revision)
            if key in self._cancelled_commit_keys:
                self._cancelled_commit_keys.remove(key)
            self._pending_commits[(stream.generation, turn_id, turn_revision)] = stream
            stream.audio_q.put(None)

    def discard_utterance(self) -> None:
        with self._stream_lock:
            stream = self._current_stream
            self._current_stream = None
            self._active_turn_id = None
            self._active_turn_revision = None
            if stream is not None:
                stream.cancelled.set()
                stream.audio_q.put(None)
                stream.done.set()

    def cancel_session(self) -> None:
        with self._stream_lock:
            self._session_generation += 1
            self._active_turn_id = None
            self._active_turn_revision = None
            self._committed_prefixes.clear()
            streams = list(self._pending_commits.values())
            self._pending_commits.clear()
            if self._current_stream is not None:
                streams.append(self._current_stream)
                self._current_stream = None
            for stream in streams:
                if stream.turn_id is not None:
                    self._cancelled_commit_keys.append((stream.turn_id, stream.turn_revision))
                stream.cancelled.set()
                stream.audio_q.put(None)
                stream.done.set()
            if len(self._cancelled_commit_keys) > 32:
                self._cancelled_commit_keys = self._cancelled_commit_keys[-32:]

    def on_session_end(self) -> None:
        self.cancel_session()
        super().on_session_end()

    def _build_recognition_config(self, language_code: str) -> Any:
        import riva.client
        from riva.client.proto.riva_audio_pb2 import AudioEncoding

        return riva.client.RecognitionConfig(
            encoding=AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=PIPELINE_SAMPLE_RATE,
            language_code=language_code,
            max_alternatives=1,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=self.word_time_offsets,
            audio_channel_count=1,
        )

    def _iter_stream_audio(self, stream: _RivaUtteranceStream) -> Iterator[bytes]:
        while not stream.cancelled.is_set() and not self.stop_event.is_set():
            try:
                chunk = stream.audio_q.get(timeout=0.05)
            except Empty:
                continue
            if chunk is None:
                break
            yield chunk

    def _emit_partial(self, stream: _RivaUtteranceStream, text: str) -> None:
        queue_out = getattr(self, "queue_out", None)
        if queue_out is None or not text or stream.cancelled.is_set() or stream.boundary_at_s is not None:
            return
        with self._stream_lock:
            turn_id = stream.turn_id
            turn_revision = stream.turn_revision
            if turn_id is None or stream.generation != self._session_generation:
                return
            prefix = self._committed_prefixes.get(turn_id, "")
        tracker = getattr(self, "speculative_turns", None)
        if tracker is not None and not tracker.is_latest(turn_id, turn_revision):
            return
        combined = _join_transcripts(prefix, text)
        if combined:
            queue_out.put(PartialTranscription(text=combined, turn_id=turn_id, turn_revision=turn_revision))

    def _stream_worker(self, stream: _RivaUtteranceStream) -> None:
        import riva.client

        streaming_cfg = riva.client.StreamingRecognitionConfig(
            config=self._build_recognition_config(stream.language_code),
            interim_results=True,
        )
        final_parts: list[str] = []
        latest_interim = ""
        last_partial = ""
        try:
            for resp in self._asr_service.streaming_response_generator(
                audio_chunks=self._iter_stream_audio(stream),
                streaming_config=streaming_cfg,
            ):
                if stream.cancelled.is_set() or self.stop_event.is_set():
                    break
                for result in getattr(resp, "results", ()):
                    alts = getattr(result, "alternatives", ())
                    if not alts:
                        continue
                    transcript = (alts[0].transcript or "").strip()
                    if getattr(result, "is_final", False):
                        if transcript:
                            final_parts.append(transcript)
                        latest_interim = ""
                    elif transcript:
                        latest_interim = transcript
                hypothesis = _join_transcripts(" ".join(final_parts), latest_interim)
                if hypothesis != last_partial:
                    last_partial = hypothesis
                    self._emit_partial(stream, hypothesis)
            raw_final = " ".join(final_parts).strip() or latest_interim.strip()
            with self._stream_lock:
                combined = _join_transcripts(stream.prefix, raw_final)
                if (
                    stream.turn_id is not None
                    and not stream.cancelled.is_set()
                    and stream.generation == self._session_generation
                ):
                    self._committed_prefixes[stream.turn_id] = combined
                    while len(self._committed_prefixes) > 16:
                        self._committed_prefixes.pop(next(iter(self._committed_prefixes)))
                stream.final_text = combined
                stream.completed_at_s = perf_counter()
        except Exception as exc:
            if not stream.cancelled.is_set():
                stream.error = str(exc) or type(exc).__name__
        finally:
            stream.done.set()

    def _await_stream_commit(self, vad_audio: STTIn) -> tuple[bool, str | None, float | None]:
        """Return (consumed, text_or_none, elapsed_s_or_none) if a streaming commit owns this turn."""
        if not self._streaming_ready():
            return False, None, None
        with self._stream_lock:
            cancel_key = (vad_audio.turn_id, vad_audio.turn_revision)
            if cancel_key in self._cancelled_commit_keys:
                self._cancelled_commit_keys.remove(cancel_key)
                return True, None, None
            generation = self._session_generation
            key = (generation, vad_audio.turn_id, vad_audio.turn_revision)
            stream = self._pending_commits.pop(key, None)
            if stream is None and self._current_stream is not None and not self._current_stream.cancelled.is_set():
                if self._current_stream.turn_id == vad_audio.turn_id:
                    stream = self._current_stream
                    self._current_stream = None
                    stream.turn_revision = vad_audio.turn_revision
                    stream.boundary_at_s = perf_counter()
                    if vad_audio.turn_id is not None:
                        stream.prefix = self._committed_prefixes.get(vad_audio.turn_id, "")
                    stream.audio_q.put(None)
        if stream is None:
            return False, None, None

        # Post-boundary streaming finalization normally finishes in <1s; fail fast on wedged gRPC streams.
        stream_timeout = min(self.timeout, 6.0)
        deadline = (stream.boundary_at_s or perf_counter()) + stream_timeout
        while not stream.done.wait(timeout=min(0.05, max(0.0, deadline - perf_counter()))):
            if self.stop_event.is_set() or generation != self._session_generation or stream.cancelled.is_set():
                return True, None, None
            if perf_counter() >= deadline:
                stream.cancelled.set()
                stream.audio_q.put(None)
                logger.warning("Riva streaming gRPC timed out turn=%s; resetting channel and falling back to offline gRPC", vad_audio.turn_id)
                self._reset_grpc()
                return False, None, None

        if self.stop_event.is_set() or generation != self._session_generation or stream.cancelled.is_set():
            return True, None, None
        if stream.error is not None or stream.final_text is None:
            logger.warning(
                "Riva streaming gRPC errored (%s); falling back to offline gRPC",
                stream.error or "empty",
            )
            return False, None, None
        elapsed = (
            max(0.0, stream.completed_at_s - stream.boundary_at_s)
            if stream.completed_at_s is not None and stream.boundary_at_s is not None
            else None
        )
        return True, stream.final_text, elapsed

    def warmup(self) -> None:
        """Warm the NVCF gRPC worker synchronously during startup with dithered PCM so the first utterance is fast."""
        logger.info("Warming up %s (%s)", self.__class__.__name__, "gRPC" if self.use_grpc else "HTTP")
        started_at_s = perf_counter()
        try:
            dither = np.frombuffer(b"\x01\x00\xff\xff" * 2000, dtype="<i2")
            self._transcribe(dither, self.language_code)
            logger.info("%s warmed up in %.3fs", self.__class__.__name__, perf_counter() - started_at_s)
        except Exception as exc:
            self._grpc_backoff_until_s = 0.0
            logger.warning("%s warmup skipped (%s)", self.__class__.__name__, exc)

    def _resolve_request_language(self, selected: str | None) -> str:
        if not selected or selected == "auto":
            return self.language_code
        if "-" in selected:
            return selected
        if selected.lower() == self.language_code.split("-", 1)[0].lower():
            return self.language_code
        return selected

    def _transcribe(self, audio: np.ndarray, language_code: str) -> str:
        pcm_bytes = _to_pcm16_bytes(audio)
        if self.use_grpc:
            return self._transcribe_grpc(pcm_bytes, language_code)
        return self._transcribe_http(pcm_bytes, language_code)

    def _transcribe_http(self, pcm_bytes: bytes, language_code: str) -> str:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        wav_bytes = _encode_wav(pcm_bytes)
        data = {
            "language": language_code,
            "word_time_offsets": "True" if self.word_time_offsets else "False",
        }
        last_exc: Exception | None = None
        for attempt in range(2):
            client = self._http_client
            if client is None:
                client = self._make_http_client()
                self._http_client = client
            try:
                response = client.post(
                    self.http_url,
                    headers=headers,
                    data=data,
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                )
                response.raise_for_status()
                payload = response.json()
                text = payload.get("text") if isinstance(payload, dict) else None
                if not isinstance(text, str):
                    raise RuntimeError("Riva HTTP transcription response missing string 'text' field")
                return text.strip()
            except httpx2.TransportError as exc:
                last_exc = exc
                logger.warning("Riva HTTP transport error (attempt %d/2): %s", attempt + 1, exc)
                old_client = self._http_client
                self._http_client = None
                if old_client is not None:
                    try:
                        old_client.close()
                    except Exception:
                        pass
                if attempt == 0 and not self.stop_event.is_set():
                    self._http_client = self._make_http_client()
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def _transcribe_grpc(self, pcm_bytes: bytes, language_code: str) -> str:
        # Circuit breaker: after a unary gRPC stall, use fast HTTP fallback for 60s instead of repeated timeouts.
        if self.http_url and perf_counter() < self._grpc_backoff_until_s:
            return self._transcribe_http(pcm_bytes, language_code)
        config = self._build_recognition_config(language_code)
        stub = getattr(self._asr_service, "stub", None)
        get_meta = getattr(self._auth, "get_auth_metadata", None)
        if stub is not None and callable(get_meta):
            from riva.client.proto import riva_asr_pb2 as rasr

            request = rasr.RecognizeRequest(config=config, audio=pcm_bytes)
            try:
                response = stub.Recognize(request, metadata=get_meta(), timeout=min(self.timeout, 6.0))
            except Exception as exc:
                self._reset_grpc()
                if self.http_url and not self.stop_event.is_set():
                    self._grpc_backoff_until_s = perf_counter() + 60.0
                    logger.warning(
                        "Riva unary gRPC failed (%s); switching to HTTP fallback for 60s and resetting channel",
                        exc,
                    )
                    return self._transcribe_http(pcm_bytes, language_code)
                stub = getattr(self._asr_service, "stub", None)
                get_meta = getattr(self._auth, "get_auth_metadata", None)
                if stub is not None and callable(get_meta):
                    response = stub.Recognize(request, metadata=get_meta(), timeout=min(self.timeout, 6.0))
                else:
                    raise
        else:
            response = self._asr_service.offline_recognize(pcm_bytes, config)
        return " ".join(
            res.alternatives[0].transcript.strip() for res in response.results if res.alternatives
        ).strip()

    def process(self, vad_audio: STTIn) -> Iterator[STTOut]:
        if vad_audio.mode == "progressive":
            return
        tracker = getattr(self, "speculative_turns", None)
        if tracker is not None and not tracker.is_latest(vad_audio.turn_id, vad_audio.turn_revision):
            return

        started_at_s = perf_counter()
        selected = vad_audio.runtime_config.selected_language if vad_audio.runtime_config else None
        request_language = self._resolve_request_language(selected)

        consumed, pred_text, stream_elapsed_s = self._await_stream_commit(vad_audio)
        if consumed and pred_text is None:
            return

        if pred_text is None:
            try:
                pred_text = self._transcribe(vad_audio.audio, request_language)
            except Exception as exc:
                logger.error("Riva STT failed turn=%s rev=%s: %s", vad_audio.turn_id, vad_audio.turn_revision, exc)
                yield TranscriptionFailure(
                    message="riva transcription request failed",
                    turn_id=vad_audio.turn_id,
                    turn_revision=vad_audio.turn_revision,
                    speech_stopped_at_s=vad_audio.speech_end_at_s,
                )
                return

        if tracker is not None and not tracker.is_latest(vad_audio.turn_id, vad_audio.turn_revision):
            return

        elapsed_s = stream_elapsed_s if stream_elapsed_s is not None else (perf_counter() - started_at_s)
        self._record_final_stt(vad_audio, elapsed_s)
        lang_short = request_language.split("-", 1)[0].lower()
        self.last_language = lang_short
        if pred_text:
            console.print(f"[yellow]USER: {pred_text}")

        yield Transcription(
            text=pred_text,
            language_code=lang_short,
            turn_id=vad_audio.turn_id,
            turn_revision=vad_audio.turn_revision,
            speech_stopped_at_s=vad_audio.speech_end_at_s,
        )

    @property
    def timing_log_level(self) -> int:
        return logging.INFO

    def should_log_timing(self, output: STTOut) -> bool:
        return isinstance(output, Transcription) and self.last_time > self.min_time_to_debug

    def cleanup(self) -> None:
        self.cancel_session()
        http_client = getattr(self, "_http_client", None)
        if http_client is not None:
            self._http_client = None
            http_client.close()
        auth = getattr(self, "_auth", None)
        channel = getattr(auth, "channel", None)
        if channel is not None and hasattr(channel, "close"):
            try:
                channel.close()
            except Exception:
                pass
        self._auth = None
        self._asr_service = None
