from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import IncidentAnswerAgent
from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.schemas.incident_search import (
    IncidentAgentRequest,
    IncidentAgentResponse,
    IncidentSearchRequest,
    IncidentSearchResponse,
)
from app.services.retrieval import IncidentRetrievalService


def get_incident_retrieval_service(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IncidentRetrievalService:
    return IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )


router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.post("/search", response_model=IncidentSearchResponse)
def search_incidents(
    body: IncidentSearchRequest,
    service: Annotated[
        IncidentRetrievalService,
        Depends(get_incident_retrieval_service),
    ],
) -> IncidentSearchResponse:
    """장애 사례 vector search와 관련 logs/tickets/PR evidence 조회."""
    return service.search(query=body.query, top_k=body.top_k)


@router.post("/answer", response_model=IncidentAgentResponse)
def answer_incident_question(
    body: IncidentAgentRequest,
    service: Annotated[
        IncidentRetrievalService,
        Depends(get_incident_retrieval_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IncidentAgentResponse:
    """retrieve_incidents -> generate_answer."""
    agent = IncidentAnswerAgent(settings=settings, retrieval_service=service)
    return agent.answer(question=body.question, top_k=body.top_k)
