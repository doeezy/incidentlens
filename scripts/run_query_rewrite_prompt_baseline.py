from __future__ import annotations

import json
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents.incident_agent import IncidentAnswerAgent
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models.evaluation import EvaluationCandidate, EvaluationCase, EvaluationResult, EvaluationRun
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.evaluation import EvaluationRunCreate
from app.services.evaluation import EvaluationService
from app.services.retrieval import IncidentRetrievalService


PREVIOUS_REPORT_PATH = ROOT_DIR / "docs" / "evaluation" / "enriched_seed_baseline_v1.json"
REPORT_JSON_PATH = ROOT_DIR / "docs" / "evaluation" / "query_rewrite_prompt_v2_baseline.json"
REPORT_MD_PATH = ROOT_DIR / "docs" / "evaluation" / "query_rewrite_prompt_v2_baseline.md"

RUN_NAME = "query_rewrite_prompt_v2_baseline"
TOP_K = 3
CANDIDATE_LIMIT = 20
RRF_K = 60
SPECIAL_QUERY = "배치 컨테이너가 메모리 제한 때문에 비정상 종료된 장애 요약해줘"


@dataclass(frozen=True)
class Ranks:
    vector_rank: int | None
    vector_score: float | None
    bm25_rank: int | None
    bm25_score: float | None
    rrf_rank: int | None
    rrf_score: float | None


def ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def reciprocal_rank(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def run_baseline(session) -> EvaluationRun:
    settings = get_settings()
    retrieval_service = IncidentRetrievalService.from_session(
        session=session,
        settings=settings,
    )
    query_agent = IncidentAnswerAgent(
        settings=settings,
        retrieval_service=retrieval_service,
    )
    service = EvaluationService(
        settings=settings,
        repository=EvaluationRepository(session),
        query_agent=query_agent,
        retrieval_service=retrieval_service,
    )
    detail = service.run(
        EvaluationRunCreate(
            run_name=RUN_NAME,
            top_k=TOP_K,
            candidate_limit=CANDIDATE_LIMIT,
            rrf_k=RRF_K,
        )
    )
    run = session.get(EvaluationRun, detail.id)
    if run is None:
        raise RuntimeError(f"created evaluation run not found: {detail.id}")
    return run


def load_previous_run_id() -> uuid.UUID:
    payload = json.loads(PREVIOUS_REPORT_PATH.read_text(encoding="utf-8"))
    return uuid.UUID(payload["run"]["id"])


def load_run_data(session, run_id: uuid.UUID):
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise RuntimeError(f"evaluation run not found: {run_id}")

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
            EvaluationCandidate.evaluation_result_id.in_([result.id for result in results])
        )
    ).all()

    candidates_by_result: dict[uuid.UUID, list[EvaluationCandidate]] = defaultdict(list)
    for candidate in candidates:
        candidates_by_result[candidate.evaluation_result_id].append(candidate)

    results_by_case_key = {
        cases[result.case_id].case_key: result
        for result in results
        if result.case_id in cases
    }
    candidates_by_case_key = {
        cases[result.case_id].case_key: candidates_by_result.get(result.id, [])
        for result in results
        if result.case_id in cases
    }
    cases_by_case_key = {case.case_key: case for case in cases.values()}
    return run, results_by_case_key, candidates_by_case_key, cases_by_case_key


def ranks_for(result: EvaluationResult, candidates: list[EvaluationCandidate]) -> Ranks:
    expected_id = result.expected_incident_id
    if expected_id is None:
        return Ranks(None, None, None, None, None, None)

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
    return Ranks(
        vector_rank=vector.rank if vector else None,
        vector_score=vector.vector_score if vector else None,
        bm25_rank=bm25.rank if bm25 else None,
        bm25_score=bm25.bm25_score if bm25 else None,
        rrf_rank=rrf.rank if rrf else None,
        rrf_score=rrf.rrf_score if rrf else None,
    )


