from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import IncidentAnswerAgent
from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.repositories.incident_repository import IncidentRepository
from app.schemas.incident_search import (
    IncidentBm25SearchRequest,
    IncidentBm25SearchResponse,
    IncidentBm25SearchResult,
    IncidentDirectAnswerRequest,
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


def get_incident_repository(
    session: Annotated[Session, Depends(db_session_dep)],
) -> IncidentRepository:
    return IncidentRepository(session)


@router.post("/search", response_model=IncidentSearchResponse)
def search_incidents(
    body: IncidentSearchRequest,
    service: Annotated[
        IncidentRetrievalService,
        Depends(get_incident_retrieval_service),
    ],
) -> IncidentSearchResponse:
    """장애 사례 vector search와 관련 logs/tickets/PR evidence 조회."""
    return service.search(
        query=body.query,
        top_k=body.top_k,
        project_name=body.project_name,
    )


@router.post("/search/bm25", response_model=IncidentBm25SearchResponse)
def search_incidents_bm25(
    body: IncidentBm25SearchRequest,
    repository: Annotated[IncidentRepository, Depends(get_incident_repository)],
) -> IncidentBm25SearchResponse:
    """장애 사례 pg_search BM25 단독 검색."""
    hits = repository.search_bm25(
        project_name=body.project_name,
        query=body.query,
        limit=body.limit,
    )
    return IncidentBm25SearchResponse(
        project_name=body.project_name.strip(),
        query=body.query.strip(),
        limit=body.limit,
        results=[
            IncidentBm25SearchResult(
                incident_id=hit.incident_id,
                bm25_score=hit.bm25_score,
                rank=hit.rank,
            )
            for hit in hits
        ],
    )


@router.post("/answer", response_model=IncidentAgentResponse)
def answer_incident_question(
    body: IncidentDirectAnswerRequest,
    service: Annotated[
        IncidentRetrievalService,
        Depends(get_incident_retrieval_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IncidentAgentResponse:
    """retrieve_incidents -> generate_answer."""
    agent = IncidentAnswerAgent(settings=settings, retrieval_service=service)
    return agent.answer(
        question=body.question,
        top_k=body.top_k,
        project_name=body.project_name,
    )
