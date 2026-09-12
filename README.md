# 🎙️ Voice Support Agent — With Real Interruption

A voice-based customer support agent you can interrupt mid-sentence.
Speak in your browser, hear it answer, talk over it — it stops immediately.

---

## The Core Feature

Most voice demos only work when you wait politely. This one doesn't.

Start speaking while the agent is talking — it stops instantly, cancels everything
upstream, and responds to what you just said. Nothing keeps running or billing you
for audio nobody will hear.

**Measured interruption latency: 150–250ms** (217ms observed in testing)
Audio stops client-side the moment sustained speech is confirmed. Latency badge
shown in the UI after every interrupt.

---

## Interruption Latency

**Measured: 150–250ms from speech detected to audio stopped.**

### How it is measured

The timestamp is recorded the moment the RMS volume monitor detects
sustained speech above the threshold:

```javascript
if (!bargeInStartedAt) {
  bargeInStartedAt = performance.now();
  interruptTimestamp = performance.now(); // speech detected here
}
```

After `CLICK_IGNORE_MS` (200ms) of sustained volume confirms it is real
speech and not a click, `stopAgentNow()` fires:

```javascript
function stopAgentNow({ hard = false } = {}) {
  const stopTime = performance.now();
  agentAudio.pause();  // audio stops here — instant, no network round trip

  const latency = Math.round(stopTime - interruptTimestamp);
  // shown as green badge: "⚡ 217ms interrupt"
}
```

### Why this number is meaningful

- `audio.pause()` is purely client-side — zero network round trip involved
- The 200–250ms is dominated by `CLICK_IGNORE_MS = 200ms` — the deliberate
  wait to confirm real speech vs a click or filler sound
- Reducing `CLICK_IGNORE_MS` to 100ms would cut latency to ~100ms but
  increases false triggers from clicks and quiet fillers
- The user perceives the stop the moment `audio.pause()` fires — within
  one animation frame (~16ms) of speech being confirmed

### Measured in the UI

Every interruption shows a green badge in the top-right corner:
**⚡ 217ms interrupt**

Resets after 3 seconds and updates on every new interruption.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        BROWSER                          │
│                                                         │
│  Microphone → RMS Volume Monitor (always-on)            │
│       │                                                 │
│       ├─ Agent speaking + RMS > threshold               │
│       │         → interruptTimestamp = now()            │
│       │         → CLICK_IGNORE_MS wait (200ms)          │
│       │         → audio.pause() [instant]               │
│       │         → ws.send({type:"interrupt"})           │
│       │         → startRecording()                      │
│       │                                                 │
│       └─ Mic button pressed                             │
│                 → interruptTimestamp = now()            │
│                 → stopAgentNow()                        │
│                 → startRecording()                      │
│                                                         │
│  MediaRecorder → silence detection → sendAudio()        │
│       │                                                 │
│       └─ WebSocket → base64 audio → server              │
└─────────────────────────────────────────────────────────┘
                          │  WebSocket /ws
                          ▼
