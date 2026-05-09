from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository
from app.repositories.incident_repository import IncidentRepository
from app.repositories.raw_ticket_repository import RawTicketRepository
from app.schemas.raw_ticket import RawTicketCreate, RawTicketIngestResponse
from app.services.embedding import EmbeddingService
from app.services.ticket import (
    LlmTicketEnrichmentService,
    RawTicketService,
    TicketIncidentRuleMatchService,
    TicketParseService,
)


def get_raw_ticket_service(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RawTicketService:
    embedding_repo = IncidentEmbeddingRepository(session)
    return RawTicketService(
        session=session,
        settings=settings,
        parse_service=TicketParseService(),
        llm_ticket_service=LlmTicketEnrichmentService(settings),
        rule_match_service=TicketIncidentRuleMatchService(),
        embedding_service=EmbeddingService(settings, embedding_repo),
        raw_ticket_repo=RawTicketRepository(session),
        incident_repo=IncidentRepository(session),
    )


router = APIRouter(prefix="/raw-tickets", tags=["raw_tickets"])


@router.post("", response_model=RawTicketIngestResponse)
def ingest_raw_ticket(
    body: RawTicketCreate,
    service: Annotated[RawTicketService, Depends(get_raw_ticket_service)],
) -> RawTicketIngestResponse:
    """티켓 수집 → 규칙/LLM 처리 → incident 매칭 → 저장 및 연관 incident 갱신."""
    return service.ingest_raw_ticket(body)
