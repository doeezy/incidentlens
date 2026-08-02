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
from app.models.evaluation import (
    EvaluationCandidate,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
)
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.evaluation import EvaluationRunCreate
from app.services.evaluation import EvaluationService
from app.services.retrieval import IncidentRetrievalService


PREVIOUS_REPORT_PATH = (
    ROOT_DIR / "docs" / "evaluation" / "batch_multi_candidate_confidence_baseline_v1.json"
)
REPORT_JSON_PATH = ROOT_DIR / "docs" / "evaluation" / "batch_confidence_compact_v1.json"
REPORT_MD_PATH = ROOT_DIR / "docs" / "evaluation" / "batch_confidence_compact_v1.md"

RUN_NAME = "batch_confidence_compact_v1"
PREVIOUS_RUN_KEY = "batch_multi_candidate_confidence_baseline"
TOP_K = 3
CANDIDATE_LIMIT = 20
RRF_K = 60


@dataclass(frozen=True)
class Ranks:
    vector_rank: int | None
    bm25_rank: int | None
    rrf_rank: int | None


def ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def reciprocal_rank(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * p) + 0.999999) - 1))
    return ordered[index]


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def metric_delta(previous: float | None, current: float | None) -> str:
    if previous is None or current is None:
        return "n/a"
    return f"{current - previous:+.3f}"


def percent_delta(previous: float | None, current: float | None) -> str:
    if previous is None or current is None or previous == 0:
        return "n/a"
    return f"{((current - previous) / previous) * 100.0:+.1f}%"


def load_previous_run_id() -> uuid.UUID:
    payload = json.loads(PREVIOUS_REPORT_PATH.read_text(encoding="utf-8"))
    return uuid.UUID(payload["runs"][PREVIOUS_RUN_KEY]["run_id"])


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
            EvaluationCandidate.evaluation_result_id.in_(
                [result.id for result in results]
            )
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
        return Ranks(None, None, None)

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
        bm25_rank=bm25.rank if bm25 else None,
        rrf_rank=rrf.rank if rrf else None,
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
        "abstain_ratio": ratio(
            sum(1 for result in results if result.abstained), len(results)
        ),
        "mean_latency_ms": ratio(sum(latencies), len(latencies)),
        "p95_latency_ms": percentile(latencies, 0.95),
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
        "rewritten_query": current.rewritten_query,
        "previous_vector_rank": previous_ranks.vector_rank,
        "current_vector_rank": current_ranks.vector_rank,
        "previous_bm25_rank": previous_ranks.bm25_rank,
        "current_bm25_rank": current_ranks.bm25_rank,
        "previous_rrf_rank": previous_ranks.rrf_rank,
        "current_rrf_rank": current_ranks.rrf_rank,
        "previous_final_rank": previous.expected_rank,
        "current_final_rank": current.expected_rank,
        "previous_confidence": previous.confidence,
        "current_confidence": current.confidence,
        "previous_final_status": final_status(previous),
        "current_final_status": final_status(current),
        "previous_abstained": previous.abstained,
        "current_abstained": current.abstained,
        "change": change,
    }


def telemetry(run: EvaluationRun) -> dict[str, Any]:
    return (run.parameters or {}).get("confidence_telemetry", {})


def telemetry_rejected_count(data: dict[str, Any]) -> int | None:
    evaluated = data.get("evaluated_candidates")
    passed = data.get("passed_candidates")
    if evaluated is None or passed is None:
        return None
    return int(evaluated) - int(passed)


