from __future__ import annotations

import json
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import SessionLocal
from app.models.evaluation import (
    EvaluationCandidate,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
)
from app.config import get_settings
from app.services.retrieval import IncidentRetrievalService

REPORT_DIR = ROOT_DIR / "docs" / "evaluation"
JSON_REPORT_PATH = REPORT_DIR / "retrieval_baseline_analysis.json"
MD_REPORT_PATH = REPORT_DIR / "retrieval_baseline_analysis.md"

CURRENT_VECTOR_MIN_SCORE = 0.45
HIGH_CONFIDENCE_SCORE = 0.65
LLM_MIN_CONFIDENCE_SCORE = 0.5
THRESHOLD_CANDIDATES = [0.45, 0.6, 0.5, 0.4, 0.3]


@dataclass(frozen=True)
class CandidateRanks:
    vector_rank: int | None
    vector_score: float | None
    bm25_rank: int | None
    bm25_score: float | None
    rrf_rank: int | None
    rrf_score: float | None


def latest_completed_run(session) -> EvaluationRun:
    run = session.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.status == "COMPLETED")
        .order_by(EvaluationRun.started_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise RuntimeError("completed evaluation run not found")
    return run


def load_run_data(session, run_id: uuid.UUID):
    results = session.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
        .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
    ).all()
    cases = {
        case.id: case
        for case in session.scalars(
            select(EvaluationCase).where(
                EvaluationCase.id.in_([result.case_id for result in results])
            )
        ).all()
    }
    candidates = session.scalars(
        select(EvaluationCandidate).where(
            EvaluationCandidate.evaluation_result_id.in_(
                [result.id for result in results]
            )
        )
    ).all()
    candidates_by_result: dict[uuid.UUID, list[EvaluationCandidate]] = defaultdict(list)
    for candidate in candidates:
        candidates_by_result[candidate.evaluation_result_id].append(candidate)
    for grouped in candidates_by_result.values():
        grouped.sort(key=lambda item: (item.search_type, item.rank, str(item.id)))
    return results, cases, candidates_by_result


def ranks_for(
    result: EvaluationResult,
    candidates: list[EvaluationCandidate],
) -> CandidateRanks:
    expected_id = result.expected_incident_id
    if expected_id is None:
        return CandidateRanks(None, None, None, None, None, None)

    def find(search_type: str) -> EvaluationCandidate | None:
        return next(
            (
                candidate
                for candidate in candidates
                if candidate.search_type == search_type
                and candidate.incident_id == expected_id
            ),
            None,
        )

    vector = find("VECTOR")
    bm25 = find("BM25")
    rrf = find("RRF")
    return CandidateRanks(
        vector_rank=vector.rank if vector else None,
        vector_score=vector.vector_score if vector else None,
        bm25_rank=bm25.rank if bm25 else None,
        bm25_score=bm25.bm25_score if bm25 else None,
        rrf_rank=rrf.rank if rrf else None,
        rrf_score=rrf.rrf_score if rrf else None,
    )


