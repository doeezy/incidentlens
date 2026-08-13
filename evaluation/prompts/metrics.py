from __future__ import annotations

from typing import Any

from evaluation.common import mean_or_none, percentile, ratio


def prompt_metrics(
    cases: list[dict[str, Any]],
    *,
    ground_truth: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ground_truth = ground_truth or {}
    latencies = [float(case["latency_ms"]) for case in cases if case.get("latency_ms") is not None]
    input_tokens = [float(case["input_tokens"]) for case in cases if case.get("input_tokens") is not None]
    output_tokens = [float(case["output_tokens"]) for case in cases if case.get("output_tokens") is not None]
    schema_ok = [case for case in cases if case.get("schema_compliance")]
    evaluable = [
        case
        for case in cases
        if case.get("query_id") in ground_truth and case.get("schema_compliance")
    ]
    incident_correct = 0
    hypothesis_correct = 0
    unsupported_rates: list[float] = []
    grounded_rates: list[float] = []
    for case in cases:
        output = case.get("output") or {}
        claims = output.get("claims") or []
        unsupported = output.get("unsupported_claims") or []
        if claims:
            unsupported_rates.append(len(unsupported) / len(claims))
        evidence_used = output.get("evidence_used") or []
        if evidence_used:
            grounded_rates.append(
                sum(1 for item in evidence_used if _has_citation(case, item))
                / len(evidence_used)
            )
    for case in evaluable:
        truth = ground_truth[str(case["query_id"])]
        output = case.get("output") or {}
        if output.get("selected_incident_id") == truth.get("expected_incident_id"):
            incident_correct += 1
        expected_root = truth.get("expected_root_cause")
        if expected_root and _contains(output.get("hypothesis"), expected_root):
            hypothesis_correct += 1
    return {
        "query_count": len(cases),
        "schema_compliance": ratio(len(schema_ok), len(cases)),
        "incident_selection_accuracy": ratio(incident_correct, len(evaluable)),
        "hypothesis_accuracy": ratio(hypothesis_correct, len(evaluable)),
        "evidence_groundedness": mean_or_none(grounded_rates),
        "unsupported_claim_rate": mean_or_none(unsupported_rates),
        "average_input_tokens": mean_or_none(input_tokens),
        "average_output_tokens": mean_or_none(output_tokens),
        "average_latency_ms": mean_or_none(latencies),
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
    }


def _has_citation(case: dict[str, Any], item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    incident_id = item.get("incident_id")
    field = item.get("field")
    if not incident_id or not field:
        return False
    candidate_ids = {
        str(candidate.get("incident_id"))
        for candidate in case.get("fixed_retrieval_results", [])
    }
    return str(incident_id) in candidate_ids


def _contains(value: Any, expected: str) -> bool:
    if not isinstance(value, str):
        return False
    return expected.strip().lower() in value.lower()

