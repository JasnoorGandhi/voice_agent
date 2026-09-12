"""
Voice Customer Support Agent
FastAPI WebSocket server — STT → LLM → TTS pipeline
with real interruption support.
"""

import asyncio
import base64
import logging
import os
import re
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agent import Agent
from stt import STT
from tts import TTS

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global components — initialized once on startup
stt: STT = None
tts: TTS = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global stt, tts
    logger.info("Loading STT and TTS...")
    stt = STT(model_name=os.getenv("WHISPER_MODEL", "base"))
    tts = TTS()
    logger.info("All components ready.")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="Voice Support Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "stt": stt is not None,
        "tts": tts is not None,
    }


# ------------------------------------------------------------------
# WebSocket endpoint — one connection per user session
# ------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected.")

    # Each connection gets its own agent (with conversation memory)
    agent = Agent()
    current_task: asyncio.Task = None

    async def cancel_current():
        """Cancel any running pipeline task cleanly."""
        nonlocal current_task
        if current_task and not current_task.done():
            current_task.cancel()
            try:
                await current_task
            except asyncio.CancelledError:
                pass
            current_task = None

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            # ── Interrupt signal from frontend ──────────────────────
            if msg_type == "interrupt":
                await cancel_current()
                await websocket.send_json({"type": "interrupted"})
                logger.info("Interrupted.")

            # ── Audio input from user ───────────────────────────────
            elif msg_type == "audio":
                # Always cancel previous task before starting new one
                await cancel_current()

                audio_bytes = base64.b64decode(message["data"])
                current_task = asyncio.create_task(
                    run_pipeline(websocket, agent, audio_bytes)
                )

            # ── Clear conversation history ──────────────────────────
            elif msg_type == "clear":
                agent.clear_history()
                await websocket.send_json({"type": "cleared"})

    except WebSocketDisconnect:
        await cancel_current()
        logger.info("Client disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await cancel_current()


_FILLER_WORDS = {
    "mhm", "mm", "hmm", "mmhm", "mmhmm", "uhhuh", "uhuh",
    "okay", "ok", "k", "kay", "yeah", "yea", "yep", "yup",
    "yes", "no", "nope", "nah", "uh", "um", "uhh", "umm",
    "ah", "oh", "huh", "hm", "mmm", "ooh", "ugh", "right",
    "sure", "alright", "allright", "gotcha", "thanks",
    # Whisper hallucinations of filler sounds:
    "bye", "goodbye", "thank you", "thankyou", "please",
    "hi", "hey", "hello", "good", "great", "nice", "cool",
    "wait", "stop", "go", "done", "fine", "wow", "see",
    "you", "i", "the", "a", "and", "or", "but",
}
_FILLER_PHRASES = {
    "got it", "uh huh", "uh-huh", "mm hmm", "mm-hmm", "mm hm",
    "oh okay", "oh ok", "okay okay", "yeah yeah", "i see",
    "all right", "got that",
}


def _is_filler(transcript: str) -> bool:
    cleaned = re.sub(r"[^a-z\s]", " ", transcript.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return True
    if cleaned in _FILLER_PHRASES or cleaned in _FILLER_WORDS:
        return True
    words = cleaned.split()
    # Stricter: under 4 words, all fillers
    if len(words) <= 4 and all(w in _FILLER_WORDS for w in words):
        return True
    # Under 3 words total is almost always a mishear
    if len(words) <= 2:
        return True
    return False


# ------------------------------------------------------------------
# Pipeline — STT → LLM → TTS (fully cancellable)
# ------------------------------------------------------------------

async def run_pipeline(websocket: WebSocket, agent: Agent, audio_bytes: bytes):
    """
    Run the full STT → LLM → TTS pipeline.
    Each await point is a cancellation checkpoint.
    If cancelled, raises CancelledError — nothing more runs or bills.
    """
    try:
        # ── Step 1: STT ─────────────────────────────────────────────
        await websocket.send_json({"type": "status", "text": "transcribing"})
        transcript = await stt.transcribe(audio_bytes)

        # Cancellation checkpoint
        await asyncio.sleep(0)

        if not transcript:
            logger.info("Empty transcript — ignoring.")
            await websocket.send_json({"type": "ignored"})
            return
        if _is_filler(transcript):
            logger.info(f"Ignoring filler: '{transcript}'")
            await websocket.send_json({"type": "ignored"})
            return

        # ── Continue trigger ─────────────────────────────────────────
        CONTINUE_TRIGGERS = {
            "continue", "keep going", "go on", "go ahead",
            "keep talking", "please continue", "carry on"
        }
        if any(t in transcript.lower() for t in CONTINUE_TRIGGERS):
            logger.info(f"Continue trigger: '{transcript}'")
            await websocket.send_json({"type": "ignored"})
            return

        # Only show transcript in chat if it's a real question
        await websocket.send_json({"type": "transcript", "text": transcript})
        


        # ── Step 2: LLM ─────────────────────────────────────────────
        await websocket.send_json({"type": "status", "text": "thinking"})
        response_text = await agent.respond(transcript)

        # Cancellation checkpoint
        await asyncio.sleep(0)

        await websocket.send_json({"type": "response_text", "text": response_text})

        # ── Step 3: TTS ─────────────────────────────────────────────
        await websocket.send_json({"type": "status", "text": "speaking"})
        audio_out = await tts.synthesize(response_text)

        # Cancellation checkpoint — last chance before sending audio
        await asyncio.sleep(0)

        if audio_out:
            audio_b64 = base64.b64encode(audio_out).decode()
            await websocket.send_json({"type": "audio", "data": audio_b64})

        await websocket.send_json({"type": "done"})

    except asyncio.CancelledError:
        # Clean cancellation — log and stop. Nothing more runs.
        logger.info("Pipeline cancelled cleanly.")
        raise  # must re-raise so asyncio knows the task is done


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,         # reload=False for stability during demo
        log_level="info",
    )