┌─────────────────────────────────────────────────────────┐
│                       SERVER                            │
│                                                         │
│  WebSocket handler                                      │
│       │                                                 │
│       ├─ {type:"interrupt"} → asyncio.Task.cancel()     │
│       │         → CancelledError propagates             │
│       │         → nothing more runs or bills            │
│       │                                                 │
│       └─ {type:"audio"} → asyncio.create_task()        │
│                                                         │
│  Pipeline Task (fully cancellable):                     │
│       │                                                 │
│       ├─ Step 1: Whisper STT                            │
│       │       → transcribe audio bytes                  │
│       │       → filler/hallucination filter             │
│       │       → cancellation checkpoint                 │
│       │                                                 │
│       ├─ Step 2: Groq LLM                               │
│       │       → inject knowledge base as context        │
│       │       → generate response (max 150 tokens)      │
│       │       → cancellation checkpoint                 │
│       │                                                 │
│       └─ Step 3: Edge TTS                               │
│               → synthesize speech                       │
│               → cancellation checkpoint                 │
│               → send base64 audio over WebSocket        │
└─────────────────────────────────────────────────────────┘
```

---

## How Interruption Works

### Client side (instant)
```javascript
// RMS volume monitor runs on every animation frame
function tick() {
  const vol = rmsVolume(); // time-domain RMS, 0-100

  if (agentSpeaking && !isRecording && vol > INTERRUPT_RMS_THRESHOLD) {
    if (!bargeInStartedAt) {
      bargeInStartedAt = performance.now();
      interruptTimestamp = performance.now(); // start measuring
    }
    if (performance.now() - bargeInStartedAt >= CLICK_IGNORE_MS) {
      agentAudio.pause();   // stops playback instantly
      agentSpeaking = false;
      stopAgentNow({ hard: false });
      startRecording({ bargeIn: true });
    }
  }
}
```

### Server side (cancellable pipeline)
```python
async def run_pipeline(websocket, agent, audio_bytes):
    try:
        transcript = await stt.transcribe(audio_bytes)
        await asyncio.sleep(0)          # cancellation checkpoint

        response = await agent.respond(transcript)
        await asyncio.sleep(0)          # cancellation checkpoint

        audio = await tts.synthesize(response)
        await asyncio.sleep(0)          # cancellation checkpoint

        await websocket.send_json({"type": "audio", "data": b64})

    except asyncio.CancelledError:
        raise  # clean exit, nothing more runs
```

---

## Filler & Hallucination Detection

Whisper often mishears short sounds as real words ("umm" → "bye", "mhm" → "thank you").
Two layers of protection:

**Layer 1 — RMS threshold (frontend)**
Only sustained speech above `INTERRUPT_RMS_THRESHOLD = 5.5` RMS triggers recording.
Short clicks (~5ms) and quiet fillers never cross this bar.

**Layer 2 — Filler filter (server)**
```python
FILLERS = {"mhm", "hmm", "okay", "yeah", "uh", "um", ...}
MISHEARS = {"bye", "thank you", "hi", "sure", "wait", ...}

if _is_filler(transcript):
    send({"type": "ignored"})  # agent resumes, nothing changes
    return
```

Transcripts under 2 words are also discarded as likely mishears regardless
of content.

---

## RMS vs Volume

The monitor uses **RMS (Root Mean Square)** — not frequency-based volume:

```javascript
// RMS: measures actual waveform deviation from silence
analyser.getByteTimeDomainData(timeData);
let sum = 0;
for (let i = 0; i < timeData.length; i++) {
  const v = (timeData[i] - 128) / 128;  // normalize -1 to +1
  sum += v * v;
}
return Math.sqrt(sum / timeData.length) * 100;
```

RMS is more accurate for perceived loudness and less sensitive to constant
background hum — making it much better for distinguishing real speech from noise.

---

## Silence Detection (Trailing Off)

Handles "I'd like the, um..." vs "...that's all" correctly:

```javascript
const SILENCE_TIMEOUT_MS = 2500;  // wait 2.5s of silence before stopping
const MIN_RECORD_MS = 1200;       // never stop before 1.2s of recording
const SPEECH_RMS_THRESHOLD = 4;   // reset timer when speech detected
```

Every time speech is detected above `SPEECH_RMS_THRESHOLD`, the silence timer
resets. Natural mid-sentence pauses keep the timer alive. Only genuine silence
for 2.5 seconds triggers auto-stop and sends the audio.

---

## What the Agent Can Do

Powered by Groq (`openai/gpt-oss-20b`) with a knowledge base injected as context:

**Answer questions about:**
- Return policy (30-day window, process, non-returnable items)
- Shipping (standard, express, next-day, international)
- Order tracking and modifications
- Payment methods
- Warranty coverage
- Contact and support options

**Simulate actions (multi-turn conversation):**
- Track an order — asks for order number, returns simulated status
- Start a return — collects order number and reason, confirms return
- Cancel an order — confirms cancellation, gives refund timeline
- Book a support callback — collects name, phone, preferred time
- Modify shipping address — asks for order number and new address

---

## Stack

| Component | Technology | Why |
|---|---|---|
| STT | OpenAI Whisper (local, base model) | No API cost, runs offline |
| LLM | Groq `openai/gpt-oss-20b` | Fast inference, free tier |
| TTS | Microsoft Edge TTS | Free, natural neural voices |
| Backend | FastAPI + WebSockets | Async-native, cancellable tasks |
| Frontend | Vanilla JS + Web Audio API | No build step, instant setup |

---

## Project Structure

```
voice_agent/
├── main.py          # FastAPI server, WebSocket handler, pipeline orchestration
├── agent.py         # Groq LLM with knowledge base context injection
├── stt.py           # Whisper STT (Windows-safe temp file handling)
├── tts.py           # Edge TTS synthesis
├── knowledge.txt    # Customer support document set
├── .env             # API keys and config (not committed)
├── .env.example     # Template
├── requirements.txt
└── frontend/
    └── index.html   # Complete UI — RMS monitor, recording, playback, WebSocket
