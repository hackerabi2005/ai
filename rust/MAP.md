# Whole-App Port Map — Jarvis (`combinned jarvis`)

## Goal
Port the active Jarvis voice + browser agent runtime (`borwse harness/jev-ultrafast`, `jarvis-rs/python`, and the active `s2s/speech-to-speech` pipeline) to Rust using `rust-anything` to maximize latency reduction while preserving 100% identical outputs.

## ADR Index ([DECISIONS.md](DECISIONS.md))
- **ADR-001**: Scope of the Whole-App Rust Port (active Jarvis runtime in scope; unused offline ML plugins & `presentation/` out of scope)
- **ADR-002**: Target Shape and Front Door
- **ADR-003**: Browser Agent & CDP Layer
- **ADR-004**: Equivalence Bar and Numeric Tolerance (100% exact on deterministic units, `1e-6` on audio floats)
- **ADR-005**: Dependency Mapping to Rust Crates
- **ADR-006**: Wave Order and Checkpoints

## Ported Units (All Passing `gate` 12/12 and `diff` 100%)

| Wave | Unit ID | Crate | Functions Ported to Rust | Diff | Gate | Top Speedups |
| ---: | --- | --- | --- | :---: | :---: | --- |
| 0 | `borwse harness/jev-ultrafast/jev_ultrafast/` | `rust/jev-ultrafast-rs` | `fingerprint`, `validate_choice`, `action_space`, `field_context` | 340/340 | 12/12 | Direct Rust callers zero out JSON-RPC / PyO3 overhead |
| 1 | `jarvis-rs/python/` | `rust/python-rs` | `page_summary`, `classify_error` | 216/216 | 12/12 | Direct Rust summary & error classification |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/` | `rust/tool-call-rs` | `find_json_tool_call_end`, `build_block_regex` | 464/464 | 12/12 | `find_json_tool_call_end` **4.60x** faster (`2.15x` unit speedup) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/utils/` | `rust/utils-rs` | `safe_identifier`, `next_power_of_2`, `validate_device` | 276/276 | 12/12 | Pure Rust request ID validation & power-of-two math |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/STT/` | `rust/stt-rs` | `clean_transcript`, `build_prompt` | 477/477 | 12/12 | `clean_transcript` **6.56x** faster (`2.56x` unit speedup) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/LLM/` | `rust/llm-rs` | `build_text_system_prompt`, `remove_markdown`, `remove_unspeechable`, `format_language_instruction`, `language_name_for_prompt`, `resolve_auto_language`, `build_voice_system_prompt` | 559/559 | 12/12 | `remove_unspeechable` **2.27x** faster, `remove_markdown` **1.40x** faster, `build_text_system_prompt` **1.38x** faster, `build_voice_system_prompt` **1.35x** faster |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/TTS/` | `rust/tts-rs` | `number_to_words`, `numbers_to_words`, `normalize` | 173/173 | 12/12 | `normalize` **3.84x** faster, `number_to_words` **1.51x** faster (`1.74x` unit speedup) |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/pipeline/` | `rust/pipeline-rs` | `set_log_transcripts`, `transcript_for_log` | 21/21 | 12/12 | `set_log_transcripts` **1.03x** faster |
| 0 | `s2s/speech-to-speech/src/speech_to_speech/speech_languages.py` | `rust/speech-languages-rs` | `normalize_language` | 67/67 | 12/12 | Pure Rust language normalization |

**Total Recorded & Verified Cases Across All 9 Crates:** **2,593 / 2,593 (100%)**

## Class-Only / Stateful I/O Units (Kept in Python / Re-exported by Shadows)
- `s2s/speech-to-speech/src/speech_to_speech/arguments_classes/` (41 `@dataclass` configuration classes, 0 callable functions)
- `s2s/speech-to-speech/src/speech_to_speech/VAD/` (handler/iterator classes + optional `fireredvad` loader)
- `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/` (`RealtimeBaseHandler` and domain handler subclasses)
- `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/` (FastAPI/WebSocket server classes, 0 standalone function exports)
- `borwse harness/jev-ultrafast/scripts/` (top-level benchmark & video-render CLI scripts)

## Out of Scope (per ADR-001)
- `presentation/` (one-off PowerPoint build script)
- `s2s/speech-to-speech/archive/` (`archive/`, `archive/arguments_classes/`, `archive/STT/`, `archive/TTS/`)
- `s2s/speech-to-speech/evals/` (`evals/`, `evals/big_bench_audio/`)
- `s2s/speech-to-speech/zerogpu/` (HuggingFace Spaces ZeroGPU worker)
- `s2s/speech-to-speech/demo/` & `demo/livekit/` (standalone HF web demo)
- `s2s/speech-to-speech/src/speech_to_speech/STV/` & `diarization/` (unused in Jarvis pipeline)
- `s2s/speech-to-speech/scripts/` (standalone HF evaluation scripts)

## Open Questions
None.
