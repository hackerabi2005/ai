"""NVIDIA NIM Riva TTS handler (Chatterbox Multilingual TTS over gRPC)."""

from __future__ import annotations

import logging
import os
import re
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any, Iterator, Optional, cast

import numpy as np
import soxr

from speech_to_speech.api.openai_realtime.runtime_config import RuntimeConfig
from speech_to_speech.pipeline.cancel_scope import CancelScope
from speech_to_speech.pipeline.events import ResponseFailedEvent
from speech_to_speech.pipeline.handler_types import TTSIn, TTSOut
from speech_to_speech.pipeline.messages import AUDIO_RESPONSE_DONE, EndOfResponse, TTSInput
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker
from speech_to_speech.pipeline.turn_latency import TTSResponseTimer
from speech_to_speech.TTS.base_tts_handler import BaseTTSHandler
from speech_to_speech.TTS.pcm_blocks import PCMBlockBuffer

logger = logging.getLogger(__name__)

PIPELINE_SAMPLE_RATE = 16000
MAX_INPUT_CHARS = 450

CHATTERBOX_LOCALES: dict[str, str] = {
    "ar": "ar-SA",
    "da": "da-DK",
    "de": "de-DE",
    "el": "el-GR",
    "en": "en-US",
    "es": "es-ES",
    "fi": "fi-FI",
    "fr": "fr-FR",
    "he": "he-IL",
    "hi": "hi-IN",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "ms": "ms-MY",
    "nb": "nb-NO",
    "nl": "nl-NL",
    "no": "nb-NO",
    "pl": "pl-PL",
    "pt": "pt-BR",
    "ru": "ru-RU",
    "sv": "sv-SE",
    "sw": "sw-KE",
    "tr": "tr-TR",
    "zh": "zh-CN",
}


