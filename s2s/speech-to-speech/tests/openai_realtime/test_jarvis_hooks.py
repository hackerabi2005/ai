"""Tests for Jarvis direct TTS `/v1/say` injection and `/utterance` transcript tap."""

from __future__ import annotations

from queue import Queue
from threading import Event

import httpx2
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.pipeline_unit import OutputSignal, PipelineUnit
from speech_to_speech.api.openai_realtime.service import RealtimeService
from speech_to_speech.api.openai_realtime.websocket_router import create_app
from speech_to_speech.pipeline.cancel_scope import CancelScope
from speech_to_speech.pipeline.events import (
    AssistantOutputEvent,
    AssistantResponseDoneEvent,
    SpeechStartedEvent,
    SpeechStoppedEvent,
    TranscriptionCompletedEvent,
)
from speech_to_speech.pipeline.messages import EndOfResponse, TTSInput
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker


def _make_unit(*, with_tts_queue: bool = True) -> tuple[PipelineUnit, Queue, Queue]:
    signal = OutputSignal()
    text_prompt_queue: Queue = Queue()
    output_queue: Queue = Queue()
    text_output_queue: Queue = Queue()
    tts_input_queue: Queue | None = Queue() if with_tts_queue else None
    tracker = SpeculativeTurnTracker()
    service = RealtimeService(
        text_prompt_queue=text_prompt_queue,
        should_listen=Event(),
        speculative_turns=tracker,
    )
    unit = PipelineUnit(
        index=0,
        service=service,
        cancel_scope=CancelScope(),
        should_listen=service.should_listen,
        response_playing=Event(),
        input_queue=Queue(),
        output_queue=output_queue,
        text_output_queue=text_output_queue,
        text_prompt_queue=text_prompt_queue,
        tts_input_queue=tts_input_queue,
        output_signal=signal,
        handlers=[],
    )
    return unit, text_prompt_queue, tts_input_queue or Queue()


def test_direct_say_enqueues_tts_items_and_protects_history_and_echo_guard(monkeypatch):
    monkeypatch.setenv("JARVIS_API_TOKEN", "test-tok")
    unit, _, tts_queue = _make_unit()
    app = create_app([unit], Event())

    with TestClient(app) as client:
        # Unauthenticated rejected when JARVIS_API_TOKEN is set.
        assert client.post("/v1/say", json={"text": "Hi"}).status_code == 401
        # No active websocket session yet -> 503.
        assert (
            client.post("/v1/say", json={"text": "Hi"}, headers={"Authorization": "Bearer test-tok"}).status_code
            == 503
        )

        with client.websocket_connect("/v1/realtime") as ws:
            ws.receive_json()  # session.created
            resp = client.post(
                "/v1/say",
                json={"text": "Opened YouTube."},
                headers={"Authorization": "Bearer test-tok"},
            )
            assert resp.status_code == 200
            assert unit.response_playing.is_set()
            data = resp.json()
            assert data["ok"] is True
            resp_key = data["response_key"]

            created = ws.receive_json()
            assert created["type"] == "response.created"
            assert created["response"].get("conversation_id") is None

            # Verify exact queue ordering into TTS: text event -> TTSInput -> done -> EndOfResponse.
            items = [tts_queue.get_nowait() for _ in range(4)]
            assert isinstance(items[0], AssistantOutputEvent)
            assert isinstance(items[1], TTSInput)
            assert items[1].text == "Opened YouTube."
            assert items[1].response_key == resp_key
            assert isinstance(items[2], AssistantResponseDoneEvent)
            assert isinstance(items[3], EndOfResponse)

            # While active, non-interrupt say returns 409 busy; interrupt=True cancels & replaces.
            busy = client.post(
                "/v1/say",
                json={"text": "Another line"},
                headers={"Authorization": "Bearer test-tok"},
            )
            assert busy.status_code == 409

            interrupted = client.post(
                "/v1/say",
                json={"text": "Stopped.", "interrupt": True},
                headers={"Authorization": "Bearer test-tok"},
            )
            assert interrupted.status_code == 200
            cancelled_msg = ws.receive_json()
            assert cancelled_msg["type"] == "response.done"
            assert cancelled_msg["response"]["status"] == "cancelled"
            new_created = ws.receive_json()
            assert new_created["type"] == "response.created"

            # Chat history stayed untouched (out-of-band).
            assert unit.service._state(unit.session.session_id).runtime_config.chat.buffer == []


def test_utterance_tap_suppresses_llm_on_handled_and_ignores_echoes(monkeypatch):
    tapped: list[dict] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"handled": True, "suppress_llm": True, "quit": False}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def post(self, url, headers=None, json=None):
            tapped.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setenv("JARVIS_API_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("JARVIS_API_TOKEN", "tap-tok")
    monkeypatch.setattr(httpx2, "AsyncClient", FakeAsyncClient)

    unit, prompt_queue, _ = _make_unit()
    tracker = unit.service.speculative_turns
    assert tracker is not None
    app = create_app([unit], Event())

    with TestClient(app) as client:
        with client.websocket_connect("/v1/realtime") as ws:
            ws.receive_json()  # session.created
            sid = unit.session.session_id

            # Record assistant output to arm the echo guard.
            unit.service._state(sid).recent_assistant_spoken_texts.append((1e12, "Opening YouTube now."))

            # 1. Self-echo must NOT hit /utterance or prompt_queue.
            t_echo, r_echo, _ = tracker.speech_started(10)
            unit.text_output_queue.put(SpeechStartedEvent(audio_start_ms=10, turn_id=t_echo, turn_revision=r_echo))
            tracker.segment_finalized(500)
            unit.text_output_queue.put(
                SpeechStoppedEvent(duration_s=0.5, audio_end_ms=500, turn_id=t_echo, turn_revision=r_echo)
            )
            unit.text_output_queue.put(
                TranscriptionCompletedEvent(transcript="Opening YouTube now", turn_id=t_echo, turn_revision=r_echo)
            )

            # 2. Real command hits /utterance once and suppresses LLM queue when suppress_llm=True.
            t1, r1, _ = tracker.speech_started(1000)
            unit.text_output_queue.put(SpeechStartedEvent(audio_start_ms=1000, turn_id=t1, turn_revision=r1))
            tracker.segment_finalized(1800)
            unit.text_output_queue.put(
                SpeechStoppedEvent(duration_s=0.8, audio_end_ms=1800, turn_id=t1, turn_revision=r1)
            )
            unit.text_output_queue.put(
                TranscriptionCompletedEvent(transcript="open youtube", turn_id=t1, turn_revision=r1)
            )

            # Drain websocket until transcription.completed for "open youtube" arrives.
            seen_transcripts = []
            for _ in range(12):
                msg = ws.receive_json()
                if msg.get("type") == "conversation.item.input_audio_transcription.completed":
                    seen_transcripts.append(msg["transcript"])
                    break

            assert seen_transcripts == ["open youtube"]
            assert len(tapped) == 1
            assert tapped[0]["url"] == "http://127.0.0.1:9999/utterance"
            assert tapped[0]["json"]["text"] == "open youtube"
            assert prompt_queue.empty()
            # Router-handled commands must not leave dangling user turns in Nemotron chat history.
            assert unit.service._state(sid).runtime_config.chat.buffer == []
            # Handled /utterance commands close the turn so rapid follow-up commands start fresh turns.
            t2, r2, reopened = tracker.speech_started(2500)
            assert reopened is False
            assert t2 != t1 and r2 == 0
