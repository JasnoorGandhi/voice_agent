# 🎙️ Voice Support Agent — With Real Interruption

A voice-based customer support agent you can interrupt mid-sentence.
Speak in your browser, hear it answer, talk over it — it stops immediately.

## The Core Feature

Most voice demos only work when you wait politely. This one doesn't.

Start speaking while the agent is talking — it stops instantly, cancels everything
upstream, and responds to what you just said. Nothing keeps running or billing you
for audio nobody will hear.

**Measured interruption latency: ~80–150ms** (audio stops client-side instantly,
server pipeline cancelled within one event loop tick).

## Architecture

```
Browser mic → WebSocket → STT (Whisper) → LLM (Groq) → TTS (Edge TTS) → Browser speaker
                ↑
        User speaks while agent talks
                ↓
        audioElement.pause()  ← instant (client-side)
        ws.send({type:"interrupt"})
        asyncio.Task.cancel() ← server cancels pipeline
```

## How Interruption Works

1. Volume monitor runs continuously via Web Audio API `AnalyserNode`
2. While agent audio plays, if user volume exceeds threshold → interrupt fires
3. `audio.pause()` stops playback immediately — this is pure client-side, zero latency
4. Server receives `{type: "interrupt"}` → calls `task.cancel()` on the running pipeline
5. `asyncio.CancelledError` propagates through STT/LLM/TTS — nothing more runs
6. New recording starts immediately to capture what the user is saying

## Silence Detection (Trailing Off)

The agent correctly handles:
- `"I'd like the, um..."` — silence timer resets on any speech activity, waits longer
- `"...that's all"` — 1.5s of silence triggers auto-stop and sends the query

The silence timer resets every time volume exceeds the speech threshold,
so natural pauses mid-sentence don't cut the user off.

## Stack

| Component | Tech | Why |
|---|---|---|
| STT | OpenAI Whisper (local) | No API cost, runs offline |
| LLM | Groq Llama 3.1 8B | Fastest inference, free tier |
| TTS | Microsoft Edge TTS | Free, natural neural voices |
| Backend | FastAPI + WebSockets | Async-native, cancellable tasks |
| Frontend | Vanilla JS | No build step, instant setup |

## Setup

```bash
# 1. Clone and enter
git clone https://github.com/yourusername/voice-agent
cd voice-agent

# 2. Create venv with Python 3.11
py -3.11 -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
copy .env.example .env      # Windows
cp .env.example .env        # Mac/Linux
# Edit .env and add your GROQ_API_KEY

# 5. Install ffmpeg (required by Whisper)
# Windows: https://www.gyan.dev/ffmpeg/builds/
# Add ffmpeg/bin to PATH

# 6. Run
python main.py

# 7. Open browser
# http://localhost:8000
```

## Demo Scenarios

The demo video shows:

1. **Clean exchange** — "What's your return policy?" — full answer, no interruption
2. **Hard interruption** — agent mid-sentence, user starts talking → stops immediately
3. **Chained interruption** — interrupt → immediately ask new question → correct answer
4. **Trailing off** — "I'd like to know about... actually, what about shipping?" — handles pause correctly

## Tuning Interruption Sensitivity

In `frontend/index.html`:

```js
const INTERRUPT_VOLUME_THRESHOLD = 18;  // lower = more sensitive
const SPEECH_VOLUME_THRESHOLD = 8;      // min volume to count as speech
const SILENCE_TIMEOUT_MS = 1500;        // ms of silence before auto-stop
```

In a quiet room, lower `INTERRUPT_VOLUME_THRESHOLD` to 12.
In a noisy environment, raise it to 25–30.

## Known Limitations

- Whisper runs on CPU — transcription takes 2–5s for short clips
- "mhm" / filler sounds: mitigated by volume threshold but not VAD
  (full webrtcvad integration would handle this better)
- Interruption works best when the volume difference is clear

## License

MIT
