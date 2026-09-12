"""
LLM Agent using Groq API directly.
No LangChain, no RAG — simple context injection for speed.
"""

import os
import logging
from groq import AsyncGroq

logger = logging.getLogger(__name__)

KNOWLEDGE = open("knowledge.txt").read()

SYSTEM_PROMPT = f"""You are a helpful customer support agent for an online store.
Answer customer questions based ONLY on the knowledge base below.
Be concise — your answers will be spoken aloud, so keep them under 3 sentences.
If the answer isn't in the knowledge base, say so and offer to connect them with a human agent.

KNOWLEDGE BASE:
{KNOWLEDGE}"""


class Agent:
    def __init__(self):
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.history = []  # conversation memory

    async def respond(self, user_text: str) -> str:
        """Generate a response to user input."""
        # Add user message to history
        self.history.append({"role": "user", "content": user_text})

        # Keep last 6 turns to avoid context overflow
        recent = self.history[-6:]

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *recent,
                ],
                max_tokens=150,      # short answers for voice
                temperature=0.5,
            )
            answer = response.choices[0].message.content.strip()

            # Add agent response to history
            self.history.append({"role": "assistant", "content": answer})
            logger.info(f"Q: {user_text[:60]} | A: {answer[:60]}")
            return answer

        except Exception as e:
            logger.error(f"Groq error: {e}")
            return "I'm having trouble connecting right now. Please try again or call 18001234"

    def clear_history(self):
        self.history = []
