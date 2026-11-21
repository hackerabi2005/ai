# Rust migration plan: combinned jarvis (Python)

3 packages, 208 source files (42834 lines), 160 test files, 0 UI files, grouped into 28 units.

| Ready | Caution | Blocked | Keep in source language |
| ---: | ---: | ---: | ---: |
| 5 | 21 | 2 | 0 |

## Start here

Best first ports: safe to port (readiness) and worth porting (loops and string work, tests, size).

| # | Unit | Lines | Priority | Readiness | Tests | Bridge | Main risks |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `borwse harness/jev-ultrafast/scripts/` | 486 | 61 | 59 | 0 | PyO3 | Hash iteration order (6); String offsets and slicing (1); Dynamic typing (4) |
| 2 | `presentation/` | 554 | 59 | 76 | 0 | PyO3 | Dynamic typing (6); Division and modulo (1); Number semantics (2) |
| 3 | `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/` | 528 | 59 | 43 | 5 | PyO3 | Regexes built at runtime (5); Hash iteration order (5); String offsets and slicing (4) |
| 4 | `s2s/speech-to-speech/src/speech_to_speech/utils/` | 399 | 52 | 46 | 7 | PyO3 | numpy array parameters (2); String offsets and slicing (1); Dynamic typing (7) |
| 5 | `s2s/speech-to-speech/src/speech_to_speech/zerogpu/` | 874 | 30 | 7 | 2 | PyO3 | Hash iteration order (5); Dynamic typing (48); Generators (22) |
| 6 | `s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/` | 1573 | 28 | 0 | 8 | PyO3 | String offsets and slicing (12); Hash iteration order (4); Regexes built at runtime (1) |
| 7 | `s2s/speech-to-speech/src/speech_to_speech/LLM/` | 5355 | 28 | 0 | 44 | PyO3 | Hash iteration order (46); String offsets and slicing (32); Regexes built at runtime (1) |
| 8 | `borwse harness/jev-ultrafast/jev_ultrafast/` | 1531 | 27 | 0 | 2 | PyO3 | Hash iteration order (25); String offsets and slicing (11); Runtime changes to code (1) |
| 9 | `s2s/speech-to-speech/src/speech_to_speech/TTS/` | 4612 | 26 | 0 | 36 | PyO3 | String offsets and slicing (54); Hash iteration order (42); numpy array parameters (17) |
| 10 | `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/` | 2953 | 26 | 0 | 1 | PyO3 | Hash iteration order (12); String offsets and slicing (7); Dynamic typing (48) |

### `borwse harness/jev-ultrafast/scripts/`

486 lines in 6 files, wave 1, priority 61, readiness 59, bridge **PyO3**.

- 2 PyPI dependencies not in the crate table: check them by hand.
- Hash iteration order x6: `borwse harness/jev-ultrafast/scripts/check_guards.py:105`, `borwse harness/jev-ultrafast/scripts/check_guards.py:105`, `borwse harness/jev-ultrafast/scripts/check_guards.py:106`
- String offsets and slicing x1: `borwse harness/jev-ultrafast/scripts/render_fixture.py:34`
- Dynamic typing x4: `borwse harness/jev-ultrafast/scripts/measure_flights.py:34`, `borwse harness/jev-ultrafast/scripts/measure_flights.py:51`, `borwse harness/jev-ultrafast/scripts/render_demo.py:27`
- Concurrency x1: `borwse harness/jev-ultrafast/scripts/record_flights.py:52`
- Exceptions x10: `borwse harness/jev-ultrafast/scripts/check_guards.py:20`, `borwse harness/jev-ultrafast/scripts/check_guards.py:61`, `borwse harness/jev-ultrafast/scripts/check_guards.py:66`

### `presentation/`

554 lines in 1 files, wave 0, priority 59, readiness 76, bridge **PyO3**.

- 1 PyPI dependencies not in the crate table: check them by hand.
- Leaf: imports no other unit.
- Dynamic typing x6: `presentation/build_pptx.py:28`, `presentation/build_pptx.py:65`, `presentation/build_pptx.py:80`
- Division and modulo x1: `presentation/build_pptx.py:174`
- Number semantics x2: `presentation/build_pptx.py:28`, `presentation/build_pptx.py:65`
- Exceptions x1: `presentation/build_pptx.py:52`

### `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/`

528 lines in 4 files, wave 0, priority 59, readiness 43, bridge **PyO3**.

- 1 PyPI dependencies not in the crate table: check them by hand.
- Import cycle with s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/, s2s/speech-to-speech/src/speech_to_speech/arguments_classes/, s2s/speech-to-speech/src/speech_to_speech/diarization/, s2s/speech-to-speech/src/speech_to_speech/VAD/, s2s/speech-to-speech/src/speech_to_speech/STV/, s2s/speech-to-speech/src/speech_to_speech/TTS/, s2s/speech-to-speech/src/speech_to_speech/zerogpu/, s2s/speech-to-speech/src/speech_to_speech/STT/, s2s/speech-to-speech/src/speech_to_speech/, s2s/speech-to-speech/src/speech_to_speech/pipeline/, s2s/speech-to-speech/src/speech_to_speech/utils/, s2s/speech-to-speech/src/speech_to_speech/LLM/, s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/: port them together.
- 5 test files import it directly.
- Regexes built at runtime x5: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:28`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:378`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:382`
- Hash iteration order x5: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:210`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:223`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:243`
- String offsets and slicing x4: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:88`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:305`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:307`
- Dynamic typing x27: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:125`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:127`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:135`
- Class inheritance x2: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:189`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_tool.py:8`
- Exceptions x15: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:111`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:116`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:130`
- Number semantics x2: `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:277`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/signature_from_schema.py:79`

