from __future__ import annotations

import uuid
from typing import Any

from app.agents.incident_agent import ConversationHistoryMessage, IncidentAnswerAgent
from app.config import Settings
from app.models.conversation import Conversation, Message
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import (
    ConversationCreateResponse,
    ConversationMessageRead,
    ConversationRead,
)
from app.schemas.incident_search import IncidentAgentResponse


class ConversationService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: ConversationRepository,
        agent: IncidentAnswerAgent,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._agent = agent

    def create_conversation(self, project_name: str) -> ConversationCreateResponse:
        conversation = self._repository.create_conversation(project_name)
        self._repository.commit()
        return ConversationCreateResponse(conversation_id=conversation.id)

    def get_conversation(self, conversation_id: uuid.UUID) -> ConversationRead:
        conversation = self._get_conversation_or_raise(conversation_id)
        messages = self._repository.list_messages(conversation.id)
        return self._to_read(conversation=conversation, messages=messages)

    def answer(
        self,
        *,
        conversation_id: uuid.UUID,
        question: str,
        top_k: int,
        request_id: str | None = None,
    ) -> IncidentAgentResponse:
        conversation = self._get_conversation_or_raise(conversation_id)
        history_messages = self._repository.list_recent_messages(
            conversation_id=conversation.id,
            limit=self._settings.conversation_history_limit,
        )
        history = [
            ConversationHistoryMessage(role=message.role, content=message.content)
            for message in history_messages
        ]

        try:
            response = self._agent.answer(
                question=question,
                top_k=top_k,
                project_name=conversation.project_name,
                request_id=request_id,
                history_messages=history,
            )
            trace_json: dict[str, Any] | None = None
            if self._agent.last_trace is not None:
                trace_json = self._agent.last_trace.model_dump(mode="json")

            self._repository.add_message(
                conversation=conversation,
                role="USER",
                content=question.strip(),
            )
            self._repository.add_message(
                conversation=conversation,
                role="ASSISTANT",
                content=response.answer,
                trace_json=trace_json,
            )
            self._repository.commit()
            return response
        except Exception:
            self._repository.rollback()
            raise

    def _get_conversation_or_raise(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = self._repository.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(str(conversation_id))
        return conversation

    def _to_read(
        self,
        *,
        conversation: Conversation,
        messages: list[Message],
    ) -> ConversationRead:
        return ConversationRead(
            id=conversation.id,
            project_name=conversation.project_name,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=[
                ConversationMessageRead(
                    id=message.id,
                    conversation_id=message.conversation_id,
                    role=message.role,  # type: ignore[arg-type]
                    content=message.content,
                    trace_json=message.trace_json,
                    created_at=message.created_at,
                )
                for message in messages
            ],
        )
