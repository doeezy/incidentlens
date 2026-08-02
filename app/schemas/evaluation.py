from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvaluationRunCreate(BaseModel):
    run_name: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_limit: int = Field(default=20, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=500)


class EvaluationCandidateRead(BaseModel):
    id: uuid.UUID
    search_type: str
    incident_id: uuid.UUID
    rank: int
    raw_score: float | None
    vector_score: float | None
    bm25_score: float | None
    rrf_score: float | None
    created_at: datetime


class EvaluationResultRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_key: str
    project_name: str
    original_query: str
    rewritten_query: str | None
    predicted_intent: str | None
    expected_incident_id: uuid.UUID | None
    expected_no_result: bool
    expected_rank: int | None
    top1_hit: bool
    top3_hit: bool
    reciprocal_rank: float
    confidence: str | None
    abstained: bool
    no_result_correct: bool | None
    retrieval_latency_ms: float | None
    total_latency_ms: float | None
    error_message: str | None
    created_at: datetime
    candidates: list[EvaluationCandidateRead] = Field(default_factory=list)


class EvaluationRunRead(BaseModel):
    id: uuid.UUID
    run_name: str
    retrieval_version: str
    embedding_model: str
    query_analyzer_version: str
    parameters: dict[str, Any]
    status: str
    total_cases: int
    completed_cases: int
    top1_accuracy: float | None
    top3_accuracy: float | None
    mrr: float | None
    no_result_accuracy: float | None
    mean_latency_ms: float | None
    started_at: datetime
    completed_at: datetime | None


class EvaluationRunDetail(EvaluationRunRead):
    results: list[EvaluationResultRead] = Field(default_factory=list)
