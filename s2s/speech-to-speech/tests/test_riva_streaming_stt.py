"""Tests for streaming gRPC support in RivaSTTHandler."""

from __future__ import annotations

import sys
from queue import Queue
from threading import Event
from types import SimpleNamespace

import numpy as np

from speech_to_speech.pipeline.messages import PartialTranscription, Transcription, VADAudio
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker
from speech_to_speech.STT.riva_stt_handler import RivaSTTHandler


def _install_streaming_fake_riva(
    monkeypatch,
    *,
    stream_script=None,
    offline_text: str = "offline fallback",
    raise_in_stream: bool = False,
):
    state = {"offline_calls": 0, "stream_calls": [], "closed": False}

    class FakeAuth:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.channel = SimpleNamespace(close=lambda: state.__setitem__("closed", True))

    class FakeASRService:
        def __init__(self, auth):
            self.auth = auth

        def offline_recognize(self, pcm_bytes, config):
            state["offline_calls"] += 1
            return SimpleNamespace(results=[SimpleNamespace(alternatives=[SimpleNamespace(transcript=offline_text)])])

        def streaming_response_generator(self, *, audio_chunks, streaming_config):
            received = []
            for chunk in audio_chunks:
                received.append(chunk)
                if raise_in_stream:
                    raise RuntimeError("stream reset")
                if stream_script and len(received) == 1:
                    for item in stream_script.get("interim", []):
                        yield SimpleNamespace(
                            results=[SimpleNamespace(is_final=False, alternatives=[SimpleNamespace(transcript=item)])]
                        )
            state["stream_calls"].append({"chunks": received, "config": streaming_config})
            if raise_in_stream:
                raise RuntimeError("stream reset")
            final_items = stream_script["final"](len(state["stream_calls"])) if stream_script else ["Scroll down"]
            for text in final_items:
                yield SimpleNamespace(
                    results=[SimpleNamespace(is_final=True, alternatives=[SimpleNamespace(transcript=text)])]
                )

    class FakeRecognitionConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeStreamingRecognitionConfig:
        def __init__(self, *, config, interim_results=False):
            self.config = config
            self.interim_results = interim_results

    fake_audio_pb2 = SimpleNamespace(AudioEncoding=SimpleNamespace(LINEAR_PCM=1))
    fake_proto = SimpleNamespace(riva_audio_pb2=fake_audio_pb2)
    fake_client = SimpleNamespace(
        Auth=FakeAuth,
        ASRService=FakeASRService,
        RecognitionConfig=FakeRecognitionConfig,
        StreamingRecognitionConfig=FakeStreamingRecognitionConfig,
        proto=fake_proto,
    )
    monkeypatch.setitem(sys.modules, "riva", SimpleNamespace(client=fake_client))
    monkeypatch.setitem(sys.modules, "riva.client", fake_client)
    monkeypatch.setitem(sys.modules, "riva.client.proto", fake_proto)
    monkeypatch.setitem(sys.modules, "riva.client.proto.riva_audio_pb2", fake_audio_pb2)
    return state


def test_riva_streaming_grpc_streams_partials_and_final_without_offline(monkeypatch):
    state = _install_streaming_fake_riva(
        monkeypatch,
        stream_script={
            "interim": ["Scroll"],
            "final": lambda _idx: ["Scroll down"],
        },
    )
    queue_out: Queue = Queue()
    tracker = SpeculativeTurnTracker()
    handler = RivaSTTHandler(
        Event(),
        Queue(),
        queue_out,
        setup_kwargs={"use_grpc": True, "api_key": "nvapi-stream", "word_time_offsets": False},
    )
    handler.speculative_turns = tracker
    assert state["offline_calls"] == 1  # warmup only

    turn_id, rev, _ = tracker.speech_started(0)
    handler.start_turn(turn_id, rev)
    handler.append_audio(b"\x01\x00" * 512)
    partial_item = queue_out.get(timeout=2.0)
    assert isinstance(partial_item, PartialTranscription)
    assert partial_item.text == "Scroll"
    handler.append_audio(b"\x02\x00" * 512)
    tracker.segment_finalized(500)
    handler.commit_boundary(turn_id, rev)

    outputs = list(handler.process(VADAudio(audio=np.zeros(1024, dtype=np.float32), mode="final", turn_id=turn_id, turn_revision=rev)))
    finals = [item for item in outputs if isinstance(item, Transcription)]
    assert [f.text for f in finals] == ["Scroll down"]
    assert state["offline_calls"] == 1  # did NOT invoke offline_recognize for utterance
    assert len(state["stream_calls"]) == 1
    assert len(state["stream_calls"][0]["chunks"]) == 2
    assert state["stream_calls"][0]["config"].config.enable_word_time_offsets is False

    handler.cleanup()
    assert state["closed"] is True


