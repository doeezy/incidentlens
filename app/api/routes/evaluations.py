from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import IncidentAnswerAgent
from app.api.routes.incidents import get_incident_retrieval_service
from app.config import Settings, get_settings
from app.deps import db_session_dep
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.evaluation import EvaluationRunCreate, EvaluationRunDetail
from app.services.evaluation import EvaluationService
from app.services.retrieval import IncidentRetrievalService

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def get_evaluation_service(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings)],
    retrieval_service: Annotated[
        IncidentRetrievalService,
        Depends(get_incident_retrieval_service),
    ],
) -> EvaluationService:
    query_agent = IncidentAnswerAgent(
        settings=settings,
        retrieval_service=retrieval_service,
    )
    return EvaluationService(
        settings=settings,
        repository=EvaluationRepository(session),
        query_agent=query_agent,
        retrieval_service=retrieval_service,
    )


@router.post("/runs", response_model=EvaluationRunDetail)
def create_evaluation_run(
    body: EvaluationRunCreate,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationRunDetail:
    return service.run(body)


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail)
def get_evaluation_run(
    run_id: uuid.UUID,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationRunDetail:
    try:
        return service.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="evaluation run not found") from None
