from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.incident import Incident
from app.services.retrieval import IncidentRetrievalService, RetrievalStageCandidate
from evaluation.common import utc_now_iso, write_json

QUERY_TYPES = (
    "exact_error",
    "error_type_only",
    "natural_language",
    "cause_keyword",
    "ambiguous",
)


def run_query_rewrite_ablation_experiment(
    *,
    session: Session,
    settings: Settings,
    baseline_cases_path: Path = Path("evaluation_result/retrieval_cases.json"),
    baseline_metrics_path: Path = Path("evaluation_result/retrieval_metrics.json"),
    output_dir: Path = Path("evaluation_result"),
) -> dict[str, Any]:
    baseline_cases = json.loads(baseline_cases_path.read_text(encoding="utf-8"))
    baseline_metrics = json.loads(baseline_metrics_path.read_text(encoding="utf-8"))
    r1_cases = baseline_cases["hybrid"]
    params = baseline_metrics["parameters"]
    top_k = int(params["top_k"])
    candidate_limit = int(params["candidate_limit"])
    rrf_k = int(params["rrf_k"])

    incident_lookup = _load_incident_lookup(session)
    service = IncidentRetrievalService.from_session(session=session, settings=settings)
    r0_cases = [
        _run_original_query_case(
            service=service,
            r1_case=case,
            incident_lookup=incident_lookup,
            top_k=top_k,
            candidate_limit=candidate_limit,
            rrf_k=rrf_k,
        )
        for case in r1_cases
    ]
    normalized_r1_cases = [_normalize_r1_case(case) for case in r1_cases]
    experiment_cases = {"R0": r0_cases, "R1": normalized_r1_cases}
    analysis = _build_analysis(r0_cases=r0_cases, r1_cases=normalized_r1_cases)
    metrics = {
        "experiment": "query_rewrite_ablation",
        "generated_at": utc_now_iso(),
        "baseline_files": {
            "retrieval_cases": str(baseline_cases_path),
            "retrieval_metrics": str(baseline_metrics_path),
        },
        "dataset": baseline_metrics["dataset"],
        "parameters": {
            **params,
            "retrieval": "Hybrid Equal Weight RRF",
            "weighted_rrf": False,
            "reranker": False,
            "r0": "Query Analyzer output observed, but retrieval uses original query text.",
            "r1": "Query Analyzer rewritten_query is used for retrieval.",
            "latency_note": (
                "The current IncidentAnswerAgent produces intent and rewritten_query in one "
                "Query Analyzer LLM call, so rewrite latency cannot be isolated from analyzer "
                "latency without changing the production prompt."
            ),
        },
        "overall": {
            "R0": _metrics(r0_cases),
            "R1": _metrics(normalized_r1_cases),
        },
        "by_query_type": {
            "R0": _metrics_by_query_type(r0_cases),
            "R1": _metrics_by_query_type(normalized_r1_cases),
        },
        "latency": {
            "R0": _latency_metrics(r0_cases),
            "R1": _latency_metrics(normalized_r1_cases),
            "rewrite_latency_isolated": None,
            "rewrite_latency_note": (
                "Not separately measurable in current implementation because Query Analyzer "
                "and Query Rewrite are bundled in one LLM call."
            ),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "query_rewrite_ablation_metrics.json", metrics)
    write_json(
        output_dir / "query_rewrite_ablation_cases.json",
        {
            "analysis": analysis,
            "cases": experiment_cases,
        },
    )
    _write_summary(
        output_dir / "query_rewrite_ablation_summary.md",
        metrics=metrics,
        analysis=analysis,
    )
    return {"metrics": metrics, "analysis": analysis, "cases": experiment_cases}


def _run_original_query_case(
    *,
    service: IncidentRetrievalService,
    r1_case: dict[str, Any],
    incident_lookup: dict[str, dict[str, Any]],
    top_k: int,
    candidate_limit: int,
    rrf_k: int,
) -> dict[str, Any]:
    started = perf_counter()
    candidates = service.search_hybrid_candidates_for_evaluation(
        query=r1_case["query"],
        limit=candidate_limit,
        candidate_limit=candidate_limit,
        rrf_k=rrf_k,
        project_name=r1_case["project_name"],
    )
    retrieval_latency_ms = (perf_counter() - started) * 1000.0
    results = [
        _candidate_payload(candidate, incident_lookup=incident_lookup)
        for candidate in candidates
    ]
    expected_rank = _rank_of(r1_case["expected_incident_id"], results)
    top_result = results[0] if results else None
    analyzer_latency = r1_case.get("query_analyzer_latency_ms")
    return {
        "experiment_group": "R0",
        "query_id": r1_case["query_id"],
        "query": r1_case["query"],
        "original_query": r1_case["query"],
        "rewritten_query": r1_case["rewritten_query"],
        "retrieval_query": r1_case["query"],
        "query_type": r1_case["query_type"],
        "project_name": r1_case["project_name"],
        "expected_incident_id": r1_case["expected_incident_id"],
        "expected_incident": r1_case.get("expected_incident"),
        "intent": r1_case.get("intent"),
        "analysis_reason": r1_case.get("analysis_reason"),
        "expected_rank": expected_rank,
        "top1_hit": expected_rank == 1,
        "recall_at_3": expected_rank is not None and expected_rank <= 3,
        "recall_at_5": expected_rank is not None and expected_rank <= 5,
        "reciprocal_rank": (1.0 / expected_rank) if expected_rank else 0.0,
        "query_analyzer_latency_ms": analyzer_latency,
        "rewrite_latency_ms": None,
        "retrieval_latency_ms": retrieval_latency_ms,
        "total_latency_ms": (
            float(analyzer_latency) + retrieval_latency_ms
            if analyzer_latency is not None
            else retrieval_latency_ms
        ),
        "results": results,
        "top_retrieved_incident_id": top_result["incident_id"] if top_result else None,
        "top_retrieved_incident": top_result.get("incident") if top_result else None,
    }


def _normalize_r1_case(case: dict[str, Any]) -> dict[str, Any]:
    analyzer_latency = case.get("query_analyzer_latency_ms")
    retrieval_latency = case.get("latency_ms")
    return {
        "experiment_group": "R1",
        "query_id": case["query_id"],
        "query": case["query"],
        "original_query": case["query"],
        "rewritten_query": case["rewritten_query"],
        "retrieval_query": case["rewritten_query"],
        "query_type": case["query_type"],
        "project_name": case["project_name"],
        "expected_incident_id": case["expected_incident_id"],
        "expected_incident": case.get("expected_incident"),
        "intent": case.get("intent"),
        "analysis_reason": case.get("analysis_reason"),
        "expected_rank": case.get("expected_rank"),
        "top1_hit": case.get("expected_rank") == 1,
        "recall_at_3": case.get("expected_rank") is not None and case.get("expected_rank") <= 3,
        "recall_at_5": case.get("expected_rank") is not None and case.get("expected_rank") <= 5,
        "reciprocal_rank": case.get("reciprocal_rank", 0.0),
        "query_analyzer_latency_ms": analyzer_latency,
        "rewrite_latency_ms": None,
        "retrieval_latency_ms": retrieval_latency,
        "total_latency_ms": (
            float(analyzer_latency) + float(retrieval_latency)
            if analyzer_latency is not None and retrieval_latency is not None
            else retrieval_latency
        ),
        "results": case.get("results", []),
        "top_retrieved_incident_id": case.get("top_retrieved_incident_id"),
        "top_retrieved_incident": case.get("top_retrieved_incident"),
    }


def _candidate_payload(
    candidate: RetrievalStageCandidate,
    *,
    incident_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    incident_id = str(candidate.incident_id)
    return {
        "incident_id": incident_id,
        "rank": candidate.rank,
        "raw_score": candidate.raw_score,
        "vector_score": candidate.vector_score,
        "bm25_score": candidate.bm25_score,
        "rrf_score": candidate.rrf_score,
        "incident": incident_lookup.get(incident_id),
    }


def _load_incident_lookup(session: Session) -> dict[str, dict[str, Any]]:
    incidents = session.scalars(select(Incident).order_by(Incident.project_name, Incident.id)).all()
    return {str(incident.id): _incident_summary(incident) for incident in incidents}


def _incident_summary(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": str(incident.id),
        "project_name": incident.project_name,
        "module_name": incident.module_name,
        "class_name": incident.class_name,
        "method_name": incident.method_name,
        "summary": incident.primary_error_summary,
        "error_type": incident.primary_error_type,
        "error_message": incident.primary_error_message,
        "keywords": incident.error_keywords or [],
        "domain_tags": incident.domain_tags or [],
        "root_cause": incident.root_cause_summary,
        "resolution": incident.resolution_summary,
    }


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(cases)
    return {
        "query_count": count,
        "top1_accuracy": _ratio(sum(1 for case in cases if case["top1_hit"]), count),
        "recall_at_3": _ratio(sum(1 for case in cases if case["recall_at_3"]), count),
        "recall_at_5": _ratio(sum(1 for case in cases if case["recall_at_5"]), count),
        "mrr": _ratio(sum(float(case["reciprocal_rank"]) for case in cases), count),
        "average_retrieval_latency_ms": _mean([case.get("retrieval_latency_ms") for case in cases]),
        "average_total_latency_ms": _mean([case.get("total_latency_ms") for case in cases]),
    }


def _metrics_by_query_type(cases: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["query_type"]].append(case)
    return {query_type: _metrics(grouped.get(query_type, [])) for query_type in QUERY_TYPES}


def _latency_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "average_query_analyzer_latency_ms": _mean([case.get("query_analyzer_latency_ms") for case in cases]),
        "average_rewrite_latency_ms": None,
        "average_retrieval_latency_ms": _mean([case.get("retrieval_latency_ms") for case in cases]),
        "average_total_latency_ms": _mean([case.get("total_latency_ms") for case in cases]),
    }


def _build_analysis(
    *,
    r0_cases: list[dict[str, Any]],
    r1_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    r0_by_id = {case["query_id"]: case for case in r0_cases}
    r1_by_id = {case["query_id"]: case for case in r1_cases}
    changes = []
    no_change = []
    for query_id in sorted(r1_by_id):
        r0 = r0_by_id[query_id]
        r1 = r1_by_id[query_id]
        item = _change_item(r0, r1)
        if r0["expected_rank"] == r1["expected_rank"]:
            no_change.append(item)
        else:
            changes.append(item)

    off_fail_on_success = [
        item for item in changes if not _hit_rank(item["r0_rank"], 5) and _hit_rank(item["r1_rank"], 5)
    ]
    off_success_on_fail = [
        item for item in changes if _hit_rank(item["r0_rank"], 5) and not _hit_rank(item["r1_rank"], 5)
    ]
    top1_same_rank_improved = [
        item for item in changes
        if item["r0_top1"] == item["r1_top1"] and _rank_better(item["r1_rank"], item["r0_rank"])
    ]
    top1_same_rank_worse = [
        item for item in changes
        if item["r0_top1"] == item["r1_top1"] and _rank_better(item["r0_rank"], item["r1_rank"])
    ]
    top1_off_fail_on_success = [
        item for item in changes if not item["r0_top1"] and item["r1_top1"]
    ]
    top1_off_success_on_fail = [
        item for item in changes if item["r0_top1"] and not item["r1_top1"]
    ]
    quality_counts = Counter(
        label
        for item in changes
        for label in item["rewrite_quality_labels"]
    )
    intent_expression_counts = {
        expression: sum(
            1
            for item in changes
            if expression in item["original_query"] or expression in item["rewritten_query"]
        )
        for expression in ("유사 장애 사례", "장애 원인", "해결 방법", "장애 요약", "원인", "해결", "요약", "사례")
    }
    return {
        "rank_changed_count": len(changes),
        "no_change_count": len(no_change),
        "rewrite_off_fail_on_success": off_fail_on_success,
        "rewrite_off_success_on_fail": off_success_on_fail,
        "top1_same_rank_improved": top1_same_rank_improved,
        "top1_same_rank_worse": top1_same_rank_worse,
        "top1_off_fail_on_success": top1_off_fail_on_success,
        "top1_off_success_on_fail": top1_off_success_on_fail,
        "no_change_examples": no_change[:20],
        "quality_label_counts": dict(sorted(quality_counts.items())),
        "intent_expression_counts_in_changed_cases": intent_expression_counts,
        "counts": {
            "rewrite_off_fail_on_success": len(off_fail_on_success),
            "rewrite_off_success_on_fail": len(off_success_on_fail),
            "top1_same_rank_improved": len(top1_same_rank_improved),
            "top1_same_rank_worse": len(top1_same_rank_worse),
            "top1_off_fail_on_success": len(top1_off_fail_on_success),
            "top1_off_success_on_fail": len(top1_off_success_on_fail),
            "no_change": len(no_change),
        },
    }


def _change_item(r0: dict[str, Any], r1: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_id": r0["query_id"],
        "query": r0["query"],
        "query_type": r0["query_type"],
        "original_query": r0["original_query"],
        "rewritten_query": r1["rewritten_query"],
        "expected_incident_id": r0["expected_incident_id"],
        "expected_incident": _compact_incident(r0.get("expected_incident")),
        "r0_rank": r0["expected_rank"],
        "r1_rank": r1["expected_rank"],
        "r0_top1": r0["top1_hit"],
        "r1_top1": r1["top1_hit"],
        "r0_top_results": [_compact_result(item) for item in r0["results"][:5]],
        "r1_top_results": [_compact_result(item) for item in r1["results"][:5]],
        "rewrite_quality_labels": _rewrite_quality_labels(r0["original_query"], r1["rewritten_query"]),
        "rewrite_diff": _rewrite_diff(r0["original_query"], r1["rewritten_query"]),
    }


def _rewrite_quality_labels(original: str, rewritten: str) -> list[str]:
    labels = []
    diff = _rewrite_diff(original, rewritten)
    removed = set(diff["removed_tokens"])
    added = set(diff["added_tokens"])
    original_identifiers = set(_identifiers(original))
    rewritten_identifiers = set(_identifiers(rewritten))
    if original_identifiers and original_identifiers <= rewritten_identifiers:
        labels.append("중요한 Exception/Class/Method/Error Code가 유지됨")
    if original_identifiers - rewritten_identifiers:
        labels.append("Class / Method / Error Code가 제거됨")
    if added & {"원인", "해결", "요약", "사례", "장애", "유사"}:
        labels.append("검색 의도 표현이 추가되어 specific signal이 희석됨")
    if removed & {"원인", "해결", "요약", "사례", "장애", "유사"}:
        labels.append("검색 의도 표현 제거")
    if len(_tokens(rewritten)) > len(_tokens(original)) + 2:
        labels.append("원래 Query보다 의미가 넓어짐")
    if len(_tokens(rewritten)) + 2 < len(_tokens(original)):
        labels.append("원래 Query보다 의미가 좁아짐")
    if _normalized_help(original, rewritten):
        labels.append("동의어/표현 정규화가 도움 가능")
    if not labels:
        labels.append("기타")
    return labels


def _rewrite_diff(original: str, rewritten: str) -> dict[str, list[str]]:
    original_tokens = _tokens(original)
    rewritten_tokens = _tokens(rewritten)
    return {
        "removed_tokens": sorted(set(original_tokens) - set(rewritten_tokens)),
        "added_tokens": sorted(set(rewritten_tokens) - set(original_tokens)),
    }


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_가-힣.-]+", text)
        if len(token.strip(".-")) >= 2
    ]