### `s2s/speech-to-speech/src/speech_to_speech/utils/`

399 lines in 5 files, wave 0, priority 52, readiness 46, bridge **PyO3**.

- 3 PyPI dependencies not in the crate table: check them by hand.
- Import cycle with s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/, s2s/speech-to-speech/src/speech_to_speech/arguments_classes/, s2s/speech-to-speech/src/speech_to_speech/diarization/, s2s/speech-to-speech/src/speech_to_speech/VAD/, s2s/speech-to-speech/src/speech_to_speech/STV/, s2s/speech-to-speech/src/speech_to_speech/TTS/, s2s/speech-to-speech/src/speech_to_speech/zerogpu/, s2s/speech-to-speech/src/speech_to_speech/STT/, s2s/speech-to-speech/src/speech_to_speech/, s2s/speech-to-speech/src/speech_to_speech/pipeline/, s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/, s2s/speech-to-speech/src/speech_to_speech/LLM/, s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/: port them together.
- 7 test files import it directly.
- numpy array parameters x2: `s2s/speech-to-speech/src/speech_to_speech/utils/utils.py:16`, `s2s/speech-to-speech/src/speech_to_speech/utils/utils.py:128`
- String offsets and slicing x1: `s2s/speech-to-speech/src/speech_to_speech/utils/utils.py:124`
- Dynamic typing x7: `s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:20`, `s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:24`, `s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:46`
- Integer width and overflow x2: `s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:24`, `s2s/speech-to-speech/src/speech_to_speech/utils/utils.py:62`
- Concurrency x1: `s2s/speech-to-speech/src/speech_to_speech/utils/thread_manager.py:20`
- Number semantics x20: `s2s/speech-to-speech/src/speech_to_speech/utils/mlx_lock.py:38`, `s2s/speech-to-speech/src/speech_to_speech/utils/mlx_lock.py:39`, `s2s/speech-to-speech/src/speech_to_speech/utils/mlx_lock.py:40`
- Exceptions x6: `s2s/speech-to-speech/src/speech_to_speech/utils/mlx_lock.py:163`, `s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:44`, `s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:78`

### `s2s/speech-to-speech/src/speech_to_speech/zerogpu/`

874 lines in 7 files, wave 0, priority 30, readiness 7, bridge **PyO3**.

- 8 PyPI dependencies not in the crate table: check them by hand.
- Import cycle with s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/, s2s/speech-to-speech/src/speech_to_speech/arguments_classes/, s2s/speech-to-speech/src/speech_to_speech/diarization/, s2s/speech-to-speech/src/speech_to_speech/VAD/, s2s/speech-to-speech/src/speech_to_speech/STV/, s2s/speech-to-speech/src/speech_to_speech/TTS/, s2s/speech-to-speech/src/speech_to_speech/STT/, s2s/speech-to-speech/src/speech_to_speech/, s2s/speech-to-speech/src/speech_to_speech/pipeline/, s2s/speech-to-speech/src/speech_to_speech/utils/, s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/, s2s/speech-to-speech/src/speech_to_speech/LLM/, s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/: port them together.
- 2 test files import it directly.
- Hash iteration order x5: `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_tts_provider.py:14`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_tts_provider.py:42`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_worker.py:83`
- Dynamic typing x48: `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:14`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:33`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:46`
- Generators x22: `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:118`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:118`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_qwen_tts.py:32`
- Class inheritance x5: `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:13`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_qwen_tts.py:48`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_stt.py:31`
- Concurrency x3: `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_worker.py:102`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_worker.py:266`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_worker.py:311`
- Exceptions x42: `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:90`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_kokoro.py:120`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/_model_qwen_tts.py:42`

## Order by package

Packages come after the workspace packages they use. Inside a package, port by wave: a unit's imports are in earlier waves.

### 1. root (`.`, portable, 2 test files)

| Wave | Unit | Status | Lines | Readiness | Bridge | Main risks |
| ---: | --- | --- | ---: | ---: | --- | --- |
| 0 | `presentation/` | ready | 554 | 76 | PyO3 | Dynamic typing (6); Division and modulo (1) |
| 1 | `jarvis-rs/python/` | caution | 1536 | 1 | PyO3 | Hash iteration order (15); String offsets and slicing (5) |

### 2. jev-ultrafast (`borwse harness/jev-ultrafast`, portable, 1 test files)

| Wave | Unit | Status | Lines | Readiness | Bridge | Main risks |
| ---: | --- | --- | ---: | ---: | --- | --- |
| 0 | `borwse harness/jev-ultrafast/jev_ultrafast/` | caution | 1531 | 0 | PyO3 | Hash iteration order (25); String offsets and slicing (11) |
| 1 | `borwse harness/jev-ultrafast/scripts/` | ready | 486 | 59 | PyO3 | Hash iteration order (6); String offsets and slicing (1) |

### 3. speech-to-speech (`s2s/speech-to-speech`, portable, 157 test files)

