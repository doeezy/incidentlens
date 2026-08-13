from __future__ import annotations

import unittest

from evaluation.retrieval.metrics import retrieval_metrics, retrieval_metrics_by_query_type
from evaluation.retrieval.runner import analyze_retrieval_failures


def _case(query_id: str, query_type: str, expected_rank: int | None, latency_ms: float):
    return {
        "query_id": query_id,
        "query_text": f"query {query_id}",
        "query_type": query_type,
        "expected_incident_id": "incident-ok",
        "expected_rank": expected_rank,
        "latency_ms": latency_ms,
        "results": [
            {
                "incident_id": "incident-ok" if expected_rank == rank else f"incident-{rank}",
                "rank": rank,
                "raw_score": 1.0 / rank,
            }
            for rank in range(1, 6)
        ]
        if expected_rank is not None and expected_rank <= 5
        else [
            {"incident_id": f"incident-{rank}", "rank": rank, "raw_score": 1.0 / rank}
            for rank in range(1, 6)
        ],
    }


class RetrievalFrameworkTest(unittest.TestCase):
    def test_retrieval_metrics_include_top1_recall_mrr_and_latency(self):
        cases = [
            _case("q1", "exact_error", 1, 10.0),
            _case("q2", "natural_language", 3, 20.0),
            _case("q3", "natural_language", None, 30.0),
        ]

        metrics = retrieval_metrics(cases, recall_k=5)

        self.assertEqual(metrics["query_count"], 3)
        self.assertEqual(metrics["top1_accuracy"], 1 / 3)
        self.assertEqual(metrics["recall_at_5"], 2 / 3)
        self.assertEqual(metrics["mrr"], (1 + 1 / 3) / 3)
        self.assertEqual(metrics["average_latency_ms"], 20.0)
        self.assertEqual(metrics["p50_latency_ms"], 20.0)

    def test_retrieval_metrics_are_grouped_by_query_type(self):
        grouped = retrieval_metrics_by_query_type(
            [
                _case("q1", "exact_error", 1, 10.0),
                _case("q2", "natural_language", None, 20.0),
            ],
            recall_k=5,
        )

        self.assertEqual(grouped["exact_error"]["top1_accuracy"], 1.0)
        self.assertEqual(grouped["natural_language"]["top1_accuracy"], 0.0)

    def test_failure_analysis_keeps_method_top_k_details(self):
        payloads = {
            "vector": {"cases": [_case("q1", "ambiguous", None, 12.0)]},
            "bm25": {"cases": [_case("q1", "ambiguous", 1, 7.0)]},
            "hybrid": {"cases": [_case("q1", "ambiguous", 2, 15.0)]},
        }

        failures = analyze_retrieval_failures(payloads, top_k=5)

        cases = failures["bm25_success_vector_failure"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["query_id"], "q1")
        self.assertEqual(cases[0]["methods"]["bm25"]["expected_rank"], 1)
        self.assertEqual(
            cases[0]["methods"]["vector"]["top_k"][0]["incident_id"],
            "incident-1",
        )


if __name__ == "__main__":
    unittest.main()