def reciprocal_rank(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def compute_retrieval_metrics(
    results: list[EvaluationResult],
    candidates_by_result: dict[uuid.UUID, list[EvaluationCandidate]],
) -> dict[str, float | None]:
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    ranks = [
        ranks_for(result, candidates_by_result.get(result.id, [])).rrf_rank
        for result in answerable
    ]
    return {
        "retrieval_top1_accuracy": ratio(
            sum(1 for rank in ranks if rank == 1),
            len(answerable),
        ),
        "retrieval_top3_accuracy": ratio(
            sum(1 for rank in ranks if rank is not None and rank <= 3),
            len(answerable),
        ),
        "retrieval_mrr": ratio(
            sum(reciprocal_rank(rank) for rank in ranks),
            len(answerable),
        ),
    }


def compute_final_metrics(results: list[EvaluationResult]) -> dict[str, float | None]:
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    no_result = [result for result in results if result.expected_no_result]
    return {
        "final_top1_accuracy": ratio(
            sum(1 for result in answerable if result.top1_hit),
            len(answerable),
        ),
        "final_top3_accuracy": ratio(
            sum(1 for result in answerable if result.top3_hit),
            len(answerable),
        ),
        "final_mrr": ratio(
            sum(result.reciprocal_rank for result in answerable),
            len(answerable),
        ),
        "answerable_recall": ratio(
            sum(1 for result in answerable if not result.abstained),
            len(answerable),
        ),
        "no_result_accuracy": ratio(
            sum(1 for result in no_result if result.no_result_correct),
            len(no_result),
        ),
    }


def classify_failure(
    result: EvaluationResult,
    ranks: CandidateRanks,
    original_query_ranks: CandidateRanks | None,
) -> str | None:
    if result.error_message:
        return "EXECUTION_ERROR"
    if result.expected_no_result:
        return None if result.no_result_correct else "RETRIEVAL_MISS"
    if result.top3_hit:
        return None
    if original_query_ranks is not None and rank_declined(
        before=original_query_ranks.rrf_rank,
        after=ranks.rrf_rank,
    ):
        return "QUERY_REWRITE_ISSUE"
    if ranks.vector_rank is None and ranks.bm25_rank is None:
        return "RETRIEVAL_MISS"
    if ranks.rrf_rank is None or ranks.rrf_rank > 3:
        return "RRF_RANKING_MISS"
    if result.abstained or result.expected_rank is None:
        return "CONFIDENCE_REJECT"
    return "CONFIDENCE_REJECT"


def rank_declined(before: int | None, after: int | None) -> bool:
    if before is None:
        return False
    if after is None:
        return True
    return after > before


def candidate_record(
    result: EvaluationResult,
    case: EvaluationCase,
    ranks: CandidateRanks,
    original_query_ranks: CandidateRanks | None,
    failure_type: str,
) -> dict[str, Any]:
    return {
        "case_key": case.case_key,
        "category": case.category,
        "original_query": result.original_query,
        "rewritten_query": result.rewritten_query,
        "expected_incident_id": (
            str(result.expected_incident_id) if result.expected_incident_id else None
        ),
        "vector_rank": ranks.vector_rank,
        "vector_score": ranks.vector_score,
        "bm25_rank": ranks.bm25_rank,
        "bm25_score": ranks.bm25_score,
        "rrf_rank": ranks.rrf_rank,
        "rrf_score": ranks.rrf_score,
        "original_query_rrf_rank": (
            original_query_ranks.rrf_rank if original_query_ranks else None
        ),
        "original_query_rrf_score": (
            original_query_ranks.rrf_score if original_query_ranks else None
        ),
        "confidence": result.confidence or "not_recorded_after_reject",
        "confidence_threshold": {
            "vector_min_score": CURRENT_VECTOR_MIN_SCORE,
            "high_confidence_score": HIGH_CONFIDENCE_SCORE,
            "llm_min_confidence_score": LLM_MIN_CONFIDENCE_SCORE,
        },
        "abstained": result.abstained,
        "failure_type": failure_type,
    }


def compute_original_query_ranks(
    session,
    run: EvaluationRun,
    results: list[EvaluationResult],
    cases: dict[uuid.UUID, EvaluationCase],
) -> dict[uuid.UUID, CandidateRanks]:
    settings = get_settings()
    retrieval_service = IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )
    top_k = int(run.parameters.get("top_k", 3))
    candidate_limit = int(run.parameters.get("candidate_limit", 20))
    rrf_k = int(run.parameters.get("rrf_k", 60))
    ranks: dict[uuid.UUID, CandidateRanks] = {}
    for result in results:
        if result.expected_no_result or result.expected_incident_id is None:
            continue
        case = cases[result.case_id]
        trace = retrieval_service.search_for_evaluation(
            query=result.original_query,
            top_k=top_k,
            candidate_limit=candidate_limit,
            rrf_k=rrf_k,
            project_name=case.project_name,
        )
        pseudo_candidates: list[EvaluationCandidate] = []
        for item in trace.vector_candidates + trace.bm25_candidates + trace.rrf_candidates:
            pseudo = EvaluationCandidate(
                evaluation_result_id=result.id,
                search_type=item.search_type,
                incident_id=item.incident_id,
                rank=item.rank,
                raw_score=item.raw_score,
                vector_score=item.vector_score,
                bm25_score=item.bm25_score,
                rrf_score=item.rrf_score,
            )
            pseudo_candidates.append(pseudo)
        ranks[result.id] = ranks_for(result, pseudo_candidates)
    return ranks