def _identifiers(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.-]*|[A-Z]{2,}-[0-9]+|[0-9]{3,}", text)
    return [token.lower() for token in tokens if len(token) >= 3]


def _normalized_help(original: str, rewritten: str) -> bool:
    return original != rewritten and bool(
        {"오류", "에러", "실패", "타임아웃", "클래스", "로딩", "접속"}
        & set(_tokens(rewritten))
    )


def _write_summary(path: Path, *, metrics: dict[str, Any], analysis: dict[str, Any]) -> None:
    lines = [
        "# Query Rewrite Ablation",
        "",
        "## Setup",
        "",
        "- R0: Query Analyzer output is observed, but Hybrid Retrieval uses the original query text.",
        "- R1: Existing baseline Hybrid result using Query Analyzer rewritten_query.",
        "- Weighted RRF and reranker were not applied.",
        "- Existing A/B/C and Weighted RRF result files were not overwritten.",
        "- Note: Query Analyzer and Query Rewrite are bundled in one LLM call, so rewrite latency is not separately measurable without changing the production prompt.",
        "",
        "## Overall Metrics",
        "",
        "| Group | Top-1 | Recall@3 | Recall@5 | MRR | Rewrite Latency(ms) | Retrieval Latency(ms) | Total Latency(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in ("R0", "R1"):
        item = metrics["overall"][group]
        latency = metrics["latency"][group]
        lines.append(
            f"| {group} | {_pct(item['top1_accuracy'])} | {_pct(item['recall_at_3'])} | "
            f"{_pct(item['recall_at_5'])} | {_num(item['mrr'])} | "
            f"{_num(latency['average_rewrite_latency_ms'])} | "
            f"{_num(latency['average_retrieval_latency_ms'])} | "
            f"{_num(latency['average_total_latency_ms'])} |"
        )
    lines.extend(["", "## Query Type Metrics", ""])
    for query_type in QUERY_TYPES:
        lines.extend([f"### {query_type}", ""])
        lines.append("| Group | Top-1 | Recall@5 | MRR | Retrieval Latency(ms) |")
        lines.append("|---|---:|---:|---:|---:|")
        for group in ("R0", "R1"):
            item = metrics["by_query_type"][group][query_type]
            lines.append(
                f"| {group} | {_pct(item['top1_accuracy'])} | {_pct(item['recall_at_5'])} | "
                f"{_num(item['mrr'])} | {_num(item['average_retrieval_latency_ms'])} |"
            )
        lines.append("")
        lines.extend(_query_type_observation(query_type, metrics))
        lines.append("")
    lines.extend(
        [
            "## Rank Change Summary",
            "",
            f"- Rank changed: {analysis['rank_changed_count']} queries",
            f"- No change: {analysis['no_change_count']} queries",
            f"- Rewrite OFF Recall@5 fail -> ON Recall@5 success: {analysis['counts']['rewrite_off_fail_on_success']}",
            f"- Rewrite OFF Recall@5 success -> ON Recall@5 fail: {analysis['counts']['rewrite_off_success_on_fail']}",
            f"- Top-1 OFF fail -> ON success: {analysis['counts']['top1_off_fail_on_success']}",
            f"- Top-1 OFF success -> ON fail: {analysis['counts']['top1_off_success_on_fail']}",
            f"- Top-1 same but rank improved: {analysis['counts']['top1_same_rank_improved']}",
            f"- Top-1 same but rank worsened: {analysis['counts']['top1_same_rank_worse']}",
            "",
            "## Rewrite Quality Label Counts",
            "",
        ]
    )
    lines.append("| Label | Count |")
    lines.append("|---|---:|")
    for label, count in analysis["quality_label_counts"].items():
        lines.append(f"| {label} | {count} |")
    lines.extend(
        [
            "",
            "## Rewrite로 좋아진 대표 Query",
            "",
            *_case_table(analysis["top1_off_fail_on_success"] or analysis["rewrite_off_fail_on_success"]),
            "",
            "## Rewrite로 나빠진 대표 Query",
            "",
            *_case_table(
                analysis["top1_off_success_on_fail"]
                or analysis["rewrite_off_success_on_fail"]
                or analysis["top1_same_rank_worse"]
            ),
            "",
            "## Top-1은 같지만 Rank 개선",
            "",
            *_case_table(analysis["top1_same_rank_improved"]),
            "",
            "## Top-1은 같지만 Rank 악화",
            "",
            *_case_table(analysis["top1_same_rank_worse"]),
            "",
            "## Decision",
            "",
            _decision(metrics, analysis),
            "",
            "## Interview / Blog Insight",
            "",
            _insight(metrics, analysis),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _query_type_observation(query_type: str, metrics: dict[str, Any]) -> list[str]:
    r0 = metrics["by_query_type"]["R0"][query_type]
    r1 = metrics["by_query_type"]["R1"][query_type]
    top1_delta = (r1["top1_accuracy"] or 0.0) - (r0["top1_accuracy"] or 0.0)
    recall_delta = (r1["recall_at_5"] or 0.0) - (r0["recall_at_5"] or 0.0)
    if query_type in {"exact_error", "error_type_only"}:
        focus = "identifier/error signal 보존 여부가 핵심이다."
    elif query_type == "natural_language":
        focus = "증상 표현 정규화가 실제 검색 단서로 바뀌는지가 핵심이다."
    elif query_type == "ambiguous":
        focus = "rewrite가 의미를 과도하게 보강하거나 좁히는지가 핵심이다."
    else:
        focus = "넓은 기술 키워드를 더 유용한 검색어로 바꾸는지가 핵심이다."
    return [
        f"- Top-1 delta R1-R0: {_signed_pct(top1_delta)}",
        f"- Recall@5 delta R1-R0: {_signed_pct(recall_delta)}",
        f"- 관찰 포인트: {focus}",
    ]


def _decision(metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    r0 = metrics["overall"]["R0"]
    r1 = metrics["overall"]["R1"]
    top1_delta = (r1["top1_accuracy"] or 0.0) - (r0["top1_accuracy"] or 0.0)
    recall_delta = (r1["recall_at_5"] or 0.0) - (r0["recall_at_5"] or 0.0)
    mrr_delta = (r1["mrr"] or 0.0) - (r0["mrr"] or 0.0)
    if top1_delta > 0 and recall_delta >= 0 and mrr_delta >= 0:
        return (
            "Rewrite 유지. 전체 Top-1/Recall@5/MRR이 모두 개선되거나 유지되며, "
            "retrieval 설정 자체는 변하지 않는다. 다만 Query Analyzer와 Rewrite가 한 LLM call에 묶여 있어 "
            "rewrite latency를 별도로 줄이려면 prompt/architecture 분리가 별도 과제다."
        )
    if top1_delta < 0 or recall_delta < 0:
        return (
            "모든 Query에 Rewrite를 적용하는 정책은 수정이 필요하다. 전체 지표 또는 Recall@5가 악화되므로, "
            "exact_error/error_type_only처럼 이미 충분한 식별자를 가진 query는 원문을 유지하고, "
            "natural_language/ambiguous에만 조건부 rewrite를 적용하는 정책을 검토한다."
        )
    return (
        "Rewrite 효과가 거의 중립적이다. 성능 개선 폭이 작다면 구현/latency 복잡도를 고려해 조건부 적용이나 "
        "rewrite guardrail부터 개선하는 것이 적절하다."
    )


def _insight(metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    r0 = metrics["overall"]["R0"]
    r1 = metrics["overall"]["R1"]
    return (
        "Query Rewrite Ablation의 핵심은 rewrite가 retrieval 모델을 강하게 만드는 기능이 아니라, "
        "retriever가 볼 검색 문자열의 정보 밀도를 바꾸는 기능이라는 점이다. "
        f"이번 결과에서 R0 Top-1={_pct(r0['top1_accuracy'])}, R1 Top-1={_pct(r1['top1_accuracy'])}, "
        f"R0 Recall@5={_pct(r0['recall_at_5'])}, R1 Recall@5={_pct(r1['recall_at_5'])}였고, "
        f"rank가 바뀐 query는 {analysis['rank_changed_count']}개였다. "
        "좋은 rewrite는 불필요한 의도 표현을 제거하고 Exception/Class/Method/Error Code 같은 단서를 보존한다. "
        "나쁜 rewrite는 원래 query보다 의미를 넓히거나 좁혀서 Hybrid가 엉뚱한 incident를 더 강하게 보게 만든다. "
        "따라서 설계 판단은 'rewrite를 켠다/끈다'보다 query type별 guardrail과 identifier 보존 정책을 두는 쪽으로 발전한다."
    )


def _case_table(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["No cases."]
    lines = [
        "| Query | Type | Original | Rewritten | R0 Rank | R1 Rank | Labels |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for item in items[:10]:
        lines.append(
            f"| {_md(item['query'])} | {item['query_type']} | {_md(item['original_query'])} | "
            f"{_md(item['rewritten_query'])} | {_rank(item['r0_rank'])} | "
            f"{_rank(item['r1_rank'])} | {_md(', '.join(item['rewrite_quality_labels']))} |"
        )
    return lines


def _rank_of(expected_incident_id: str, results: list[dict[str, Any]]) -> int | None:
    for result in results:
        if result["incident_id"] == expected_incident_id:
            return int(result["rank"])
    return None


def _hit_rank(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def _rank_better(left: int | None, right: int | None) -> bool:
    if left is None:
        return False
    if right is None:
        return True
    return left < right


def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
    incident = item.get("incident") or {}
    return {
        "incident_id": item.get("incident_id"),
        "rank": item.get("rank"),
        "rrf_score": item.get("rrf_score"),
        "vector_score": item.get("vector_score"),
        "bm25_score": item.get("bm25_score"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
    }


def _compact_incident(incident: dict[str, Any] | None) -> dict[str, Any] | None:
    if not incident:
        return None
    return {
        "incident_id": incident.get("incident_id"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
    }


def _ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _signed_pct(value: float) -> str:
    return f"{value * 100:+.2f}pp"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _rank(value: Any) -> str:
    return "None" if value is None else str(value)


def _md(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")
