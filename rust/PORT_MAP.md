# Port map: combinned jarvis

9 of 28 units have a Rust port; no original changed since it was recorded.

## Ports

| Unit | Crate | In Rust | Kept in the original | Cases | Last diff | Original |
| --- | --- | --- | --- | ---: | ---: | --- |
| `borwse harness/jev-ultrafast/jev_ultrafast/` | `rust/jev-ultrafast-rs` | `fingerprint`, `validate_choice`, `action_space`, `field_context` | `Agent`, `browser_operation`, `StalePage`, `Browser`, `load_environment`, `response_state`, `close_browser`, `command`, `main`, `Handler`, `post_json`, `choose`, `field_text` | 340 | 340/340 | unchanged |
| `jarvis-rs/python/` | `rust/python-rs` | `page_summary`, `classify_error` | `execute_tool`, `serve_stdio`, `main`, `BridgeSession` | 216 | 216/216 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/LLM/` | `rust/llm-rs` | `build_text_system_prompt`, `remove_markdown`, `remove_unspeechable`, `format_language_instruction`, `language_name_for_prompt`, `resolve_auto_language`, `build_voice_system_prompt` | `AudioInputNotifier`, `TextDelta`, `ReasoningDelta`, `AssistantMessage`, `ToolCall`, `Usage`, `ProviderResponseEnd`, `BaseOpenAICompatibleHandler`, `make_user_message`, `make_user_audio_message`, `make_assistant_message`, `make_system_message`, `add_supported_item`, `build_active_chat`, `ChatItemError`, `CompactionResult`, `ResponsesFunctionCall`, `ResponsesAssistantMessage`, `Chat`, `TransformersToolCallFunction`, `TransformersToolCall`, `TransformersSystemMessage`, `TransformersUserMessage`, `TransformersAssistantMessage`, `TransformersFunctionCallMessage`, `TransformersToolMessage`, `ChatCompletionsApiModelHandler`, `build_compactor`, `StreamContext`, `BaseLanguageModelHandler`, `LanguageModelHandler`, `VisionLanguageModelHandler`, `LMOutputProcessor`, `ResponsesApiModelHandler`, `sent_tokenize_preserving_markdown_code`, `image_url_to_pil`, `ZeroGPULLMHandler` | 559 | 559/559 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/` | `rust/tool-call-rs` | `find_json_tool_call_end`, `build_block_regex` | `parse_json_tool_call_block`, `parse_function_call`, `extract_function_calls_from_text`, `FunctionToolCall`, `FunctionTool`, `signature_from_schema`, `build_tool_system_prompt` | 464 | 464/464 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/STT/` | `rust/stt-rs` | `clean_transcript`, `build_prompt` | `BaseSTTHandler`, `FasterWhisperSTTHandler`, `LightningWhisperSTTHandler`, `MLXAudioWhisperSTTHandler`, `NemoASRSTTHandler`, `NemotronTranscriptionOperation`, `TranscriptionRequestError`, `TranscriptionRequestCancelled`, `HttpTranscriptionResult`, `HttpTranscriptionOperation`, `OpenAICompatibleSTTHandler`, `ParaformerSTTHandler`, `ParakeetTDTSTTHandler`, `language_to_code`, `resolve_torch_dtype`, `Qwen3ASRSTTHandler`, `RivaSTTHandler`, `SenseVoiceSTTHandler`, `demo_smart_progressive`, `PartialTranscription`, `SmartProgressiveStreamingHandler`, `StreamingTranscriptionError`, `StreamingSTTProtocol`, `OpenAIRealtimeProtocol`, `VLLMRealtimeProtocol`, `StatefulStreamingSTTHandler`, `OpenAIRealtimeSTTHandler`, `VLLMRealtimeSTTHandler`, `TranscriptionNotifier`, `WhisperSTTHandler`, `ZeroGPUSTTHandler` | 477 | 477/477 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/TTS/` | `rust/tts-rs` | `number_to_words`, `numbers_to_words`, `normalize` | `BaseTTSHandler`, `ChatTTSHandler`, `Drama3TTSHandler`, `FacebookMMSTTSHandler`, `KittenTTSHandler`, `KokoroTTSHandler`, `MiniMaxSpeechOperation`, `MiniMaxTTSHandler`, `OmniVoiceTTSHandler`, `SpeechRequestCancelled`, `SpeechRequestError`, `HttpSpeechOperation`, `OpenAICompatibleTTSHandler`, `PCMBlockBuffer`, `PhononTTSHandler`, `PersianPhonemizer`, `PocketTTSHandler`, `Qwen3TTSHandler`, `RivaTTSHandler`, `SupertonicTTSHandler`, `ZeroGPUTTSHandler` | 173 | 173/173 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/pipeline/` | `rust/pipeline-rs` | `set_log_transcripts`, `transcript_for_log` | `CancelScope`, `conversation_output`, `model_startup_output`, `is_control_message`, `ControlKind`, `PipelineControlMessage`, `PipelineEvent`, `SpeechStartedEvent`, `SpeechStoppedEvent`, `PartialTranscriptionEvent`, `TranscriptionCompletedEvent`, `TranscriptionFailedEvent`, `AudioInputCompletedEvent`, `AssistantOutputEvent`, `AssistantToolCallReadyEvent`, `TokenUsageEvent`, `AssistantResponseDoneEvent`, `ResponseGenerationDoneEvent`, `ResponseFailedEvent`, `ResponseHistory`, `build_language_detector`, `warm_language_detector`, `detect_language_from_text`, `PipelineLogFilter`, `PipelineMessage`, `VADAudio`, `PartialTranscription`, `Transcription`, `TranscriptionFailure`, `AssistantTextPart`, `AssistantToolCallPart`, `AssistantReasoningPart`, `LLMResponseChunk`, `TokenUsage`, `EndOfResponse`, `TTSInput`, `AudioOutput`, `ResponsePrefetchTransaction`, `GenerateResponseRequest`, `SpeakerInterval`, `SpeakerAttribution`, `SpeakerSession`, `SpeakerAttributionFuture`, `PendingSpeakerAttribution`, `TurnPhase`, `TurnGateAction`, `TurnGate`, `TurnOutputHeld`, `SpeculativeTurnTracker`, `warn_if_log_transcripts_enabled`, `log_exception`, `active_turn_latency_tracker`, `bind_active_turn_latency_tracker`, `record_response_tts_ttfa`, `record_response_e2e`, `MLXLockStat`, `SpeechLatencyAnchor`, `TurnLatencyTracker`, `TurnLatencyStore`, `TTSResponseTimer`, `Viseme` | 21 | 21/21 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/speech_languages.py` | `rust/speech-languages-rs` | `normalize_language` | `backend_language_capabilities`, `SpeechLanguageCapabilities` | 67 | 67/67 | unchanged |
| `s2s/speech-to-speech/src/speech_to_speech/utils/` | `rust/utils-rs` | `safe_identifier`, `next_power_of_2`, `validate_device` | `acquire_mlx_lock`, `release_mlx_lock`, `MLXLockContext`, `log_response_binding`, `HttpRequestContext`, `HttpRequestTrace`, `ThreadManager`, `audio_to_wav_base64`, `response_wants_audio`, `is_out_of_band`, `is_npu_available`, `resolve_device`, `int2float` | 276 | 276/276 | unchanged |

