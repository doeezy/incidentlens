from __future__ import annotations

from pathlib import Path
from typing import Any


def write_retrieval_report(
    *,
    method_payloads: dict[str, dict[str, Any]],
    failure_payload: dict[str, Any],
    output_path: Path,
    top_k: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Retrieval Experiment",
        "",
        "## Hypothesis",
        "",
        "IncidentLens 데이터에서 Vector, BM25, Hybrid Retrieval의 안정성이 Query Type에 따라 달라질 수 있다.",
        "",
        "## Setup",
        "",
    ]
    first = next(iter(method_payloads.values()))
    params = first["parameters"]
    lines.extend(
        [
            f"- Query Count: {first['dataset']['query_count']}",
            f"- Top-K / Recall@K: {top_k}",
            f"- Candidate Limit: {params['candidate_limit']}",
            f"- RRF K: {params['rrf_k']}",
            f"- Embedding Model: {params['embedding_model']}",
            "",
            "## Overall Result",
            "",
            f"| Method | Top-1 Accuracy | Recall@{top_k} | MRR | Avg Latency | p50 | p95 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method, payload in method_payloads.items():
        metrics = payload["metrics"]["overall"]
        lines.append(
            "| "
            + " | ".join(
                [
                    method,
                    _fmt(metrics["top1_accuracy"]),
                    _fmt(metrics[f"recall_at_{top_k}"]),
                    _fmt(metrics["mrr"]),
                    _fmt(metrics["average_latency_ms"]),
                    _fmt(metrics["p50_latency_ms"]),
                    _fmt(metrics["p95_latency_ms"]),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Result by Query Type", ""])
    for method, payload in method_payloads.items():
        lines.extend([f"### {method}", ""])
        lines.append(f"| Query Type | Top-1 | Recall@{top_k} | MRR | Avg Latency |")
        lines.append("|---|---:|---:|---:|---:|")
        for query_type, metrics in payload["metrics"]["by_query_type"].items():
            lines.append(
                f"| {query_type} | {_fmt(metrics['top1_accuracy'])} | "
                f"{_fmt(metrics[f'recall_at_{top_k}'])} | {_fmt(metrics['mrr'])} | "
                f"{_fmt(metrics['average_latency_ms'])} |"
            )
        lines.append("")
    lines.extend(["## Failure Analysis", ""])
    for case_type, cases in failure_payload["cases"].items():
        lines.append(f"- {case_type}: {len(cases)}")
    lines.extend(
        [
            "",
            "## Observations",
            "",
            "실험 결과에서 확인 가능한 사실만 수동으로 작성한다.",
            "",
            "## Decision",
            "",
            "정확도, 실패 케이스, latency를 함께 검토한 뒤 선택한다.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)