def compute_metrics(
    results_by_case_key: dict[str, EvaluationResult],
    candidates_by_case_key: dict[str, list[EvaluationCandidate]],
) -> dict[str, float | None]:
    results = list(results_by_case_key.values())
    answerable = [
        result
        for result in results
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    no_result = [result for result in results if result.expected_no_result]
    retrieval_ranks = [
        ranks_for(result, candidates_by_case_key.get(case_key, [])).rrf_rank
        for case_key, result in results_by_case_key.items()
        if not result.expected_no_result and result.expected_incident_id is not None
    ]
    latencies = [
        result.total_latency_ms
        for result in results
        if result.total_latency_ms is not None
    ]
    return {
        "retrieval_top1_accuracy": ratio(
            sum(1 for rank in retrieval_ranks if rank == 1), len(answerable)
        ),
        "retrieval_top3_accuracy": ratio(
            sum(1 for rank in retrieval_ranks if rank is not None and rank <= 3),
            len(answerable),
        ),
        "retrieval_mrr": ratio(
            sum(reciprocal_rank(rank) for rank in retrieval_ranks),
            len(answerable),
        ),
        "final_top1_accuracy": ratio(
            sum(1 for result in answerable if result.top1_hit), len(answerable)
        ),
        "final_top3_accuracy": ratio(
            sum(1 for result in answerable if result.top3_hit), len(answerable)
        ),
        "final_mrr": ratio(
            sum(result.reciprocal_rank for result in answerable), len(answerable)
        ),
        "no_result_accuracy": ratio(
            sum(1 for result in no_result if result.no_result_correct), len(no_result)
        ),
        "abstain_ratio": ratio(sum(1 for result in results if result.abstained), len(results)),
        "mean_latency_ms": ratio(sum(latencies), len(latencies)),
    }


def performance_key(result: EvaluationResult) -> tuple[int, int]:
    if result.expected_no_result:
        return (0, 0) if result.no_result_correct else (1, 999)
    if result.expected_rank is None:
        return (1, 999)
    return (0, result.expected_rank)


def final_status(result: EvaluationResult) -> str:
    if result.error_message:
        return "error"
    if result.expected_no_result:
        return "no_result_correct" if result.no_result_correct else "false_positive"
    if result.expected_rank is None:
        return "miss"
    if result.expected_rank == 1:
        return "top1"
    if result.expected_rank <= 3:
        return "top3"
    return f"rank{result.expected_rank}"


def compare_case(
    *,
    previous: EvaluationResult,
    current: EvaluationResult,
    previous_candidates: list[EvaluationCandidate],
    current_candidates: list[EvaluationCandidate],
) -> dict[str, Any]:
    previous_ranks = ranks_for(previous, previous_candidates)
    current_ranks = ranks_for(current, current_candidates)
    previous_key = performance_key(previous)
    current_key = performance_key(current)
    if current_key < previous_key:
        change = "improved"
    elif current_key > previous_key:
        change = "regressed"
    else:
        change = "same"
    return {
        "case_key": None,
        "original_query": current.original_query,
        "previous_rewritten_query": previous.rewritten_query,
        "current_rewritten_query": current.rewritten_query,
        "previous_rrf_rank": previous_ranks.rrf_rank,
        "current_rrf_rank": current_ranks.rrf_rank,
        "previous_final_rank": previous.expected_rank,
        "current_final_rank": current.expected_rank,
        "previous_final_status": final_status(previous),
        "current_final_status": final_status(current),
        "previous_abstained": previous.abstained,
        "current_abstained": current.abstained,
        "change": change,
    }


def build_payload(session, previous_run_id: uuid.UUID, current_run_id: uuid.UUID) -> dict[str, Any]:
    (
        previous_run,
        previous_results,
        previous_candidates,
        previous_cases,
    ) = load_run_data(session, previous_run_id)
    current_run, current_results, current_candidates, current_cases = load_run_data(
        session, current_run_id
    )
    if set(previous_results) != set(current_results):
        raise RuntimeError("previous/current evaluation case sets differ")

    comparisons = []
    special_comparison = None
    for case_key in sorted(current_results):
        comparison = compare_case(
            previous=previous_results[case_key],
            current=current_results[case_key],
            previous_candidates=previous_candidates.get(case_key, []),
            current_candidates=current_candidates.get(case_key, []),
        )
        comparison["case_key"] = case_key
        comparisons.append(comparison)
        if current_results[case_key].original_query == SPECIAL_QUERY:
            special_comparison = comparison

    change_counts = Counter(item["change"] for item in comparisons)
    rewrite_changed = [
        item
        for item in comparisons
        if item["previous_rewritten_query"] != item["current_rewritten_query"]
    ]
    rrf_rank_changed = [
        item
        for item in comparisons
        if item["previous_rrf_rank"] != item["current_rrf_rank"]
    ]

    current_parameters = current_run.parameters or {}
    previous_parameters = previous_run.parameters or {}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "query_rewrite_prompt_v2_effect_only",
        "constraints": {
            "evaluation_dataset_changed": False,
            "seed_data_changed": False,
            "retrieval_logic_changed": False,
            "bm25_vector_rrf_confidence_changed": False,
        },
        "previous_run": {
            "id": str(previous_run.id),
            "run_name": previous_run.run_name,
            "parameters": {
                "top_k": previous_parameters.get("top_k"),
                "candidate_limit": previous_parameters.get("candidate_limit"),
                "rrf_k": previous_parameters.get("rrf_k"),
            },
        },
        "current_run": {
            "id": str(current_run.id),
            "run_name": current_run.run_name,
            "parameters": {
                "top_k": current_parameters.get("top_k"),
                "candidate_limit": current_parameters.get("candidate_limit"),
                "rrf_k": current_parameters.get("rrf_k"),
            },
            "confidence_telemetry": current_parameters.get("confidence_telemetry", {}),
        },
        "case_count": len(current_results),
        "category_distribution": dict(
            Counter(case.category for case in current_cases.values())
        ),
        "previous_metrics": compute_metrics(previous_results, previous_candidates),
        "current_metrics": compute_metrics(current_results, current_candidates),
        "change_counts": dict(change_counts),
        "rewrite_changed_count": len(rewrite_changed),
        "rrf_rank_changed_count": len(rrf_rank_changed),
        "special_case": special_comparison,
        "improved_cases": [item for item in comparisons if item["change"] == "improved"],
        "same_cases": [item for item in comparisons if item["change"] == "same"],
        "regressed_cases": [item for item in comparisons if item["change"] == "regressed"],
        "rewrite_changed_cases": rewrite_changed,
        "rrf_rank_changed_cases": rrf_rank_changed,
    }


