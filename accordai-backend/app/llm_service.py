from groq import Groq
from app.config import get_settings
from app.rag_service import retrieve_context, format_context_for_prompt
from typing import List
import logging
logger = logging.getLogger(__name__)
settings = get_settings()
client = Groq(api_key=settings.GROQ_API_KEY)

async def get_ai_response(
    user_message: str,
    conversation_history: List[dict] = None
) -> str:
    # Retrieve relevant context from knowledge base
    chunks = retrieve_context(user_message)
    context = format_context_for_prompt(chunks)

    # Build system prompt — inject RAG context if available
    if context:
        system_prompt = (
            "You are a helpful customer service assistant. "
            "Keep responses brief and conversational (1-3 sentences). "
            "Be friendly, professional, and helpful.\n\n"
            "Use the following information to answer the user's question accurately. "
            "If the answer isn't in the provided information, use your general knowledge "
            "but stay within your role as a customer service agent.\n\n"
            f"{context}"
        )
        logger.info(f"RAG context injected ({len(chunks)} chunks)")
    else:
        system_prompt = (
            "You are a helpful customer service assistant. "
            "Keep responses brief and conversational (1-3 sentences). "
            "Be friendly, professional, and helpful."
        )
        logger.info("No RAG context found, using base prompt.")

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.7,
        max_tokens=150
    )
    return response.choices[0].message.content