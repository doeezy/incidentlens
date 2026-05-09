"""공통 LLM(Chat Completions) 호출. 임베딩은 ``app.services.embedding`` 참고."""

from app.llm.chat_client import OpenAiChatClient

__all__ = ["OpenAiChatClient"]