```

---

## Setup

### Prerequisites
- Python 3.11
- FFmpeg on PATH ([download](https://www.gyan.dev/ffmpeg/builds/) → extract → add bin/ to PATH)
- Groq API key ([console.groq.com](https://console.groq.com) — free, no credit card)

### Install

```bash
# 1. Clone
git clone https://github.com/yourusername/voice-agent
cd voice-agent

# 2. Virtual environment (Python 3.11 required)
py -3.11 -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Mac/Linux

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
copy .env.example .env      # Windows
cp .env.example .env        # Mac/Linux
```

Edit `.env`:
```env
GROQ_API_KEY=your-groq-key-here
GROQ_MODEL=openai/gpt-oss-20b
WHISPER_MODEL=base
```

### Run

```bash
python main.py
```

Open **http://localhost:8000** in your browser.

---

## Demo Script

Run these scenarios in order for the demo video:

### 1. Clean exchange
```
Say: "What is your return policy?"
Let it finish completely.
```
Expected: Full answer about 30-day returns, no interruption.

### 2. Hard interruption mid-sentence
```
Say: "Tell me about your shipping options"
Wait for it to start speaking...
Mid-sentence say: "Actually, how do I track my order?"
```
Expected: Stops immediately, green ⚡ badge shows latency (~217ms), answers tracking question.

### 3. Chained interruption
```
Say: "What payment methods do you accept?"
As it answers, say: "Do you accept PayPal specifically?"
```
Expected: Interrupts, answers the specific PayPal question correctly.

### 4. Trailing off
```
Say: "I'd like to know about... actually, what are your shipping costs?"
(pause 1-2 seconds after "about", then continue)
```
Expected: Waits through the pause, processes the full question correctly.

### 5. Action simulation
```
Say: "I want to track my order"
Agent asks for order number → Say: "It's 12345"
```
Expected: Multi-turn conversation, simulates tracking result.

### 6. Filler resilience (bonus)
```
While agent is speaking, say "mhm" or "okay" quietly
```
Expected: Agent does NOT stop — continues speaking.

---

## Tuning

Adjust these constants in `frontend/index.html`:

```javascript
const SILENCE_TIMEOUT_MS = 2500;      // longer = more patient with pauses
const MIN_RECORD_MS = 1200;           // minimum recording before auto-stop
const SPEECH_RMS_THRESHOLD = 4;       // lower = more sensitive to quiet speech
const INTERRUPT_RMS_THRESHOLD = 5.5;  // higher = harder to accidentally interrupt
const CLICK_IGNORE_MS = 200;          // ms of sustained sound before interrupt fires
```

**In a quiet room:** lower `INTERRUPT_RMS_THRESHOLD` to 4.0
**In a noisy room:** raise `INTERRUPT_RMS_THRESHOLD` to 8.0–10.0
**To reduce latency:** lower `CLICK_IGNORE_MS` to 100ms (more false triggers)

---

## Known Limitations

- Whisper runs on CPU — transcription takes 2–4s for short clips
- Filler filter catches common mishears but not all Whisper hallucinations
- Full webrtcvad integration would give better VAD than RMS thresholding
- Edge TTS requires internet connection (Microsoft servers)
- Groq model availability varies by day — update `GROQ_MODEL` in `.env` if
  you hit rate limits or 404 errors

---

## License

MIT
