from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings
from evaluation.common import read_json, utc_now_iso, write_json
from evaluation.retrieval.reranker_ablation_runner import (
    QUERY_TYPES,
    _cost_metrics,
    _load_pricing,
    _rerank_case,
    _token_metrics,
)

FINAL_TOP_K = 5


def run_reranker_candidate_pool_experiment(
    *,
    settings: Settings,
    retrieval_cases_path: Path = Path("evaluation_result/retrieval_cases.json"),
    retrieval_metrics_path: Path = Path("evaluation_result/retrieval_metrics.json"),
    r5_cases_path: Path = Path("evaluation_result/reranker_ablation_cases.json"),
    output_dir: Path = Path("evaluation_result"),
) -> dict[str, Any]:
    retrieval_cases = read_json(retrieval_cases_path)
    retrieval_metrics = read_json(retrieval_metrics_path)
    r5_payload = read_json(r5_cases_path)
    hybrid_cases = retrieval_cases["hybrid"]
    r5_cases = [_normalize_pool_case(case, pool_size=5) for case in r5_payload["cases"]["RR1"]]

    r10_cases = []
    for index, case in enumerate(hybrid_cases, start=1):
        reranked = _rerank_case(settings=settings, case=case, top_k=10)
        r10_cases.append(_normalize_pool_case(reranked, pool_size=10))
        if index == 1 or index % 10 == 0 or index == len(hybrid_cases):
            print(f"reranked top10 {index}/{len(hybrid_cases)}", flush=True)

    pricing = _load_pricing(settings.llm_model_name)
    cases = {"R5": r5_cases, "R10": r10_cases}
    analysis = _build_analysis(r5_cases=r5_cases, r10_cases=r10_cases)
    metrics = {
        "experiment": "reranker_candidate_pool",
        "generated_at": utc_now_iso(),
        "baseline_files": {
            "retrieval_cases": str(retrieval_cases_path),
            "retrieval_metrics": str(retrieval_metrics_path),
            "r5_reranker_cases": str(r5_cases_path),
        },
        "dataset": retrieval_metrics["dataset"],
        "parameters": {
            **retrieval_metrics["parameters"],
            "reranker_model": settings.llm_model_name,
            "reranker_prompt": "evaluation.retrieval.reranker_ablation_runner._rerank_messages",
            "temperature": "model default",
            "max_tokens": 700,
            "final_top_k": FINAL_TOP_K,
            "r5_candidate_pool": 5,
            "r10_candidate_pool": 10,
            "cost_pricing": pricing,
        },
        "overall": {
            "R5": _metrics(r5_cases),
            "R10": _metrics(r10_cases),
            "delta": _metric_delta(_metrics(r5_cases), _metrics(r10_cases)),
        },
        "retrieval_stage": {
            "R5": _retrieval_stage_metrics(r5_cases, pool_size=5),
            "R10": _retrieval_stage_metrics(r10_cases, pool_size=10),
        },
        "by_query_type": {
            "R5": _metrics_by_query_type(r5_cases),
            "R10": _metrics_by_query_type(r10_cases),
            "delta": _metrics_delta_by_query_type(r5_cases, r10_cases),
        },
        "latency": {
            "R5": _latency_metrics(r5_cases),
            "R10": _latency_metrics(r10_cases),
            "delta": _latency_delta(_latency_metrics(r5_cases), _latency_metrics(r10_cases)),
        },
        "token_usage": {
            "R5": _token_metrics(r5_cases),
            "R10": _token_metrics(r10_cases),
            "delta": _token_delta(_token_metrics(r5_cases), _token_metrics(r10_cases)),
        },
        "api_cost_usd": {
            "R5": _cost_metrics(r5_cases, pricing),
            "R10": _cost_metrics(r10_cases, pricing),
        },
    }
    metrics["decision"] = _decision(metrics=metrics, analysis=analysis)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "reranker_candidate_pool_metrics.json", metrics)
    write_json(
        output_dir / "reranker_candidate_pool_cases.json",
        {"analysis": analysis, "cases": cases},
    )
    _write_summary(
        output_dir / "reranker_candidate_pool_summary.md",
        metrics=metrics,
        analysis=analysis,
    )
    return {"metrics": metrics, "analysis": analysis, "cases": cases}