def test_riva_streaming_grpc_joins_reopened_turn_prefix(monkeypatch):
    _install_streaming_fake_riva(
        monkeypatch,
        stream_script={
            "interim": [],
            "final": lambda idx: ["Open"] if idx == 1 else ["YouTube"],
        },
    )
    tracker = SpeculativeTurnTracker()
    handler = RivaSTTHandler(Event(), Queue(), Queue(), setup_kwargs={"use_grpc": True, "api_key": "nvapi-stream"})
    handler.speculative_turns = tracker

    turn_id, rev0, _ = tracker.speech_started(0)
    handler.start_turn(turn_id, rev0)
    handler.append_audio(b"\x01\x00" * 512)
    tracker.segment_finalized(400, output_hold_ms=800)
    handler.commit_boundary(turn_id, rev0)
    out0 = list(handler.process(VADAudio(audio=np.zeros(512, dtype=np.float32), mode="final", turn_id=turn_id, turn_revision=rev0)))
    assert [o.text for o in out0] == ["Open"]

    turn_id2, rev1, reopened = tracker.speech_started(600)
    assert reopened and turn_id2 == turn_id and rev1 == 1
    handler.start_turn(turn_id2, rev1)
    handler.append_audio(b"\x02\x00" * 512)
    tracker.segment_finalized(1000)
    handler.commit_boundary(turn_id2, rev1)
    out1 = list(handler.process(VADAudio(audio=np.zeros(512, dtype=np.float32), mode="final", turn_id=turn_id2, turn_revision=rev1)))
    assert [o.text for o in out1] == ["Open YouTube"]
    handler.cleanup()


def test_riva_streaming_grpc_discard_and_cancel_and_offline_fallback(monkeypatch):
    state = _install_streaming_fake_riva(monkeypatch, raise_in_stream=True, offline_text="Recovered command")
    tracker = SpeculativeTurnTracker()
    handler = RivaSTTHandler(Event(), Queue(), Queue(), setup_kwargs={"use_grpc": True, "api_key": "nvapi-stream"})
    handler.speculative_turns = tracker

    # Rejected burst: discard cleanly, no crash.
    handler.append_audio(b"\x01\x00" * 256)
    handler.discard_utterance()

    # Stream error falls back cleanly to offline_recognize.
    tid, rev, _ = tracker.speech_started(100)
    handler.start_turn(tid, rev)
    handler.append_audio(b"\x02\x00" * 256)
    tracker.segment_finalized(300)
    handler.commit_boundary(tid, rev)
    outputs = list(handler.process(VADAudio(audio=np.zeros(512, dtype=np.float32), mode="final", turn_id=tid, turn_revision=rev)))
    assert [o.text for o in outputs if isinstance(o, Transcription)] == ["Recovered command"]
    assert state["offline_calls"] == 2  # warmup + fallback

    # cancel_session invalidates in-flight/committed stream so stale commit yields nothing.
    tid2, rev2, _ = tracker.speech_started(500)
    handler.start_turn(tid2, rev2)
    handler.append_audio(b"\x03\x00" * 256)
    handler.commit_boundary(tid2, rev2)
    handler.cancel_session()
    assert list(handler.process(VADAudio(audio=np.zeros(512, dtype=np.float32), mode="final", turn_id=tid2, turn_revision=rev2))) == []
    handler.cleanup()


def test_riva_unary_grpc_disables_punctuation_and_falls_back_to_http(monkeypatch):
    _install_streaming_fake_riva(monkeypatch, offline_text="open youtube")
    handler = RivaSTTHandler(
        Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "use_grpc": True,
            "streaming": False,
            "api_key": "nvapi-unary",
            "http_url": "https://example.test/v1/audio/transcriptions",
        },
    )
    cfg = handler._build_recognition_config("en-US")
    assert cfg.enable_automatic_punctuation is False

    # Simulate a gRPC Recognize deadline timeout and verify immediate HTTP fallback.
    class _TimeoutStub:
        def Recognize(self, _request, **_kwargs):
            raise TimeoutError("Deadline Exceeded")

    fake_rasr = SimpleNamespace(RecognizeRequest=lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setitem(sys.modules, "riva.client.proto.riva_asr_pb2", fake_rasr)
    sys.modules["riva.client.proto"].riva_asr_pb2 = fake_rasr
    handler._asr_service.stub = _TimeoutStub()
    handler._auth.get_auth_metadata = lambda: []
    monkeypatch.setattr(handler, "_transcribe_http", lambda _pcm, _lang: "close tab")

    out = list(handler.process(VADAudio(audio=np.zeros(512, dtype=np.float32), mode="final", turn_id="t1", turn_revision=0)))
    assert [o.text for o in out if isinstance(o, Transcription)] == ["close tab"]
    # Second turn during 60s backoff goes straight to HTTP without calling gRPC Recognize again.
    grpc_calls = []
    handler._asr_service.stub = SimpleNamespace(Recognize=lambda *a, **kw: grpc_calls.append(1))
    out2 = list(handler.process(VADAudio(audio=np.zeros(512, dtype=np.float32), mode="final", turn_id="t2", turn_revision=0)))
    assert [o.text for o in out2 if isinstance(o, Transcription)] == ["close tab"]
    assert grpc_calls == []
    handler.cleanup()
