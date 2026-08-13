from __future__ import annotations

import uuid
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from app.agents.incident_agent import IncidentAnswerAgent, QueryAnalysis
from app.config import Settings
from app.models.evaluation import (
    EvaluationCandidate,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
)
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.evaluation import (
    EvaluationCandidateRead,
    EvaluationResultRead,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunRead,
)
from app.services.retrieval import IncidentRetrievalService, RetrievalEvaluationTrace

_RETRIEVAL_VERSION = "hybrid-rrf-confidence:batch-multi-candidate-compact-v1"
_QUERY_ANALYZER_VERSION = "incident-agent-query-analyzer:v1"


class EvaluationService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: EvaluationRepository,
        query_agent: IncidentAnswerAgent,
        retrieval_service: IncidentRetrievalService,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._query_agent = query_agent
        self._retrieval_service = retrieval_service

    def run(self, request: EvaluationRunCreate) -> EvaluationRunDetail:
        cases = self._repository.list_active_cases()
        confidence_telemetry = self._empty_confidence_telemetry()
        now = datetime.now(timezone.utc)
        run = self._repository.create_run(
            EvaluationRun(
                run_name=request.run_name.strip(),
                retrieval_version=_RETRIEVAL_VERSION,
                embedding_model=self._settings.embedding_model_name,
                query_analyzer_version=_QUERY_ANALYZER_VERSION,
                parameters=request.model_dump(),
                status="RUNNING",
                total_cases=len(cases),
                completed_cases=0,
                started_at=now,
            )
        )
        self._repository.commit()

        for case in cases:
            self._run_one_case(
                run=run,
                case=case,
                request=request,
                confidence_telemetry=confidence_telemetry,
            )

        self._complete_run(run, confidence_telemetry=confidence_telemetry)
        return self.get_run(run.id)

    def get_run(self, run_id: uuid.UUID) -> EvaluationRunDetail:
        run = self._repository.get_run(run_id)
        if run is None:
            raise KeyError(str(run_id))

        results = self._repository.list_results_for_run(run.id)
        case_map = self._repository.get_case_map([result.case_id for result in results])
        candidates_by_result = self._repository.list_candidates_for_results(
            [result.id for result in results]
        )
        return EvaluationRunDetail(
            **self._run_to_read(run).model_dump(),
            results=[
                self._result_to_read(
                    result=result,
                    case=case_map[result.case_id],
                    candidates=candidates_by_result.get(result.id, []),
                )
                for result in results
                if result.case_id in case_map
            ],
        )

    def _run_one_case(
        self,
        *,
        run: EvaluationRun,
        case: EvaluationCase,
        request: EvaluationRunCreate,
        confidence_telemetry: dict[str, Any],
    ) -> None:
        start = perf_counter()
        try:
            analysis = self._query_agent.analyze_query(case.question)
            trace: RetrievalEvaluationTrace | None = None
            retrieval_latency_ms: float | None = None
            if analysis.retrieval_required and analysis.query_sufficient:
                retrieval_start = perf_counter()
                trace = self._retrieval_service.search_for_evaluation(
                    query=analysis.rewritten_query or case.question,
                    top_k=request.top_k,
                    candidate_limit=request.candidate_limit,
                    rrf_k=request.rrf_k,
                    project_name=case.project_name,
                    query_intent=analysis.intent,
                )
                retrieval_latency_ms = self._elapsed_ms(retrieval_start)

            result = self._build_success_result(
                run=run,
                case=case,
                analysis=analysis,
                trace=trace,
                retrieval_latency_ms=retrieval_latency_ms,
                total_latency_ms=self._elapsed_ms(start),
            )
            self._repository.create_result(result)
            if trace is not None:
                self._merge_confidence_telemetry(
                    aggregate=confidence_telemetry,
                    case_telemetry=trace.confidence_telemetry,
                )
                self._repository.create_candidates(
                    self._build_candidates(result_id=result.id, trace=trace)
                )
            run.completed_cases += 1
            self._repository.update_run(run)
            self._repository.commit()
        except Exception as exc:
            self._repository.rollback()
            error_result = EvaluationResult(
                run_id=run.id,
                case_id=case.id,
                original_query=case.question,
                rewritten_query=None,
                predicted_intent=None,
                expected_incident_id=case.expected_incident_id,
                expected_no_result=case.expected_no_result,
                expected_rank=None,
                top1_hit=False,
                top3_hit=False,
                reciprocal_rank=0.0,
                confidence=None,
                abstained=True,
                no_result_correct=case.expected_no_result,
                retrieval_latency_ms=None,
                total_latency_ms=self._elapsed_ms(start),
                error_message=str(exc),
            )
            self._repository.create_result(error_result)
            run.completed_cases += 1
            self._repository.update_run(run)
            self._repository.commit()

    def _build_success_result(
        self,
        *,
        run: EvaluationRun,
        case: EvaluationCase,
        analysis: QueryAnalysis,
        trace: RetrievalEvaluationTrace | None,
        retrieval_latency_ms: float | None,
        total_latency_ms: float,
    ) -> EvaluationResult:
        search_results = trace.search_response.results if trace is not None else []
        expected_rank = self._expected_rank(case, search_results)
        abstained = len(search_results) == 0
        no_result_correct = case.expected_no_result and abstained
        top_confidence = search_results[0].confidence if search_results else None
        return EvaluationResult(
            run_id=run.id,
            case_id=case.id,
            original_query=case.question,
            rewritten_query=analysis.rewritten_query,
            predicted_intent=analysis.intent,
            expected_incident_id=case.expected_incident_id,
            expected_no_result=case.expected_no_result,
            expected_rank=expected_rank,
            top1_hit=expected_rank == 1,
            top3_hit=expected_rank is not None and expected_rank <= 3,
            reciprocal_rank=(1.0 / expected_rank) if expected_rank else 0.0,
            confidence=top_confidence,
            abstained=abstained,
            no_result_correct=no_result_correct if case.expected_no_result else None,
            retrieval_latency_ms=retrieval_latency_ms,
            total_latency_ms=total_latency_ms,
            error_message=None,
        )

    def _build_candidates(
        self,
        *,
        result_id: uuid.UUID,
        trace: RetrievalEvaluationTrace,
    ) -> list[EvaluationCandidate]:
        candidates = []
        for item in (
            trace.vector_candidates + trace.bm25_candidates + trace.rrf_candidates
        ):
            candidates.append(
                EvaluationCandidate(
                    evaluation_result_id=result_id,
                    search_type=item.search_type,
                    incident_id=item.incident_id,
                    rank=item.rank,
                    raw_score=item.raw_score,
                    vector_score=item.vector_score,
                    bm25_score=item.bm25_score,
                    rrf_score=item.rrf_score,
                )
            )
        return candidates

    def _complete_run(
        self,
        run: EvaluationRun,
        *,
        confidence_telemetry: dict[str, Any],
    ) -> None:
        results = self._repository.list_results_for_run(run.id)
        expected_results = [
            result
            for result in results
            if not result.expected_no_result and result.expected_incident_id is not None
        ]
        no_result_results = [result for result in results if result.expected_no_result]
        latencies = [
            result.total_latency_ms
            for result in results
            if result.total_latency_ms is not None
        ]

        run.status = "COMPLETED"
        run.completed_cases = len(results)
        run.top1_accuracy = self._ratio(
            sum(1 for result in expected_results if result.top1_hit),
            len(expected_results),
        )
        run.top3_accuracy = self._ratio(
            sum(1 for result in expected_results if result.top3_hit),
            len(expected_results),
        )
        run.mrr = self._ratio(
            sum(result.reciprocal_rank for result in expected_results),
            len(expected_results),
        )
        run.no_result_accuracy = self._ratio(
            sum(1 for result in no_result_results if result.no_result_correct),
            len(no_result_results),
        )
        run.mean_latency_ms = self._ratio(sum(latencies), len(latencies))
        run.parameters = {
            **run.parameters,
            "confidence_telemetry": {
                **confidence_telemetry,
                "avg_llm_calls_per_case": self._ratio(
                    confidence_telemetry["llm_calls"],
                    len(results),
                ),
                "avg_prompt_input_tokens": self._ratio(
                    confidence_telemetry["prompt_input_tokens"],
                    confidence_telemetry["token_observations"],
                ),
                "avg_output_tokens": self._ratio(
                    confidence_telemetry["output_tokens"],
                    confidence_telemetry["token_observations"],
                ),
            },
        }
        run.completed_at = datetime.now(timezone.utc)
        self._repository.update_run(run)
        self._repository.commit()

    def _empty_confidence_telemetry(self) -> dict[str, Any]:
        return {
            "evaluated_candidates": 0,
            "llm_calls": 0,
            "batch_llm_calls": 0,
            "individual_llm_calls": 0,
            "llm_failures": 0,
            "fallback_executions": 0,
            "llm_low_confidence_rejections": 0,
            "pre_llm_rejections": 0,
            "passed_candidates": 0,
            "prompt_input_tokens": 0,
            "output_tokens": 0,
            "token_observations": 0,
            "rejected_by": {},
        }

    def _merge_confidence_telemetry(
        self,
        *,
        aggregate: dict[str, Any],
        case_telemetry: Any,
    ) -> None:
        aggregate["evaluated_candidates"] += case_telemetry.evaluated_candidates
        aggregate["llm_calls"] += case_telemetry.llm_calls
        aggregate["batch_llm_calls"] += case_telemetry.batch_llm_calls
        aggregate["individual_llm_calls"] += case_telemetry.individual_llm_calls
        aggregate["llm_failures"] += case_telemetry.llm_failures
        aggregate["fallback_executions"] += case_telemetry.fallback_executions
        aggregate["llm_low_confidence_rejections"] += (
            case_telemetry.llm_low_confidence_rejections
        )
        aggregate["pre_llm_rejections"] += case_telemetry.pre_llm_rejections
        aggregate["passed_candidates"] += case_telemetry.passed_candidates
        aggregate["prompt_input_tokens"] += case_telemetry.prompt_input_tokens
        aggregate["output_tokens"] += case_telemetry.output_tokens
        aggregate["token_observations"] += case_telemetry.token_observations
        rejected_by = case_telemetry.rejected_by or {}
        aggregate_rejected_by = aggregate["rejected_by"]
        for reason, count in rejected_by.items():
            aggregate_rejected_by[reason] = aggregate_rejected_by.get(reason, 0) + count

    def _expected_rank(self, case: EvaluationCase, results: list[Any]) -> int | None:
        if case.expected_incident_id is None:
            return None
        for index, result in enumerate(results, start=1):
            if result.incident_id == case.expected_incident_id:
                return index
        return None

    def _run_to_read(self, run: EvaluationRun) -> EvaluationRunRead:
        return EvaluationRunRead(
            id=run.id,
            run_name=run.run_name,
            retrieval_version=run.retrieval_version,
            embedding_model=run.embedding_model,
            query_analyzer_version=run.query_analyzer_version,
            parameters=run.parameters,
            status=run.status,
            total_cases=run.total_cases,
            completed_cases=run.completed_cases,
            top1_accuracy=run.top1_accuracy,
            top3_accuracy=run.top3_accuracy,
            mrr=run.mrr,
            no_result_accuracy=run.no_result_accuracy,
            mean_latency_ms=run.mean_latency_ms,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def _result_to_read(
        self,
        *,
        result: EvaluationResult,
        case: EvaluationCase,
        candidates: list[EvaluationCandidate],
    ) -> EvaluationResultRead:
        return EvaluationResultRead(
            id=result.id,
            case_id=result.case_id,
            case_key=case.case_key,
            project_name=case.project_name,
            original_query=result.original_query,
            rewritten_query=result.rewritten_query,
            predicted_intent=result.predicted_intent,
            expected_incident_id=result.expected_incident_id,
            expected_no_result=result.expected_no_result,
            expected_rank=result.expected_rank,
            top1_hit=result.top1_hit,
            top3_hit=result.top3_hit,
            reciprocal_rank=result.reciprocal_rank,
            confidence=result.confidence,
            abstained=result.abstained,
            no_result_correct=result.no_result_correct,
            retrieval_latency_ms=result.retrieval_latency_ms,
            total_latency_ms=result.total_latency_ms,
            error_message=result.error_message,
            created_at=result.created_at,
            candidates=[
                EvaluationCandidateRead(
                    id=candidate.id,
                    search_type=candidate.search_type,
                    incident_id=candidate.incident_id,
                    rank=candidate.rank,
                    raw_score=candidate.raw_score,
                    vector_score=candidate.vector_score,
                    bm25_score=candidate.bm25_score,
                    rrf_score=candidate.rrf_score,
                    created_at=candidate.created_at,
                )
                for candidate in candidates
            ],
        )

    def _elapsed_ms(self, start: float) -> float:
        return (perf_counter() - start) * 1000.0

    def _ratio(self, numerator: float, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return float(numerator) / float(denominator)
