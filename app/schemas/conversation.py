from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    project_name: str = Field(..., min_length=1)


class ConversationCreateResponse(BaseModel):
    conversation_id: uuid.UUID


class ConversationMessageRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["USER", "ASSISTANT"]
    content: str
    trace_json: dict[str, Any] | None
    created_at: datetime


class ConversationRead(BaseModel):
    id: uuid.UUID
    project_name: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageRead] = Field(default_factory=list)