def metric_delta(previous: float | None, current: float | None) -> str:
    if previous is None or current is None:
        return "n/a"
    return f"{current - previous:+.3f}"


def write_report(payload: dict[str, Any]) -> None:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    previous_metrics = payload["previous_metrics"]
    current_metrics = payload["current_metrics"]
    special = payload["special_case"]
    lines = [
        "# Query Rewrite Prompt v2 Baseline",
        "",
        "Query Rewrite 프롬프트 변경 효과만 확인하기 위한 재실행 결과다. Evaluation Dataset, seed 데이터, BM25, Vector, RRF, Confidence 로직은 변경하지 않았다.",
        "",
        "## Run 설정",
        "",
        f"- previous_run_id: `{payload['previous_run']['id']}`",
        f"- current_run_id: `{payload['current_run']['id']}`",
        f"- top_k: `{payload['current_run']['parameters']['top_k']}`",
        f"- candidate_limit: `{payload['current_run']['parameters']['candidate_limit']}`",
        f"- rrf_k: `{payload['current_run']['parameters']['rrf_k']}`",
        f"- case_count: `{payload['case_count']}`",
        "",
        "## Metrics 비교",
        "",
        "| metric | previous | current | delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric in [
        "retrieval_top1_accuracy",
        "retrieval_top3_accuracy",
        "retrieval_mrr",
        "final_top1_accuracy",
        "final_top3_accuracy",
        "final_mrr",
        "no_result_accuracy",
        "abstain_ratio",
        "mean_latency_ms",
    ]:
        lines.append(
            f"| {metric} | {fmt(previous_metrics.get(metric))} | "
            f"{fmt(current_metrics.get(metric))} | "
            f"{metric_delta(previous_metrics.get(metric), current_metrics.get(metric))} |"
        )

    lines.extend(
        [
            "",
            "## 지정 Case 비교",
            "",
            f"- original query: `{SPECIAL_QUERY}`",
            f"- 이전 rewritten_query: `{special['previous_rewritten_query'] if special else 'n/a'}`",
            f"- 현재 rewritten_query: `{special['current_rewritten_query'] if special else 'n/a'}`",
            f"- 이전 RRF rank: `{special['previous_rrf_rank'] if special else 'n/a'}`",
            f"- 현재 RRF rank: `{special['current_rrf_rank'] if special else 'n/a'}`",
            f"- 이전 최종 상태: `{special['previous_final_status'] if special else 'n/a'}`",
            f"- 현재 최종 상태: `{special['current_final_status'] if special else 'n/a'}`",
            f"- 변화: `{special['change'] if special else 'n/a'}`",
            "",
            "## Case 변화 요약",
            "",
            f"- 개선된 Case: `{payload['change_counts'].get('improved', 0)}`",
            f"- 동일한 Case: `{payload['change_counts'].get('same', 0)}`",
            f"- 하락한 Case: `{payload['change_counts'].get('regressed', 0)}`",
            f"- rewritten_query가 바뀐 Case: `{payload['rewrite_changed_count']}`",
            f"- RRF rank가 바뀐 Case: `{payload['rrf_rank_changed_count']}`",
            "",
        ]
    )

    for title, key in [
        ("개선된 Case", "improved_cases"),
        ("하락한 Case", "regressed_cases"),
        ("rewritten_query 변경 Case", "rewrite_changed_cases"),
        ("RRF rank 변경 Case", "rrf_rank_changed_cases"),
    ]:
        lines.extend(
            [
                f"## {title}",
                "",
                "| case_key | previous rewrite | current rewrite | previous RRF | current RRF | previous final | current final |",
                "| --- | --- | --- | ---: | ---: | --- | --- |",
            ]
        )
        rows = payload[key]
        if not rows:
            lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
        else:
            for item in rows:
                lines.append(
                    f"| `{item['case_key']}` | {item['previous_rewritten_query']} | "
                    f"{item['current_rewritten_query']} | {fmt(item['previous_rrf_rank'])} | "
                    f"{fmt(item['current_rrf_rank'])} | {item['previous_final_status']} | "
                    f"{item['current_final_status']} |"
                )
        lines.append("")

    REPORT_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    init_db()
    previous_run_id = load_previous_run_id()
    session = SessionLocal()
    try:
        current_run = run_baseline(session)
        payload = build_payload(session, previous_run_id, current_run.id)
        write_report(payload)
        print("REPORT_JSON", REPORT_JSON_PATH)
        print("REPORT_MD", REPORT_MD_PATH)
        print(json.dumps(payload["current_metrics"], ensure_ascii=False, indent=2))
        print(json.dumps(payload["change_counts"], ensure_ascii=False, indent=2))
        print(json.dumps(payload["special_case"], ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
