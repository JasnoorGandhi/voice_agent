"""
Text-to-Speech using Microsoft Edge TTS (free, no API key).
"""

import logging
import edge_tts

logger = logging.getLogger(__name__)

VOICE = "en-US-AriaNeural"


class TTS:
    async def synthesize(self, text: str) -> bytes:
        """Convert text to MP3 audio bytes."""
        if not text.strip():
            return b""
        try:
            communicate = edge_tts.Communicate(text, VOICE)
            audio = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
            logger.info(f"TTS synthesized {len(audio)} bytes.")
            return audio
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return b""
