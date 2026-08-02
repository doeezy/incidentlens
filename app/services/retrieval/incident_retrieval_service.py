from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm import OpenAiChatClient
from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository
from app.repositories.incident_repository import IncidentBm25SearchHit, IncidentRepository
from app.schemas.incident_search import (
    EvidenceLog,
    EvidencePr,
    EvidenceTicket,
    IncidentSearchResponse,
    IncidentSearchResult,
)
from app.services.embedding import EmbeddingService
from app.tracing import (
    AgentTraceConfidence,
    AgentTraceConfidenceEvaluation,
    AgentTraceRetrieval,
    AgentTraceRetrievalCandidate,
)
from app.utils.json_text import extract_first_json_object
from app.utils.text_preview import preview_truncated

logger = logging.getLogger(__name__)

_HIGH_CONFIDENCE_SCORE = 0.65
_MIN_SCORE = 0.45
_MIN_LLM_CONFIDENCE_SCORE = 0.5
_VECTOR_ONLY_PRE_REJECT_SCORE = 0.05
_RRF_K = 60
_MAX_ERROR_KEYWORDS = 5
_MAX_DOMAIN_TAGS = 5
_MAX_PRIMARY_ERROR_SUMMARY_CHARS = 300
_MAX_SUSPECTED_CAUSE_CHARS = 200
_MAX_ROOT_CAUSE_SUMMARY_CHARS = 200
_MAX_RESOLUTION_SUMMARY_CHARS = 250