def _normalize_pool_case(case: dict[str, Any], *, pool_size: int) -> dict[str, Any]:
    full_rank = case.get("expected_rank")
    final_rank = full_rank if full_rank is not None and full_rank <= FINAL_TOP_K else None
    retrieval_rank = _retrieval_rank(case)
    normalized = {
        **case,
        "experiment_group": f"R{pool_size}",
        "candidate_pool_size": pool_size,
        "retrieval_rank": retrieval_rank,
        "retrieval_recall_at_5": retrieval_rank is not None and retrieval_rank <= 5,
        "retrieval_recall_at_10": retrieval_rank is not None and retrieval_rank <= 10,
        "rerank_full_rank": full_rank,
        "expected_rank": final_rank,
        "top1_hit": final_rank == 1,
        "recall_at_3": final_rank is not None and final_rank <= 3,
        "recall_at_5": final_rank is not None and final_rank <= 5,
        "reciprocal_rank": (1.0 / final_rank) if final_rank else 0.0,
        "final_results": case.get("results", [])[:FINAL_TOP_K],
        "all_reranked_results": case.get("results", []),
    }
    return normalized


def _retrieval_rank(case: dict[str, Any]) -> int | None:
    expected_id = case["expected_incident_id"]
    for item in case.get("results", []):
        if item.get("incident_id") == expected_id:
            return item.get("retrieval_rank") or item.get("rank")
    return case.get("baseline_hybrid_rank")


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(cases)
    ranks = [case.get("expected_rank") for case in cases]
    return {
        "query_count": count,
        "top1_accuracy": _ratio(sum(1 for rank in ranks if rank == 1), count),
        "recall_at_3": _ratio(sum(1 for rank in ranks if rank is not None and rank <= 3), count),
        "final_recall_at_5": _ratio(sum(1 for rank in ranks if rank is not None and rank <= 5), count),
        "mrr": _ratio(sum((1.0 / int(rank)) for rank in ranks if rank is not None), count),
        "average_retrieval_latency_ms": _mean([case.get("retrieval_latency_ms") for case in cases]),
        "average_reranker_latency_ms": _mean([case.get("reranker_latency_ms") for case in cases]),
        "average_total_latency_ms": _mean([case.get("total_latency_ms") for case in cases]),
    }


def _metrics_by_query_type(cases: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = {query_type: [] for query_type in QUERY_TYPES}
    for case in cases:
        grouped.setdefault(case["query_type"], []).append(case)
    return {query_type: _metrics(grouped.get(query_type, [])) for query_type in QUERY_TYPES}


def _metric_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _delta(left.get(key), right.get(key))
        for key in ("top1_accuracy", "recall_at_3", "final_recall_at_5", "mrr")
    }


def _metrics_delta_by_query_type(
    r5_cases: list[dict[str, Any]],
    r10_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    r5 = _metrics_by_query_type(r5_cases)
    r10 = _metrics_by_query_type(r10_cases)
    return {query_type: _metric_delta(r5[query_type], r10[query_type]) for query_type in QUERY_TYPES}


def _retrieval_stage_metrics(cases: list[dict[str, Any]], *, pool_size: int) -> dict[str, Any]:
    count = len(cases)
    return {
        "query_count": count,
        "candidate_pool_size": pool_size,
        "retrieval_recall_at_5": _ratio(sum(1 for case in cases if case["retrieval_recall_at_5"]), count),
        "retrieval_recall_at_10": _ratio(sum(1 for case in cases if case["retrieval_recall_at_10"]), count),
    }


def _latency_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "average_query_analyzer_latency_ms": _mean([case.get("query_analyzer_latency_ms") for case in cases]),
        "average_retrieval_latency_ms": _mean([case.get("retrieval_latency_ms") for case in cases]),
        "average_reranker_latency_ms": _mean([case.get("reranker_latency_ms") for case in cases]),
        "average_total_latency_ms": _mean([case.get("total_latency_ms") for case in cases]),
    }


def _latency_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {key: _delta(left.get(key), right.get(key)) for key in left}


def _token_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {key: _delta(left.get(key), right.get(key)) for key in left if key != "missing_usage_count"}