def _split_text(text: str, limit: int = MAX_INPUT_CHARS) -> list[str]:
    """Split text under Chatterbox's 500-char limit while keeping sentence/word boundaries."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("\n"))
        if split_at > limit // 3:
            split_at += 1
        else:
            split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = limit
        part = remaining[:split_at].strip()
        if part:
            chunks.append(part)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


class RivaTTSHandler(BaseTTSHandler):
    """Streaming Text-to-Speech handler for NVIDIA NIM Chatterbox Multilingual TTS via Riva gRPC."""

    def setup(
        self,
        should_listen: Event,
        server: str = "grpc.nvcf.nvidia.com:443",
        use_ssl: bool = True,
        function_id: str = "ddacc747-1269-4fab-bfd9-8f593dead106",
        api_key: Optional[str] = None,
        language_code: str = "en-US",
        voice: str = "Chatterbox-Multilingual.en-US.Male",
        sample_rate: int = 16000,
        blocksize: int = 512,
        cancel_scope: CancelScope | None = None,
        speculative_turns: SpeculativeTurnTracker | None = None,
        detect_llm_output_language: bool = False,
        gen_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if blocksize < 1:
            raise ValueError("Riva TTS blocksize must be >= 1")
        if sample_rate <= 0:
            raise ValueError("Riva TTS sample_rate must be > 0")
        if not language_code or not language_code.strip():
            raise ValueError("Riva TTS language_code must not be empty")

        self.should_listen = should_listen
        self.server = server
        self.use_ssl = use_ssl
        self.function_id = function_id
        self.api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY")
        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY environment variable is required for Riva TTS.")
        self.language_code = language_code.strip()
        self.voice = voice
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.cancel_scope = cancel_scope
        self.speculative_turns = speculative_turns
        self.detect_llm_output_language = detect_llm_output_language
        self.gen_kwargs = gen_kwargs or {}
        self._operation_lock = Lock()
        self._closed = Event()
        self._warmup_thread: Thread | None = None
        self._failed_responses: set[tuple[int | None, str | None, str | None, int | None]] = set()
        self._auth: Any = None
        self.service: Any = None
        self._audio_encoding_pcm: Any = None

        self._init_grpc()
        self.warmup()

    def _init_grpc(self) -> None:
        import riva.client
        from riva.client.proto.riva_audio_pb2 import AudioEncoding

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
        self.service = riva.client.SpeechSynthesisService(self._auth)
        self._audio_encoding_pcm = AudioEncoding.LINEAR_PCM

    def _reset_grpc(self) -> None:
        auth = getattr(self, "_auth", None)
        channel = getattr(auth, "channel", None)
        if channel is not None and hasattr(channel, "close"):
            try:
                channel.close()
            except Exception:
                pass
        self._init_grpc()

    def warmup(self) -> None:
        """Warm up the Riva gRPC TTS worker in the background without blocking startup."""

        def _bg_warm() -> None:
            if self.stop_event.is_set() or self._closed.is_set():
                return
            logger.info("Warming up %s in background", self.__class__.__name__)
            started_at_s = perf_counter()
            try:
                responses = self.service.synthesize_online(
                    "Warmup.",
                    voice_name=self.voice,
                    language_code=self.language_code,
                    sample_rate_hz=self.sample_rate,
                    encoding=self._audio_encoding_pcm,
                )
                received = any(getattr(resp, "audio", b"") for resp in responses)
                if self.stop_event.is_set() or self._closed.is_set():
                    return
                if not received:
                    logger.warning("%s warmup returned no audio", self.__class__.__name__)
                else:
                    logger.info("%s warmed up in %.3fs", self.__class__.__name__, perf_counter() - started_at_s)
            except Exception as exc:
                if self.stop_event.is_set() or self._closed.is_set():
                    return
                logger.warning("%s warmup skipped (%s)", self.__class__.__name__, exc)

        thread = Thread(target=_bg_warm, name="riva-tts-warmup", daemon=True)
        self._warmup_thread = thread
        thread.start()

    def process(self, tts_input: TTSIn) -> Iterator[TTSOut]:
        if isinstance(tts_input, EndOfResponse):
            if self._gate_end_of_response(tts_input):
                lock = getattr(self, "_operation_lock", None)
                failed = getattr(self, "_failed_responses", None)
                if lock is not None and failed is not None:
                    with lock:
                        failed.discard(self._response_identity(tts_input))
                yield AUDIO_RESPONSE_DONE
            return

        if not self._admit_input(tts_input, commit=False):
            return

        cancel_generation = tts_input.cancel_generation
        if cancel_generation is None and self.cancel_scope is not None:
            cancel_generation = self.cancel_scope.generation
        response_identity = self._response_identity(tts_input, cancel_generation)
        with self._operation_lock:
            if response_identity in self._failed_responses:
                return

        text = tts_input.text.strip()
        if not text:
            return

        def cancel_check() -> bool:
            if self.stop_event.is_set() or self._is_stale(cancel_generation):
                return True
            return self.speculative_turns is not None and not self.speculative_turns.is_latest(
                tts_input.turn_id,
                tts_input.turn_revision,
            )

        lang_code, voice = self._resolve_language_and_voice(tts_input)
        first_audio = True
        first_provider_seen = False
        timer = self._latency_timer(tts_input, cancel_generation, also_cancelled=cancel_check)
        resampler = (
            soxr.ResampleStream(self.sample_rate, PIPELINE_SAMPLE_RATE, 1, dtype="int16")
            if self.sample_rate != PIPELINE_SAMPLE_RATE
            else None
        )
        blocks = PCMBlockBuffer(self.blocksize)

        def emit_blocks(chunk_iter: Iterator[np.ndarray]) -> Iterator[TTSOut]:
            nonlocal first_audio
            for block in chunk_iter:
                if cancel_check():
                    return
                if first_audio:
                    if not self._commit_first_audio(tts_input):
                        return
                    self._log_first_audio_latency(tts_input, timer)
                    first_audio = False
                yield block

        try:
            for segment in _split_text(text):
                if cancel_check():
                    return
                for attempt in range(2):
                    byte_remainder = b""
                    got_segment_audio = False
                    stream = self.service.synthesize_online(
                        segment,
                        voice_name=voice,
                        language_code=lang_code,
                        sample_rate_hz=self.sample_rate,
                        encoding=self._audio_encoding_pcm,
                    )
                    try:
                        for resp in stream:
                            if cancel_check():
                                return
                            raw = getattr(resp, "audio", b"")
                            if not raw:
                                continue
                            got_segment_audio = True
                            if not first_provider_seen:
                                timer.first_provider_audio()
                                first_provider_seen = True
                            chunk_bytes = byte_remainder + raw
                            usable = len(chunk_bytes) - (len(chunk_bytes) % 2)
                            byte_remainder = chunk_bytes[usable:]
                            if not usable:
                                continue
                            samples = np.frombuffer(chunk_bytes[:usable], dtype="<i2")
                            if resampler is not None:
                                samples = resampler.resample_chunk(samples, last=False)
                            yield from emit_blocks(blocks.push(samples))
                            if cancel_check():
                                return
                        break
                    except Exception as seg_exc:
                        if attempt == 0 and not got_segment_audio and not cancel_check():
                            logger.warning("Riva TTS gRPC error (%s); resetting channel and retrying once", seg_exc)
                            self._reset_grpc()
                            continue
                        raise
                    finally:
                        close = getattr(stream, "close", None)
                        if callable(close):
                            close()

            if resampler is not None:
                tail = resampler.resample_chunk(np.empty(0, dtype=np.int16), last=True)
                yield from emit_blocks(blocks.push(tail))
                if cancel_check():
                    return

            yield from emit_blocks(blocks.flush())
            if cancel_check():
                return

            if first_audio:
                raise RuntimeError("Riva TTS returned no audio")
        except Exception as exc:
            logger.error("Riva TTS failed: %s", exc, exc_info=True)
            if not cancel_check():
                with self._operation_lock:
                    self._failed_responses.add(response_identity)
                self.queue_out.put(
                    cast(
                        TTSOut,
                        ResponseFailedEvent(
                            message="riva speech request failed",
                            turn_id=tts_input.turn_id,
                            turn_revision=tts_input.turn_revision,
                            cancel_generation=cancel_generation,
                            response_key=tts_input.response_key,
                        ),
                    )
                )

    def _resolve_language_and_voice(self, tts_input: TTSInput) -> tuple[str, str]:
        voice = self._resolve_voice(tts_input.runtime_config, tts_input.response)
        selected = tts_input.selected_language
        candidate: str | None = None
        if selected is None and self.detect_llm_output_language:
            candidate = tts_input.response_assistant_language_code
        elif selected not in (None, "auto"):
            candidate = tts_input.tts_language_code
        elif tts_input.tts_language_code:
            candidate = tts_input.tts_language_code

        lang_code = self._map_language_code(candidate) if candidate else self.language_code
        if voice.startswith("Chatterbox-Multilingual.") and re.fullmatch(
            r"Chatterbox-Multilingual\.[A-Za-z-]+?\.[A-Za-z]+", voice
        ):
            suffix = voice.rsplit(".", 1)[1]
            voice = f"Chatterbox-Multilingual.{lang_code}.{suffix}"
        return lang_code, voice

    def _map_language_code(self, code: str) -> str:
        normalized = code.strip()
        if not normalized:
            return self.language_code
        if normalized in CHATTERBOX_LOCALES.values():
            return normalized
        short = normalized.split("-", 1)[0].lower()
        return CHATTERBOX_LOCALES.get(short, self.language_code)

    def _resolve_voice(self, runtime_config: RuntimeConfig | None, response: Any) -> str:
        override: Any = None
        if response and response.audio and response.audio.output and response.audio.output.voice:
            override = response.audio.output.voice
        elif runtime_config is not None:
            audio = runtime_config.session.audio
            output = audio.output if audio is not None else None
            if output is not None and output.voice:
                override = output.voice
        if isinstance(override, str) and override.startswith("Chatterbox-"):
            return override
        return self.voice

    def _commit_first_audio(self, tts_input: TTSInput) -> bool:
        tracker = self.speculative_turns
        if tracker is None or tts_input.turn_id is None or tts_input.turn_revision is None:
            return True
        return tracker.wait_for_gate(tts_input.turn_id, tts_input.turn_revision, commit=True)

    @staticmethod
    def _response_identity(
        message: TTSInput | EndOfResponse,
        cancel_generation: int | None = None,
    ) -> tuple[int | None, str | None, str | None, int | None]:
        if cancel_generation is None:
            cancel_generation = message.cancel_generation
        return (cancel_generation, message.response_key, message.turn_id, message.turn_revision)

    def _log_first_audio_latency(self, tts_input: TTSInput, timer: TTSResponseTimer) -> None:
        logger.info("Riva TTS time to first audio: %.3fs", perf_counter() - timer.started_at_s)
        elapsed_s = timer.speech_stop_elapsed_s()
        if elapsed_s is None:
            return
        latency_s = timer.first_yield(ignore_cancel=True)
        if latency_s is None:
            if getattr(self, "turn_latency_store", None) is not None:
                return
            latency_s = max(0.0, elapsed_s)
        logger.info(
            "Last speech detected to first speech out: %.3fs (turn=%s rev=%s)",
            latency_s,
            tts_input.turn_id,
            tts_input.turn_revision,
        )

    def on_session_end(self) -> None:
        lock = getattr(self, "_operation_lock", None)
        failed = getattr(self, "_failed_responses", None)
        if lock is not None and failed is not None:
            with lock:
                failed.clear()

    def cleanup(self) -> None:
        self._closed.set()
        auth = getattr(self, "_auth", None)
        channel = getattr(auth, "channel", None)
        if channel is not None and hasattr(channel, "close"):
            try:
                channel.close()
            except Exception:
                pass
        self._auth = None
        self.service = None
        warmup_thread = getattr(self, "_warmup_thread", None)
        if warmup_thread is not None and warmup_thread.is_alive():
            warmup_thread.join(timeout=1.0)
