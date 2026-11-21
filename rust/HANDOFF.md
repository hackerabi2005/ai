# Handoff — Jarvis Whole-App Rust Migration

- **Skill to load**: [SKILL.md](C:/Users/Abish/.gemini/config/skills/rust-anything/SKILL.md) and [whole-app.md](C:/Users/Abish/.gemini/config/skills/rust-anything/whole-app.md)
- **Plan & Measured Port Map**: [MAP.md](MAP.md) and [PORT_MAP.md](PORT_MAP.md)
- **Decisions & Glossary**: [DECISIONS.md](DECISIONS.md) (ADR-001 through ADR-006) and [GLOSSARY.md](GLOSSARY.md)
- **Where the port stands**:
  - **All 9 active callable units ported and passing `gate` 12/12 (2,593 / 2,593 recorded cases match)**:
    1. [rust/jev-ultrafast-rs](jev-ultrafast-rs/src/port.rs) (`340/340` cases, shadow: [jev_ultrafast_shadow.py](jev-ultrafast-rs/shadow/jev_ultrafast_shadow.py))
    2. [rust/python-rs](python-rs/src/port.rs) (`216/216` cases, shadow: [python_shadow.py](python-rs/shadow/python_shadow.py))
    3. [rust/tool-call-rs](tool-call-rs/src/port.rs) (`464/464` cases, **4.60x** speedup on `find_json_tool_call_end`, shadow: [tool_call_shadow.py](tool-call-rs/shadow/tool_call_shadow.py))
    4. [rust/utils-rs](utils-rs/src/port.rs) (`276/276` cases, shadow: [utils_shadow.py](utils-rs/shadow/utils_shadow.py))
    5. [rust/stt-rs](stt-rs/src/port.rs) (`477/477` cases, **6.56x** speedup on `clean_transcript`, shadow: [stt_shadow.py](stt-rs/shadow/stt_shadow.py))
    6. [rust/llm-rs](llm-rs/src/port.rs) (`559/559` cases, **2.27x** speedup on `remove_unspeechable`, **1.40x** on `remove_markdown`, shadow: [llm_shadow.py](llm-rs/shadow/llm_shadow.py))
    7. [rust/tts-rs](tts-rs/src/port.rs) (`173/173` cases, **3.84x** speedup on `normalize`, shadow: [tts_shadow.py](tts-rs/shadow/tts_shadow.py))
    8. [rust/pipeline-rs](pipeline-rs/src/port.rs) (`21/21` cases, shadow: [pipeline_shadow.py](pipeline-rs/shadow/pipeline_shadow.py))
    9. [rust/speech-languages-rs](speech-languages-rs/src/port.rs) (`67/67` cases, shadow: [speech_languages_shadow.py](speech-languages-rs/shadow/speech_languages_shadow.py))
  - **In progress / broken**: None.