def _build_analysis(
    *,
    r5_cases: list[dict[str, Any]],
    r10_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    r5_by_id = {case["query_id"]: case for case in r5_cases}
    r10_by_id = {case["query_id"]: case for case in r10_cases}
    rows = []
    for query_id in sorted(r5_by_id):
        rows.append(_case_change_item(r5_by_id[query_id], r10_by_id[query_id]))

    rank_6_10_recovered = [
        row for row in rows
        if _rank_between(row["retrieval_rank"], 6, 10) and _hit(row["r10_final_rank"], 5)
    ]
    rank_6_10_not_recovered = [
        row for row in rows
        if _rank_between(row["retrieval_rank"], 6, 10) and not _hit(row["r10_final_rank"], 5)
    ]
    r5_fail_r10_success = [
        row for row in rows
        if not _hit(row["r5_final_rank"], 5) and _hit(row["r10_final_rank"], 5)
    ]
    r5_success_r10_fail = [
        row for row in rows
        if _hit(row["r5_final_rank"], 5) and not _hit(row["r10_final_rank"], 5)
    ]
    top1_improved = [
        row for row in rows
        if not row["r5_top1"] and row["r10_top1"]
    ]
    top1_worsened = [
        row for row in rows
        if row["r5_top1"] and not row["r10_top1"]
    ]
    top1_same = [
        row for row in rows
        if row["r5_top1"] == row["r10_top1"]
    ]
    expected_rank_improved = [
        row for row in rows
        if _rank_better(row["r10_final_rank"], row["r5_final_rank"])
    ]
    expected_rank_worsened = [
        row for row in rows
        if _rank_better(row["r5_final_rank"], row["r10_final_rank"])
    ]
    expected_rank_same = [
        row for row in rows
        if row["r5_final_rank"] == row["r10_final_rank"]
    ]
    return {
        "rank_6_10_recovered": rank_6_10_recovered,
        "rank_6_10_not_recovered": rank_6_10_not_recovered,
        "r5_fail_r10_success": r5_fail_r10_success,
        "r5_success_r10_fail": r5_success_r10_fail,
        "top1_improved": top1_improved,
        "top1_worsened": top1_worsened,
        "top1_same_examples": top1_same[:30],
        "expected_rank_improved": expected_rank_improved,
        "expected_rank_worsened": expected_rank_worsened,
        "expected_rank_same_examples": expected_rank_same[:30],
        "counts": {
            "rank_6_10_recovered": len(rank_6_10_recovered),
            "rank_6_10_not_recovered": len(rank_6_10_not_recovered),
            "r5_fail_r10_success": len(r5_fail_r10_success),
            "r5_success_r10_fail": len(r5_success_r10_fail),
            "top1_improved": len(top1_improved),
            "top1_worsened": len(top1_worsened),
            "top1_same": len(top1_same),
            "expected_rank_improved": len(expected_rank_improved),
            "expected_rank_worsened": len(expected_rank_worsened),
            "expected_rank_same": len(expected_rank_same),
        },
        "by_query_type": _change_counts_by_query_type(rows),
        "reranker_status_counts": {
            "R5": _status_counts(r5_cases),
            "R10": _status_counts(r10_cases),
        },
    }


def _case_change_item(r5: dict[str, Any], r10: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_id": r5["query_id"],
        "query": r5["query"],
        "rewritten_query": r5["rewritten_query"],
        "query_type": r5["query_type"],
        "expected_incident_id": r5["expected_incident_id"],
        "expected_incident": _compact_incident(r5.get("expected_incident")),
        "retrieval_rank": r10.get("retrieval_rank"),
        "r5_final_rank": r5.get("expected_rank"),
        "r10_full_rerank_rank": r10.get("rerank_full_rank"),
        "r10_final_rank": r10.get("expected_rank"),
        "r5_top1": r5.get("top1_hit"),
        "r10_top1": r10.get("top1_hit"),
        "r5_top_results": [_compact_result(item) for item in r5.get("final_results", [])],
        "r10_top_results": [_compact_result(item) for item in r10.get("final_results", [])],
    }


def _change_counts_by_query_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    output = {}
    for query_type in QUERY_TYPES:
        items = [row for row in rows if row["query_type"] == query_type]
        output[query_type] = {
            "query_count": len(items),
            "rank_6_10_recovered": sum(1 for row in items if _rank_between(row["retrieval_rank"], 6, 10) and _hit(row["r10_final_rank"], 5)),
            "r5_fail_r10_success": sum(1 for row in items if not _hit(row["r5_final_rank"], 5) and _hit(row["r10_final_rank"], 5)),
            "r5_success_r10_fail": sum(1 for row in items if _hit(row["r5_final_rank"], 5) and not _hit(row["r10_final_rank"], 5)),
            "top1_improved": sum(1 for row in items if not row["r5_top1"] and row["r10_top1"]),
            "top1_worsened": sum(1 for row in items if row["r5_top1"] and not row["r10_top1"]),
            "expected_rank_improved": sum(1 for row in items if _rank_better(row["r10_final_rank"], row["r5_final_rank"])),
            "expected_rank_worsened": sum(1 for row in items if _rank_better(row["r5_final_rank"], row["r10_final_rank"])),
        }
    return output


def _write_summary(path: Path, *, metrics: dict[str, Any], analysis: dict[str, Any]) -> None:
    lines = [
        "# Reranker Candidate Pool Experiment",
        "",
        "## 1. Hypothesis",
        "",
        "Retrieval 후보를 Top-10까지 넓히면 기존 rank 6~10에 있던 정답 incident를 reranker가 Final Top-5 안으로 끌어올릴 수 있다. 다만 latency/token/cost 증가가 품질 개선 대비 합리적인지 함께 검증한다.",
        "",
        "## 2. Experiment Setup",
        "",
        "- R5: Query Analyzer -> Query Rewrite -> Equal Weight Hybrid Retrieval Top-5 -> Reranker -> Final Top-5",
        "- R10: Query Analyzer -> Query Rewrite -> Equal Weight Hybrid Retrieval Top-10 -> Reranker -> Final Top-5",
        "- Dataset, excluded query handling, embedding model, incident dataset, BM25/Vector settings, RRF k, reranker model/prompt, max tokens are unchanged.",
        "- Weighted RRF and reranker prompt changes were not applied.",
        "",
        "## 3. Metrics",
        "",
        "- Top-1 Accuracy, Recall@3, Final Recall@5, MRR",
        "- Retrieval latency, Reranker latency, Total latency",
        "- Prompt/Completion/Total tokens, estimated API cost",
        "- R10 retrieval-stage Recall@5 and Recall@10",
        "",
        "## 4. Overall Results",
        "",
        "| Group | Top-1 | Recall@3 | Final Recall@5 | MRR | Retrieval(ms) | Reranker(ms) | Total(ms) | Prompt Tok | Completion Tok | Total Tok | Cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in ("R5", "R10"):
        item = metrics["overall"][group]
        tokens = metrics["token_usage"][group]
        cost = metrics["api_cost_usd"][group]
        lines.append(
            f"| {group} | {_pct(item['top1_accuracy'])} | {_pct(item['recall_at_3'])} | "
            f"{_pct(item['final_recall_at_5'])} | {_num(item['mrr'])} | "
            f"{_num(item['average_retrieval_latency_ms'])} | {_num(item['average_reranker_latency_ms'])} | "
            f"{_num(item['average_total_latency_ms'])} | {_num(tokens['prompt_tokens'])} | "
            f"{_num(tokens['completion_tokens'])} | {_num(tokens['total_tokens'])} | {_cost_text(cost)} |"
        )
    delta = metrics["overall"]["delta"]
    lines.extend(
        [
            "",
            f"- Top-1 delta R10-R5: {_signed_pct(delta['top1_accuracy'])}",
            f"- Final Recall@5 delta R10-R5: {_signed_pct(delta['final_recall_at_5'])}",
            f"- MRR delta R10-R5: {_signed_num(delta['mrr'])}",
            f"- R10 Retrieval Recall@5: {_pct(metrics['retrieval_stage']['R10']['retrieval_recall_at_5'])}",
            f"- R10 Retrieval Recall@10: {_pct(metrics['retrieval_stage']['R10']['retrieval_recall_at_10'])}",
            "",
            "## 5. Query Type Results",
            "",
            "| Query Type | R5 Top-1 | R10 Top-1 | R5 Final R@5 | R10 Final R@5 | MRR Delta | R5->R10 Success | R5->R10 Regression |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for query_type in QUERY_TYPES:
        r5 = metrics["by_query_type"]["R5"][query_type]
        r10 = metrics["by_query_type"]["R10"][query_type]
        qdelta = metrics["by_query_type"]["delta"][query_type]
        changes = analysis["by_query_type"][query_type]
        lines.append(
            f"| {query_type} | {_pct(r5['top1_accuracy'])} | {_pct(r10['top1_accuracy'])} | "
            f"{_pct(r5['final_recall_at_5'])} | {_pct(r10['final_recall_at_5'])} | "
            f"{_signed_num(qdelta['mrr'])} | {changes['r5_fail_r10_success']} | {changes['r5_success_r10_fail']} |"
        )
    lines.extend(
        [
            "",
            "## 6. Rank 6~10 Recovery Cases",
            "",
            f"- Recovered into Final Top-5: {analysis['counts']['rank_6_10_recovered']}",
            f"- Still not recovered: {analysis['counts']['rank_6_10_not_recovered']}",
            "",
            "### Recovered",
            "",
            *_case_table(analysis["rank_6_10_recovered"]),
            "",
            "### Not Recovered",
            "",
            *_case_table(analysis["rank_6_10_not_recovered"]),
            "",
            "## 7. Failure / Regression Cases",
            "",
            f"- R5 failed but R10 Final Recall@5 succeeded: {analysis['counts']['r5_fail_r10_success']}",
            f"- R5 succeeded but R10 pushed out of Final Top-5: {analysis['counts']['r5_success_r10_fail']}",
            f"- Top-1 improved: {analysis['counts']['top1_improved']}",
            f"- Top-1 worsened: {analysis['counts']['top1_worsened']}",
            f"- Top-1 same: {analysis['counts']['top1_same']}",
            f"- Expected incident final rank improved: {analysis['counts']['expected_rank_improved']}",
            f"- Expected incident final rank worsened: {analysis['counts']['expected_rank_worsened']}",
            f"- Expected incident final rank same: {analysis['counts']['expected_rank_same']}",
            "",
            "### R5 Fail -> R10 Success",
            "",
            *_case_table(analysis["r5_fail_r10_success"]),
            "",
            "### R5 Success -> R10 Regression",
            "",
            *_case_table(analysis["r5_success_r10_fail"]),
            "",
            "## 8. Latency / Token / Cost Comparison",
            "",
        ]
    )
    latency_delta = metrics["latency"]["delta"]
    token_delta = metrics["token_usage"]["delta"]
    lines.extend(
        [
            f"- Retrieval latency delta: {_signed_num(latency_delta['average_retrieval_latency_ms'])} ms",
            f"- Reranker latency delta: {_signed_num(latency_delta['average_reranker_latency_ms'])} ms",
            f"- Total latency delta: {_signed_num(latency_delta['average_total_latency_ms'])} ms",
            f"- Prompt token delta: {_signed_num(token_delta['prompt_tokens'])}",
            f"- Completion token delta: {_signed_num(token_delta['completion_tokens'])}",
            f"- Total token delta: {_signed_num(token_delta['total_tokens'])}",
            f"- Reranker status counts R5: {metrics['decision']['r5_status_counts']}",
            f"- Reranker status counts R10: {metrics['decision']['r10_status_counts']}",
            "",
            "## 9. Decision",
            "",
            f"- Recommendation: `{metrics['decision']['recommendation']}`",
            f"- Reason: {metrics['decision']['reason']}",
            "",
            "## 10. Limitations / Next Step",
            "",
            "- R5 result reuses the existing reranker ablation output to preserve baseline files.",
            "- R10 uses the same retrieved Hybrid candidate list already produced under the baseline settings, then expands only the reranker candidate pool to Top-10.",
            "- Next: if R10 only helps a specific query_type, test conditional Top-10 expansion for that type or for cases with flat RRF score gaps.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _decision(*, metrics: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    delta = metrics["overall"]["delta"]
    latency_delta = metrics["latency"]["delta"]
    token_delta = metrics["token_usage"]["delta"]
    final_recall_delta = delta["final_recall_at_5"] or 0.0
    top1_delta = delta["top1_accuracy"] or 0.0
    mrr_delta = delta["mrr"] or 0.0
    r10_success = analysis["counts"]["r5_fail_r10_success"]
    regressions = analysis["counts"]["r5_success_r10_fail"]
    r10_status_counts = analysis.get("reranker_status_counts", {}).get("R10", {})
    r5_status_counts = analysis.get("reranker_status_counts", {}).get("R5", {})
    r10_fallbacks = sum(
        int(count)
        for status, count in r10_status_counts.items()
        if status != "ok"
    )
    improvement_is_narrow = r10_success <= 1 and final_recall_delta < 0.01
    if (
        final_recall_delta > 0.01
        and regressions == 0
        and top1_delta >= 0
        and mrr_delta >= 0
        and r10_fallbacks == 0
    ):
        recommendation = "adopt_r10"
        reason = "R10 improves Final Recall@5 meaningfully without regressions or reranker stability issues."
    elif r10_success > 0 and regressions == 0 and top1_delta >= 0 and mrr_delta >= 0:
        recommendation = "conditional_r10"
        reason = (
            "R10 recovers a small number of missed cases without aggregate ranking regressions, "
            "but the gain is narrow and comes with higher latency/token usage and reranker fallbacks."
            if improvement_is_narrow or r10_fallbacks
            else "R10 helps some failed R5 cases without hurting aggregate ranking metrics; consider conditional expansion."
        )
    else:
        recommendation = "keep_r5"
        reason = (
            "R10 does not improve Final Recall@5 enough to justify the extra reranker latency/token/cost, "
            "or it introduces regressions."
        )
    return {
        "recommendation": recommendation,
        "reason": reason,
        "top1_delta": top1_delta,
        "final_recall_at_5_delta": final_recall_delta,
        "mrr_delta": mrr_delta,
        "r5_fail_r10_success": r10_success,
        "r5_success_r10_fail": regressions,
        "average_total_latency_delta_ms": latency_delta.get("average_total_latency_ms"),
        "total_token_delta": token_delta.get("total_tokens"),
        "r5_status_counts": r5_status_counts,
        "r10_status_counts": r10_status_counts,
    }


def _case_table(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["No cases."]
    lines = [
        "| Query | Type | Retrieval Rank | R5 Final Rank | R10 Full Rank | R10 Final Rank | Expected |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in items[:10]:
        lines.append(
            f"| {_md(item['query'])} | {item['query_type']} | {_rank(item['retrieval_rank'])} | "
            f"{_rank(item['r5_final_rank'])} | {_rank(item['r10_full_rerank_rank'])} | "
            f"{_rank(item['r10_final_rank'])} | {_md(_incident_label(item.get('expected_incident')))} |"
        )
    return lines


def _rank_between(rank: int | None, start: int, end: int) -> bool:
    return rank is not None and start <= rank <= end


def _hit(rank: int | None, k: int) -> bool:
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
        "retrieval_rank": item.get("retrieval_rank"),
        "reranker_score": item.get("reranker_score"),
        "reranker_reason": item.get("reranker_reason"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
    }


def _status_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    output: dict[str, int] = {}
    for case in cases:
        status = str(case.get("reranker_status"))
        output[status] = output.get(status, 0) + 1
    return dict(sorted(output.items()))


def _compact_incident(incident: dict[str, Any] | None) -> dict[str, Any] | None:
    if not incident:
        return None
    return {
        "incident_id": incident.get("incident_id"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
    }


def _incident_label(incident: dict[str, Any] | None) -> str:
    if not incident:
        return "n/a"
    return f"{incident.get('error_type')} / {incident.get('summary')}"


def _ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return float(right) - float(left)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _signed_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:+.2f}pp"


def _signed_num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+.4f}"


def _rank(value: Any) -> str:
    return "None" if value is None else str(value)


def _md(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def _cost_text(cost: dict[str, Any]) -> str:
    if not cost.get("priced"):
        return "n/a"
    return f"${float(cost['total_usd']):.6f}"