def score_ranges(
    results: list[EvaluationResult],
    candidates_by_result: dict[uuid.UUID, list[EvaluationCandidate]],
) -> dict[str, dict[str, float | int | None]]:
    buckets: dict[str, list[float]] = {
        "vector_score": [],
        "bm25_score": [],
        "rrf_score": [],
        "expected_vector_score": [],
        "expected_rrf_score": [],
    }
    for result in results:
        for candidate in candidates_by_result.get(result.id, []):
            if candidate.vector_score is not None:
                buckets["vector_score"].append(candidate.vector_score)
            if candidate.bm25_score is not None:
                buckets["bm25_score"].append(candidate.bm25_score)
            if candidate.rrf_score is not None:
                buckets["rrf_score"].append(candidate.rrf_score)
        ranks = ranks_for(result, candidates_by_result.get(result.id, []))
        if ranks.vector_score is not None:
            buckets["expected_vector_score"].append(ranks.vector_score)
        if ranks.rrf_score is not None:
            buckets["expected_rrf_score"].append(ranks.rrf_score)

    def describe(values: list[float]) -> dict[str, float | int | None]:
        if not values:
            return {"count": 0, "min": None, "max": None, "mean": None}
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }

    return {name: describe(values) for name, values in buckets.items()}


def simulate_threshold(
    threshold: float,
    results: list[EvaluationResult],
    candidates_by_result: dict[uuid.UUID, list[EvaluationCandidate]],
) -> dict[str, float | None]:
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    no_result = [result for result in results if result.expected_no_result]

    def accepted_top3(result: EvaluationResult) -> list[EvaluationCandidate]:
        top3 = [
            candidate
            for candidate in candidates_by_result.get(result.id, [])
            if candidate.search_type == "RRF" and candidate.rank <= 3
        ]
        accepted = []
        for candidate in top3:
            # 저장된 candidate만으로 LLM confidence 결과는 재구성할 수 없다.
            # 따라서 threshold simulation은 vector_score gate만 적용한다.
            if candidate.vector_score is not None and candidate.vector_score >= threshold:
                accepted.append(candidate)
        return sorted(accepted, key=lambda item: item.rank)

    top1_hits = 0
    answerable_hits = 0
    for result in answerable:
        accepted = accepted_top3(result)
        expected = result.expected_incident_id
        if any(candidate.incident_id == expected for candidate in accepted):
            answerable_hits += 1
            if accepted and accepted[0].incident_id == expected:
                top1_hits += 1

    no_result_correct = 0
    for result in no_result:
        if not accepted_top3(result):
            no_result_correct += 1

    return {
        "threshold": threshold,
        "answerable_recall": ratio(answerable_hits, len(answerable)),
        "final_top1_accuracy": ratio(top1_hits, len(answerable)),
        "no_result_accuracy": ratio(no_result_correct, len(no_result)),
    }