def build_payload(
    session,
    previous_run_id: uuid.UUID,
    current_run_id: uuid.UUID,
) -> dict[str, Any]:
    (
        previous_run,
        previous_results,
        previous_candidates,
        previous_cases,
    ) = load_run_data(session, previous_run_id)
    current_run, current_results, current_candidates, current_cases = load_run_data(
        session,
        current_run_id,
    )
    if set(previous_results) != set(current_results):
        raise RuntimeError("previous/current evaluation case sets differ")

    comparisons = []
    for case_key in sorted(current_results):
        comparison = compare_case(
            previous=previous_results[case_key],
            current=current_results[case_key],
            previous_candidates=previous_candidates.get(case_key, []),
            current_candidates=current_candidates.get(case_key, []),
        )
        comparison["case_key"] = case_key
        comparisons.append(comparison)

    previous_telemetry = telemetry(previous_run)
    current_telemetry = telemetry(current_run)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "batch_confidence_prompt_payload_compact_v1",
        "constraints": {
            "query_analyzer_changed": False,
            "vector_changed": False,
            "bm25_changed": False,
            "rrf_changed": False,
            "evaluation_dataset_changed": False,
            "seed_data_changed": False,
            "model_changed": False,
            "confidence_judgement_policy_changed": False,
            "confidence_payload_compacted": True,
        },
        "previous_run": {
            "id": str(previous_run.id),
            "run_name": previous_run.run_name,
            "retrieval_version": previous_run.retrieval_version,
            "parameters": {
                "top_k": (previous_run.parameters or {}).get("top_k"),
                "candidate_limit": (previous_run.parameters or {}).get(
                    "candidate_limit"
                ),
                "rrf_k": (previous_run.parameters or {}).get("rrf_k"),
            },
            "confidence_telemetry": previous_telemetry,
        },
        "current_run": {
            "id": str(current_run.id),
            "run_name": current_run.run_name,
            "retrieval_version": current_run.retrieval_version,
            "parameters": {
                "top_k": (current_run.parameters or {}).get("top_k"),
                "candidate_limit": (current_run.parameters or {}).get("candidate_limit"),
                "rrf_k": (current_run.parameters or {}).get("rrf_k"),
            },
            "confidence_telemetry": current_telemetry,
        },
        "case_count": len(current_results),
        "category_distribution": dict(
            Counter(case.category for case in current_cases.values())
        ),
        "previous_metrics": compute_metrics(previous_results, previous_candidates),
        "current_metrics": compute_metrics(current_results, current_candidates),
        "previous_rejected_candidates": telemetry_rejected_count(previous_telemetry),
        "current_rejected_candidates": telemetry_rejected_count(current_telemetry),
        "change_counts": dict(Counter(item["change"] for item in comparisons)),
        "improved_cases": [item for item in comparisons if item["change"] == "improved"],
        "same_cases": [item for item in comparisons if item["change"] == "same"],
        "regressed_cases": [item for item in comparisons if item["change"] == "regressed"],
    }