| Wave | Unit | Status | Lines | Readiness | Bridge | Main risks |
| ---: | --- | --- | ---: | ---: | --- | --- |
| 0 | `s2s/speech-to-speech/archive/` | ready | 0 | 100 | PyO3 | - |
| 0 | `s2s/speech-to-speech/archive/arguments_classes/` | caution | 81 | 100 | PyO3 | - |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/api/` | ready | 0 | 100 | PyO3 | - |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/evals/` | ready | 1 | 100 | PyO3 | - |
| 0 | `s2s/speech-to-speech/demo/livekit/` | caution | 44 | 92 | PyO3 | Async and promises (4); Class inheritance (1) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/STV/` | caution | 175 | 63 | PyO3 | String offsets and slicing (3); numpy array parameters (1) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/arguments_classes/` | caution | 1724 | 57 | PyO3 | Class inheritance (6); Number semantics (14) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/diarization/` | caution | 397 | 51 | PyO3 | String offsets and slicing (5); numpy array parameters (4) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/utils/` | caution | 399 | 46 | PyO3 | numpy array parameters (2); String offsets and slicing (1) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/` | caution | 528 | 43 | PyO3 | Regexes built at runtime (5); Hash iteration order (5) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/zerogpu/` | caution | 874 | 7 | PyO3 | Hash iteration order (5); Dynamic typing (48) |
| 0 | `s2s/speech-to-speech/demo/` | blocked | 1141 | 0 | PyO3 | String offsets and slicing (5); Hash iteration order (5) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/` | caution | 3229 | 0 | PyO3 | Hash iteration order (77); String offsets and slicing (7) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/LLM/` | caution | 5355 | 0 | PyO3 | Hash iteration order (46); String offsets and slicing (32) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/STT/` | caution | 4694 | 0 | PyO3 | numpy array parameters (19); Hash iteration order (17) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/TTS/` | caution | 4612 | 0 | PyO3 | String offsets and slicing (54); Hash iteration order (42) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/VAD/` | caution | 1421 | 0 | PyO3 | numpy array parameters (12); String offsets and slicing (9) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/` | blocked | 5740 | 0 | PyO3 | Hash iteration order (40); String offsets and slicing (33) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/` | caution | 2953 | 0 | PyO3 | Hash iteration order (12); String offsets and slicing (7) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/` | caution | 1573 | 0 | PyO3 | String offsets and slicing (12); Hash iteration order (4) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/pipeline/` | caution | 2060 | 0 | PyO3 | Hash iteration order (12); String offsets and slicing (1) |
| 1 | `s2s/speech-to-speech/archive/STT/` | caution | 52 | 83 | PyO3 | String offsets and slicing (1); Generators (2) |
| 1 | `s2s/speech-to-speech/archive/TTS/` | caution | 315 | 43 | PyO3 | String offsets and slicing (5); Generators (8) |
| 1 | `s2s/speech-to-speech/scripts/` | caution | 1359 | 0 | PyO3 | String offsets and slicing (5); Hash iteration order (1) |

## PyPI dependencies

| Package | Units | Rust | Fit | Note |
| --- | ---: | --- | --- | --- |
| `fastapi` | 2 | - | none | Web framework: keep the app in Python. |
| `starlette` | 1 | - | none | Web framework: keep the app in Python. |
| `torch` | 11 | ? | unknown |  |
| `openai` | 10 | ? | unknown |  |
| `transformers` | 9 | ? | unknown |  |
| `httpx2` | 7 | ? | unknown |  |
| `huggingface-hub` | 6 | ? | unknown |  |
| `scipy` | 6 | ? | unknown |  |
| `soundfile` | 4 | ? | unknown |  |
| `websockets` | 4 | ? | unknown |  |
| `browser-harness` | 3 | ? | unknown |  |
| `librosa` | 3 | ? | unknown |  |
| `mlx` | 3 | ? | unknown |  |
| `faster-qwen3-tts` | 2 | ? | unknown |  |
| `kokoro` | 2 | ? | unknown |  |
| `mlx-audio` | 2 | ? | unknown |  |
| `nano-parakeet` | 2 | ? | unknown |  |
| `nltk` | 2 | ? | unknown |  |
| `riva` | 2 | ? | unknown |  |
| `soxr` | 2 | ? | unknown |  |
| `aioice` | 1 | ? | unknown |  |
| `aiortc` | 1 | ? | unknown |  |
| `anyio` | 1 | ? | unknown |  |
| `auth` | 1 | ? | unknown |  |
| `chattts` | 1 | ? | unknown |  |
| `df` | 1 | ? | unknown |  |
| `examples` | 1 | ? | unknown |  |
| `faster-whisper` | 1 | ? | unknown |  |
| `fireredvad` | 1 | ? | unknown |  |
| `funasr` | 1 | ? | unknown |  |
| `jsonschema` | 1 | ? | unknown |  |
| `kittenml` | 1 | ? | unknown |  |
| `lightning-whisper-mlx` | 1 | ? | unknown |  |
| `limiter` | 1 | ? | unknown |  |
| `lingua` | 1 | ? | unknown |  |
| `melo` | 1 | ? | unknown |  |
| `mlx-lm` | 1 | ? | unknown |  |
| `mlx-vlm` | 1 | ? | unknown |  |
| `moonshine` | 1 | ? | unknown |  |
| `nemo` | 1 | ? | unknown |  |
| `omegaconf` | 1 | ? | unknown |  |
| `omnivoice` | 1 | ? | unknown |  |
| `onnxruntime` | 1 | ? | unknown |  |
| `parler-tts` | 1 | ? | unknown |  |
| `pocket-tts` | 1 | ? | unknown |  |
| `pptx` | 1 | ? | unknown |  |
| `ptts` | 1 | ? | unknown |  |
| `pywebrtc-audio` | 1 | ? | unknown |  |
| `qwen-tts` | 1 | ? | unknown |  |
| `sounddevice` | 1 | ? | unknown |  |
| `spaces` | 1 | ? | unknown |  |
| `supertonic` | 1 | ? | unknown |  |
| `torch-npu` | 1 | ? | unknown |  |
| `torchaudio` | 1 | ? | unknown |  |
| `uvicorn` | 1 | ? | unknown |  |
| `numpy` | 13 | ndarray | partial | Broadcasting and dtype rules differ; check numerics. |
| `pydantic` | 5 | serde, garde | partial | Validation errors will differ. |
| `pil` | 2 | image | partial |  |
| `av` | 1 | ffmpeg-next | partial | Binds the C libraries. For pure Rust, remade-ffmpeg covers a subset of codecs (and has an ffmpeg-compatible CLI): check its codec table. |
| `yaml` | 1 | serde_yaml_ng, saphyr | partial | Round-tripping comments is not covered. |
| `rich` | 5 | owo-colors, anstream | good |  |
| `httpx` | 1 | reqwest | good |  |
| `jinja2` | 1 | minijinja | good | Same template language, by Jinja's author. |
| `requests` | 1 | reqwest | good |  |

## Blocked

- `s2s/speech-to-speech/demo/`: `fastapi` has no Rust equivalent.
- `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/`: `fastapi` has no Rust equivalent.

## Risk guide

- **String offsets and slicing** (High): JS indexes strings in UTF-16 code units, Rust in UTF-8 bytes. Offsets that cross the boundary must be converted, or non-ASCII text gets wrong ranges silently.
- **Regex features the `regex` crate lacks** (High): Lookaround, backreferences and the `y` flag are not in the `regex` crate. Use `fancy-regex` for those patterns, or rewrite them, and test them on non-ASCII text: `\w`, `\b` and case-insensitive matching differ between engines even where a pattern compiles. JS `/i` without `u` never matches a non-ASCII letter to an ASCII one, Rust `(?i)` does (`ſ` matches `s`, the Kelvin sign `K` matches `k`): write `(?i-u)` or compare with `eq_ignore_ascii_case`.
- **Regexes built at runtime** (High): Patterns come from data or config in JS syntax. Rust regex syntax differs, so user-visible behavior can change. Pin it with tests on real patterns.
- **Dynamic typing** (Medium): Values whose shape is checked at runtime need an explicit Rust enum or `serde_json::Value`.
- **Exceptions** (Low): Thrown errors become `Result`. Errors crossing the bridge must map back to the same JS error shape.
- **Async and promises** (Medium): Promises become futures. Bridge with napi-rs `async fn` or `wasm-bindgen-futures`, or keep the async shell in JS and port the sync core.
- **Generators** (Medium): Lazy generators become iterators, or return a collected Vec across the bridge.
- **Class inheritance** (Medium): Class hierarchies become traits plus composition; `instanceof` checks become enums.
- **Number semantics** (Low): JS numbers are f64; bitwise ops truncate to i32; parseInt is lenient. Pick Rust integer types deliberately. Printing differs: `${n}` gives `1e+21`, `1e-7` and `0` for -0 where Rust's `{}` does not, so use `js::number_to_string`. `Math.round` rounds halves up (-2.5 gives -2), Rust's `round` away from zero: use `js::math_round`. `toFixed` rounds exact halves up ((2.5).toFixed(0) is "3"), Rust's `{:.0}` to even.
- **Integer width and overflow** (Medium): Python ints never overflow; C, Go and Java ints wrap or are undefined on overflow. Pick i64, i128 or a bignum crate deliberately, and use wrapping_* where the source wraps.
- **Division and modulo** (Medium): Python `//` and `%` floor toward negative infinity; Rust `/` and `%` truncate: use `div_euclid`/`rem_euclid` or explicit floor math. C division by zero is undefined.
- **Hash iteration order** (High): Set and map iteration order comes from the source language's hash function. A port cannot reproduce it: sort before output, or make the order part of the contract.
- **Concurrency** (Medium): Threads, goroutines and locks need a design in Rust (channels, Send/Sync), not a line-by-line translation; keep concurrency in the caller where possible.
- **Runtime changes to code** (High): Code that rewrites classes or modules at runtime has no Rust equivalent: keep it in the source language and port the stable parts.
- **numpy array parameters** (High): `record` passes JSON values, never numpy arrays, so a function that takes `np.ndarray` gets no valid cases on the unit path. Record the app instead (`app record`, `app replay`), or port the function together with a caller that takes and returns plain lists.