def write_markdown(payload: dict[str, Any]) -> None:
    metrics = payload["metrics"]
    failure_counts = payload["failure_counts"]
    ranges = payload["confidence_score_analysis"]["score_ranges"]
    simulation = payload["threshold_simulation"]
    lines = [
        "# Retrieval Evaluation Baseline 분석 리포트",
        "",
        f"- run_id: `{payload['run']['id']}`",
        f"- 전체 케이스 수: `{payload['run']['total_cases']}`",
        f"- 정답 존재 케이스 수: `{payload['case_counts']['answerable_cases']}`",
        f"- 정답 없음 케이스 수: `{payload['case_counts']['no_result_cases']}`",
        "",
        "## 지표",
        "",
        "| 단계 | Top1 | Top3 | MRR | answerable_recall | no_result_accuracy |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        (
            "| Confidence 적용 전 순수 Retrieval | "
            f"{metrics['pure_retrieval']['retrieval_top1_accuracy']:.3f} | "
            f"{metrics['pure_retrieval']['retrieval_top3_accuracy']:.3f} | "
            f"{metrics['pure_retrieval']['retrieval_mrr']:.3f} | "
            "n/a | n/a |"
        ),
        (
            "| Confidence 적용 후 최종 Pipeline | "
            f"{metrics['final_pipeline']['final_top1_accuracy']:.3f} | "
            f"{metrics['final_pipeline']['final_top3_accuracy']:.3f} | "
            f"{metrics['final_pipeline']['final_mrr']:.3f} | "
            f"{metrics['final_pipeline']['answerable_recall']:.3f} | "
            f"{metrics['final_pipeline']['no_result_accuracy']:.3f} |"
        ),
        "",
        "## 실패 유형 분류",
        "",
    ]
    for name in [
        "RETRIEVAL_MISS",
        "RRF_RANKING_MISS",
        "CONFIDENCE_REJECT",
        "QUERY_REWRITE_ISSUE",
        "EXECUTION_ERROR",
    ]:
        lines.append(f"- {name}: {failure_counts.get(name, 0)}")

    lines.extend(
        [
            "",
            "## Confidence 점수 분석",
            "",
            "- 현재 confidence filtering은 `rrf_score`가 아니라 `vector_score`를 입력 점수로 사용한다.",
            "- `vector_score = max(0.0, 1.0 - cosine_distance)`로 계산된다.",
            "- 현재 threshold는 vector high `>= 0.65`, vector reject `< 0.45`, LLM confidence reject `< 0.5`이다.",
            "- RRF score는 최종 `score`로 저장되지만 `_evaluate_confidence()`에는 `hit.vector_score`가 전달된다. 즉 RRF 점수를 confidence 확률처럼 직접 사용하지는 않는다.",
            "- 다만 RRF Top3 안에 들어온 많은 정답 후보의 vector_score가 `0.45`보다 낮아서 confidence 단계에서 제거된다.",
            "",
            "저장된 candidate 기준 점수 범위:",
            "",
            "| 점수 | 개수 | 최소 | 최대 | 평균 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, item in ranges.items():
        lines.append(
            f"| {name} | {item['count']} | "
            f"{_fmt(item['min'])} | {_fmt(item['max'])} | {_fmt(item['mean'])} |"
        )

    lines.extend(
        [
            "",
            "## Threshold 후보별 시뮬레이션",
            "",
            "이 시뮬레이션은 저장된 RRF Top3 candidate에 vector_score gate만 적용했다. 저장 데이터에는 candidate별 LLM confidence score가 없으므로 최종 pipeline의 완전한 재현은 아니다.",
            "",
            "| threshold | answerable_recall | final_top1_accuracy | no_result_accuracy |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for item in simulation:
        lines.append(
            f"| {item['threshold']:.2f} | "
            f"{_fmt(item['answerable_recall'])} | "
            f"{_fmt(item['final_top1_accuracy'])} | "
            f"{_fmt(item['no_result_accuracy'])} |"
        )

    lines.extend(
        [
            "",
            "## 실패 케이스",
            "",
            "| case_key | category | Vector | BM25 | RRF | abstained | failure_type |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in payload["failures"]:
        lines.append(
            f"| `{item['case_key']}` | {item['category']} | "
            f"{_rank_score(item['vector_rank'], item['vector_score'])} | "
            f"{_rank_score(item['bm25_rank'], item['bm25_score'])} | "
            f"{_rank_score(item['rrf_rank'], item['rrf_score'])}"
            f" (orig: {_rank_score(item['original_query_rrf_rank'], item['original_query_rrf_score'])}) | "
            f"{item['abstained']} | {item['failure_type']} |"
        )

    MD_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _rank_score(rank: int | None, score: float | None) -> str:
    if rank is None:
        return "n/a"
    return f"{rank} / {_fmt(score)}"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    session = SessionLocal()
    try:
        run = latest_completed_run(session)
        results, cases, candidates_by_result = load_run_data(session, run.id)
        answerable = [
            result
            for result in results
            if not result.expected_no_result and result.expected_incident_id is not None
        ]
        no_result = [result for result in results if result.expected_no_result]

        failures = []
        failure_counts: Counter[str] = Counter()
        original_query_ranks = compute_original_query_ranks(
            session,
            run,
            results,
            cases,
        )
        for result in results:
            case = cases[result.case_id]
            ranks = ranks_for(result, candidates_by_result.get(result.id, []))
            original_ranks = original_query_ranks.get(result.id)
            failure_type = classify_failure(result, ranks, original_ranks)
            if failure_type is not None:
                failure_counts[failure_type] += 1
                failures.append(
                    candidate_record(
                        result,
                        case,
                        ranks,
                        original_ranks,
                        failure_type,
                    )
                )

        payload = {
            "run": {
                "id": str(run.id),
                "run_name": run.run_name,
                "status": run.status,
                "total_cases": run.total_cases,
                "completed_cases": run.completed_cases,
                "parameters": run.parameters,
            },
            "case_counts": {
                "answerable_cases": len(answerable),
                "no_result_cases": len(no_result),
            },
            "metrics": {
                "pure_retrieval": compute_retrieval_metrics(
                    results,
                    candidates_by_result,
                ),
                "final_pipeline": compute_final_metrics(results),
            },
            "failure_counts": dict(failure_counts),
            "failures": failures,
            "query_rewrite_comparison": [
                {
                    "case_key": cases[result.case_id].case_key,
                    "original_query": result.original_query,
                    "rewritten_query": result.rewritten_query,
                    "original_query_rrf_rank": original_query_ranks[result.id].rrf_rank,
                    "rewritten_query_rrf_rank": ranks_for(
                        result,
                        candidates_by_result.get(result.id, []),
                    ).rrf_rank,
                    "declined": rank_declined(
                        before=original_query_ranks[result.id].rrf_rank,
                        after=ranks_for(
                            result,
                            candidates_by_result.get(result.id, []),
                        ).rrf_rank,
                    ),
                }
                for result in answerable
                if result.id in original_query_ranks
            ],
            "confidence_score_analysis": {
                "calculation": {
                    "input_score": "vector_score",
                    "vector_score_formula": "max(0.0, 1.0 - cosine_distance)",
                    "rrf_score_formula": "sum(1 / (rrf_k + rank))",
                    "uses_rrf_as_probability": False,
                    "current_thresholds": {
                        "high_confidence_score": HIGH_CONFIDENCE_SCORE,
                        "vector_min_score": CURRENT_VECTOR_MIN_SCORE,
                        "llm_min_confidence_score": LLM_MIN_CONFIDENCE_SCORE,
                    },
                    "compatibility": (
                        "The gate compares vector_score to 0.45/0.65. "
                        "Stored RRF scores are around 0.014-0.033 and are not "
                        "compatible with probability-like thresholds, but the current "
                        "code does not pass RRF score into confidence filtering."
                    ),
                },
                "score_ranges": score_ranges(results, candidates_by_result),
            },
            "threshold_simulation": [
                simulate_threshold(threshold, results, candidates_by_result)
                for threshold in THRESHOLD_CANDIDATES
            ],
        }
        JSON_REPORT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_markdown(payload)
        print(JSON_REPORT_PATH)
        print(MD_REPORT_PATH)
    finally:
        session.close()


if __name__ == "__main__":
    main()
