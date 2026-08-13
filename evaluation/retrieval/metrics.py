from __future__ import annotations

from collections import defaultdict
from typing import Any

from evaluation.common import mean_or_none, percentile, ratio


def rank_of(expected_incident_id: str, results: list[dict[str, Any]]) -> int | None:
    for item in results:
        if str(item["incident_id"]) == expected_incident_id:
            return int(item["rank"])
    return None


def retrieval_metrics(cases: list[dict[str, Any]], *, recall_k: int = 5) -> dict[str, Any]:
    expected_cases = [case for case in cases if case.get("expected_incident_id")]
    latencies = [float(case["latency_ms"]) for case in cases if case.get("latency_ms") is not None]
    ranks = [case.get("expected_rank") for case in expected_cases]
    return {
        "query_count": len(cases),
        "top1_accuracy": ratio(sum(1 for rank in ranks if rank == 1), len(expected_cases)),
        f"recall_at_{recall_k}": ratio(
            sum(1 for rank in ranks if rank is not None and int(rank) <= recall_k),
            len(expected_cases),
        ),
        "mrr": ratio(
            sum((1.0 / int(rank)) for rank in ranks if rank is not None),
            len(expected_cases),
        ),
        "average_latency_ms": mean_or_none(latencies),
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
    }


def retrieval_metrics_by_query_type(cases: list[dict[str, Any]], *, recall_k: int = 5) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[str(case["query_type"])].append(case)
    return {
        query_type: retrieval_metrics(items, recall_k=recall_k)
        for query_type, items in sorted(grouped.items())
    }

