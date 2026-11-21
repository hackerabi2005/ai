# Jarvis (`jarvis-rs`)

Session-only hands-free voice browser agent combining:
- `../s2s/speech-to-speech`: Riva streaming gRPC STT + Nemotron-3.5-Lightning (`enable_thinking=false`) + Riva TTS + AEC3 + two-stage barge-in + direct `/v1/say` narration & `/utterance` transcript tap
- `../borwse harness/jev-ultrafast`: Experiential Labs `jev-latest` browser agent + Chrome CDP

## Setup

1. Rotate any exposed keys and fill `.env` (or keep keys in `s2s/speech-to-speech/.env` and `borwse harness/jev-ultrafast/.env`):
   ```bash
   cp .env.example .env
   ```
2. Open Chrome visibly on your desktop and allow remote debugging when prompted.

## Voice flow (active only while `jarvis run` is running)

- **Browser commands** (e.g. *"open YouTube"*, *"search Wikipedia for Alan Turing"*, *"find one-way flights from Zurich to London..."*, *"scroll down"*, *"go back"*, *"read page"*, *"stop"*) route straight to Jev / the broker without waiting on the LLM, and progress is spoken via fixed narrator lines (*"Opening YouTube."*, *"Opened YouTube."*, *"Done."*, *"Stopped."*).
- **Risky clicks/selects** (`pay`, `buy`, `submit`, `send`, `delete`, `confirm`, etc.) pause and ask you to say **"yes"** or **"no"**.
- **Conversation** (e.g. *"explain quantum entanglement"*, *"tell me a joke"*) goes to Nemotron and speaks back via Riva TTS.
- **Quit** with `Ctrl+C` or by saying **"Jarvis, quit"**.

## Commands

```bash
# Check keys, venvs, Chrome connection, and browser bridge
cargo run -- doctor

# Run one browser task through the Rust broker (no voice)
cargo run -- browse --url "https://www.google.com/travel/flights?hl=en" --goal "One-way flights from Zurich to London on December 20, 2026"

# Run the supervised voice + browser session
cargo run -- run
```