## Whole app

Shape: **server**.

| Entry point | Kind | Found from |
| --- | --- | --- |
| `borwse harness/jev-ultrafast/jev_ultrafast/demo.py` | server | `HTTPServer(` at borwse harness/jev-ultrafast/jev_ultrafast/demo.py:135 |
| `borwse harness/jev-ultrafast/scripts/check_guards.py` | cli | `if __name__ == "__main__"` at borwse harness/jev-ultrafast/scripts/check_guards.py:136 |
| `borwse harness/jev-ultrafast/scripts/smoke.py` | cli | `if __name__ == "__main__"` at borwse harness/jev-ultrafast/scripts/smoke.py:56 |
| `jarvis-rs/python/jev_bridge.py` | cli | `if __name__ == "__main__"` at jarvis-rs/python/jev_bridge.py:1452 |
| `presentation/build_pptx.py` | cli | `if __name__ == "__main__"` at presentation/build_pptx.py:604 |
| `s2s/speech-to-speech/demo/livekit/agent.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/demo/livekit/agent.py:56 |
| `s2s/speech-to-speech/demo/server.py` | server | `FastAPI(` at s2s/speech-to-speech/demo/server.py:150 |
| `s2s/speech-to-speech/scripts/benchmark_stt.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/scripts/benchmark_stt.py:384 |
| `s2s/speech-to-speech/scripts/benchmark_tts.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/scripts/benchmark_tts.py:414 |
| `s2s/speech-to-speech/scripts/check_pocket_tts_farsi.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/scripts/check_pocket_tts_farsi.py:123 |
| `s2s/speech-to-speech/scripts/prepare_eval_space.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/scripts/prepare_eval_space.py:92 |
| `s2s/speech-to-speech/scripts/synthetic_conversation_realtime_client.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/scripts/synthetic_conversation_realtime_client.py:568 |
| `s2s/speech-to-speech/src/speech_to_speech/STT/smart_progressive_streaming.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/src/speech_to_speech/STT/smart_progressive_streaming.py:342 |
| `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/websocket_router.py` | server | `FastAPI(` at s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/websocket_router.py:680 |
| `s2s/speech-to-speech/src/speech_to_speech/cli.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/src/speech_to_speech/cli.py:286 |
| `s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/__main__.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/__main__.py:386 |
| `s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/job.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/job.py:79 |
| `s2s/speech-to-speech/src/speech_to_speech/s2s_pipeline.py` | cli | `if __name__ == "__main__"` at s2s/speech-to-speech/src/speech_to_speech/s2s_pipeline.py:929 |

### Every dependency

| Dependency | Declared | Used by | Rust | Fit | Note |
| --- | --- | --- | --- | --- | --- |
| `fastapi` | no | 2 | - | none | Web framework: keep the app in Python. |
| `starlette` | no | 1 | - | none | Web framework: keep the app in Python. |
| `torch` | no | 11 | ? | unknown |  |
| `openai` | no | 10 | ? | unknown |  |
| `transformers` | no | 9 | ? | unknown |  |
| `httpx2` | no | 7 | ? | unknown |  |
| `huggingface-hub` | no | 6 | ? | unknown |  |
| `scipy` | no | 6 | ? | unknown |  |
| `soundfile` | no | 4 | ? | unknown |  |
| `websockets` | no | 4 | ? | unknown |  |
| `browser-harness` | no | 3 | ? | unknown |  |
| `librosa` | no | 3 | ? | unknown |  |
| `mlx` | no | 3 | ? | unknown |  |
| `faster-qwen3-tts` | no | 2 | ? | unknown |  |
| `kokoro` | no | 2 | ? | unknown |  |
| `mlx-audio` | no | 2 | ? | unknown |  |
| `nano-parakeet` | no | 2 | ? | unknown |  |
| `nltk` | no | 2 | ? | unknown |  |
| `riva` | no | 2 | ? | unknown |  |
| `soxr` | no | 2 | ? | unknown |  |
| `aioice` | no | 1 | ? | unknown |  |
| `aiortc` | no | 1 | ? | unknown |  |
| `anyio` | no | 1 | ? | unknown |  |
| `auth` | no | 1 | ? | unknown |  |
| `chattts` | no | 1 | ? | unknown |  |
| `df` | no | 1 | ? | unknown |  |
| `examples` | no | 1 | ? | unknown |  |
| `faster-whisper` | no | 1 | ? | unknown |  |
| `fireredvad` | no | 1 | ? | unknown |  |
| `funasr` | no | 1 | ? | unknown |  |
| `jsonschema` | no | 1 | ? | unknown |  |
| `kittenml` | no | 1 | ? | unknown |  |
| `lightning-whisper-mlx` | no | 1 | ? | unknown |  |
| `limiter` | no | 1 | ? | unknown |  |
| `lingua` | no | 1 | ? | unknown |  |
| `melo` | no | 1 | ? | unknown |  |
| `mlx-lm` | no | 1 | ? | unknown |  |
| `mlx-vlm` | no | 1 | ? | unknown |  |
| `moonshine` | no | 1 | ? | unknown |  |
| `nemo` | no | 1 | ? | unknown |  |
| `omegaconf` | no | 1 | ? | unknown |  |
| `omnivoice` | no | 1 | ? | unknown |  |
| `onnxruntime` | no | 1 | ? | unknown |  |
| `parler-tts` | no | 1 | ? | unknown |  |
| `pocket-tts` | no | 1 | ? | unknown |  |
| `pptx` | no | 1 | ? | unknown |  |
| `ptts` | no | 1 | ? | unknown |  |
| `pywebrtc-audio` | no | 1 | ? | unknown |  |
| `qwen-tts` | no | 1 | ? | unknown |  |
| `sounddevice` | no | 1 | ? | unknown |  |
| `spaces` | no | 1 | ? | unknown |  |
| `supertonic` | no | 1 | ? | unknown |  |
| `torch-npu` | no | 1 | ? | unknown |  |
| `torchaudio` | no | 1 | ? | unknown |  |
| `uvicorn` | no | 1 | ? | unknown |  |
| `numpy` | no | 13 | ndarray | partial | Broadcasting and dtype rules differ; check numerics. |
| `pydantic` | no | 5 | serde, garde | partial | Validation errors will differ. |
| `pil` | no | 2 | image | partial |  |
| `av` | no | 1 | ffmpeg-next | partial | Binds the C libraries. For pure Rust, remade-ffmpeg covers a subset of codecs (and has an ffmpeg-compatible CLI): check its codec table. |
| `yaml` | no | 1 | serde_yaml_ng, saphyr | partial | Round-tripping comments is not covered. |
| `rich` | no | 5 | owo-colors, anstream | good |  |
| `httpx` | no | 1 | reqwest | good |  |
| `jinja2` | no | 1 | minijinja | good | Same template language, by Jinja's author. |
| `requests` | no | 1 | reqwest | good |  |

### Pieces, in port order

- wave 0: `borwse harness/jev-ultrafast/jev_ultrafast/` (1531 lines)
- wave 0: `presentation/` (554 lines)
- wave 0: `s2s/speech-to-speech/archive/` (0 lines)
- wave 0: `s2s/speech-to-speech/archive/arguments_classes/` (81 lines)
- wave 0: `s2s/speech-to-speech/demo/` (1141 lines)
- wave 0: `s2s/speech-to-speech/demo/livekit/` (44 lines)
- wave 0: `s2s/speech-to-speech/src/speech_to_speech/`, `s2s/speech-to-speech/src/speech_to_speech/LLM/`, `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/`, `s2s/speech-to-speech/src/speech_to_speech/STT/`, `s2s/speech-to-speech/src/speech_to_speech/STV/`, `s2s/speech-to-speech/src/speech_to_speech/TTS/`, `s2s/speech-to-speech/src/speech_to_speech/VAD/`, `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/`, `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/`, `s2s/speech-to-speech/src/speech_to_speech/arguments_classes/`, `s2s/speech-to-speech/src/speech_to_speech/diarization/`, `s2s/speech-to-speech/src/speech_to_speech/pipeline/`, `s2s/speech-to-speech/src/speech_to_speech/utils/`, `s2s/speech-to-speech/src/speech_to_speech/zerogpu/`, tangled: one piece (34161 lines)
- wave 0: `s2s/speech-to-speech/src/speech_to_speech/api/` (0 lines)
- wave 0: `s2s/speech-to-speech/src/speech_to_speech/evals/` (1 lines)
- wave 0: `s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/` (1573 lines)
- wave 1: `borwse harness/jev-ultrafast/scripts/` (486 lines)
- wave 1: `jarvis-rs/python/` (1536 lines)
- wave 1: `s2s/speech-to-speech/archive/STT/` (52 lines)
- wave 1: `s2s/speech-to-speech/archive/TTS/` (315 lines)
- wave 1: `s2s/speech-to-speech/scripts/` (1359 lines)

### Decisions for the user

**D1** (shape): The app is a server, entered through borwse harness/jev-ultrafast/jev_ultrafast/demo.py, borwse harness/jev-ultrafast/scripts/check_guards.py, borwse harness/jev-ultrafast/scripts/smoke.py, jarvis-rs/python/jev_bridge.py, presentation/build_pptx.py, s2s/speech-to-speech/demo/livekit/agent.py, s2s/speech-to-speech/demo/server.py, s2s/speech-to-speech/scripts/benchmark_stt.py, s2s/speech-to-speech/scripts/benchmark_tts.py, s2s/speech-to-speech/scripts/check_pocket_tts_farsi.py, s2s/speech-to-speech/scripts/prepare_eval_space.py, s2s/speech-to-speech/scripts/synthetic_conversation_realtime_client.py, s2s/speech-to-speech/src/speech_to_speech/STT/smart_progressive_streaming.py, s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/websocket_router.py, s2s/speech-to-speech/src/speech_to_speech/cli.py, s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/__main__.py, s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/job.py, s2s/speech-to-speech/src/speech_to_speech/s2s_pipeline.py. Port every entry point, in that shape?

> Yes: an axum front door (`app front-door`) takes the server over first

**D2** (blocked s2s/speech-to-speech/demo/): s2s/speech-to-speech/demo/ is blocked: `fastapi` has no Rust equivalent. Rework that part in Rust, or keep the unit outside?

> Research the blocker first; then port it with the piece that uses it

**D3** (blocked s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/): s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/ is blocked: `fastapi` has no Rust equivalent. Rework that part in Rust, or keep the unit outside?

> Research the blocker first; then port it with the piece that uses it

**D4** (dependency fastapi): No crate does what fastapi does (used by 2 units; Web framework: keep the app in Python). Reimplement what the app uses, or drop the feature?

> Reimplement only the part the app uses, proved by its recorded cases

**D5** (dependency starlette): No crate does what starlette does (used by 1 unit; Web framework: keep the app in Python). Reimplement what the app uses, or drop the feature?

> Reimplement only the part the app uses, proved by its recorded cases

**D6** (dependency torch): Which crate replaces torch (used by 11 units)?

> Research it against primary sources into rust/research/torch.md before porting what uses it

**D7** (dependency openai): Which crate replaces openai (used by 10 units)?

> Research it against primary sources into rust/research/openai.md before porting what uses it

**D8** (dependency transformers): Which crate replaces transformers (used by 9 units)?

> Research it against primary sources into rust/research/transformers.md before porting what uses it

**D9** (dependency httpx2): Which crate replaces httpx2 (used by 7 units)?

> Research it against primary sources into rust/research/httpx2.md before porting what uses it

**D10** (dependency huggingface-hub): Which crate replaces huggingface-hub (used by 6 units)?

> Research it against primary sources into rust/research/huggingface-hub.md before porting what uses it

**D11** (dependency scipy): Which crate replaces scipy (used by 6 units)?

> Research it against primary sources into rust/research/scipy.md before porting what uses it

**D12** (dependency soundfile): Which crate replaces soundfile (used by 4 units)?

> Research it against primary sources into rust/research/soundfile.md before porting what uses it

**D13** (dependency websockets): Which crate replaces websockets (used by 4 units)?

> Research it against primary sources into rust/research/websockets.md before porting what uses it

**D14** (dependency browser-harness): Which crate replaces browser-harness (used by 3 units)?

> Research it against primary sources into rust/research/browser-harness.md before porting what uses it

**D15** (dependency librosa): Which crate replaces librosa (used by 3 units)?

> Research it against primary sources into rust/research/librosa.md before porting what uses it

**D16** (dependency mlx): Which crate replaces mlx (used by 3 units)?

> Research it against primary sources into rust/research/mlx.md before porting what uses it

**D17** (dependency faster-qwen3-tts): Which crate replaces faster-qwen3-tts (used by 2 units)?

> Research it against primary sources into rust/research/faster-qwen3-tts.md before porting what uses it

**D18** (dependency kokoro): Which crate replaces kokoro (used by 2 units)?

> Research it against primary sources into rust/research/kokoro.md before porting what uses it

**D19** (dependency mlx-audio): Which crate replaces mlx-audio (used by 2 units)?

> Research it against primary sources into rust/research/mlx-audio.md before porting what uses it

**D20** (dependency nano-parakeet): Which crate replaces nano-parakeet (used by 2 units)?

> Research it against primary sources into rust/research/nano-parakeet.md before porting what uses it

**D21** (dependency nltk): Which crate replaces nltk (used by 2 units)?

> Research it against primary sources into rust/research/nltk.md before porting what uses it

**D22** (dependency riva): Which crate replaces riva (used by 2 units)?

> Research it against primary sources into rust/research/riva.md before porting what uses it

**D23** (dependency soxr): Which crate replaces soxr (used by 2 units)?

> Research it against primary sources into rust/research/soxr.md before porting what uses it

**D24** (dependency aioice): Which crate replaces aioice (used by 1 unit)?

> Research it against primary sources into rust/research/aioice.md before porting what uses it

**D25** (dependency aiortc): Which crate replaces aiortc (used by 1 unit)?

> Research it against primary sources into rust/research/aiortc.md before porting what uses it

**D26** (dependency anyio): Which crate replaces anyio (used by 1 unit)?

> Research it against primary sources into rust/research/anyio.md before porting what uses it

**D27** (dependency auth): Which crate replaces auth (used by 1 unit)?

> Research it against primary sources into rust/research/auth.md before porting what uses it

**D28** (dependency chattts): Which crate replaces chattts (used by 1 unit)?

> Research it against primary sources into rust/research/chattts.md before porting what uses it

**D29** (dependency df): Which crate replaces df (used by 1 unit)?

> Research it against primary sources into rust/research/df.md before porting what uses it

**D30** (dependency examples): Which crate replaces examples (used by 1 unit)?

> Research it against primary sources into rust/research/examples.md before porting what uses it

**D31** (dependency faster-whisper): Which crate replaces faster-whisper (used by 1 unit)?

> Research it against primary sources into rust/research/faster-whisper.md before porting what uses it

**D32** (dependency fireredvad): Which crate replaces fireredvad (used by 1 unit)?

> Research it against primary sources into rust/research/fireredvad.md before porting what uses it

**D33** (dependency funasr): Which crate replaces funasr (used by 1 unit)?

> Research it against primary sources into rust/research/funasr.md before porting what uses it

**D34** (dependency jsonschema): Which crate replaces jsonschema (used by 1 unit)?

> Research it against primary sources into rust/research/jsonschema.md before porting what uses it

**D35** (dependency kittenml): Which crate replaces kittenml (used by 1 unit)?

> Research it against primary sources into rust/research/kittenml.md before porting what uses it

**D36** (dependency lightning-whisper-mlx): Which crate replaces lightning-whisper-mlx (used by 1 unit)?

> Research it against primary sources into rust/research/lightning-whisper-mlx.md before porting what uses it

**D37** (dependency limiter): Which crate replaces limiter (used by 1 unit)?

> Research it against primary sources into rust/research/limiter.md before porting what uses it

**D38** (dependency lingua): Which crate replaces lingua (used by 1 unit)?

> Research it against primary sources into rust/research/lingua.md before porting what uses it

**D39** (dependency melo): Which crate replaces melo (used by 1 unit)?

> Research it against primary sources into rust/research/melo.md before porting what uses it

**D40** (dependency mlx-lm): Which crate replaces mlx-lm (used by 1 unit)?

> Research it against primary sources into rust/research/mlx-lm.md before porting what uses it

**D41** (dependency mlx-vlm): Which crate replaces mlx-vlm (used by 1 unit)?

> Research it against primary sources into rust/research/mlx-vlm.md before porting what uses it

**D42** (dependency moonshine): Which crate replaces moonshine (used by 1 unit)?

> Research it against primary sources into rust/research/moonshine.md before porting what uses it

**D43** (dependency nemo): Which crate replaces nemo (used by 1 unit)?

> Research it against primary sources into rust/research/nemo.md before porting what uses it

**D44** (dependency omegaconf): Which crate replaces omegaconf (used by 1 unit)?

> Research it against primary sources into rust/research/omegaconf.md before porting what uses it

**D45** (dependency omnivoice): Which crate replaces omnivoice (used by 1 unit)?

> Research it against primary sources into rust/research/omnivoice.md before porting what uses it

**D46** (dependency onnxruntime): Which crate replaces onnxruntime (used by 1 unit)?

> Research it against primary sources into rust/research/onnxruntime.md before porting what uses it

**D47** (dependency parler-tts): Which crate replaces parler-tts (used by 1 unit)?

> Research it against primary sources into rust/research/parler-tts.md before porting what uses it

**D48** (dependency pocket-tts): Which crate replaces pocket-tts (used by 1 unit)?

> Research it against primary sources into rust/research/pocket-tts.md before porting what uses it

**D49** (dependency pptx): Which crate replaces pptx (used by 1 unit)?

> Research it against primary sources into rust/research/pptx.md before porting what uses it

**D50** (dependency ptts): Which crate replaces ptts (used by 1 unit)?

> Research it against primary sources into rust/research/ptts.md before porting what uses it

**D51** (dependency pywebrtc-audio): Which crate replaces pywebrtc-audio (used by 1 unit)?

> Research it against primary sources into rust/research/pywebrtc-audio.md before porting what uses it

**D52** (dependency qwen-tts): Which crate replaces qwen-tts (used by 1 unit)?

> Research it against primary sources into rust/research/qwen-tts.md before porting what uses it

**D53** (dependency sounddevice): Which crate replaces sounddevice (used by 1 unit)?

> Research it against primary sources into rust/research/sounddevice.md before porting what uses it

**D54** (dependency spaces): Which crate replaces spaces (used by 1 unit)?

> Research it against primary sources into rust/research/spaces.md before porting what uses it

**D55** (dependency supertonic): Which crate replaces supertonic (used by 1 unit)?

> Research it against primary sources into rust/research/supertonic.md before porting what uses it

**D56** (dependency torch-npu): Which crate replaces torch-npu (used by 1 unit)?

> Research it against primary sources into rust/research/torch-npu.md before porting what uses it

**D57** (dependency torchaudio): Which crate replaces torchaudio (used by 1 unit)?

> Research it against primary sources into rust/research/torchaudio.md before porting what uses it

**D58** (dependency uvicorn): Which crate replaces uvicorn (used by 1 unit)?

> Research it against primary sources into rust/research/uvicorn.md before porting what uses it

**D59** (dependency numpy): numpy maps to ndarray only in part (used by 13 units; Broadcasting and dtype rules differ; check numerics). Use it?

> Use ndarray, and record cases for the behavior it does not cover

**D60** (dependency pydantic): pydantic maps to serde, garde only in part (used by 5 units; Validation errors will differ). Use it?

> Use serde, garde, and record cases for the behavior it does not cover

**D61** (dependency pil): pil maps to image only in part (used by 2 units). Use it?

> Use image, and record cases for the behavior it does not cover

**D62** (dependency av): av maps to ffmpeg-next only in part (used by 1 unit; Binds the C libraries. For pure Rust, remade-ffmpeg covers a subset of codecs (and has an ffmpeg-compatible CLI): check its codec table). Use it?

> Use ffmpeg-next, and record cases for the behavior it does not cover

**D63** (dependency yaml): yaml maps to serde_yaml_ng, saphyr only in part (used by 1 unit; Round-tripping comments is not covered). Use it?

> Use serde_yaml_ng, saphyr, and record cases for the behavior it does not cover

**D64** (tangled units): s2s/speech-to-speech/src/speech_to_speech/, s2s/speech-to-speech/src/speech_to_speech/LLM/, s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/, s2s/speech-to-speech/src/speech_to_speech/STT/, s2s/speech-to-speech/src/speech_to_speech/STV/, s2s/speech-to-speech/src/speech_to_speech/TTS/, s2s/speech-to-speech/src/speech_to_speech/VAD/, s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/, s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/, s2s/speech-to-speech/src/speech_to_speech/arguments_classes/, s2s/speech-to-speech/src/speech_to_speech/diarization/, s2s/speech-to-speech/src/speech_to_speech/pipeline/, s2s/speech-to-speech/src/speech_to_speech/utils/, s2s/speech-to-speech/src/speech_to_speech/zerogpu/ import each other (34161 lines). Port them as one piece?

> Yes: one piece in wave 0, no glue between its parts

