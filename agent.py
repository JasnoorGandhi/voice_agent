"""
LLM Agent using Groq API directly.
No LangChain, no RAG — simple context injection for speed.
"""

import os
import logging
from groq import AsyncGroq

logger = logging.getLogger(__name__)

KNOWLEDGE = open("knowledge.txt").read()

SYSTEM_PROMPT = SYSTEM_PROMPT = f"""You are a helpful voice-based customer support agent for an online store.
You can answer questions AND handle real customer requests through conversation.
Do NOT include reasoning, thinking, or explanation — only the final answer.


KNOWLEDGE BASE:
{KNOWLEDGE}

CAPABILITIES:
You can simulate the following actions by collecting required information conversationally:

1. TRACK AN ORDER
   - Ask for order number
   - Simulate: "Your order #{{order_number}} is currently out for delivery and will arrive by tomorrow."

2. START A RETURN
   - Ask for order number and reason for return
   - Confirm item details
   - Simulate: "I've initiated return #R{{order_number}} for you. A prepaid label will be emailed within 24 hours."

3. CANCEL AN ORDER
   - Ask for order number
   - Confirm cancellation
   - Simulate: "Order #{{order_number}} has been successfully cancelled. Refund will appear in 5-7 business days."

4. BOOK A SUPPORT CALLBACK
   - Ask for name, phone number, and best time to call
   - Simulate: "Done! A support agent will call you at {{phone}} at {{time}}."

5. MODIFY SHIPPING ADDRESS
   - Ask for order number and new address
   - Simulate: "Shipping address for order #{{order_number}} has been updated successfully."

RULES:
- You are a VOICE agent — keep responses short, under 3 sentences.
- Collect one piece of information at a time — don't ask multiple questions at once.
- Always confirm details before simulating an action.
- After completing an action, ask if there's anything else you can help with.
- If unsure, offer to connect with a human agent.
- Never break character — always simulate as if actions are real."""


class Agent:
    def __init__(self):
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.history = []  # conversation memory

    async def respond(self, user_text: str) -> str:
        """Generate a response to user input."""
        self.history.append({"role": "user", "content": user_text})
        recent = self.history[-6:]

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *recent,
                ],
                max_tokens=200,
                temperature=0.5,
            )
            
            message = response.choices[0].message
            
            # Handle reasoning models (qwen, deepseek etc.)
            # that return content separately from reasoning
            answer = ""
            if hasattr(message, 'reasoning') and message.reasoning:
                # reasoning is separate — content is the actual answer
                answer = (message.content or "").strip()
            else:
                answer = (message.content or "").strip()

            # Strip any leftover CONTENT: or REASONING: prefixes
            for prefix in ["CONTENT:", "REASONING:", "Answer:", "Response:"]:
                if answer.startswith(prefix):
                    answer = answer[len(prefix):].strip()

            if not answer:
                answer = "I'm sorry, I couldn't generate a response. Please try again."

            self.history.append({"role": "assistant", "content": answer})
            logger.info(f"Q: {user_text[:60]} | A: {answer[:60]}")
            return answer

        except Exception as e:
            error_str = str(e)
            logger.error(f"Groq error: {e}")
            
            # Extract answer from tool_use_failed errors
            # The model answered correctly but wrapped it in a tool call
            if 'failed_generation' in error_str and 'arguments' in error_str:
                try:
                    import re
                    # Extract text after "arguments":
                    match = re.search(r'"arguments":\s*(.+?)\}\'', error_str)
                    if match:
                        answer = match.group(1).strip().strip('"')
                        if answer:
                            self.history.append({"role": "assistant", "content": answer})
                            logger.info(f"Recovered from tool error: {answer[:60]}")
                            return answer
                except Exception:
                    pass
            
            return "I'm having trouble connecting right now. Please try again or call 1-800-HELP-NOW."

    def clear_history(self):
        self.history = []
