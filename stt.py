"""
Speech-to-Text using OpenAI Whisper (local).
Windows-safe: uses delete=False temp file.
"""

import os
import logging
import tempfile
import asyncio
import whisper

logger = logging.getLogger(__name__)


class STT:
    def __init__(self, model_name: str = "base"):
        logger.info(f"Loading Whisper model '{model_name}'...")
        self.model = whisper.load_model(model_name)
        logger.info("Whisper ready.")

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes to text. Runs in thread pool to avoid blocking."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_bytes)

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        """Synchronous transcription — called in thread pool."""
        # Windows fix: close file before whisper reads it
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.close()
            result = self.model.transcribe(tmp.name, fp16=False, language="en")
            transcript = result.get("text", "").strip()
            logger.info(f"Transcript: '{transcript}'")
            return transcript
        except Exception as e:
            logger.error(f"Whisper error: {e}")
            return ""
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