## Not ported yet

In the order `analyze` suggests.

| Unit | Lines | Exports | Readiness |
| --- | ---: | ---: | ---: |
| `borwse harness/jev-ultrafast/scripts/` | 486 | 6 | 59 |
| `presentation/` | 554 | 7 | 76 |
| `s2s/speech-to-speech/src/speech_to_speech/zerogpu/` | 874 | 35 | 7 |
| `s2s/speech-to-speech/src/speech_to_speech/evals/big_bench_audio/` | 1573 | 41 | 0 |
| `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/handlers/` | 2953 | 7 | 0 |
| `s2s/speech-to-speech/archive/arguments_classes/` | 81 | 2 | 100 |
| `s2s/speech-to-speech/src/speech_to_speech/STV/` | 175 | 1 | 63 |
| `s2s/speech-to-speech/archive/STT/` | 52 | 1 | 83 |
| `s2s/speech-to-speech/src/speech_to_speech/diarization/` | 397 | 3 | 51 |
| `s2s/speech-to-speech/demo/livekit/` | 44 | 2 | 92 |
| `s2s/speech-to-speech/archive/` | 0 | 0 | 100 |
| `s2s/speech-to-speech/src/speech_to_speech/api/` | 0 | 0 | 100 |
| `s2s/speech-to-speech/src/speech_to_speech/evals/` | 1 | 0 | 100 |
| `s2s/speech-to-speech/src/speech_to_speech/arguments_classes/` | 1724 | 41 | 57 |
| `s2s/speech-to-speech/archive/TTS/` | 315 | 2 | 43 |
| `s2s/speech-to-speech/src/speech_to_speech/api/openai_realtime/` | 5740 | 0 | 0 |
| `s2s/speech-to-speech/src/speech_to_speech/VAD/` | 1421 | 8 | 0 |
| `s2s/speech-to-speech/scripts/` | 1359 | 24 | 0 |
| `s2s/speech-to-speech/demo/` | 1141 | 0 | 0 |

Regenerate with `rust-anything map --write`. Commit this file: when the original changes upstream, the next map marks every port whose recording it outdated.
