from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository
from app.repositories.incident_repository import IncidentRepository
from app.repositories.raw_pr_repository import RawPrRepository
from app.repositories.raw_ticket_repository import RawTicketRepository
from app.schemas.raw_pr import RawPrCreate, RawPrIngestResponse
from app.services.embedding import EmbeddingService
from app.services.pr import LlmPrEnrichmentService, RawPrParseService, RawPrService


def get_raw_pr_service(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RawPrService:
    embedding_repo = IncidentEmbeddingRepository(session)
    return RawPrService(
        session=session,
        parse_service=RawPrParseService(),
        llm_enrichment_service=LlmPrEnrichmentService(settings),
        embedding_service=EmbeddingService(settings, embedding_repo),
        raw_pr_repo=RawPrRepository(session),
        raw_ticket_repo=RawTicketRepository(session),
        incident_repo=IncidentRepository(session),
    )


router = APIRouter(prefix="/raw-prs", tags=["raw_prs"])


@router.post("", response_model=RawPrIngestResponse)
def ingest_raw_pr(
    body: RawPrCreate,
    service: Annotated[RawPrService, Depends(get_raw_pr_service)],
) -> RawPrIngestResponse:
    """GitHub PR 수집 → 전처리 → 관련 ticket의 incident 연결 → embedding 갱신."""
    return service.ingest_raw_pr(body)
