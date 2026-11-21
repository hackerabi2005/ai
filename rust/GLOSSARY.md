# Domain Glossary — Jarvis Rust Migration

| Original Term (Python) | Meaning | Rust Name (Type / Module / Function) | Crate / Location |
| --- | --- | --- | --- |
| `fingerprint` (`jev_ultrafast.browser`) | Canonical sorted-key SHA-256 digest of observed page state (`url`, `text`, `actions`, `scroll`) | `fingerprint` | [rust/jev-ultrafast-rs/src/port.rs](jev-ultrafast-rs/src/port.rs) |
| `validate_choice` (`jev_ultrafast.model`) | TypeSafe Jev probability sum, max-choice, and confidence validator | `validate_choice` | [rust/jev-ultrafast-rs/src/port.rs](jev-ultrafast-rs/src/port.rs) |
| `action_space` (`jev_ultrafast.model`) | Single-pass DOM element & operation target indexer (`CLICK`, `TYPE_TEXT`, `SELECT`, controls) | `action_space` | [rust/jev-ultrafast-rs/src/port.rs](jev-ultrafast-rs/src/port.rs) |
| `field_context` (`jev_ultrafast.model`) | Bounded field context builder for text entry (`page["text"][:6000]`, `history[-6:]`) | `field_context` | [rust/jev-ultrafast-rs/src/port.rs](jev-ultrafast-rs/src/port.rs) |
| `page_summary` (`jarvis-rs/python/jev_bridge.py`) | Bounded visible page context (`url`, `title`, `text[:6000]`, `fingerprint`) | `page_summary` | [rust/python-rs/src/port.rs](python-rs/src/port.rs) |
| `classify_error` (`jarvis-rs/python/jev_bridge.py`) | Error classifier (`missing_key`, `budget_exceeded`, `chrome_not_ready`, `browser_error`) | `classify_error` | [rust/python-rs/src/port.rs](python-rs/src/port.rs) |
| `find_json_tool_call_end` (`speech_to_speech.LLM.tool_call.function_call`) | Quote-aware `<tool_call>...</tool_call>` closing tag scanner returning character offset | `find_json_tool_call_end` | [rust/tool-call-rs/src/port.rs](tool-call-rs/src/port.rs) |
| `build_block_regex` (`speech_to_speech.LLM.tool_call.tool_prompt`) | Regex builder escaping delimiter tags | `build_block_regex` | [rust/tool-call-rs/src/port.rs](tool-call-rs/src/port.rs) |
| `safe_identifier` (`speech_to_speech.utils.request_tracing`) | ASCII request correlation identifier validator (`[A-Za-z0-9_.-]{1,128}`) | `safe_identifier` | [rust/utils-rs/src/port.rs](utils-rs/src/port.rs) |
| `next_power_of_2` / `validate_device` (`speech_to_speech.utils.utils`) | Power-of-two sizing & compute device validator | `next_power_of_2`, `validate_device` | [rust/utils-rs/src/port.rs](utils-rs/src/port.rs) |
| `clean_transcript` / `build_prompt` (`speech_to_speech.STT.nemotron_transcribe`) | Nemotron STT `<ev:*>` / `<sty:*>` / `<spk:*>` tag stripper and transcription prompt builder | `clean_transcript`, `build_prompt` | [rust/stt-rs/src/port.rs](stt-rs/src/port.rs) |
| `remove_markdown` / `remove_unspeechable` (`speech_to_speech.LLM.utils`) | Code-preserving Markdown stripper and per-delta TTS speechable character filter | `remove_markdown`, `remove_unspeechable` | [rust/llm-rs/src/port.rs](llm-rs/src/port.rs) |
| `build_text_system_prompt` / `build_voice_system_prompt` (`speech_to_speech.LLM`) | Text and voice channel system prompt assemblers | `build_text_system_prompt`, `build_voice_system_prompt` | [rust/llm-rs/src/port.rs](llm-rs/src/port.rs) |
| `number_to_words` / `numbers_to_words` / `normalize` (`speech_to_speech.TTS.persian_normalization`) | TTS number-to-words and Unicode NFC text normalizer | `number_to_words`, `numbers_to_words`, `normalize` | [rust/tts-rs/src/port.rs](tts-rs/src/port.rs) |
| `set_log_transcripts` / `transcript_for_log` (`speech_to_speech.pipeline.transcript_logging`) | Atomic privacy gate for logging character count vs. full transcript | `set_log_transcripts`, `transcript_for_log` | [rust/pipeline-rs/src/port.rs](pipeline-rs/src/port.rs) |
| `normalize_language` (`speech_to_speech.speech_languages`) | Language name/code normalizer | `normalize_language` | [rust/speech-languages-rs/src/port.rs](speech-languages-rs/src/port.rs) |
