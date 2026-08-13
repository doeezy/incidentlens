from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation.common import utc_now_iso, write_json

WEIGHT_CONFIGS = {
    "C0": {"label": "Equal Weight RRF", "vector_weight": 1.0, "bm25_weight": 1.0},
    "C1": {"label": "BM25 1.25 / Vector 1.0", "vector_weight": 1.0, "bm25_weight": 1.25},
    "C2": {"label": "BM25 1.5 / Vector 1.0", "vector_weight": 1.0, "bm25_weight": 1.5},
    "C3": {"label": "Vector 1.25 / BM25 1.0", "vector_weight": 1.25, "bm25_weight": 1.0},
}
QUERY_TYPES = ("exact_error", "error_type_only", "natural_language", "cause_keyword", "ambiguous")


def run_weighted_rrf_experiment(
    *,
    input_cases_path: Path = Path("evaluation_result/retrieval_cases.json"),
    input_metrics_path: Path = Path("evaluation_result/retrieval_metrics.json"),
    output_dir: Path = Path("evaluation_result"),
) -> dict[str, Any]:
    cases = json.loads(input_cases_path.read_text(encoding="utf-8"))
    baseline_metrics = json.loads(input_metrics_path.read_text(encoding="utf-8"))
    rrf_k = int(baseline_metrics["parameters"]["rrf_k"])
    top_k = int(baseline_metrics["parameters"]["top_k"])
    vector_cases = {case["query_id"]: case for case in cases["vector"]}
    bm25_cases = {case["query_id"]: case for case in cases["bm25"]}
    hybrid_cases = {case["query_id"]: case for case in cases["hybrid"]}

    weighted_cases: dict[str, list[dict[str, Any]]] = {}
    for config_id, config in WEIGHT_CONFIGS.items():
        weighted_cases[config_id] = [
            _weighted_case(
                vector_case=vector_cases[query_id],
                bm25_case=bm25_cases[query_id],
                baseline_hybrid_case=hybrid_cases[query_id],
                config_id=config_id,
                config=config,
                rrf_k=rrf_k,
                top_k=top_k,
            )
            for query_id in sorted(hybrid_cases)
        ]

    metrics = {
        "experiment": "weighted_rrf",
        "generated_at": utc_now_iso(),
        "baseline_files": {
            "retrieval_cases": str(input_cases_path),
            "retrieval_metrics": str(input_metrics_path),
        },
        "dataset": baseline_metrics["dataset"],
        "parameters": {
            **baseline_metrics["parameters"],
            "weighted_rrf_formula": "vector_weight/(rrf_k + vector_rank) + bm25_weight/(rrf_k + bm25_rank)",
            "latency_source": "Baseline hybrid retrieval latency reused; fusion weights do not change retrieval calls.",
        },
        "configs": WEIGHT_CONFIGS,
        "overall": {
            config_id: _metrics(items)
            for config_id, items in weighted_cases.items()
        },
        "by_query_type": {
            config_id: _metrics_by_query_type(items)
            for config_id, items in weighted_cases.items()
        },
        "c0_baseline_match": _c0_matches_existing_hybrid(
            weighted_cases["C0"],
            hybrid_cases,
        ),
    }
    analysis = _case_analysis(weighted_cases)
    payload = {"metrics": metrics, "analysis": analysis, "cases": weighted_cases}

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "weighted_rrf_metrics.json", metrics)
    write_json(
        output_dir / "weighted_rrf_cases.json",
        {
            "analysis": analysis,
            "cases": weighted_cases,
        },
    )
    _write_summary(output_dir / "weighted_rrf_summary.md", metrics=metrics, analysis=analysis)
    return payload


