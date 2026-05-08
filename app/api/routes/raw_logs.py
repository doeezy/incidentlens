from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository
from app.repositories.incident_repository import IncidentRepository
from app.repositories.raw_log_repository import RawLogRepository
from app.schemas.raw_log import RawLogCreate, RawLogIngestResponse
from app.services.embedding_service import EmbeddingService
from app.services.incident_match_service import IncidentMatchService
from app.services.incident_service import IncidentService
from app.services.llm_log_enrichment_service import LlmLogEnrichmentService
from app.services.log_parse_service import LogParseService


def get_incident_service(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IncidentService:
    embedding_repo = IncidentEmbeddingRepository(session)
    return IncidentService(
        session=session,
        settings=settings,
        parse_service=LogParseService(),
        llm_enrichment_service=LlmLogEnrichmentService(settings),
        match_service=IncidentMatchService(settings),
        embedding_service=EmbeddingService(settings, embedding_repo),
        raw_log_repo=RawLogRepository(session),
        incident_repo=IncidentRepository(session),
    )


router = APIRouter(prefix="/raw-logs", tags=["raw_logs"])


@router.post("", response_model=RawLogIngestResponse)
def ingest_raw_log(
    body: RawLogCreate,
    service: Annotated[IncidentService, Depends(get_incident_service)],
) -> RawLogIngestResponse:
    """raw 로그 수집 → 파싱 저장 → incident 연결/생성 → embedding 갱신."""
    return service.ingest_raw_log(body)