def write_report(payload: dict[str, Any]) -> None:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    previous_metrics = payload["previous_metrics"]
    current_metrics = payload["current_metrics"]
    previous_telemetry = payload["previous_run"]["confidence_telemetry"]
    current_telemetry = payload["current_run"]["confidence_telemetry"]

    lines = [
        "# Batch Confidence Compact v1",
        "",
        "Batch Multi-Candidate Confidence는 유지하고 prompt payload만 줄인 실험 결과다. Query Analyzer, Vector, BM25, RRF, Evaluation Dataset, Seed 데이터, 모델은 변경하지 않았다.",
        "",
        "## Compact 변경",
        "",
        "- 후보별 점수(`vector_score`, `bm25_score`, `rrf_score`)는 prompt에서 제거했다. 최종 응답과 evaluation trace에는 기존처럼 저장한다.",
        "- 후보별 입력은 `incident_id`, `rrf`, `vec`, `bm25`, `type`, `msg`, `summary` 중심으로 제한했다.",
        "- `ROOT_CAUSE`는 `cause`, `root`, 구분 단서용 `keywords`, `tags`만 추가한다.",
        "- `RESOLUTION`은 `resolution`만 추가한다.",
        "- `SIMILAR_CASE`는 `keywords`, `tags`만 최대 5개씩 추가한다.",
        "- `SUMMARY`는 `summary` 중심이며, 구분 단서용 `keywords`, `tags`, 짧은 원인/해결 문맥만 추가한다.",
        "- null, 빈 문자열, 빈 배열은 prompt에서 제거한다.",
        "- summary/cause/resolution 계열 텍스트는 지정 길이로 잘라 전송한다.",
        "- Batch 판단 기준, ranking 적용, should_include 처리, fallback 정책은 변경하지 않았다.",
        "",
        "## Run 설정",
        "",
        f"- previous batch run: `{payload['previous_run']['id']}`",
        f"- compact run: `{payload['current_run']['id']}`",
        f"- top_k: `{payload['current_run']['parameters']['top_k']}`",
        f"- candidate_limit: `{payload['current_run']['parameters']['candidate_limit']}`",
        f"- rrf_k: `{payload['current_run']['parameters']['rrf_k']}`",
        f"- case_count: `{payload['case_count']}`",
        "",
        "## Metrics 비교",
        "",
        "| metric | batch baseline | compact | delta |",
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
        "p95_latency_ms",
    ]:
        lines.append(
            f"| {metric} | {fmt(previous_metrics.get(metric))} | "
            f"{fmt(current_metrics.get(metric))} | "
            f"{metric_delta(previous_metrics.get(metric), current_metrics.get(metric))} |"
        )

    lines.extend(
        [
            "",
            "## Confidence Telemetry 비교",
            "",
            "| metric | batch baseline | compact | delta |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    telemetry_rows = [
        ("llm_calls", "llm_calls"),
        ("avg_llm_calls_per_case", "avg_llm_calls_per_case"),
        ("batch_llm_calls", "batch_llm_calls"),
        ("individual_llm_calls", "individual_llm_calls"),
        ("fallback_executions", "fallback_executions"),
        ("llm_failures", "llm_failures"),
        ("evaluated_candidates", "evaluated_candidates"),
        ("passed_candidates", "passed_candidates"),
        ("rejected_candidates", None),
        ("avg_prompt_input_tokens", "avg_prompt_input_tokens"),
        ("avg_output_tokens", "avg_output_tokens"),
        ("token_observations", "token_observations"),
    ]
    for label, key in telemetry_rows:
        if key is None:
            previous = payload["previous_rejected_candidates"]
            current = payload["current_rejected_candidates"]
        else:
            previous = previous_telemetry.get(key)
            current = current_telemetry.get(key)
        lines.append(
            f"| {label} | {fmt(previous)} | {fmt(current)} | "
            f"{metric_delta(previous, current)} |"
        )

    latency_change = percent_delta(
        previous_metrics.get("mean_latency_ms"),
        current_metrics.get("mean_latency_ms"),
    )
    call_change = percent_delta(
        previous_telemetry.get("llm_calls"),
        current_telemetry.get("llm_calls"),
    )
    lines.extend(
        [
            "",
            "## 변화 요약",
            "",
            f"- final_top1_accuracy 변화: `{metric_delta(previous_metrics.get('final_top1_accuracy'), current_metrics.get('final_top1_accuracy'))}`",
            f"- final_top3_accuracy 변화: `{metric_delta(previous_metrics.get('final_top3_accuracy'), current_metrics.get('final_top3_accuracy'))}`",
            f"- no_result_accuracy 변화: `{metric_delta(previous_metrics.get('no_result_accuracy'), current_metrics.get('no_result_accuracy'))}`",
            f"- mean_latency_ms 변화율: `{latency_change}`",
            f"- LLM 호출 수 변화율: `{call_change}`",
            f"- fallback 실행 수: `{fmt(current_telemetry.get('fallback_executions'))}`",
            "",
            "이전 batch baseline에는 OpenAI usage token telemetry가 저장되어 있지 않아 실제 변경 전 token 수는 `n/a`로 둔다. compact run부터 `avg_prompt_input_tokens`, `avg_output_tokens`, `token_observations`를 실제 OpenAI usage 값으로 저장한다.",
            "",
            "## Case 변화",
            "",
            f"- 개선된 Case: `{payload['change_counts'].get('improved', 0)}`",
            f"- 동일한 Case: `{payload['change_counts'].get('same', 0)}`",
            f"- 하락한 Case: `{payload['change_counts'].get('regressed', 0)}`",
            "",
        ]
    )

    for title, key in [
        ("개선된 Case", "improved_cases"),
        ("하락한 Case", "regressed_cases"),
    ]:
        lines.extend(
            [
                f"## {title}",
                "",
                "| case_key | previous final | compact final | previous confidence | compact confidence | vector rank | BM25 rank | RRF rank | query |",
                "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        rows = payload[key]
        if not rows:
            lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
        else:
            for item in rows:
                lines.append(
                    f"| `{item['case_key']}` | {item['previous_final_status']} | "
                    f"{item['current_final_status']} | {item['previous_confidence']} | "
                    f"{item['current_confidence']} | {fmt(item['current_vector_rank'])} | "
                    f"{fmt(item['current_bm25_rank'])} | {fmt(item['current_rrf_rank'])} | "
                    f"{item['original_query']} |"
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
        print(json.dumps(payload["current_run"]["confidence_telemetry"], ensure_ascii=False, indent=2))
        print(json.dumps(payload["change_counts"], ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
