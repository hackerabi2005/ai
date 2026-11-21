# Architecture Decision Records — Jarvis Rust Migration

## ADR-001: Scope of the Whole-App Rust Port
Status: accepted (2026-11-20)
Context: The workspace contains 208 Python files (42,834 lines) across 28 units, of which ~36,000 lines are unused alternative offline ML model plugins (`mlx`, `kokoro`, `qwen-tts`, `parler-tts`, `funasr`, `nemo`, `archive/`, `evals/big_bench_audio/`) and `presentation/build_pptx.py`. The active Jarvis voice + browser runtime (`borwse harness/jev-ultrafast/`, `jarvis-rs/python/`, and the active `s2s/speech-to-speech` pipeline configured by `jarvis-rs/config/jarvis_s2s.yaml`) comprises the latency-critical hot path.
Decision: Port the complete active Jarvis stack (`borwse harness/jev-ultrafast/jev_ultrafast/`, `borwse harness/jev-ultrafast/scripts/`, `jarvis-rs/python/`, and the active `s2s/speech-to-speech` units: `LLM/tool_call/`, `utils/`, `arguments_classes/`, `VAD/`, `STT/`, `LLM/`, `TTS/`, `pipeline/`, `api/openai_realtime/`, `src/speech_to_speech/`) to Rust to minimize latency while keeping 100% identical outputs. Mark unused offline S2S backends (`archive/`, `zerogpu/`, `evals/`, unused local TTS/STT models) and `presentation/` out of scope.
Consequences: Focuses engineering and verification on every line that runs in Jarvis or its guard/benchmark suite, eliminating Python interpreter and IPC latency without wasting cycles on dead model plugins.

## ADR-002: Target Shape and Front Door
Status: accepted (2026-11-20)
Context: `jarvis-rs` already provides the Rust CLI entry point (`jarvis doctor`, `jarvis browse`, `jarvis run`) and loopback `axum` tool API, while spawning Python subprocesses for `jev_bridge.py` and `speech_to_speech.cli`.
Decision: Build and verify unit crates under `rust/` using `rust-anything` (`bridge`, `record`, `build`, `diff`, `bench`, `shadow`, `gate`), wire their shadows/modules into the runtime, and lift the active units into a pure-Rust runtime while keeping all CLI flags, environment variables, JSON-RPC envelopes, and HTTP/WebSocket endpoints (`/v1/say`, `/v1/pool`, `/utterance`) identical.
Consequences: External callers, tests, and voice workflows see zero behavioral or output changes while cross-process and Python overhead is removed.

## ADR-003: Browser Agent & CDP Layer
Status: accepted (2026-11-20)
Context: `jev_ultrafast` (`agent.py`, `client.py`, `parse.py`, `prompt.py`, `schema.py`, `trace.py`, `demo.py`) and `jarvis-rs/python/jev_bridge.py` sit on the critical latency path between user voice commands, the `jev-latest` HTTP/2 endpoint, and Chrome CDP (via `browser-harness` / `bh`).
Decision: Port all `jev_ultrafast` parsing, prompt formatting, schema/action validation, guard checks, trace formatting, and `jev_bridge` heuristic/planning logic to Rust with 100% output equivalence, and connect directly to the browser harness / CDP from Rust.
Consequences: Eliminates Python startup, JSON serialization overhead, and per-step parsing/prompting latency on browser tasks.

## ADR-004: Equivalence Bar and Numeric Tolerance
Status: accepted (2026-11-20)
Context: The user requires zero change to functionality or output while maximizing latency improvements.
Decision:
- Deterministic units (`jev_ultrafast`, `jev_ultrafast/scripts`, `jarvis-rs/python`, `LLM/tool_call`, `arguments_classes`, `utils` string/config helpers): 100% exact match on `rust-anything diff` and `gate`.
- Numeric/audio/VAD units (`utils` audio helpers, `VAD`, `STT`, `TTS` PCM math): `--float-tolerance 1e-6`.
- External network effects (Experiential Labs `jev-latest`, NVIDIA Riva gRPC STT/TTS, NVIDIA NIM chat completions): verified against recorded fixtures.
Consequences: Any output mismatch fails `diff`/`gate` and must be fixed in the Rust port, never by mutating recordings.

## ADR-005: Dependency Mapping to Rust Crates
Status: accepted (2026-11-20)
Context: `analyze --whole-app` flagged Python dependencies with `none`, `partial`, or `unknown` fit.
Decision:
- `fastapi` / `starlette` / `uvicorn` / `websockets` -> `axum` + `tokio` + `tokio-tungstenite`
- `httpx` / `httpx2` / `requests` / `openai` -> `reqwest` (with HTTP/2 + streaming SSE)
- `pydantic` / `jsonschema` -> `serde` + `serde_json`
- `yaml` / `omegaconf` -> `serde_yaml_ng`
- `numpy` / `scipy` / `soxr` (active audio/PCM slice) -> `ndarray` + pure-Rust PCM resampling/conversion
- `riva` -> `tonic` + `prost` (NVIDIA Riva gRPC protocol)
- `onnxruntime` / `torch` (Silero VAD) -> `ort`
- `sounddevice` -> `cpal`
- `pywebrtc-audio` -> `webrtc-audio-processing` / AEC3 FFI
- Python `dict` / `set` where insertion order reaches output -> `indexmap`
- Python `re` -> `regex` (and `fancy-regex` where lookaround/backreferences are used)
Consequences: Every active runtime dependency has a fast, battle-tested Rust replacement.

## ADR-006: Wave Order and Checkpoints
Status: accepted (2026-11-20)
Context: Porting unit-by-unit with `rust-anything` ensures each unit passes `record`, `diff`, `bench`, and `gate` before moving on.
Decision: Port in priority order of latency impact and dependency waves:
1. Wave 0/1 Browser Agent & Scripts: `borwse harness/jev-ultrafast/jev_ultrafast/` and `borwse harness/jev-ultrafast/scripts/`
2. Wave 1 Jarvis Python Bridge & Tools: `jarvis-rs/python/` (`jev_bridge.py`, `jarvis_tools.py`)
3. Active S2S Core Units: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/`, `s2s/speech-to-speech/src/speech_to_speech/utils/`, `s2s/speech-to-speech/src/speech_to_speech/arguments_classes/`, `VAD/`, `STT/`, `LLM/`, `TTS/`, `pipeline/`, `api/openai_realtime/`.
Consequences: Delivers immediate, measurable latency gains on the browser and voice hot paths first while keeping the repo green at every step.
