from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_conversation(self, project_name: str) -> Conversation:
        conversation = Conversation(project_name=project_name.strip())
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self._session.get(Conversation, conversation_id)

    def list_messages(self, conversation_id: uuid.UUID) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(self._session.scalars(stmt).all())

    def list_recent_messages(
        self,
        *,
        conversation_id: uuid.UUID,
        limit: int,
    ) -> list[Message]:
        if limit <= 0:
            return []
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        messages = list(self._session.scalars(stmt).all())
        return list(reversed(messages))

    def add_message(
        self,
        *,
        conversation: Conversation,
        role: str,
        content: str,
        trace_json: dict | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            trace_json=trace_json,
        )
        conversation.updated_at = datetime.now(timezone.utc)
        self._session.add(message)
        self._session.add(conversation)
        self._session.flush()
        return message

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
