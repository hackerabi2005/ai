# Jarvis Handoff Document

## 1. Repository & Git Status
- **Remote:** `https://github.com/hackerabi2005/ai.git` (`main`)
- **Author:** `hackerabi2005 <abishekji2005@gmail.com>`
- **Language Breakdown:** Configured via [.gitattributes](file:///c:/Users/Abish/Desktop/combinned%20jarvis/.gitattributes) so GitHub Linguist reports **100% Rust** across [jarvis-rs/](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs) and [rust/](file:///c:/Users/Abish/Desktop/combinned%20jarvis/rust).

---

## 2. Architecture Overview

```mermaid
flowchart LR
    Mic["Microphone / ONNX Silero VAD"] --> STT["Riva STT (NVCF gRPC)"]
    STT --> Router["jarvis-rs Router (<1ms deterministic)"]
    Router -->|Direct Voice Route| Broker["jarvis-rs Broker"]
    STT -->|Conversational / Q&A| LLM["Nemotron-3-Ultra LLM"]
    LLM -->|Tool Calls| Broker
    Broker -->|JSON-Lines stdio| Bridge["jev_bridge.py + PyO3 Crates"]
    Bridge -->|CDP| Chrome["Local Chrome Session"]
    Broker -->|Spoken Feedback| TTS["Riva TTS (Chatterbox 16kHz)"]
```

### Core Components
1. **Rust Supervisor, Router, Broker & CLI (`jarvis-rs/`)**
   - [supervisor.rs](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/src/supervisor.rs): Checks `127.0.0.1:8765` availability before spawning, launches the local loopback tool API, warms Chrome in a non-blocking background `tokio::spawn` task (seeding initial active URL), injects all 9 PyO3 crates into `PYTHONPATH`, supervises `speech-to-speech` + `jev_bridge.py`, and runs per-spawn `announce_when_ready` (60s window).
   - [router.rs](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/src/router.rs): Deterministic `<1ms` voice router for 40+ browser, media, tab, scroll, zoom, search, and appearance commands.
   - [broker.rs](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/src/broker.rs) & [api.rs](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/src/api.rs): Enforces `PipelineGuard` concurrency locking across multi-step voice pipelines, honors mid-flight `stop_requested` checks in `open_url` / `click_target`, and runs `is_risky_action` confirmation gates.
   - [Cargo.toml](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/Cargo.toml): Includes `[profile.release]` (`opt-level = 3`, `lto = "thin"`, `codegen-units = 1`, `strip = "symbols"`).

2. **PyO3 Rust Port Crates (`rust/`) & Wired Call Sites**
   - Mapped in [PORT_MAP.md](file:///c:/Users/Abish/Desktop/combinned%20jarvis/rust/PORT_MAP.md) and unified in [rust/app/src/lib.rs](file:///c:/Users/Abish/Desktop/combinned%20jarvis/rust/app/src/lib.rs).
   - Benchmark-verified Rust accelerators wired directly into Python (`try/except ImportError` fallbacks preserved):
     - `llm_rs`: [LLM/utils.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/LLM/utils.py) (`remove_markdown` optimized with byte fast-path checks: `20.97x` faster on plain prose / `1.44x` on markdown, `1,603/1,603` diff cases matching; `remove_unspeechable` `3.84x` faster).
     - `tool_call_rs`: [function_call.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py) (`find_json_tool_call_end` `15.97x` faster).
     - `stt_rs`: [nemotron_transcribe.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/STT/nemotron_transcribe.py) (`clean_transcript` `6.45x` faster).
     - `tts_rs`: [persian_normalization.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/TTS/persian_normalization.py) (`normalize` `2.64x` faster).

---

## 3. Fixes & Optimizations

### A. Cold Startup Speed (`29.14s` → `4.67s`) & Clean Shutdown
- **ONNX Silero VAD Without PyTorch ([vad_iterator.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/VAD/vad_iterator.py), [vad_handler.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/VAD/vad_handler.py), [s2s_pipeline.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/s2s_pipeline.py)):**
  - Replaced top-level `import torch` across VAD and pipeline modules with lazy `torch` loading and pure-NumPy `SileroOnnxModel` via `onnxruntime` (`max_diff = 4.23e-06` vs PyTorch JIT, matching trigger parity).
  - `build_configured_server()` cold build runs in `4.67s` with `torch_loaded=False`.
- **Spawn Audio Worker Isolation ([_audio_worker.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/_audio_worker.py), [audio_client.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/audio_client.py), [cli.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/cli.py)):**
  - Extracted the spawned child-process audio loop into lightweight `_audio_worker.py` (`0.227s` import vs `1.703s` for `audio_client.py`).
- **Non-Blocking Warmup & Thread-Safe Shutdown ([riva_stt_handler.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/STT/riva_stt_handler.py), [riva_tts_handler.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/TTS/riva_tts_handler.py), [chat_completions_language_model.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/LLM/chat_completions_language_model.py), [base_openai_compatible_language_model.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/LLM/base_openai_compatible_language_model.py)):**
  - Moved Riva STT (`15s` warmup RPC, lock-protected `_grpc_lock`), Riva TTS, and LLM warmups onto tracked background daemon threads using sync client + `_closed` event guards and short `join(timeout=1.0)` on `cleanup()`. Eliminates cold `DEADLINE_EXCEEDED` startup blocks, cross-thread `asyncio.Runner` cleanup failures, and CPython `_enter_buffered_busy` stderr crashes on exit.

### B. Deadlock, Broken Imports & Protocol Fixes
- **Bounded Chrome Warmup & CDP Keys ([jev_bridge.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/python/jev_bridge.py)):**
  - Added `_ensure_daemon_bounded(8.0)` so `warm_browser` / tab attach never deadlocks Chrome's `Allow remote debugging?` popup, prewarms `jev` HTTP async, returns attached active URL to seed `Broker.record_initial_url`, and uses `_dispatch_key(browser, "press_enter")` (with `char` `\r` event).
- **Removed Stale Deleted-Module Imports ([s2s_pipeline.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/s2s_pipeline.py)):**
  - Fixed `HfArgumentParser` `F821` error and replaced references to deleted `diarization`, `STV.w2v_stv_handler`, and `TTS.phonon_tts_handler` with explicit `ValueError` errors.
- **Loopback Tap Resilience ([websocket_router.py](file:///c:/Users/Abish/Desktop/combinned%20jarvis/s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/websocket_router.py)):**
  - Retries `/utterance` once with a fresh `httpx2.AsyncClient` on `TransportError`.
- **Offline-Friendly Diagnostics ([main.rs](file:///c:/Users/Abish/Desktop/combinned%20jarvis/jarvis-rs/src/main.rs)):**
  - Upgraded `jarvis doctor` to verify `.env` keys, Python venvs, `jarvis_s2s.yaml`, PyO3 extensions, Silero ONNX cache, port `127.0.0.1:8765`, `jev_bridge` ping, and treat unlaunched Chrome/daemon/Browser-Use-cloud lines as informational rather than fatal.

---

## 4. How to Run & Verify

### Start Jarvis (Release)
```powershell
cargo run --release --manifest-path "c:\Users\Abish\Desktop\combinned jarvis\jarvis-rs\Cargo.toml" -- run
```
Wait for `Ready — start speaking.` / `ASSISTANT: Jarvis ready.` before speaking.

### Run Diagnostics & Test Suites
```powershell
# System & config doctor
.\jarvis-rs\target\release\jarvis.exe doctor

# Rust supervisor, router, broker & API tests (30 tests: 10 lib + 20 integration)
cargo clippy --all-targets --manifest-path "jarvis-rs\Cargo.toml" -- -D warnings
cargo test --manifest-path "jarvis-rs\Cargo.toml"

# Unified Rust workspace & llm-rs
cargo clippy --workspace --all-targets --manifest-path "rust\app\Cargo.toml" -- -D warnings
cargo test --workspace --manifest-path "rust\app\Cargo.toml"
cargo test --manifest-path "rust\llm-rs\Cargo.toml"

# Python suites (use venv python directly so copied shebangs don't resolve old paths)
.\borwse` harness\jev-ultrafast\.venv\Scripts\python.exe -m pytest jarvis-rs\python\test_jev_bridge.py -v
.\s2s\speech-to-speech\.venv\Scripts\python.exe -m pytest jarvis-rs\python\test_jarvis_tools.py -v
.\s2s\speech-to-speech\.venv\Scripts\python.exe -m ruff check --select E9,F63,F7,F82 jarvis-rs\python "borwse harness\jev-ultrafast\jev_ultrafast" s2s\speech-to-speech\src
```
