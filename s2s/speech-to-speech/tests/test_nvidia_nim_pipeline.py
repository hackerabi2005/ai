"""Unit tests for the NVIDIA NIM default pipeline (Riva STT, Nemotron Chat Completions, Riva TTS)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from queue import Queue
from threading import Event
from types import SimpleNamespace

import httpx2
import numpy as np
import pytest
import torch
from openai.types.realtime import RealtimeSessionCreateRequest

import speech_to_speech.LLM.base_openai_compatible_language_model as base_llm_mod
import speech_to_speech.LLM.chat_completions_language_model as ccm
from speech_to_speech.api.openai_realtime.audio_client import (
    PlaybackBuffer,
    RealtimeAudioClient,
    _FriendlyEventRenderer,
    handle_server_event,
)
from speech_to_speech.api.openai_realtime.echo_canceller import EchoCanceller
from speech_to_speech.api.openai_realtime.runtime_config import RuntimeConfig
from speech_to_speech.api.openai_realtime.service import RealtimeService, _is_assistant_self_echo
from speech_to_speech.backend_registry import (
    LLM_BACKENDS,
    STT_BACKENDS,
    TTS_BACKENDS,
    HandlerContext,
    create_backend_handler,
)
from speech_to_speech.config import load_config, resolve_config, validate_config
from speech_to_speech.configured_runtime import build_configured_client
from speech_to_speech.LLM.chat import Chat, make_user_message
from speech_to_speech.LLM.chat_completions_language_model import ChatCompletionsApiModelHandler
from speech_to_speech.pipeline.cancel_scope import CancelScope
from speech_to_speech.pipeline.events import (
    AssistantOutputEvent,
    ResponseFailedEvent,
    SpeechStartedEvent,
    SpeechStoppedEvent,
    TranscriptionCompletedEvent,
)
from speech_to_speech.pipeline.messages import (
    AUDIO_RESPONSE_DONE,
    AssistantTextPart,
    EndOfResponse,
    GenerateResponseRequest,
    LLMResponseChunk,
    Transcription,
    TranscriptionFailure,
    TTSInput,
    VADAudio,
)
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker
from speech_to_speech.s2s_pipeline import build_local_pipeline, parse_arguments
from speech_to_speech.STT.openai_compatible_handler import (
    HttpTranscriptionOperation,
    OpenAICompatibleSTTHandler,
)
from speech_to_speech.STT.riva_stt_handler import RivaSTTHandler
from speech_to_speech.TTS.riva_tts_handler import RivaTTSHandler, _split_text
from speech_to_speech.VAD.vad_handler import VADHandler
from tests.llm_history import drive_llm
from tests.turns import reopen


def _context() -> HandlerContext:
    return HandlerContext(
        stop_event=Event(),
        queue_in=Queue(),
        queue_out=Queue(),
        text_output_queue=Queue(),
        should_listen=Event(),
        cancel_scope=CancelScope(),
        speculative_turns=SpeculativeTurnTracker(),
        pipeline_index=0,
        sample_rate=16000,
        enable_live_transcription=False,
        live_transcription_update_interval=0.5,
    )


def _install_fake_riva(monkeypatch, *, asr_text="hello nim", tts_chunks=None):
    calls: dict[str, list] = {"auth": [], "asr": [], "tts": []}
    chunks = tts_chunks if tts_chunks is not None else [np.arange(1024, dtype="<i2").tobytes()]

    class FakeAuth:
        def __init__(self, **kwargs):
            calls["auth"].append(kwargs)
            self.channel = SimpleNamespace(close=lambda: None)

    class FakeASRService:
        def __init__(self, auth):
            self.auth = auth

        def offline_recognize(self, pcm_bytes, config):
            calls["asr"].append((pcm_bytes, config))
            return SimpleNamespace(results=[SimpleNamespace(alternatives=[SimpleNamespace(transcript=asr_text)])])

    class FakeSynthesisService:
        def __init__(self, auth):
            self.auth = auth

        def synthesize_online(self, text, **kwargs):
            calls["tts"].append((text, kwargs))
            for chunk in chunks:
                yield SimpleNamespace(audio=chunk)

    class FakeRecognitionConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_audio_pb2 = SimpleNamespace(AudioEncoding=SimpleNamespace(LINEAR_PCM=1))
    fake_proto = SimpleNamespace(riva_audio_pb2=fake_audio_pb2)
    fake_client = SimpleNamespace(
        Auth=FakeAuth,
        ASRService=FakeASRService,
        SpeechSynthesisService=FakeSynthesisService,
        RecognitionConfig=FakeRecognitionConfig,
        proto=fake_proto,
    )
    monkeypatch.setitem(sys.modules, "riva", SimpleNamespace(client=fake_client))
    monkeypatch.setitem(sys.modules, "riva.client", fake_client)
    monkeypatch.setitem(sys.modules, "riva.client.proto", fake_proto)
    monkeypatch.setitem(sys.modules, "riva.client.proto.riva_audio_pb2", fake_audio_pb2)
    return calls


def test_riva_stt_http_mode_warmup_transcribe_and_skip_progressive(monkeypatch):
    requests: list[tuple[str, dict]] = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **kwargs):
            self.closed = False

        def post(self, url, **kwargs):
            requests.append((url, kwargs))
            text = "" if len(requests) == 1 else "Testing NVIDIA NIM."
            return FakeResponse({"text": text})

        def close(self):
            self.closed = True

    monkeypatch.setattr(httpx2, "Client", FakeClient)
    handler = RivaSTTHandler(Event(), Queue(), Queue(), setup_kwargs={"api_key": "nvapi-test"})
    assert len(requests) == 1
    assert requests[0][1]["headers"]["Authorization"] == "Bearer nvapi-test"
    assert requests[0][1]["data"] == {"language": "en-US", "word_time_offsets": "True"}

    # Progressive updates are skipped to avoid spamming remote NVCF calls.
    assert list(handler.process(VADAudio(audio=np.zeros(1600, dtype=np.float32), mode="progressive"))) == []
    assert len(requests) == 1

    outputs = list(
        handler.process(
            VADAudio(
                audio=np.ones(1600, dtype=np.float32) * 0.1,
                mode="final",
                turn_id="turn_1",
                turn_revision=0,
            )
        )
    )
    assert len(outputs) == 1
    assert isinstance(outputs[0], Transcription)
    assert outputs[0].text == "Testing NVIDIA NIM."
    assert outputs[0].language_code == "en"
    assert len(requests) == 2

    handler.cleanup()


def test_riva_stt_http_error_yields_transcription_failure(monkeypatch):
    call_count = 0

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def post(self, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"text": ""})
            raise httpx2.ConnectError("network down")

        def close(self):
            pass

    monkeypatch.setattr(httpx2, "Client", FakeClient)
    handler = RivaSTTHandler(Event(), Queue(), Queue(), setup_kwargs={"api_key": "nvapi-test"})
    outputs = list(
        handler.process(
            VADAudio(audio=np.zeros(1600, dtype=np.float32), mode="final", turn_id="t1", turn_revision=2)
        )
    )
    assert len(outputs) == 1
    assert isinstance(outputs[0], TranscriptionFailure)
    assert outputs[0].turn_id == "t1"
    assert outputs[0].turn_revision == 2


def test_riva_stt_http_resets_client_and_retries_once_on_transport_error(monkeypatch):
    clients_created = 0
    closed_clients = 0
    attempts = 0

    class FakeClient:
        def __init__(self, **kwargs):
            nonlocal clients_created
            clients_created += 1

        def post(self, url, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise httpx2.WriteTimeout("stale keep-alive")
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"text": "Recovered."})

        def close(self):
            nonlocal closed_clients
            closed_clients += 1

    monkeypatch.setattr(httpx2, "Client", FakeClient)
    handler = RivaSTTHandler(Event(), Queue(), Queue(), setup_kwargs={"api_key": "nvapi-test"})
    outputs = list(
        handler.process(VADAudio(audio=np.ones(1600, dtype=np.float32), mode="final", turn_id="t1", turn_revision=0))
    )
    assert [o.text for o in outputs if isinstance(o, Transcription)] == ["Recovered."]
    assert clients_created == 2
    assert closed_clients == 1
    handler.cleanup()


def test_riva_stt_http_recovers_on_later_turn_after_double_transport_error(monkeypatch):
    attempts = 0

    class FakeClient:
        def post(self, url, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts in (2, 3):
                raise httpx2.WriteTimeout("upload stalled")
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"text": "Turn 2 ok."})

        def close(self):
            pass

    monkeypatch.setattr(httpx2, "Client", lambda **kwargs: FakeClient())
    handler = RivaSTTHandler(Event(), Queue(), Queue(), setup_kwargs={"api_key": "nvapi-test"})
    fail_out = list(
        handler.process(VADAudio(audio=np.ones(1600, dtype=np.float32), mode="final", turn_id="t1", turn_revision=0))
    )
    assert isinstance(fail_out[0], TranscriptionFailure)
    assert handler._http_client is None
    ok_out = list(
        handler.process(VADAudio(audio=np.ones(1600, dtype=np.float32), mode="final", turn_id="t2", turn_revision=0))
    )
    assert [o.text for o in ok_out if isinstance(o, Transcription)] == ["Turn 2 ok."]
    handler.cleanup()


def test_riva_stt_grpc_mode_uses_riva_client_metadata_and_config(monkeypatch):
    calls = _install_fake_riva(monkeypatch, asr_text="Hello via gRPC.")
    handler = RivaSTTHandler(
        Event(),
        Queue(),
        Queue(),
        setup_kwargs={"use_grpc": True, "api_key": "nvapi-grpc"},
    )
    assert calls["auth"][0]["uri"] == "grpc.nvcf.nvidia.com:443"
    assert calls["auth"][0]["use_ssl"] is True
    assert calls["auth"][0]["metadata_args"] == [
        ["function-id", "1598d209-5e27-4d3c-8079-4751568b1081"],
        ["authorization", "Bearer nvapi-grpc"],
    ]

    outputs = list(
        handler.process(VADAudio(audio=np.zeros(1600, dtype=np.float32), mode="final", turn_id="t1", turn_revision=0))
    )
    assert len(outputs) == 1
    assert outputs[0].text == "Hello via gRPC."
    assert outputs[0].language_code == "en"
    pcm_bytes, config = calls["asr"][-1]
    assert len(pcm_bytes) == 3200
    assert config.language_code == "en-US"
    assert config.enable_word_time_offsets is True
    handler.cleanup()


def test_openai_stt_nvcf_compatibility_omits_model_and_sets_defaults(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(OpenAICompatibleSTTHandler, "warmup", lambda self: None)
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        OpenAICompatibleSTTHandler(
            Event(),
            Queue(),
            Queue(),
            setup_kwargs={
                "base_url": "https://1598d209-5e27-4d3c-8079-4751568b1081.invocation.api.nvcf.nvidia.com/v1",
                "model": "nvidia/parakeet-ctc-1_1b-asr",
            },
        )
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env-stt")
    handler = OpenAICompatibleSTTHandler(
        Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "base_url": "https://1598d209-5e27-4d3c-8079-4751568b1081.invocation.api.nvcf.nvidia.com/v1",
            "model": "nvidia/parakeet-ctc-1_1b-asr",
        },
    )
    assert handler.model is None
    assert handler.language == "en-US"
    assert handler.api_key == "nvapi-env-stt"

    op = HttpTranscriptionOperation(
        endpoint_url=handler.endpoint_url,
        api_key=handler.api_key,
        model=handler.model,
        wav_bytes=b"RIFF",
        language=handler.language,
        response_format="json",
        timeout_s=10.0,
    )
    kwargs = op._request_kwargs()
    assert "model" not in kwargs["data"]
    assert kwargs["data"]["language"] == "en-US"
    assert kwargs["data"]["word_time_offsets"] == "True"


def test_riva_tts_streams_pcm_blocks_and_honors_cancellation(monkeypatch):
    # Split odd byte counts across chunks to verify remainder reassembly.
    raw_samples = np.arange(1100, dtype="<i2").tobytes()
    calls = _install_fake_riva(monkeypatch, tts_chunks=[raw_samples[:501], raw_samples[501:]])
    tracker = SpeculativeTurnTracker()
    turn_id, revision = tracker.start_turn()
    scope = CancelScope()

    handler = RivaTTSHandler(
        Event(),
        Queue(),
        Queue(),
        setup_args=(Event(),),
        setup_kwargs={
            "api_key": "nvapi-tts",
            "blocksize": 512,
            "cancel_scope": scope,
            "speculative_turns": tracker,
        },
    )
    assert calls["auth"][0]["metadata_args"] == [
        ["function-id", "ddacc747-1269-4fab-bfd9-8f593dead106"],
        ["authorization", "Bearer nvapi-tts"],
    ]

    # Generic OpenAI voice "alloy" should fall back to Chatterbox default; French code adapts voice.
    cfg = RuntimeConfig(
        session=RealtimeSessionCreateRequest(
            type="realtime",
            audio={"output": {"voice": "alloy"}},
        )
    )
    tts_in = TTSInput(
        text="Bonjour.",
        runtime_config=cfg,
        selected_language="fr",
        tts_language_code="fr",
        turn_id=turn_id,
        turn_revision=revision,
        cancel_generation=scope.generation,
        response_key="resp-1",
    )
    blocks = list(handler.process(tts_in))
    assert [b.size for b in blocks] == [512, 512, 76]
    np.testing.assert_array_equal(np.concatenate(blocks), np.arange(1100, dtype="<i2"))
    _, synth_kwargs = calls["tts"][-1]
    assert synth_kwargs["language_code"] == "fr-FR"
    assert synth_kwargs["voice_name"] == "Chatterbox-Multilingual.fr-FR.Male"
    assert synth_kwargs["sample_rate_hz"] == 16000
    assert list(handler.process(EndOfResponse(turn_id=turn_id, turn_revision=revision, response_key="resp-1"))) == [
        AUDIO_RESPONSE_DONE
    ]

    # Cancelled / stale turn produces no audio.
    turn_2, rev_2 = tracker.start_turn()
    reopen(tracker, turn_2, rev_2)
    assert list(handler.process(TTSInput(text="Stale", turn_id=turn_2, turn_revision=rev_2))) == []
    handler.cleanup()


def test_riva_tts_error_emits_response_failed_event(monkeypatch):
    calls = _install_fake_riva(monkeypatch)
    handler = RivaTTSHandler(
        Event(),
        Queue(),
        Queue(),
        setup_args=(Event(),),
        setup_kwargs={"api_key": "nvapi-tts"},
    )
    handler.service.synthesize_online = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    assert calls["tts"]
    assert list(handler.process(TTSInput(text="Hello", turn_id="t1", turn_revision=0, response_key="r1"))) == []
    failure = handler.queue_out.get_nowait()
    assert isinstance(failure, ResponseFailedEvent)
    assert failure.response_key == "r1"


def test_split_text_respects_max_input_length():
    text = ("This is a test sentence. " * 30).strip()
    parts = _split_text(text, limit=450)
    assert len(parts) > 1
    assert all(len(part) <= 450 for part in parts)
    assert " ".join(parts) == text


def test_nemotron_chat_completions_defaults_and_streaming(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env-llm")
    args = parse_arguments([])
    assert args.llm_backend.spec is LLM_BACKENDS["chat-completions"]
    assert args.stt_backend.spec is STT_BACKENDS["riva"]
    assert args.tts_backend.spec is TTS_BACKENDS["riva"]

    captured: list[dict] = []

    class FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks
            self._iter = None

        def __iter__(self):
            return iter(self._chunks)

        async def __aenter__(self):
            self._iter = iter(self._chunks)
            return self

        async def __aexit__(self, *exc):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            assert self._iter is not None
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration from None

        def close(self):
            pass

    monkeypatch.setattr(ccm, "Stream", FakeStream)

    class FakeSyncClient:
        def __init__(self, **kwargs):
            self.api_key = kwargs.get("api_key")
            self.base_url = kwargs.get("base_url")
            self.organization = None
            self.project = None
            self.max_retries = 2

        def with_options(self, **kwargs):
            return self

        def close(self):
            pass

    class FakeAsyncCompletions:
        async def create(self, **kwargs):
            captured.append(kwargs)
            if kwargs.get("stream"):
                return FakeStream(
                    [
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    delta=SimpleNamespace(content=None, reasoning_content="Thinking...", tool_calls=None),
                                    finish_reason=None,
                                )
                            ],
                            usage=None,
                        ),
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    delta=SimpleNamespace(content="Hello world.", reasoning_content=None, tool_calls=None),
                                    finish_reason="stop",
                                )
                            ],
                            usage=None,
                        ),
                        SimpleNamespace(
                            choices=[],
                            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                        ),
                    ]
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    class FakeAsyncClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeAsyncCompletions())

        def with_options(self, **kwargs):
            return self

        async def close(self):
            return None

    monkeypatch.setattr(base_llm_mod, "OpenAI", FakeSyncClient)
    monkeypatch.setattr(
        ChatCompletionsApiModelHandler,
        "_make_async_client",
        lambda self: FakeAsyncClient(),
    )

    handler = create_backend_handler(args.llm_backend, _context())
    try:
        assert handler.client.api_key == "nvapi-env-llm"
        assert captured[0]["max_tokens"] == 16
        assert captured[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}

        chat = Chat(10)
        chat.add_item(make_user_message("Say hi"))
        session = RealtimeSessionCreateRequest(
            type="realtime",
            instructions="Be concise.",
            extensions=["speech_to_speech.reasoning.delta"],
        )
        req = GenerateResponseRequest(runtime_config=RuntimeConfig(chat=chat, session=session))
        outputs = list(drive_llm(handler, req))
        chunks = [o for o in outputs if isinstance(o, LLMResponseChunk)]
        assert "".join(c.text for c in chunks) == "Hello world."
        assert any(p.type == "reasoning" and p.text == "Thinking..." for c in chunks for p in c.parts)

        turn_kwargs = captured[-1]
        assert turn_kwargs["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
        assert turn_kwargs["temperature"] == 1.0
        assert turn_kwargs["top_p"] == 0.95
        assert turn_kwargs["max_tokens"] == 16384
        assert turn_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
        assert turn_kwargs["stream"] is True
    finally:
        handler.cleanup()


def test_nvidia_nim_yaml_config_validates_and_resolves(monkeypatch):
    yaml_path = Path(__file__).resolve().parent.parent / "example_configs" / "nvidia_nim.yaml"
    doc = load_config(yaml_path)
    validate_config(doc)
    resolved = resolve_config(doc, environ={})
    pipeline = resolved.pipelines["nvidia_nim"]
    assert pipeline.stages["vad"].backend == "silero"
    assert pipeline.stages["stt"].backend == "riva"
    assert pipeline.stages["llm"].backend == "chat-completions"
    assert pipeline.stages["tts"].backend == "riva"
    assert pipeline.stages["llm"].selection.config["model_name"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert pipeline.stages["llm"].selection.config["gen_kwargs"] == {
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 16384,
    }
    client_cfg = build_configured_client(resolved, local=True)
    assert client_cfg.playback_buffer_ms == 196.0


def test_local_pipeline_uses_playback_buffer_for_riva_tts(monkeypatch):
    unit = SimpleNamespace(handlers=[object()])
    monkeypatch.setattr("speech_to_speech.s2s_pipeline._build_pipeline_unit", lambda **_kwargs: unit)
    args = parse_arguments(["--tts", "riva"], command="local")
    manager = build_local_pipeline(args, Event())
    client = manager.handlers[-1]
    assert isinstance(client, RealtimeAudioClient)
    assert client.config.playback_buffer_ms == 196.0


def test_local_audio_defaults_to_echo_cancellation_and_handles_block_mic_conflict(monkeypatch):
    default_args = parse_arguments([], command="local")
    assert default_args.local_audio_kwargs.local_audio_echo_cancellation is True

    unit = SimpleNamespace(handlers=[object()])
    monkeypatch.setattr("speech_to_speech.s2s_pipeline._build_pipeline_unit", lambda **_kwargs: unit)
    block_args = parse_arguments(["--local_audio_block_mic_during_playback", "--tts", "riva"], command="local")
    manager = build_local_pipeline(block_args, Event())
    client = manager.handlers[-1]
    assert isinstance(client, RealtimeAudioClient)
    assert client.config.block_mic_during_playback is True
    assert client.config.echo_cancellation is False

    yaml_path = Path(__file__).resolve().parent.parent / "example_configs" / "nvidia_nim.yaml"
    resolved_with_client = resolve_config(load_config(yaml_path), environ={}, include_client=True)
    configured_client = build_configured_client(resolved_with_client, local=True)
    assert configured_client.echo_cancellation is True
    assert configured_client.playback_buffer_ms == 196.0


def test_playback_buffer_holds_active_through_write_tail_and_resets_on_clear():
    playback = PlaybackBuffer(16000)
    playback.append(b"\x01\x02" * 100)
    playback.write(bytearray(200))

    assert playback.buffered_bytes == 0
    assert playback.is_active() is True

    playback.clear()
    assert playback.is_active() is False


def test_echo_canceller_suppresses_low_residual_bleed_and_keeps_barge_in():
    canceller = EchoCanceller.__new__(EchoCanceller)
    next_reply = [np.zeros(160, dtype=np.int16)]
    canceller._apm = SimpleNamespace(speech_probability=0.0, process=lambda _near, _far: next_reply[0])
    canceller._rate = 16000
    canceller._frame_bytes = 320
    canceller._capture = bytearray()
    canceller._capture_time = 0.0
    canceller._render = __import__("collections").deque()
    canceller._next_render_time = None
    canceller._next_capture_time = None
    canceller._last_reference_active_time = -float("inf")
    canceller._lock = __import__("threading").Lock()
    canceller._failed = False

    speaker_ref = np.full(160, 14000, dtype=np.int16).tobytes()
    mic_frame = np.full(160, 300, dtype=np.int16).tobytes()

    # Low residual bleed during active playback -> zeroed.
    next_reply[0] = np.full(160, 100, dtype=np.int16)
    canceller.render(speaker_ref, 0.0)
    assert canceller.capture(mic_frame, 0.0) == b"\x00" * 320

    # Within the 250ms acoustic tail -> still zeroed.
    assert canceller.capture(mic_frame, 0.05) == b"\x00" * 320

    # Normal near-end speech (~1500 RMS) during loud TTS playback -> preserved.
    barge_in = np.full(160, 1500, dtype=np.int16)
    next_reply[0] = barge_in
    canceller.render(speaker_ref, 0.06)
    assert canceller.capture(mic_frame, 0.06) == barge_in.tobytes()


def test_vad_handler_suppresses_low_rms_bleed_during_playback_and_allows_barge_in():
    seen_inputs: list[torch.Tensor] = []

    class FakeIterator:
        triggered = False
        min_silence_samples = 1024
        speech_pad_samples = 480
        active_speech_samples = 0
        last_utterance_active_speech_samples = 0
        buffer: list[torch.Tensor] = []

        def __call__(self, tensor: torch.Tensor):
            seen_inputs.append(tensor.clone())
            return None

        def speech_buffer(self):
            return []

    vad = VADHandler.__new__(VADHandler)
    vad.stop_event = Event()
    vad.should_listen = Event()
    vad.should_listen.set()
    vad.sample_rate = 16000
    vad.min_silence_ms = 64
    vad.min_speech_ms = 384
    vad.min_speech_continuation_ms = 192
    vad.max_speech_ms = float("inf")
    vad.audio_enhancement = False
    vad.enable_realtime_transcription = False
    vad.realtime_processing_pause = 0.5
    vad.text_output_queue = Queue()
    vad.speculative_turns = SpeculativeTurnTracker()
    vad.speculative_reopen_ms = 800
    vad.short_segment_merge_ms = 0
    vad.smart_turn_analyzer = None
    vad.iterator = FakeIterator()
    vad.last_process_time = 0.0
    vad._total_samples = 0
    vad._last_log_time = 0.0
    vad._log_chunks = 0
    vad._log_speech_starts = 0
    vad._log_speech_ends = 0
    vad._log_progressive_yields = 0
    vad._speech_started_emitted = False
    vad._speculative_audio_prefix = None
    vad.transcription_window_samples = None
    vad._last_window_snapshot_samples = 0
    vad._window_check_after_samples = 0
    vad._speculative_raw_audio_prefix = None
    vad._pending_short_segment = None
    vad.streaming_stt_sink = None
    vad._streaming_pre_speech = bytearray()
    vad.diarization_worker = None
    vad._diarization_streaming = False
    vad._speculative_speaker_prefix = None
    vad.response_playing = Event()
    vad._response_playing_hold_until_s = 0.0
    vad.response_playing.set()

    low_bleed = np.full(512, 100, dtype=np.int16).tobytes()
    list(vad.process(low_bleed))
    assert float(seen_inputs[-1].abs().max()) == 0.0
    assert vad._active_speech_min_ms(0) == 384.0

    loud_barge_in = np.full(512, 4000, dtype=np.int16).tobytes()
    list(vad.process(loud_barge_in))
    assert float(seen_inputs[-1].abs().max()) > 0.1

    vad.response_playing.clear()
    vad._response_playing_hold_until_s = 0.0
    assert vad._active_speech_min_ms(0) == 384.0


def test_realtime_service_drops_assistant_self_echo_and_keeps_real_user_speech():
    prompt_queue: Queue = Queue()
    should_listen = Event()
    should_listen.set()
    tracker = SpeculativeTurnTracker()
    service = RealtimeService(
        text_prompt_queue=prompt_queue,
        should_listen=should_listen,
        speculative_turns=tracker,
    )
    conn_id = service.register()

    service.dispatch_pipeline_event(
        conn_id,
        AssistantOutputEvent(parts=[AssistantTextPart(text="GPU computing accelerates parallel workloads.")]),
    )
    service.dispatch_pipeline_event(
        conn_id,
        AssistantOutputEvent(parts=[AssistantTextPart(text="Please stop and confirm.")]),
    )
    service.finish_response(conn_id)

    # 3+ word echo of assistant output must be dropped without queueing LLM work.
    echo_turn, echo_rev, _ = tracker.speech_started(100)
    service.dispatch_pipeline_event(
        conn_id, SpeechStartedEvent(audio_start_ms=100, turn_id=echo_turn, turn_revision=echo_rev)
    )
    tracker.segment_finalized(1000)
    service.dispatch_pipeline_event(
        conn_id, SpeechStoppedEvent(duration_s=0.9, audio_end_ms=1000, turn_id=echo_turn, turn_revision=echo_rev)
    )
    echo_events = service.dispatch_pipeline_event(
        conn_id,
        TranscriptionCompletedEvent(
            transcript="GPU computing accelerates parallel workloads",
            turn_id=echo_turn,
            turn_revision=echo_rev,
        ),
    )
    assert echo_events == []
    assert prompt_queue.empty()
    assert service._state(conn_id).runtime_config.chat.buffer == []

    # Short command (<3 words) even containing an assistant word passes through.
    short_turn, short_rev, _ = tracker.speech_started(1500)
    service.dispatch_pipeline_event(
        conn_id, SpeechStartedEvent(audio_start_ms=1500, turn_id=short_turn, turn_revision=short_rev)
    )
    tracker.segment_finalized(2000)
    service.dispatch_pipeline_event(
        conn_id, SpeechStoppedEvent(duration_s=0.5, audio_end_ms=2000, turn_id=short_turn, turn_revision=short_rev)
    )
    service.dispatch_pipeline_event(
        conn_id,
        TranscriptionCompletedEvent(transcript="stop", turn_id=short_turn, turn_revision=short_rev),
    )
    assert not prompt_queue.empty()
    assert prompt_queue.get_nowait().runtime_config.chat.buffer[-1].content[0].text == "stop"

    # Genuine distinct 3+ word user speech passes through.
    service.finish_response(conn_id)
    user_turn, user_rev, _ = tracker.speech_started(3000)
    service.dispatch_pipeline_event(
        conn_id, SpeechStartedEvent(audio_start_ms=3000, turn_id=user_turn, turn_revision=user_rev)
    )
    tracker.segment_finalized(4000)
    service.dispatch_pipeline_event(
        conn_id, SpeechStoppedEvent(duration_s=1.0, audio_end_ms=4000, turn_id=user_turn, turn_revision=user_rev)
    )
    service.dispatch_pipeline_event(
        conn_id,
        TranscriptionCompletedEvent(
            transcript="Explain quantum entanglement simply",
            turn_id=user_turn,
            turn_revision=user_rev,
        ),
    )
    assert not prompt_queue.empty()
    assert (
        prompt_queue.get_nowait().runtime_config.chat.buffer[-1].content[0].text
        == "Explain quantum entanglement simply"
    )


def test_prepare_barge_in_terminal_rejects_noise_and_confirms_real_speech():
    prompt_queue: Queue = Queue()
    should_listen = Event()
    should_listen.set()
    tracker = SpeculativeTurnTracker()
    service = RealtimeService(
        text_prompt_queue=prompt_queue,
        should_listen=should_listen,
        speculative_turns=tracker,
    )
    conn_id = service.register()
    service.response._ensure_response(conn_id)
    service.dispatch_pipeline_event(
        conn_id,
        AssistantOutputEvent(parts=[AssistantTextPart(text="Rust guarantees memory safety at compile time.")]),
    )
    assert service._state(conn_id).in_response

    # Unverified mid-playback onset must defer input_audio_buffer.speech_started without cancelling TTS.
    t1, r1, _ = tracker.speech_started(100)
    started_1 = service.dispatch_pipeline_event(
        conn_id,
        SpeechStartedEvent(
            audio_start_ms=100,
            turn_id=t1,
            turn_revision=r1,
            interrupt_response=False,
            confirm_interrupt=True,
        ),
    )
    assert started_1 == []
    assert service._state(conn_id).in_response
    assert len(service._state(conn_id).pending_deferred_speech_started) == 1

    # Empty transcript -> discarded silently; TTS keeps playing and nothing queues for LLM.
    tracker.segment_finalized(500)
    service.dispatch_pipeline_event(
        conn_id,
        SpeechStoppedEvent(duration_s=0.4, audio_end_ms=500, turn_id=t1, turn_revision=r1),
    )
    handled_noise, cancelled, pre_events = service.prepare_barge_in_terminal(
        conn_id,
        TranscriptionCompletedEvent(transcript="   ", turn_id=t1, turn_revision=r1),
    )
    assert (handled_noise, cancelled, pre_events) == (True, False, [])
    assert service._state(conn_id).in_response
    assert not service._state(conn_id).pending_deferred_speech_started
    assert prompt_queue.empty()

    # Genuine human speech -> cancels active TTS, emits held speech_started, and queues LLM request.
    t2, r2, _ = tracker.speech_started(800)
    started_2 = service.dispatch_pipeline_event(
        conn_id,
        SpeechStartedEvent(
            audio_start_ms=800,
            turn_id=t2,
            turn_revision=r2,
            interrupt_response=False,
            confirm_interrupt=True,
        ),
    )
    assert started_2 == []
    tracker.segment_finalized(1500)
    service.dispatch_pipeline_event(
        conn_id,
        SpeechStoppedEvent(duration_s=0.7, audio_end_ms=1500, turn_id=t2, turn_revision=r2),
    )
    final_msg = TranscriptionCompletedEvent(
        transcript="Switch to Python instead",
        turn_id=t2,
        turn_revision=r2,
    )
    handled_noise, cancelled, pre_events = service.prepare_barge_in_terminal(conn_id, final_msg)
    assert handled_noise is False
    assert cancelled is True
    assert [e.type for e in pre_events[-2:]] == ["response.done", "input_audio_buffer.speech_started"]
    assert not service._state(conn_id).in_response
    service.dispatch_pipeline_event(conn_id, final_msg)
    assert not prompt_queue.empty()
    assert prompt_queue.get_nowait().runtime_config.chat.buffer[-1].content[0].text == "Switch to Python instead"


def test_echo_window_stays_active_12s_after_long_audio_finishes(monkeypatch):
    service = RealtimeService(text_prompt_queue=Queue(), should_listen=Event())
    conn_id = service.register()
    st = service._state(conn_id)
    clock = [100.0]
    monkeypatch.setattr("speech_to_speech.api.openai_realtime.service.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("speech_to_speech.api.openai_realtime.handlers.response.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("speech_to_speech.api.openai_realtime.handlers.audio.time.monotonic", lambda: clock[0])

    # LLM emits text at t=100s, audio plays for 18s until t=118s.
    service.dispatch_pipeline_event(
        conn_id,
        AssistantOutputEvent(parts=[AssistantTextPart(text="Long explanation about neural network gradients.")]),
    )
    clock[0] = 118.0
    service.audio.encode_audio_chunk(conn_id, b"\x01\x00" * 160)
    service.finish_response(conn_id)

    # At t=124s (24s after text emission, only 6s after audio playback stopped), echo must still filter.
    clock[0] = 124.0
    t1, r1 = "echo_long", 1
    out = service.dispatch_pipeline_event(
        conn_id,
        TranscriptionCompletedEvent(
            transcript="neural network gradients",
            turn_id=t1,
            turn_revision=r1,
        ),
    )
    assert out == []
    assert st.runtime_config.chat.buffer == []


def test_audio_client_suppresses_blank_final_user_transcript(capsys):
    playback = PlaybackBuffer(16000)
    renderer = _FriendlyEventRenderer()
    handle_server_event(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed",
            item_id="item_blank",
            transcript="   ",
        ),
        playback=playback,
        renderer=renderer,
        print_json=False,
    )
    assert capsys.readouterr().out == ""


def test_echo_filter_catches_partial_and_fuzzy_echo_during_playback_but_allows_stop():
    service = RealtimeService(text_prompt_queue=Queue(), should_listen=Event())
    conn_id = service.register()
    st = service._state(conn_id)
    service.dispatch_pipeline_event(
        conn_id,
        AssistantOutputEvent(parts=[AssistantTextPart(text="Quantum computing runs parallel threads across GPU shaders.")]),
    )
    st.playback_expected_until_s = time.monotonic() + 5.0

    # Partial 2-word, single content word, and slightly misheard 3-word echo during active playback -> blocked.
    assert _is_assistant_self_echo(st, "parallel threads") is True
    assert _is_assistant_self_echo(st, "shaders") is True
    assert _is_assistant_self_echo(st, "peril threads across") is True

    # Real barge-in commands and unrelated user utterances -> allowed through.
    assert _is_assistant_self_echo(st, "stop") is False
    assert _is_assistant_self_echo(st, "wait") is False
    assert _is_assistant_self_echo(st, "Explain Rust lifetimes") is False


def test_vad_handler_stays_playback_active_while_playback_until_s_has_remaining_audio():
    vad = VADHandler.__new__(VADHandler)
    vad.response_playing = Event()
    vad._response_playing_hold_until_s = 0.0
    vad.playback_until_s = [time.monotonic() + 3.0]
    assert vad._is_playback_active() is True
    vad.playback_until_s[0] = 0.0
    vad._response_playing_hold_until_s = 0.0
    assert vad._is_playback_active() is False


def test_nvidia_nim_handlers_require_env_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        RivaSTTHandler(Event(), Queue(), Queue())
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        RivaTTSHandler(Event(), Queue(), Queue(), setup_args=(Event(),))
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        ChatCompletionsApiModelHandler(
            Event(),
            Queue(),
            Queue(),
            setup_kwargs={
                "base_url": "https://integrate.api.nvidia.com/v1",
                "model_name": "nvidia/nemotron-3-ultra-550b-a55b",
            },
        )