class _ConfidenceEval(BaseModel):
    confidence: Literal["high", "medium", "low"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reason: str


class _BatchConfidenceEvaluation(BaseModel):
    incident_id: uuid.UUID
    confidence: Literal["high", "medium", "low"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    should_include: bool
    reason: str


class _BatchConfidenceEval(BaseModel):
    evaluations: list[_BatchConfidenceEvaluation]
    ranking: list[uuid.UUID]
    no_relevant_candidate: bool


@dataclass(frozen=True)
class _VectorSearchHit:
    incident_id: uuid.UUID
    distance: float
    vector_score: float
    rank: int


@dataclass(frozen=True)
class _RrfSearchHit:
    incident_id: uuid.UUID
    rrf_rank: int
    vector_rank: int | None
    keyword_rank: int | None
    vector_score: float | None
    bm25_score: float | None
    distance: float | None
    rrf_score: float


@dataclass(frozen=True)
class _HybridConfidenceInput:
    query: str
    incident: Incident
    vector_rank: int | None
    vector_score: float | None
    bm25_rank: int | None
    bm25_score: float | None
    rrf_rank: int
    rrf_score: float
    query_intent: str | None = None

    @property
    def in_vector(self) -> bool:
        return self.vector_rank is not None

    @property
    def in_bm25(self) -> bool:
        return self.bm25_rank is not None

    @property
    def in_both(self) -> bool:
        return self.in_vector and self.in_bm25


@dataclass
class ConfidenceTelemetry:
    evaluated_candidates: int = 0
    llm_calls: int = 0
    batch_llm_calls: int = 0
    individual_llm_calls: int = 0
    llm_failures: int = 0
    fallback_executions: int = 0
    llm_low_confidence_rejections: int = 0
    pre_llm_rejections: int = 0
    passed_candidates: int = 0
    prompt_input_tokens: int = 0
    output_tokens: int = 0
    token_observations: int = 0
    rejected_by: dict[str, int] | None = None

    def record_rejection(self, reason: str) -> None:
        if self.rejected_by is None:
            self.rejected_by = {}
        self.rejected_by[reason] = self.rejected_by.get(reason, 0) + 1


@dataclass(frozen=True)
class RetrievalStageCandidate:
    search_type: Literal["VECTOR", "BM25", "RRF"]
    incident_id: uuid.UUID
    rank: int
    raw_score: float | None
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None


@dataclass(frozen=True)
class RetrievalEvaluationTrace:
    search_response: IncidentSearchResponse
    vector_candidates: list[RetrievalStageCandidate]
    bm25_candidates: list[RetrievalStageCandidate]
    rrf_candidates: list[RetrievalStageCandidate]
    confidence_telemetry: ConfidenceTelemetry


class IncidentRetrievalService:
    """Vector retrieval for incidents and their connected evidence.

    This service is intentionally independent from FastAPI routers so it can be
    reused by a LangGraph agent.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings,
        embedding_service: EmbeddingService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._embedding_service = embedding_service
        self._llm = OpenAiChatClient(settings)
        self._confidence_telemetry = ConfidenceTelemetry()
        self._last_trace_retrieval = AgentTraceRetrieval()
        self._last_trace_confidence = AgentTraceConfidence()
        self._last_retrieval_ms: float | None = None
        self._last_confidence_ms: float | None = None
        self._last_batch_confidence_input_ids: list[uuid.UUID] = []
        self._last_batch_confidence_eval: _BatchConfidenceEval | None = None

    @classmethod
    def from_session(
        cls,
        *,
        session: Session,
        settings: Settings,
    ) -> "IncidentRetrievalService":
        embedding_repo = IncidentEmbeddingRepository(session)
        return cls(
            session=session,
            settings=settings,
            embedding_service=EmbeddingService(settings, embedding_repo),
        )

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        project_name: str | None = None,
        query_intent: str | None = None,
    ) -> IncidentSearchResponse:
        clean_query = query.strip()
        clean_project_name = project_name.strip() if project_name else None
        retrieval_start = perf_counter()
        vector_hits, bm25_hits, rrf_hits = self._search_hybrid_candidates(
            query=clean_query,
            top_k=top_k,
            candidate_limit=self._candidate_limit(top_k),
            rrf_k=_RRF_K,
            project_name=clean_project_name,
        )
        self._last_retrieval_ms = self._elapsed_ms(retrieval_start)
        self._last_trace_retrieval = self._build_retrieval_trace(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            rrf_hits=rrf_hits,
        )
        return self._build_search_response(
            query=clean_query,
            top_k=top_k,
            project_name=clean_project_name,
            hits=rrf_hits,
            query_intent=query_intent,
        )

    @property
    def last_trace_retrieval(self) -> AgentTraceRetrieval:
        return self._last_trace_retrieval

    @property
    def last_trace_confidence(self) -> AgentTraceConfidence:
        return self._last_trace_confidence

    @property
    def last_retrieval_ms(self) -> float | None:
        return self._last_retrieval_ms

    @property
    def last_confidence_ms(self) -> float | None:
        return self._last_confidence_ms

    def search_for_evaluation(
        self,
        *,
        query: str,
        top_k: int,
        candidate_limit: int,
        rrf_k: int,
        project_name: str,
        query_intent: str | None = None,
    ) -> RetrievalEvaluationTrace:
        clean_query = query.strip()
        clean_project_name = project_name.strip()
        vector_hits, bm25_hits, rrf_hits = self._search_hybrid_candidates(
            query=clean_query,
            top_k=max(top_k, candidate_limit),
            candidate_limit=candidate_limit,
            rrf_k=rrf_k,
            project_name=clean_project_name,
        )
        search_response = self._build_search_response(
            query=clean_query,
            top_k=top_k,
            project_name=clean_project_name,
            hits=rrf_hits[:top_k],
            query_intent=query_intent,
        )
        return RetrievalEvaluationTrace(
            search_response=search_response,
            vector_candidates=[
                RetrievalStageCandidate(
                    search_type="VECTOR",
                    incident_id=hit.incident_id,
                    rank=hit.rank,
                    raw_score=hit.vector_score,
                    vector_score=hit.vector_score,
                )
                for hit in vector_hits
            ],
            bm25_candidates=[
                RetrievalStageCandidate(
                    search_type="BM25",
                    incident_id=hit.incident_id,
                    rank=hit.rank,
                    raw_score=hit.bm25_score,
                    bm25_score=hit.bm25_score,
                )
                for hit in bm25_hits
            ],
            rrf_candidates=[
                RetrievalStageCandidate(
                    search_type="RRF",
                    incident_id=hit.incident_id,
                    rank=rank,
                    raw_score=hit.rrf_score,
                    vector_score=hit.vector_score,
                    bm25_score=hit.bm25_score,
                    rrf_score=hit.rrf_score,
                )
                for rank, hit in enumerate(rrf_hits, start=1)
            ],
            confidence_telemetry=self._confidence_telemetry,
        )

    def _search_hybrid_candidates(
        self,
        *,
        query: str,
        top_k: int,
        candidate_limit: int,
        rrf_k: int,
        project_name: str | None,
    ) -> tuple[list[_VectorSearchHit], list[IncidentBm25SearchHit], list[_RrfSearchHit]]:
        logging.info("========== search query, top_k: %s, %s", query, top_k)
        query_vector = self._embedding_service.embed_text(query)
        vector_hits = self._search_embeddings(
            query_vector=query_vector,
            limit=candidate_limit,
            project_name=project_name,
        )
        logging.info("========== search_embeddings hits: %s", vector_hits)

        bm25_hits: list[IncidentBm25SearchHit] = []
        if project_name is not None:
            bm25_hits = IncidentRepository(self._session).search_bm25(
                project_name=project_name,
                query=query,
                limit=candidate_limit,
            )
        logging.info("========== search_bm25 hits: %s", bm25_hits)

        rrf_hits = self._merge_with_rrf(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            top_k=top_k,
            rrf_k=rrf_k,
        )
        return vector_hits, bm25_hits, rrf_hits

    def _build_retrieval_trace(
        self,
        *,
        vector_hits: list[_VectorSearchHit],
        bm25_hits: list[IncidentBm25SearchHit],
        rrf_hits: list[_RrfSearchHit],
    ) -> AgentTraceRetrieval:
        return AgentTraceRetrieval(
            vector_candidate_count=len(vector_hits),
            bm25_candidate_count=len(bm25_hits),
            rrf_candidate_count=len(rrf_hits),
            vector_candidates=[
                AgentTraceRetrievalCandidate(
                    search_type="VECTOR",
                    incident_id=hit.incident_id,
                    rank=hit.rank,
                    raw_score=hit.vector_score,
                    vector_score=hit.vector_score,
                    distance=hit.distance,
                )
                for hit in vector_hits
            ],
            bm25_candidates=[
                AgentTraceRetrievalCandidate(
                    search_type="BM25",
                    incident_id=hit.incident_id,
                    rank=hit.rank,
                    raw_score=hit.bm25_score,
                    bm25_score=hit.bm25_score,
                )
                for hit in bm25_hits
            ],
            rrf_candidates=[
                AgentTraceRetrievalCandidate(
                    search_type="RRF",
                    incident_id=hit.incident_id,
                    rank=hit.rrf_rank,
                    raw_score=hit.rrf_score,
                    vector_score=hit.vector_score,
                    bm25_score=hit.bm25_score,
                    rrf_score=hit.rrf_score,
                    distance=hit.distance,
                    vector_rank=hit.vector_rank,
                    bm25_rank=hit.keyword_rank,
                )
                for hit in rrf_hits
            ],
        )

    def _build_confidence_trace(
        self,
        *,
        confidence_inputs: list[_HybridConfidenceInput],
        confidence_results: list[tuple[_HybridConfidenceInput, _ConfidenceEval]],
    ) -> AgentTraceConfidence:
        batch_eval = self._last_batch_confidence_eval
        selected_incident_ids = [
            confidence_input.incident.id for confidence_input, _ in confidence_results
        ]
        return AgentTraceConfidence(
            batch_input_candidate_ids=[
                confidence_input.incident.id for confidence_input in confidence_inputs
            ],
            llm_evaluations=[
                AgentTraceConfidenceEvaluation(
                    incident_id=evaluation.incident_id,
                    confidence=evaluation.confidence,
                    confidence_score=evaluation.confidence_score,
                    should_include=evaluation.should_include,
                    reason=evaluation.reason,
                )
                for evaluation in (batch_eval.evaluations if batch_eval else [])
            ],
            ranking=list(batch_eval.ranking) if batch_eval else [],
            selected_incident_id=selected_incident_ids[0]
            if selected_incident_ids
            else None,
            selected_incident_ids=selected_incident_ids,
        )

    def _build_search_response(
        self,
        *,
        query: str,
        top_k: int,
        project_name: str | None,
        hits: list[_RrfSearchHit],
        query_intent: str | None = None,
    ) -> IncidentSearchResponse:
        self._confidence_telemetry = ConfidenceTelemetry()
        incident_ids = [hit.incident_id for hit in hits]
        # incident_id 목록으로 incidents 조회
        incidents = self._load_incidents(incident_ids)
        # incident_id 목록으로 logs 조회
        evidence_logs = self._load_logs(incident_ids)
        # incident_id 목록으로 tickets 조회
        evidence_tickets = self._load_tickets(incident_ids)
        # incident_id 목록으로 prs 조회
        evidence_prs = self._load_prs(incident_ids)

        confidence_inputs: list[_HybridConfidenceInput] = []
        hits_by_incident_id: dict[uuid.UUID, _RrfSearchHit] = {}
        for hit in hits[: min(top_k, 3)]:
            incident = incidents.get(hit.incident_id)
            if incident is None:
                continue
            hits_by_incident_id[hit.incident_id] = hit
            confidence_inputs.append(
                _HybridConfidenceInput(
                    query=query,
                    incident=incident,
                    vector_rank=hit.vector_rank,
                    vector_score=hit.vector_score,
                    bm25_rank=hit.keyword_rank,
                    bm25_score=hit.bm25_score,
                    rrf_rank=hit.rrf_rank,
                    rrf_score=hit.rrf_score,
                    query_intent=query_intent,
                ),
            )

        results: list[IncidentSearchResult] = []
        confidence_start = perf_counter()
        confidence_results = self._evaluate_batch_confidence(
            confidence_inputs=confidence_inputs,
        )
        self._last_confidence_ms = self._elapsed_ms(confidence_start)
        for confidence_input, confidence_eval in confidence_results[:top_k]:
            hit = hits_by_incident_id[confidence_input.incident.id]
            results.append(
                self._build_result(
                    incident=confidence_input.incident,
                    hit=hit,
                    confidence_eval=confidence_eval,
                    evidence_logs=evidence_logs,
                    evidence_tickets=evidence_tickets,
                    evidence_prs=evidence_prs,
                ),
            )
        self._last_trace_confidence = self._build_confidence_trace(
            confidence_inputs=confidence_inputs,
            confidence_results=confidence_results[:top_k],
        )

        return IncidentSearchResponse(
            query=query,
            top_k=top_k,
            project_name=project_name,
            results=results,
        )

    def _build_result(
        self,
        *,
        incident: Incident,
        hit: _RrfSearchHit,
        confidence_eval: _ConfidenceEval,
        evidence_logs: dict[uuid.UUID, list[EvidenceLog]],
        evidence_tickets: dict[uuid.UUID, list[EvidenceTicket]],
        evidence_prs: dict[uuid.UUID, list[EvidencePr]],
    ) -> IncidentSearchResult:
        return IncidentSearchResult(
            incident_id=incident.id,
            score=hit.rrf_score,
            distance=hit.distance,
            vector_rank=hit.vector_rank,
            keyword_rank=hit.keyword_rank,
            rrf_rank=hit.rrf_rank,
            vector_score=hit.vector_score,
            bm25_score=hit.bm25_score,
            rrf_score=hit.rrf_score,
            confidence=confidence_eval.confidence,
            confidence_score=confidence_eval.confidence_score,
            confidence_reason=confidence_eval.reason,
            project_name=incident.project_name,
            status=incident.status,
            first_detected_at=incident.first_detected_at,
            last_seen_at=incident.last_seen_at,
            resolved_at=incident.resolved_at,
            summary=incident.primary_error_summary,
            error_type=incident.primary_error_type,
            error_message=incident.primary_error_message,
            root_cause=incident.root_cause_summary,
            suspected_cause=incident.suspected_cause,
            resolution=incident.resolution_summary,
            keywords=list(incident.error_keywords or []),
            domain_tags=list(incident.domain_tags or []),
            evidence_logs=evidence_logs.get(incident.id, []),
            evidence_tickets=evidence_tickets.get(incident.id, []),
            evidence_prs=evidence_prs.get(incident.id, []),
        )

    def _evaluate_batch_confidence(
        self,
        *,
        confidence_inputs: list[_HybridConfidenceInput],
    ) -> list[tuple[_HybridConfidenceInput, _ConfidenceEval]]:
        self._last_batch_confidence_input_ids = [
            confidence_input.incident.id for confidence_input in confidence_inputs
        ]
        self._last_batch_confidence_eval = None
        if not confidence_inputs:
            return []

        self._confidence_telemetry.evaluated_candidates += len(confidence_inputs)
        self._confidence_telemetry.llm_calls += 1
        self._confidence_telemetry.batch_llm_calls += 1
        batch_eval = self._evaluate_batch_confidence_with_llm(
            confidence_inputs=confidence_inputs,
        )
        self._last_batch_confidence_eval = batch_eval
        if batch_eval is None:
            self._confidence_telemetry.llm_failures += 1
            self._confidence_telemetry.fallback_executions += 1
            self._confidence_telemetry.record_rejection("batch_llm_failed")
            logger.info(
                "batch confidence failed; falling back to individual confidence "
                "candidate_count=%s",
                len(confidence_inputs),
            )
            return self._evaluate_confidence_individually(confidence_inputs)

        return self._rank_batch_confidence_results(
            confidence_inputs=confidence_inputs,
            batch_eval=batch_eval,
        )

    def _rank_batch_confidence_results(
        self,
        *,
        confidence_inputs: list[_HybridConfidenceInput],
        batch_eval: _BatchConfidenceEval,
    ) -> list[tuple[_HybridConfidenceInput, _ConfidenceEval]]:
        inputs_by_id = {
            confidence_input.incident.id: confidence_input
            for confidence_input in confidence_inputs
        }
        evaluations_by_id = {
            evaluation.incident_id: evaluation for evaluation in batch_eval.evaluations
        }

        ranked: list[tuple[_HybridConfidenceInput, _ConfidenceEval]] = []
        seen_ranked_ids: set[uuid.UUID] = set()
        for incident_id in batch_eval.ranking:
            evaluation = evaluations_by_id.get(incident_id)
            confidence_input = inputs_by_id.get(incident_id)
            if evaluation is None or confidence_input is None:
                continue
            seen_ranked_ids.add(incident_id)
            if not self._batch_evaluation_should_pass(evaluation):
                self._record_batch_rejection(evaluation)
                continue
            self._confidence_telemetry.passed_candidates += 1
            ranked.append(
                (
                    confidence_input,
                    _ConfidenceEval(
                        confidence=evaluation.confidence,
                        confidence_score=evaluation.confidence_score,
                        reason=evaluation.reason,
                    ),
                )
            )

        for incident_id, evaluation in evaluations_by_id.items():
            if incident_id in seen_ranked_ids:
                continue
            if self._batch_evaluation_should_pass(evaluation):
                # ranking에 없는 include=true 후보는 출력 계약 위반이므로 보수적으로 제외한다.
                self._confidence_telemetry.record_rejection(
                    "batch_include_missing_from_ranking"
                )
                continue
            self._record_batch_rejection(evaluation)

        return ranked

    def _batch_evaluation_should_pass(
        self,
        evaluation: _BatchConfidenceEvaluation,
    ) -> bool:
        return (
            evaluation.should_include
            and evaluation.confidence != "low"
            and evaluation.confidence_score >= _MIN_LLM_CONFIDENCE_SCORE
        )

    def _record_batch_rejection(
        self,
        evaluation: _BatchConfidenceEvaluation,
    ) -> None:
        if evaluation.confidence == "low":
            self._confidence_telemetry.llm_low_confidence_rejections += 1
            self._confidence_telemetry.record_rejection("batch_low_confidence")
            return
        if evaluation.confidence_score < _MIN_LLM_CONFIDENCE_SCORE:
            self._confidence_telemetry.llm_low_confidence_rejections += 1
            self._confidence_telemetry.record_rejection("batch_low_confidence_score")
            return
        self._confidence_telemetry.record_rejection("batch_should_exclude")

    def _chat_json_schema_strict_with_usage(
        self,
        messages: list[dict[str, object]],
        *,
        schema_model: type[BaseModel],
        schema_name: str,
    ) -> str | None:
        method = getattr(self._llm, "chat_json_schema_strict_with_usage", None)
        if method is None:
            return self._llm.chat_json_schema_strict(
                messages,
                schema_model=schema_model,
                schema_name=schema_name,
            )
        result = method(
            messages,
            schema_model=schema_model,
            schema_name=schema_name,
        )
        self._record_llm_usage(result)
        return result.text if result else None

    def _chat_json_object_with_usage(
        self,
        messages: list[dict[str, object]],
    ) -> str | None:
        method = getattr(self._llm, "chat_json_object_with_usage", None)
        if method is None:
            return self._llm.chat_json_object(messages)
        result = method(messages)
        self._record_llm_usage(result)
        return result.text if result else None

    def _record_llm_usage(self, result: object | None) -> None:
        if result is None:
            return
        prompt_tokens = getattr(result, "prompt_tokens", None)
        completion_tokens = getattr(result, "completion_tokens", None)
        if prompt_tokens is None and completion_tokens is None:
            return
        if prompt_tokens is not None:
            self._confidence_telemetry.prompt_input_tokens += int(prompt_tokens)
        if completion_tokens is not None:
            self._confidence_telemetry.output_tokens += int(completion_tokens)
        self._confidence_telemetry.token_observations += 1

    def _evaluate_confidence_individually(
        self,
        confidence_inputs: list[_HybridConfidenceInput],
    ) -> list[tuple[_HybridConfidenceInput, _ConfidenceEval]]:
        ranked: list[tuple[_HybridConfidenceInput, _ConfidenceEval]] = []
        for confidence_input in confidence_inputs:
            confidence_eval = self._evaluate_confidence(
                confidence_input=confidence_input,
                count_candidate=False,
            )
            if confidence_eval is not None:
                ranked.append((confidence_input, confidence_eval))
        return ranked

    def _evaluate_confidence(
        self,
        *,
        confidence_input: _HybridConfidenceInput,
        count_candidate: bool = True,
    ) -> _ConfidenceEval | None:
        if count_candidate:
            self._confidence_telemetry.evaluated_candidates += 1

        if self._should_reject_before_llm(confidence_input):
            self._confidence_telemetry.pre_llm_rejections += 1
            self._confidence_telemetry.record_rejection("vector_only_too_low")
            return None

        self._confidence_telemetry.llm_calls += 1
        self._confidence_telemetry.individual_llm_calls += 1
        llm_eval = self._evaluate_confidence_with_llm(
            confidence_input=confidence_input,
        )

        if llm_eval is None:
            self._confidence_telemetry.llm_failures += 1
            self._confidence_telemetry.record_rejection("llm_eval_failed")
            logger.info(
                "confidence rejected: llm_eval_failed incident_id=%s "
                "vector_rank=%s bm25_rank=%s rrf_rank=%s",
                confidence_input.incident.id,
                confidence_input.vector_rank,
                confidence_input.bm25_rank,
                confidence_input.rrf_rank,
            )
            return None

        if llm_eval.confidence_score < _MIN_LLM_CONFIDENCE_SCORE:
            self._confidence_telemetry.llm_low_confidence_rejections += 1
            self._confidence_telemetry.record_rejection("llm_low_confidence")
            return None
        self._confidence_telemetry.passed_candidates += 1
        return llm_eval

    def _should_reject_before_llm(
        self,
        confidence_input: _HybridConfidenceInput,
    ) -> bool:
        """BM25 근거가 없는 vector-only 극저점 후보만 LLM 호출 전에 제거한다.

        기존 `_MIN_SCORE=0.45`는 vector-only 여부와 무관하게 후보를 제거했다.
        Hybrid Retrieval에서는 BM25/RRF 근거를 보존해야 하므로 더 낮은
        `_VECTOR_ONLY_PRE_REJECT_SCORE`를 별도로 둔다.
        """
        if confidence_input.in_bm25:
            return False
        if confidence_input.rrf_rank <= 3:
            return False
        if confidence_input.vector_score is None:
            return False
        return confidence_input.vector_score < _VECTOR_ONLY_PRE_REJECT_SCORE

    def _evaluate_batch_confidence_with_llm(
        self,
        *,
        confidence_inputs: list[_HybridConfidenceInput],
    ) -> _BatchConfidenceEval | None:
        if not self._settings.openai_api_key:
            return None

        query_intent = self._normalize_query_intent(confidence_inputs[0].query_intent)
        prompt = {
            "q": confidence_inputs[0].query,
            "intent": query_intent,
            "candidates": [
                self._batch_confidence_candidate_payload(
                    confidence_input,
                    query_intent=query_intent,
                )
                for confidence_input in confidence_inputs
            ],
            "rules": (
                "Evaluate every incident_id. ranking includes only "
                "should_include=true ids. No match means ranking=[] and "
                "no_relevant_candidate=true. Weak/indirect relevance must use "
                "confidence=low or confidence_score < 0.5."
            ),
        }
        messages = [
            {
                "role": "developer",
                "content": (
                    "Return JSON only matching the schema. Compare candidates against "
                    "the query. Candidate keys: rrf/vec/bm25 are ranks, not "
                    "probabilities. Do not infer missing causes, fixes, components, "
                    "or context. Exact error/class/code/file/column/service/module/"
                    "action/symptom/cause matches are strong; generic shared words are "
                    "weak. For queries containing '외부 연동', '외부 호출', "
                    "'외부 API', external integration/API, or partner API call "
                    "failure, prefer external/partner API call or timeout evidence. "
                    "Treat SSL/TLS/PKIX/인증서/certificate failures as different "
                    "security/certificate problems unless those words appear in the query. "
                    "For call-failure queries, API timeout/call evidence is stronger "
                    "than webhook JSON/enum mapping. If the query mentions CSS, "
                    "화면 깨짐, 정적 리소스, or frontend assets, reject backend "
                    "Redis/cache server/pool incidents unless Redis, server cache, or "
                    "data cache is explicit; the Korean word '캐시' alone is not "
                    "explicit Redis/server-cache evidence. 반드시 지킬 것: CSS 깨짐/"
                    "정적 리소스 캐시 문제와 Redis/cache 조회/서버/connection pool "
                    "장애는 cache 단어를 공유해도 다른 문제다. For that mismatch, "
                    "return should_include=false, confidence=low, confidence_score <= 0.4. "
                    "If your reason says weak, indirect, or 직접 연관성 약함, do not "
                    "include that candidate. SMTP/mail auth failures and HTTPS/SSL/TLS/"
                    "PKIX certificate incidents are different even if both mention auth. "
                    "Do not auto-select RRF rank 1. If none "
                    "match, return ranking=[] and no_relevant_candidate=true. "
                    "evaluations must have one item per input incident_id; ranking "
                    "must contain only included ids in relevance order. Reasons: one "
                    "Korean sentence."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]

        expected_ids = [item.incident.id for item in confidence_inputs]
        text = self._chat_json_schema_strict_with_usage(
            messages,
            schema_model=_BatchConfidenceEval,
            schema_name="BatchIncidentConfidenceEval",
        )
        parsed = self._parse_batch_confidence_eval(
            text,
            expected_ids=expected_ids,
            allow_json_extraction=False,
        )
        if parsed is not None:
            return parsed

        text = self._chat_json_object_with_usage(messages)
        return self._parse_batch_confidence_eval(
            text,
            expected_ids=expected_ids,
            allow_json_extraction=True,
        )

    def _batch_confidence_candidate_payload(
        self,
        confidence_input: _HybridConfidenceInput,
        *,
        query_intent: str | None,
    ) -> dict[str, object]:
        incident = confidence_input.incident
        payload: dict[str, object | None] = {
            "incident_id": str(incident.id),
            "rrf": confidence_input.rrf_rank,
            "vec": confidence_input.vector_rank,
            "bm25": confidence_input.bm25_rank,
            "type": incident.primary_error_type,
            "msg": incident.primary_error_message,
            "summary": self._truncate_text(
                incident.primary_error_summary,
                _MAX_PRIMARY_ERROR_SUMMARY_CHARS,
            ),
        }
        if query_intent == "ROOT_CAUSE":
            if self._query_mentions_project(confidence_input.query, incident.project_name):
                payload["keywords"] = self._compact_list(
                    incident.error_keywords,
                    _MAX_ERROR_KEYWORDS,
                )
                payload["tags"] = self._compact_list(
                    incident.domain_tags,
                    _MAX_DOMAIN_TAGS,
                )
            payload["cause"] = self._truncate_text(
                incident.suspected_cause,
                _MAX_SUSPECTED_CAUSE_CHARS,
            )
            payload["root"] = self._truncate_text(
                incident.root_cause_summary,
                _MAX_ROOT_CAUSE_SUMMARY_CHARS,
            )
        elif query_intent == "RESOLUTION":
            payload["resolution"] = self._truncate_text(
                incident.resolution_summary,
                _MAX_RESOLUTION_SUMMARY_CHARS,
            )
        elif query_intent == "SIMILAR_CASE":
            payload["keywords"] = self._compact_list(
                incident.error_keywords,
                _MAX_ERROR_KEYWORDS,
            )
            payload["tags"] = self._compact_list(
                incident.domain_tags,
                _MAX_DOMAIN_TAGS,
            )
        elif query_intent == "SUMMARY":
            payload["keywords"] = self._compact_list(
                incident.error_keywords,
                _MAX_ERROR_KEYWORDS,
            )
            payload["tags"] = self._compact_list(
                incident.domain_tags,
                _MAX_DOMAIN_TAGS,
            )
            payload["cause"] = self._truncate_text(
                incident.suspected_cause,
                _MAX_SUSPECTED_CAUSE_CHARS,
            )
            payload["root"] = self._truncate_text(
                incident.root_cause_summary,
                _MAX_ROOT_CAUSE_SUMMARY_CHARS,
            )
            payload["resolution"] = self._truncate_text(
                incident.resolution_summary,
                _MAX_RESOLUTION_SUMMARY_CHARS,
            )
        return self._drop_empty_payload_values(payload)

    def _normalize_query_intent(self, query_intent: str | None) -> str | None:
        if not query_intent:
            return None
        normalized = query_intent.strip().upper()
        return normalized or None

    def _query_mentions_project(self, query: str, project_name: str | None) -> bool:
        if not project_name:
            return False
        normalized_query = query.lower().replace("_", "-")
        normalized_project = project_name.lower().replace("_", "-")
        return normalized_project in normalized_query

    def _truncate_text(self, value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if len(clean) <= limit:
            return clean
        return clean[:limit].rstrip()

    def _compact_list(self, values: list[str] | None, limit: int) -> list[str]:
        if not values:
            return []
        compacted = []
        for value in values:
            clean = value.strip() if isinstance(value, str) else ""
            if clean:
                compacted.append(clean)
            if len(compacted) >= limit:
                break
        return compacted

    def _drop_empty_payload_values(
        self,
        payload: dict[str, object | None],
    ) -> dict[str, object]:
        cleaned: dict[str, object] = {}
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, list) and not value:
                continue
            cleaned[key] = value
        return cleaned

    def _parse_batch_confidence_eval(
        self,
        text: str | None,
        *,
        expected_ids: list[uuid.UUID],
        allow_json_extraction: bool,
    ) -> _BatchConfidenceEval | None:
        if not text or not text.strip():
            return None
        try:
            json_text = (
                extract_first_json_object(text) if allow_json_extraction else text
            )
            parsed = _BatchConfidenceEval.model_validate_json(json_text or text)
        except ValidationError as exc:
            logger.debug(
                "batch confidence eval parse failed: %s preview=%s",
                exc,
                preview_truncated(text, 800),
            )
            return None

        expected_id_set = set(expected_ids)
        evaluation_ids = [evaluation.incident_id for evaluation in parsed.evaluations]
        ranking_ids = list(parsed.ranking)
        if set(evaluation_ids) != expected_id_set or len(evaluation_ids) != len(
            expected_ids
        ):
            logger.info(
                "batch confidence eval invalid evaluation ids expected=%s actual=%s",
                [str(item) for item in expected_ids],
                [str(item) for item in evaluation_ids],
            )
            return None
        if len(set(ranking_ids)) != len(ranking_ids) or not set(ranking_ids).issubset(
            expected_id_set
        ):
            logger.info(
                "batch confidence eval invalid ranking ids expected=%s actual=%s",
                [str(item) for item in expected_ids],
                [str(item) for item in ranking_ids],
            )
            return None
        included_ids = {
            evaluation.incident_id
            for evaluation in parsed.evaluations
            if evaluation.should_include
        }
        if not set(ranking_ids).issubset(included_ids):
            logger.info(
                "batch confidence eval ranking contains excluded candidates ranking=%s included=%s",
                [str(item) for item in ranking_ids],
                [str(item) for item in included_ids],
            )
            return None
        if parsed.no_relevant_candidate and ranking_ids:
            logger.info("batch confidence eval no_relevant_candidate with non-empty ranking")
            return None
        return parsed

    def _evaluate_confidence_with_llm(
        self,
        *,
        confidence_input: _HybridConfidenceInput,
    ) -> _ConfidenceEval | None:
        if not self._settings.openai_api_key:
            return None
        incident = confidence_input.incident

        prompt = {
            "task": "incident_confidence_eval",
            "instruction": (
                "사용자 query와 검색된 incident가 같은 문제를 가리킬 가능성만 평가한다. "
                "검색 점수는 보조 근거로만 사용하고, 점수를 정답 확률로 해석하지 않는다. "
                "질의에 없는 원인이나 장애 정보를 추론하여 일치한다고 판단하지 않는다."
            ),
            # confidence 평가 기준
            "confidence_criteria": {
                "high": (
                    "query에 incident의 에러 현상, 서비스, 모듈, 클래스명, "
                    "에러 코드, 라이브러리명, 원인 또는 해결 맥락이 직접 겹침"
                ),
                "medium": (
                    "도메인/증상은 유사하지만 핵심 에러, 서비스, 원인, 해결 "
                    "근거가 일부 부족함"
                ),
                "low": "관련 근거 부족 또는 다른 문제",
            },
            "search_score_rules": [
                "vector_score, bm25_score, rrf_score를 정답 확률로 해석하지 말 것",
                "검색 순위와 점수는 보조 근거로만 사용할 것",
                "RRF 1위라는 이유만으로 high confidence를 주지 말 것",
                "같은 예외 타입이나 기술 키워드만으로 high confidence를 주지 말 것",
                "클래스명, 에러 코드, 서비스명, 모듈명의 정확한 일치는 강한 근거로 사용할 것",
            ],
            "query": confidence_input.query,
            "incident": {
                "summary": incident.primary_error_summary,
                "error_type": incident.primary_error_type,
                "error_message": incident.primary_error_message,
                "module_name": incident.module_name,
                "class_name": incident.class_name,
                "method_name": incident.method_name,
                "suspected_cause": incident.suspected_cause,
                "root_cause_summary": incident.root_cause_summary,
                "keywords": incident.error_keywords,
                "domain_tags": incident.domain_tags,
                "resolution": incident.resolution_summary,
            },
            "retrieval_evidence": {
                "included_in_vector": confidence_input.in_vector,
                "vector_rank": confidence_input.vector_rank,
                "vector_score": confidence_input.vector_score,
                "included_in_bm25": confidence_input.in_bm25,
                "bm25_rank": confidence_input.bm25_rank,
                "bm25_score": confidence_input.bm25_score,
                "included_in_both_vector_and_bm25": confidence_input.in_both,
                "rrf_rank": confidence_input.rrf_rank,
                "rrf_score": confidence_input.rrf_score,
            },
            "output_contract": {
                "must_be_json_only": True,
                "format": {
                    "confidence": "high | medium | low",
                    "confidence_score": "0.0~1.0 float",
                    "reason": "한국어 한 문장",
                },
            },
        }
        messages = [
            {
                "role": "developer",
                "content": (
                    "Return JSON only. "
                    "Evaluate only whether the user query and retrieved incident "
                    "likely refer to the same problem. Treat vector, BM25, and RRF "
                    "scores as supporting retrieval evidence only, never as calibrated "
                    "probabilities. Do not infer missing causes, fixes, or hidden context."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]

        text = self._chat_json_schema_strict_with_usage(
            messages,
            schema_model=_ConfidenceEval,
            schema_name="IncidentConfidenceEval",
        )
        parsed = self._parse_confidence_eval(text, allow_json_extraction=False)
        if parsed is not None:
            return parsed

        text = self._chat_json_object_with_usage(messages)
        return self._parse_confidence_eval(text, allow_json_extraction=True)

    def _parse_confidence_eval(
        self,
        text: str | None,
        *,
        allow_json_extraction: bool,
    ) -> _ConfidenceEval | None:
        if not text or not text.strip():
            return None
        try:
            json_text = (
                extract_first_json_object(text) if allow_json_extraction else text
            )
            return _ConfidenceEval.model_validate_json(json_text or text)
        except ValidationError as exc:
            logger.debug(
                "confidence eval parse failed: %s preview=%s",
                exc,
                preview_truncated(text, 800),
            )
            return None

    def _search_embeddings(
        self,
        *,
        query_vector: list[float],
        limit: int,
        project_name: str | None = None,
    ) -> list[_VectorSearchHit]:
        if limit <= 0 or not query_vector:
            return []

        # 현재는 데이터가 적으므로 exact scan을 사용
        # TODO: incident_embeddings 데이터가 충분히 많아지면 HNSW 인덱스 적용 예정
        query_vector_str = "[" + ",".join(map(str, query_vector)) + "]"
        project_filter = ""
        params: dict[str, object] = {
            "query_vector": query_vector_str,
            "limit": limit,
        }
        if project_name is not None:
            project_filter = "WHERE i.project_name = :project_name"
            params["project_name"] = project_name

        rows = self._session.execute(
            text(f"""
                SELECT incident_id, distance, rank
                FROM (
                    SELECT
                        ie.incident_id,
                        ie.embedding_vector <=> CAST(:query_vector AS vector) AS distance,
                        rank() OVER (
                            ORDER BY ie.embedding_vector <=> CAST(:query_vector AS vector), ie.incident_id ASC
                        ) AS rank
                    FROM incident_embeddings ie
                    JOIN incidents i ON i.id = ie.incident_id
                    {project_filter}
                ) AS exact_search
                ORDER BY rank ASC
                LIMIT :limit
            """),
            params,
        ).all()

        return [
            _VectorSearchHit(
                incident_id=incident_id,
                distance=float(distance),
                vector_score=max(0.0, 1.0 - float(distance)),
                rank=int(rank),
            )
            for incident_id, distance, rank in rows
        ]

    def _candidate_limit(self, top_k: int) -> int:
        if top_k <= 0:
            return 0
        return max(top_k * 5, 20)

    def _merge_with_rrf(
        self,
        *,
        vector_hits: list[_VectorSearchHit],
        bm25_hits: list[IncidentBm25SearchHit],
        top_k: int,
        rrf_k: int = _RRF_K,
    ) -> list[_RrfSearchHit]:
        merged: dict[uuid.UUID, dict[str, object]] = {}

        for hit in vector_hits:
            data = merged.setdefault(hit.incident_id, {"rrf_score": 0.0})
            data["vector_rank"] = hit.rank
            data["vector_score"] = hit.vector_score
            data["distance"] = hit.distance
            data["rrf_score"] = float(data["rrf_score"]) + self._rrf_score(
                rank=hit.rank,
                rrf_k=rrf_k,
            )

        for hit in bm25_hits:
            data = merged.setdefault(hit.incident_id, {"rrf_score": 0.0})
            data["keyword_rank"] = hit.rank
            data["bm25_score"] = hit.bm25_score
            data["rrf_score"] = float(data["rrf_score"]) + self._rrf_score(
                rank=hit.rank,
                rrf_k=rrf_k,
            )

        unranked_results = [
            _RrfSearchHit(
                incident_id=incident_id,
                rrf_rank=0,
                vector_rank=data.get("vector_rank"),  # type: ignore[arg-type]
                keyword_rank=data.get("keyword_rank"),  # type: ignore[arg-type]
                vector_score=data.get("vector_score"),  # type: ignore[arg-type]
                bm25_score=data.get("bm25_score"),  # type: ignore[arg-type]
                distance=data.get("distance"),  # type: ignore[arg-type]
                rrf_score=float(data["rrf_score"]),
            )
            for incident_id, data in merged.items()
        ]
        unranked_results.sort(key=lambda hit: (-hit.rrf_score, str(hit.incident_id)))
        ranked_results = [
            _RrfSearchHit(
                incident_id=hit.incident_id,
                rrf_rank=rank,
                vector_rank=hit.vector_rank,
                keyword_rank=hit.keyword_rank,
                vector_score=hit.vector_score,
                bm25_score=hit.bm25_score,
                distance=hit.distance,
                rrf_score=hit.rrf_score,
            )
            for rank, hit in enumerate(unranked_results, start=1)
        ]
        return ranked_results[:top_k]

    def _rrf_score(self, *, rank: int, rrf_k: int) -> float:
        return 1.0 / (rrf_k + rank)

    def _elapsed_ms(self, start: float) -> float:
        return (perf_counter() - start) * 1000.0

    def _load_incidents(
        self, incident_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Incident]:
        if not incident_ids:
            return {}
        stmt = select(Incident).where(Incident.id.in_(incident_ids))
        return {incident.id: incident for incident in self._session.scalars(stmt).all()}

    def _load_logs(
        self,
        incident_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[EvidenceLog]]:
        if not incident_ids:
            return {}
        stmt = (
            select(RawLog)
            .where(RawLog.incident_id.in_(incident_ids))
            .order_by(RawLog.occurred_at.asc())
        )
        grouped: dict[uuid.UUID, list[EvidenceLog]] = defaultdict(list)
        for log in self._session.scalars(stmt).all():
            if log.incident_id is None:
                continue
            grouped[log.incident_id].append(
                EvidenceLog(
                    id=log.id,
                    log_level=log.log_level,
                    raw_message=log.raw_message,
                    error_type=log.error_type,
                    error_message=log.error_message,
                    normalized_summary=log.normalized_summary,
                    occurred_at=log.occurred_at,
                )
            )
        return grouped

    def _load_tickets(
        self,
        incident_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[EvidenceTicket]]:
        if not incident_ids:
            return {}
        stmt = (
            select(RawTicket)
            .where(RawTicket.incident_id.in_(incident_ids))
            .order_by(RawTicket.ticket_created_at.asc())
        )
        grouped: dict[uuid.UUID, list[EvidenceTicket]] = defaultdict(list)
        for ticket in self._session.scalars(stmt).all():
            if ticket.incident_id is None:
                continue
            grouped[ticket.incident_id].append(
                EvidenceTicket(
                    id=ticket.id,
                    ticket_key=ticket.ticket_key,
                    title=ticket.title,
                    description=ticket.description,
                    status=ticket.status,
                    priority=ticket.priority,
                    reporter=ticket.reporter,
                    assignee=ticket.assignee,
                    normalized_summary=ticket.normalized_summary,
                    suspected_cause=ticket.suspected_cause,
                    resolution_note=ticket.resolution_note,
                    ticket_created_at=ticket.ticket_created_at,
                )
            )
        return grouped

    def _load_prs(
        self,
        incident_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[EvidencePr]]:
        if not incident_ids:
            return {}
        stmt = (
            select(RawPr)
            .where(RawPr.incident_id.in_(incident_ids))
            .order_by(RawPr.pr_created_at.asc())
        )
        grouped: dict[uuid.UUID, list[EvidencePr]] = defaultdict(list)
        for pr in self._session.scalars(stmt).all():
            if pr.incident_id is None:
                continue
            grouped[pr.incident_id].append(
                EvidencePr(
                    id=pr.id,
                    pr_key=pr.pr_key,
                    title=pr.title,
                    description=pr.description,
                    author=pr.author,
                    status=pr.status,
                    source_branch=pr.source_branch,
                    target_branch=pr.target_branch,
                    changed_files=list(pr.changed_files or []),
                    diff_summary=pr.diff_summary,
                    normalized_summary=pr.normalized_summary,
                    suspected_fix_for=pr.suspected_fix_for,
                    resolution_note=pr.resolution_note,
                    merged_at=pr.merged_at,
                )
            )
        return grouped
