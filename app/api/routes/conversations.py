from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import IncidentAnswerAgent
from app.api.routes.incidents import get_incident_retrieval_service
from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationCreateResponse,
    ConversationRead,
)
from app.services.conversations import ConversationService
from app.services.retrieval import IncidentRetrievalService


router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def get_conversation_service(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings)],
    retrieval_service: Annotated[
        IncidentRetrievalService,
        Depends(get_incident_retrieval_service),
    ],
) -> ConversationService:
    agent = IncidentAnswerAgent(
        settings=settings,
        retrieval_service=retrieval_service,
    )
    return ConversationService(
        settings=settings,
        repository=ConversationRepository(session),
        agent=agent,
    )


@router.post("", response_model=ConversationCreateResponse)
def create_conversation(
    body: ConversationCreateRequest,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationCreateResponse:
    return service.create_conversation(body.project_name)


@router.get("/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: uuid.UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationRead:
    try:
        return service.get_conversation(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="conversation not found") from None