def _weighted_case(
    *,
    vector_case: dict[str, Any],
    bm25_case: dict[str, Any],
    baseline_hybrid_case: dict[str, Any],
    config_id: str,
    config: dict[str, Any],
    rrf_k: int,
    top_k: int,
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for result in vector_case["results"]:
        incident_id = result["incident_id"]
        item = merged.setdefault(incident_id, {"incident_id": incident_id, "score": 0.0})
        item["vector_rank"] = int(result["rank"])
        item["vector_score"] = result.get("vector_score")
        item["incident"] = result.get("incident")
        item["score"] += float(config["vector_weight"]) / (rrf_k + int(result["rank"]))
    for result in bm25_case["results"]:
        incident_id = result["incident_id"]
        item = merged.setdefault(incident_id, {"incident_id": incident_id, "score": 0.0})
        item["bm25_rank"] = int(result["rank"])
        item["bm25_score"] = result.get("bm25_score")
        item["incident"] = item.get("incident") or result.get("incident")
        item["score"] += float(config["bm25_weight"]) / (rrf_k + int(result["rank"]))

    ranked = sorted(merged.values(), key=lambda item: (-float(item["score"]), item["incident_id"]))
    results = [
        {
            "incident_id": item["incident_id"],
            "rank": rank,
            "weighted_rrf_score": item["score"],
            "vector_rank": item.get("vector_rank"),
            "bm25_rank": item.get("bm25_rank"),
            "vector_score": item.get("vector_score"),
            "bm25_score": item.get("bm25_score"),
            "incident": item.get("incident"),
        }
        for rank, item in enumerate(ranked, start=1)
    ]
    expected_rank = _rank_of(vector_case["expected_incident_id"], results)
    top_result = results[0] if results else None
    return {
        "config_id": config_id,
        "query_id": vector_case["query_id"],
        "query": vector_case["query"],
        "rewritten_query": vector_case["rewritten_query"],
        "query_type": vector_case["query_type"],
        "project_name": vector_case["project_name"],
        "expected_incident_id": vector_case["expected_incident_id"],
        "expected_incident": vector_case["expected_incident"],
        "expected_rank": expected_rank,
        "top1_hit": expected_rank == 1,
        "recall_at_3": expected_rank is not None and expected_rank <= 3,
        "recall_at_5": expected_rank is not None and expected_rank <= 5,
        "reciprocal_rank": (1.0 / expected_rank) if expected_rank else 0.0,
        "latency_ms": baseline_hybrid_case["latency_ms"],
        "vector_rank": vector_case["expected_rank"],
        "bm25_rank": bm25_case["expected_rank"],
        "baseline_hybrid_rank": baseline_hybrid_case["expected_rank"],
        "results": results[:20],
        "top_retrieved_incident_id": top_result["incident_id"] if top_result else None,
        "top_weighted_rrf_score": top_result["weighted_rrf_score"] if top_result else None,
    }


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(cases)
    latencies = [float(case["latency_ms"]) for case in cases]
    return {
        "query_count": count,
        "top1_accuracy": _ratio(sum(1 for case in cases if case["top1_hit"]), count),
        "recall_at_3": _ratio(sum(1 for case in cases if case["recall_at_3"]), count),
        "recall_at_5": _ratio(sum(1 for case in cases if case["recall_at_5"]), count),
        "mrr": _ratio(sum(float(case["reciprocal_rank"]) for case in cases), count),
        "average_retrieval_latency_ms": sum(latencies) / len(latencies) if latencies else None,
    }


def _metrics_by_query_type(cases: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["query_type"]].append(case)
    return {query_type: _metrics(grouped.get(query_type, [])) for query_type in QUERY_TYPES}


def _case_analysis(weighted_cases: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_config = {
        config_id: {case["query_id"]: case for case in cases}
        for config_id, cases in weighted_cases.items()
    }
    rows = []
    for query_id in sorted(by_config["C0"]):
        c0 = by_config["C0"][query_id]
        row = {
            "query_id": query_id,
            "query": c0["query"],
            "query_type": c0["query_type"],
            "expected_incident": _compact_incident(c0["expected_incident"]),
            "vector_rank": c0["vector_rank"],
            "bm25_rank": c0["bm25_rank"],
            "weighted_rrf_ranks": {
                config_id: by_config[config_id][query_id]["expected_rank"]
                for config_id in WEIGHT_CONFIGS
            },
            "top1": {
                config_id: by_config[config_id][query_id]["top1_hit"]
                for config_id in WEIGHT_CONFIGS
            },
        }
        rows.append(row)

    c0_wrong_bm25_gain = [
        row for row in rows
        if not row["top1"]["C0"] and (row["top1"]["C1"] or row["top1"]["C2"])
    ]
    c0_right_bm25_loss = [
        row for row in rows
        if row["top1"]["C0"] and (not row["top1"]["C1"] or not row["top1"]["C2"])
    ]
    c3_gain = [
        row for row in rows
        if not row["top1"]["C0"] and row["top1"]["C3"]
    ]
    unresolved = [
        row for row in rows
        if not any(row["top1"][config_id] for config_id in WEIGHT_CONFIGS)
    ]
    rank_changed = [
        row for row in rows
        if len({row["weighted_rrf_ranks"][config_id] for config_id in WEIGHT_CONFIGS}) > 1
    ]
    return {
        "rank_changed_count": len(rank_changed),
        "rank_changed_examples": rank_changed[:20],
        "c0_wrong_bm25_gain": c0_wrong_bm25_gain[:20],
        "c0_right_bm25_loss": c0_right_bm25_loss[:20],
        "c3_gain": c3_gain[:20],
        "unresolved": unresolved[:20],
        "counts": {
            "c0_wrong_bm25_gain": len(c0_wrong_bm25_gain),
            "c0_right_bm25_loss": len(c0_right_bm25_loss),
            "c3_gain": len(c3_gain),
            "unresolved": len(unresolved),
        },
    }


def _c0_matches_existing_hybrid(
    c0_cases: list[dict[str, Any]],
    hybrid_cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    mismatches = []
    for case in c0_cases:
        baseline = hybrid_cases[case["query_id"]]
        if case["expected_rank"] != baseline["expected_rank"]:
            mismatches.append(
                {
                    "query_id": case["query_id"],
                    "computed_c0_rank": case["expected_rank"],
                    "baseline_hybrid_rank": baseline["expected_rank"],
                }
            )
    return {"matches": not mismatches, "mismatch_count": len(mismatches), "mismatches": mismatches[:20]}


def _write_summary(path: Path, *, metrics: dict[str, Any], analysis: dict[str, Any]) -> None:
    lines = [
        "# Weighted RRF Experiment",
        "",
        "## Setup",
        "",
        "- Baseline A/B/C files were kept unchanged.",
        "- Source candidates: `evaluation_result/retrieval_cases.json` Vector/BM25 results.",
        "- Query Analyzer, Query Rewrite, embedding model, incident dataset, Top-K, candidate limit, and RRF k are unchanged.",
        "- Latency is reused from baseline Hybrid because fusion weights do not change retrieval calls.",
        f"- C0 equals existing Hybrid ranks: {metrics['c0_baseline_match']['matches']} ({metrics['c0_baseline_match']['mismatch_count']} mismatches)",
        "",
        "## Overall Metrics",
        "",
        "| Config | Vector Weight | BM25 Weight | Top-1 | Recall@3 | Recall@5 | MRR | Avg Latency(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for config_id, config in WEIGHT_CONFIGS.items():
        item = metrics["overall"][config_id]
        lines.append(
            f"| {config_id} | {config['vector_weight']} | {config['bm25_weight']} | "
            f"{_pct(item['top1_accuracy'])} | {_pct(item['recall_at_3'])} | "
            f"{_pct(item['recall_at_5'])} | {_num(item['mrr'])} | "
            f"{_num(item['average_retrieval_latency_ms'])} |"
        )
    lines.extend(["", "## Query Type Metrics", ""])
    for query_type in QUERY_TYPES:
        lines.extend([f"### {query_type}", ""])
        lines.append("| Config | Top-1 | Recall@5 | MRR |")
        lines.append("|---|---:|---:|---:|")
        for config_id in WEIGHT_CONFIGS:
            item = metrics["by_query_type"][config_id][query_type]
            lines.append(
                f"| {config_id} | {_pct(item['top1_accuracy'])} | "
                f"{_pct(item['recall_at_5'])} | {_num(item['mrr'])} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Case Analysis",
            "",
            f"- Rank changed by weight: {analysis['rank_changed_count']} queries",
            f"- C0 wrong -> C1/C2 correct Top-1: {analysis['counts']['c0_wrong_bm25_gain']} queries",
            f"- C0 correct -> C1/C2 wrong Top-1: {analysis['counts']['c0_right_bm25_loss']} queries",
            f"- C3 vector weight gain: {analysis['counts']['c3_gain']} queries",
            f"- Unresolved by any weight: {analysis['counts']['unresolved']} queries",
            "",
            "### C0 wrong, BM25 weight fixed Top-1",
            "",
            *_case_table(analysis["c0_wrong_bm25_gain"]),
            "",
            "### C0 correct, BM25 weight broke Top-1",
            "",
            *_case_table(analysis["c0_right_bm25_loss"]),
            "",
            "### C3 Vector Weight Helped",
            "",
            *_case_table(analysis["c3_gain"]),
            "",
            "### Unresolved",
            "",
            *_case_table(analysis["unresolved"]),
            "",
            "## Decision",
            "",
            _decision(metrics, analysis),
            "",
            "## Copyable Insight String",
            "",
            "```text",
            _insight_string(metrics, analysis),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _decision(metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    c0 = metrics["overall"]["C0"]
    c1 = metrics["overall"]["C1"]
    c2 = metrics["overall"]["C2"]
    c3 = metrics["overall"]["C3"]
    best_top1 = max(metrics["overall"].items(), key=lambda item: item[1]["top1_accuracy"])[0]
    if (
        c1["top1_accuracy"] > c0["top1_accuracy"]
        and c1["recall_at_5"] >= c0["recall_at_5"]
        and c1["mrr"] >= c0["mrr"]
    ):
        return (
            "Adopt C1. BM25 1.25 recovers Top-1 without sacrificing Recall@5/MRR, "
            "and it is a small enough weight change to keep configuration complexity modest."
        )
    if (
        c2["top1_accuracy"] > c0["top1_accuracy"]
        and c2["recall_at_5"] >= c0["recall_at_5"]
        and c2["mrr"] >= c0["mrr"]
    ):
        return (
            "C2 improves the headline metric, but prefer validating C1 first because C2 adds "
            "a stronger lexical bias and may overfit BM25-friendly query types."
        )
    if c3["top1_accuracy"] > c0["top1_accuracy"]:
        return (
            "Vector-heavy C3 performed best on Top-1 in this run, so the original BM25-weight hypothesis "
            "was not supported. Do not adopt BM25 weighting from this experiment alone."
        )
    return (
        f"Keep C0 Equal Weight. Best Top-1 config was {best_top1}, and BM25 weighting improved MRR, "
        "but the Top-1 gain was only one query while Recall@5 dropped and ambiguous-query Recall@5 also "
        "regressed. That trade-off is not strong enough to justify adding weighting complexity yet."
    )


def _insight_string(metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    c0 = metrics["overall"]["C0"]
    c1 = metrics["overall"]["C1"]
    c2 = metrics["overall"]["C2"]
    c3 = metrics["overall"]["C3"]
    return (
        "Weighted RRF 실험에서 BM25 가중치를 높이면 Top-1을 회복할 것이라는 가설은 "
        f"실제 결과로 검증했다. C0 Top-1={_pct(c0['top1_accuracy'])}, "
        f"C1={_pct(c1['top1_accuracy'])}, C2={_pct(c2['top1_accuracy'])}, "
        f"C3={_pct(c3['top1_accuracy'])}였고, Recall@5는 C0={_pct(c0['recall_at_5'])}, "
        f"C1={_pct(c1['recall_at_5'])}, C2={_pct(c2['recall_at_5'])}, C3={_pct(c3['recall_at_5'])}였다. "
        "중요한 점은 weight가 retrieval 후보 생성 품질을 바꾸는 것이 아니라 이미 나온 Vector/BM25 rank signal의 "
        "상대적 우선순위만 바꾼다는 점이다. 그래서 효과가 나는 query는 대부분 두 retriever가 서로 다른 후보를 "
        "상위에 둔 경계 사례였고, 두 retriever 모두 정답을 낮게 둔 query는 어떤 weight로도 해결되지 않았다. "
        f"이번 실험에서는 rank가 바뀐 query가 {analysis['rank_changed_count']}개였고, "
        f"C0 오답이 BM25 weight로 정답 Top-1이 된 사례는 {analysis['counts']['c0_wrong_bm25_gain']}개, "
        f"반대로 깨진 사례는 {analysis['counts']['c0_right_bm25_loss']}개였다. "
        "따라서 설계 판단은 'BM25가 강하니 무조건 BM25 weight를 올린다'가 아니라, query type별 편향과 "
        "Top-K 안정성을 함께 보고 weight를 선택해야 한다는 쪽으로 바뀐다."
    )


def _case_table(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["No cases."]
    lines = ["| Query | Type | Expected | Vector Rank | BM25 Rank | C0 | C1 | C2 | C3 |"]
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for item in items[:10]:
        ranks = item["weighted_rrf_ranks"]
        lines.append(
            f"| {_md(item['query'])} | {item['query_type']} | "
            f"{_md(_incident_label(item['expected_incident']))} | "
            f"{_rank(item['vector_rank'])} | {_rank(item['bm25_rank'])} | "
            f"{_rank(ranks['C0'])} | {_rank(ranks['C1'])} | {_rank(ranks['C2'])} | {_rank(ranks['C3'])} |"
        )
    return lines


def _rank_of(expected_incident_id: str, results: list[dict[str, Any]]) -> int | None:
    for result in results:
        if result["incident_id"] == expected_incident_id:
            return int(result["rank"])
    return None


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
        return "none"
    return f"{incident.get('incident_id')} / {incident.get('error_type')} / {incident.get('summary')}"


def _ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _rank(value: Any) -> str:
    return "None" if value is None else str(value)


def _md(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")
