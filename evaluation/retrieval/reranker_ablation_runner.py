from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.utils.json_schema_strict import strict_object_schema_from_model
from evaluation.common import read_json, utc_now_iso, write_json

QUERY_TYPES = (
    "exact_error",
    "error_type_only",
    "natural_language",
    "cause_keyword",
    "ambiguous",
)


class _RerankedCandidate(BaseModel):
    incident_id: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    reason: str


class _RerankResponse(BaseModel):
    ranked_candidates: list[_RerankedCandidate]


@dataclass(frozen=True)
class _RerankCallResult:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None


def run_reranker_ablation_experiment(
    *,
    settings: Settings,
    input_cases_path: Path = Path("evaluation_result/retrieval_cases.json"),
    input_metrics_path: Path = Path("evaluation_result/retrieval_metrics.json"),
    output_dir: Path = Path("evaluation_result"),
) -> dict[str, Any]:
    baseline_cases = read_json(input_cases_path)
    baseline_metrics = read_json(input_metrics_path)
    hybrid_cases = baseline_cases["hybrid"]
    params = baseline_metrics["parameters"]
    top_k = int(params["top_k"])

    rr0_cases = [_baseline_case(case=case, top_k=top_k) for case in hybrid_cases]
    rr1_cases = []
    for index, case in enumerate(hybrid_cases, start=1):
        rr1_cases.append(
            _rerank_case(
                settings=settings,
                case=case,
                top_k=top_k,
            )
        )
        if index == 1 or index % 10 == 0 or index == len(hybrid_cases):
            print(f"reranked {index}/{len(hybrid_cases)}", flush=True)
    analysis = _build_analysis(rr0_cases=rr0_cases, rr1_cases=rr1_cases)
    pricing = _load_pricing(settings.llm_model_name)
    metrics = {
        "experiment": "reranker_ablation",
        "generated_at": utc_now_iso(),
        "baseline_files": {
            "retrieval_cases": str(input_cases_path),
            "retrieval_metrics": str(input_metrics_path),
        },
        "dataset": baseline_metrics["dataset"],
        "parameters": {
            **params,
            "rr0": "Query Analyzer -> Query Rewrite -> Hybrid Retrieval(Equal Weight RRF)",
            "rr1": "RR0 top_k candidates reranked by LLM; candidate set unchanged.",
            "reranker_model": settings.llm_model_name,
            "reranker_candidate_scope": f"Hybrid retrieval top-{top_k} only",
            "reranker_changes_retrieval_candidates": False,
            "cost_pricing": pricing,
        },
        "overall": {
            "RR0": _metrics(rr0_cases),
            "RR1": _metrics(rr1_cases),
            "delta": _metric_delta(_metrics(rr0_cases), _metrics(rr1_cases)),
        },
        "by_query_type": {
            "RR0": _metrics_by_query_type(rr0_cases),
            "RR1": _metrics_by_query_type(rr1_cases),
            "delta": _metrics_delta_by_query_type(rr0_cases, rr1_cases),
        },
        "latency": {
            "RR0": _latency_metrics(rr0_cases),
            "RR1": _latency_metrics(rr1_cases),
            "delta": _latency_delta(_latency_metrics(rr0_cases), _latency_metrics(rr1_cases)),
        },
        "token_usage": {
            "RR0": _token_metrics(rr0_cases),
            "RR1": _token_metrics(rr1_cases),
            "delta": _token_delta(_token_metrics(rr0_cases), _token_metrics(rr1_cases)),
        },
        "api_cost_usd": {
            "RR0": _cost_metrics(rr0_cases, pricing),
            "RR1": _cost_metrics(rr1_cases, pricing),
            "note": (
                "Cost is null when evaluation/config/model_pricing.json does not "
                "define non-zero pricing for the reranker model."
            ),
        },
    }
    metrics["decision"] = _decision(metrics=metrics, analysis=analysis)
    payload = {"metrics": metrics, "analysis": analysis, "cases": {"RR0": rr0_cases, "RR1": rr1_cases}}

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "reranker_ablation_metrics.json", metrics)
    write_json(
        output_dir / "reranker_ablation_cases.json",
        {
            "analysis": analysis,
            "cases": {
                "RR0": rr0_cases,
                "RR1": rr1_cases,
            },
        },
    )
    _write_summary(
        output_dir / "reranker_ablation_summary.md",
        metrics=metrics,
        analysis=analysis,
    )
    return payload


def _baseline_case(*, case: dict[str, Any], top_k: int) -> dict[str, Any]:
    results = [_normalize_result(result, rank=index) for index, result in enumerate(case["results"][:top_k], start=1)]
    expected_rank = _rank_of(case["expected_incident_id"], results)
    analyzer_latency = case.get("query_analyzer_latency_ms")
    retrieval_latency = case.get("latency_ms")
    total_latency = _sum_or_none([analyzer_latency, retrieval_latency])
    top_result = results[0] if results else None
    return {
        "experiment_group": "RR0",
        "query_id": case["query_id"],
        "query": case["query"],
        "rewritten_query": case["rewritten_query"],
        "query_type": case["query_type"],
        "project_name": case["project_name"],
        "expected_incident_id": case["expected_incident_id"],
        "expected_incident": case.get("expected_incident"),
        "intent": case.get("intent"),
        "analysis_reason": case.get("analysis_reason"),
        "expected_rank": expected_rank,
        "top1_hit": expected_rank == 1,
        "recall_at_3": expected_rank is not None and expected_rank <= 3,
        "recall_at_5": expected_rank is not None and expected_rank <= 5,
        "reciprocal_rank": (1.0 / expected_rank) if expected_rank else 0.0,
        "query_analyzer_latency_ms": analyzer_latency,
        "retrieval_latency_ms": retrieval_latency,
        "reranker_latency_ms": 0.0,
        "total_latency_ms": total_latency,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reranker_status": "not_applied",
        "results": results,
        "top_retrieved_incident_id": top_result["incident_id"] if top_result else None,
        "top_retrieved_incident": top_result.get("incident") if top_result else None,
    }


def _rerank_case(
    *,
    settings: Settings,
    case: dict[str, Any],
    top_k: int,
) -> dict[str, Any]:
    baseline = _baseline_case(case=case, top_k=top_k)
    candidates = baseline["results"]
    started = perf_counter()
    result = _call_reranker_llm(
        settings=settings,
        messages=_rerank_messages(case=case, candidates=candidates),
    )
    reranker_latency_ms = (perf_counter() - started) * 1000.0
    if result is None:
        reranked_results = candidates
        status = "llm_failed_fallback_original_order"
        prompt_tokens = None
        completion_tokens = None
        parsed_items: list[dict[str, Any]] = []
    else:
        try:
            parsed = _RerankResponse.model_validate_json(result.text)
            reranked_results, parsed_items, status = _apply_rerank(
                candidates=candidates,
                parsed=parsed,
            )
        except (ValidationError, json.JSONDecodeError):
            reranked_results = candidates
            parsed_items = []
            status = "parse_failed_fallback_original_order"
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens

    for rank, item in enumerate(reranked_results, start=1):
        item["rank"] = rank
        item["rerank_rank"] = rank
    expected_rank = _rank_of(case["expected_incident_id"], reranked_results)
    analyzer_latency = case.get("query_analyzer_latency_ms")
    retrieval_latency = case.get("latency_ms")
    total_tokens = (
        int(prompt_tokens) + int(completion_tokens)
        if prompt_tokens is not None and completion_tokens is not None
        else None
    )
    top_result = reranked_results[0] if reranked_results else None
    return {
        **baseline,
        "experiment_group": "RR1",
        "expected_rank": expected_rank,
        "top1_hit": expected_rank == 1,
        "recall_at_3": expected_rank is not None and expected_rank <= 3,
        "recall_at_5": expected_rank is not None and expected_rank <= 5,
        "reciprocal_rank": (1.0 / expected_rank) if expected_rank else 0.0,
        "retrieval_latency_ms": retrieval_latency,
        "reranker_latency_ms": reranker_latency_ms,
        "total_latency_ms": _sum_or_none([analyzer_latency, retrieval_latency, reranker_latency_ms]),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reranker_model": settings.llm_model_name,
        "reranker_status": status,
        "reranker_output": parsed_items,
        "results": reranked_results,
        "top_retrieved_incident_id": top_result["incident_id"] if top_result else None,
        "top_retrieved_incident": top_result.get("incident") if top_result else None,
    }


def _call_reranker_llm(
    *,
    settings: Settings,
    messages: list[dict[str, object]],
) -> _RerankCallResult | None:
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=10.0,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=settings.llm_model_name,
            messages=messages,
            max_tokens=700,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "RerankResponse",
                    "schema": strict_object_schema_from_model(_RerankResponse),
                    "strict": True,
                },
            },
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return None
        usage = getattr(response, "usage", None)
        return _RerankCallResult(
            text=text,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
    except Exception as exc:
        print(f"reranker call failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def _rerank_messages(
    *,
    case: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, object]]:
    candidate_lines = []
    for candidate in candidates:
        incident = candidate.get("incident") or {}
        candidate_lines.append(
            {
                "incident_id": candidate["incident_id"],
                "retrieval_rank": candidate["retrieval_rank"],
                "rrf_score": candidate.get("rrf_score"),
                "vector_score": candidate.get("vector_score"),
                "bm25_score": candidate.get("bm25_score"),
                "summary": incident.get("summary"),
                "error_type": incident.get("error_type"),
                "error_message": incident.get("error_message"),
                "module_name": incident.get("module_name"),
                "class_name": incident.get("class_name"),
                "method_name": incident.get("method_name"),
                "keywords": (incident.get("keywords") or [])[:6],
                "domain_tags": incident.get("domain_tags") or [],
                "root_cause": incident.get("root_cause"),
            }
        )
    return [
        {
            "role": "system",
            "content": (
                "You are a strict incident-search reranker. Rerank only the provided "
                "candidate incidents by relevance to the user query. Do not add or drop "
                "candidate IDs. Prefer exact error messages, exception/class/method matches, "
                "then semantic symptom/root-cause similarity. Return every candidate exactly once. "
                "Keep each reason under 12 words."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "query": case["query"],
                    "rewritten_query": case["rewritten_query"],
                    "query_type": case["query_type"],
                    "intent": case.get("intent"),
                    "candidates": candidate_lines,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _apply_rerank(
    *,
    candidates: list[dict[str, Any]],
    parsed: _RerankResponse,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    by_id = {candidate["incident_id"]: candidate for candidate in candidates}
    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    parsed_items: list[dict[str, Any]] = []
    for item in parsed.ranked_candidates:
        if item.incident_id not in by_id or item.incident_id in seen:
            continue
        seen.add(item.incident_id)
        candidate = dict(by_id[item.incident_id])
        candidate["reranker_score"] = item.relevance_score
        candidate["reranker_reason"] = item.reason
        ranked.append(candidate)
        parsed_items.append(item.model_dump())
    for candidate in candidates:
        if candidate["incident_id"] in seen:
            continue
        fallback = dict(candidate)
        fallback["reranker_score"] = None
        fallback["reranker_reason"] = "Missing from reranker output; appended in original retrieval order."
        ranked.append(fallback)
    status = "ok" if len(seen) == len(candidates) else "partial_output_filled_original_order"
    return ranked, parsed_items, status


def _normalize_result(result: dict[str, Any], *, rank: int) -> dict[str, Any]:
    return {
        **result,
        "retrieval_rank": rank,
        "rank": rank,
    }


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(cases)
    ranks = [case.get("expected_rank") for case in cases]
    return {
        "query_count": count,
        "top1_accuracy": _ratio(sum(1 for rank in ranks if rank == 1), count),
        "recall_at_3": _ratio(sum(1 for rank in ranks if rank is not None and rank <= 3), count),
        "recall_at_5": _ratio(sum(1 for rank in ranks if rank is not None and rank <= 5), count),
        "mrr": _ratio(sum((1.0 / int(rank)) for rank in ranks if rank is not None), count),
        "average_retrieval_latency_ms": _mean([case.get("retrieval_latency_ms") for case in cases]),
        "average_reranker_latency_ms": _mean([case.get("reranker_latency_ms") for case in cases]),
        "average_total_latency_ms": _mean([case.get("total_latency_ms") for case in cases]),
    }


def _metrics_by_query_type(cases: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["query_type"]].append(case)
    return {query_type: _metrics(grouped.get(query_type, [])) for query_type in QUERY_TYPES}


def _metric_delta(rr0: dict[str, Any], rr1: dict[str, Any]) -> dict[str, Any]:
    keys = ("top1_accuracy", "recall_at_3", "recall_at_5", "mrr")
    return {key: _delta(rr0.get(key), rr1.get(key)) for key in keys}


def _metrics_delta_by_query_type(
    rr0_cases: list[dict[str, Any]],
    rr1_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    rr0 = _metrics_by_query_type(rr0_cases)
    rr1 = _metrics_by_query_type(rr1_cases)
    return {
        query_type: _metric_delta(rr0[query_type], rr1[query_type])
        for query_type in QUERY_TYPES
    }


def _latency_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "average_query_analyzer_latency_ms": _mean([case.get("query_analyzer_latency_ms") for case in cases]),
        "average_retrieval_latency_ms": _mean([case.get("retrieval_latency_ms") for case in cases]),
        "average_reranker_latency_ms": _mean([case.get("reranker_latency_ms") for case in cases]),
        "average_total_latency_ms": _mean([case.get("total_latency_ms") for case in cases]),
        "p50_reranker_latency_ms": _percentile([case.get("reranker_latency_ms") for case in cases], 0.50),
        "p95_reranker_latency_ms": _percentile([case.get("reranker_latency_ms") for case in cases], 0.95),
    }


def _latency_delta(rr0: dict[str, Any], rr1: dict[str, Any]) -> dict[str, Any]:
    return {key: _delta(rr0.get(key), rr1.get(key)) for key in rr0}


def _token_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "prompt_tokens": _sum_int([case.get("prompt_tokens") for case in cases]),
        "completion_tokens": _sum_int([case.get("completion_tokens") for case in cases]),
        "total_tokens": _sum_int([case.get("total_tokens") for case in cases]),
        "average_prompt_tokens": _mean([case.get("prompt_tokens") for case in cases]),
        "average_completion_tokens": _mean([case.get("completion_tokens") for case in cases]),
        "average_total_tokens": _mean([case.get("total_tokens") for case in cases]),
        "missing_usage_count": sum(1 for case in cases if case.get("total_tokens") is None),
    }


def _token_delta(rr0: dict[str, Any], rr1: dict[str, Any]) -> dict[str, Any]:
    return {key: _delta(rr0.get(key), rr1.get(key)) for key in rr0 if key != "missing_usage_count"}


def _cost_metrics(cases: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    input_price = pricing.get("input_per_1m_tokens_usd")
    output_price = pricing.get("output_per_1m_tokens_usd")
    if not input_price or not output_price:
        return {
            "total_usd": None,
            "average_usd_per_query": None,
            "priced": False,
        }
    prompt_tokens = _sum_int([case.get("prompt_tokens") for case in cases]) or 0
    completion_tokens = _sum_int([case.get("completion_tokens") for case in cases]) or 0
    total = (prompt_tokens / 1_000_000 * float(input_price)) + (
        completion_tokens / 1_000_000 * float(output_price)
    )
    return {
        "total_usd": total,
        "average_usd_per_query": _ratio(total, len(cases)),
        "priced": True,
    }


def _build_analysis(
    *,
    rr0_cases: list[dict[str, Any]],
    rr1_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    rr0_by_id = {case["query_id"]: case for case in rr0_cases}
    rr1_by_id = {case["query_id"]: case for case in rr1_cases}
    rows = []
    changed = []
    no_change = []
    for query_id in sorted(rr0_by_id):
        item = _change_item(rr0_by_id[query_id], rr1_by_id[query_id])
        rows.append(item)
        if item["retrieval_rank"] == item["rerank_rank"]:
            no_change.append(item)
        else:
            changed.append(item)

    rr0_fail_rr1_success = [
        item for item in changed if not item["rr0_top1"] and item["rr1_top1"]
    ]
    rr0_success_rr1_fail = [
        item for item in changed if item["rr0_top1"] and not item["rr1_top1"]
    ]
    rank_only_improved = [
        item for item in changed
        if item["rr0_top1"] == item["rr1_top1"] and _rank_better(item["rerank_rank"], item["retrieval_rank"])
    ]
    rank_only_worsened = [
        item for item in changed
        if item["rr0_top1"] == item["rr1_top1"] and _rank_better(item["retrieval_rank"], item["rerank_rank"])
    ]
    failure_labels = Counter(
        item["failure_reason"]
        for item in rr0_success_rr1_fail
        if item["failure_reason"]
    )
    improvement_labels = Counter(
        item["improvement_reason"]
        for item in rr0_fail_rr1_success + rank_only_improved
        if item["improvement_reason"]
    )
    status_counts = Counter(case.get("reranker_status") for case in rr1_cases)
    return {
        "rank_changed_count": len(changed),
        "no_change_count": len(no_change),
        "rank_changed_queries": changed,
        "rr0_fail_rr1_success": rr0_fail_rr1_success,
        "rr0_success_rr1_fail": rr0_success_rr1_fail,
        "rank_only_improved": rank_only_improved,
        "rank_only_worsened": rank_only_worsened,
        "no_change_examples": no_change[:30],
        "counts": {
            "rr0_fail_rr1_success": len(rr0_fail_rr1_success),
            "rr0_success_rr1_fail": len(rr0_success_rr1_fail),
            "rank_only_improved": len(rank_only_improved),
            "rank_only_worsened": len(rank_only_worsened),
            "no_change": len(no_change),
        },
        "by_query_type_change_counts": _change_counts_by_query_type(rows),
        "improvement_reason_counts": dict(sorted(improvement_labels.items())),
        "failure_reason_counts": dict(sorted(failure_labels.items())),
        "reranker_status_counts": dict(sorted(status_counts.items())),
    }


def _change_item(rr0: dict[str, Any], rr1: dict[str, Any]) -> dict[str, Any]:
    retrieval_rank = rr0["expected_rank"]
    rerank_rank = rr1["expected_rank"]
    return {
        "query_id": rr0["query_id"],
        "query": rr0["query"],
        "rewritten_query": rr0["rewritten_query"],
        "query_type": rr0["query_type"],
        "expected_incident_id": rr0["expected_incident_id"],
        "expected_incident": _compact_incident(rr0.get("expected_incident")),
        "retrieval_rank": retrieval_rank,
        "rerank_rank": rerank_rank,
        "rr0_top1": rr0["top1_hit"],
        "rr1_top1": rr1["top1_hit"],
        "rr0_top_results": [_compact_result(item) for item in rr0["results"][:5]],
        "rr1_top_results": [_compact_result(item) for item in rr1["results"][:5]],
        "improvement_reason": _improvement_reason(rr0, rr1),
        "failure_reason": _failure_reason(rr0, rr1),
    }


def _change_counts_by_query_type(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["query_type"]].append(row)
    output = {}
    for query_type in QUERY_TYPES:
        items = grouped.get(query_type, [])
        output[query_type] = {
            "query_count": len(items),
            "rank_changed": sum(1 for item in items if item["retrieval_rank"] != item["rerank_rank"]),
            "rr0_fail_rr1_success": sum(1 for item in items if not item["rr0_top1"] and item["rr1_top1"]),
            "rr0_success_rr1_fail": sum(1 for item in items if item["rr0_top1"] and not item["rr1_top1"]),
            "rank_only_improved": sum(
                1
                for item in items
                if item["rr0_top1"] == item["rr1_top1"]
                and _rank_better(item["rerank_rank"], item["retrieval_rank"])
            ),
            "rank_only_worsened": sum(
                1
                for item in items
                if item["rr0_top1"] == item["rr1_top1"]
                and _rank_better(item["retrieval_rank"], item["rerank_rank"])
            ),
        }
    return output


def _improvement_reason(rr0: dict[str, Any], rr1: dict[str, Any]) -> str | None:
    if not _rank_better(rr1["expected_rank"], rr0["expected_rank"]):
        return None
    if rr0["expected_rank"] is not None:
        if _top_result_has_keyword_bias(rr0, rr1):
            return "Keyword bias 완화"
        return "Retrieval는 맞았지만 순위만 틀림"
    return "기타"


def _failure_reason(rr0: dict[str, Any], rr1: dict[str, Any]) -> str | None:
    if not _rank_better(rr0["expected_rank"], rr1["expected_rank"]):
        return None
    if rr0["expected_rank"] is None:
        return "Retrieval이 이미 틀림"
    expected = rr0.get("expected_incident") or {}
    if not expected.get("summary") and not expected.get("error_message"):
        return "Evidence 부족"
    if rr1.get("reranker_status") != "ok":
        return "기타"
    return "LLM이 의미를 잘못 이해"


def _top_result_has_keyword_bias(rr0: dict[str, Any], rr1: dict[str, Any]) -> bool:
    before = rr0["results"][0] if rr0.get("results") else {}
    after = rr1["results"][0] if rr1.get("results") else {}
    if after.get("incident_id") != rr0.get("expected_incident_id"):
        return False
    before_incident = before.get("incident") or {}
    expected = rr0.get("expected_incident") or {}
    return before_incident.get("error_type") == expected.get("error_type") and before.get("incident_id") != after.get("incident_id")


def _decision(*, metrics: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    delta = metrics["overall"]["delta"]
    latency_delta = metrics["latency"]["delta"]
    tokens = metrics["token_usage"]["RR1"]
    by_type_delta = metrics["by_query_type"]["delta"]
    top1_delta = delta["top1_accuracy"] or 0.0
    recall_delta = delta["recall_at_5"] or 0.0
    mrr_delta = delta["mrr"] or 0.0
    avg_reranker_ms = metrics["latency"]["RR1"]["average_reranker_latency_ms"] or 0.0
    natural_delta = by_type_delta["natural_language"]["top1_accuracy"] or 0.0
    ambiguous_delta = by_type_delta["ambiguous"]["top1_accuracy"] or 0.0

    if top1_delta > 0.01 and recall_delta >= 0 and mrr_delta >= 0 and avg_reranker_ms < 1500:
        recommendation = "adopt"
        reason = "Top-1/MRR 개선이 latency 비용 대비 충분하고 Recall@5가 후보 고정 조건에서 유지되었다."
    elif natural_delta > 0.03 or ambiguous_delta > 0.03:
        recommendation = "conditional"
        reason = "전체 채택 근거는 약하지만 natural_language 또는 ambiguous query에서 조건부 적용 여지가 있다."
    else:
        recommendation = "do_not_adopt_by_default"
        reason = "품질 개선 폭이 latency/token/cost 증가를 상쇄할 만큼 크지 않다."
    return {
        "recommendation": recommendation,
        "reason": reason,
        "top1_delta": top1_delta,
        "recall_at_5_delta": recall_delta,
        "mrr_delta": mrr_delta,
        "average_reranker_latency_ms": avg_reranker_ms,
        "average_total_latency_delta_ms": latency_delta.get("average_total_latency_ms"),
        "rr1_total_tokens": tokens.get("total_tokens"),
        "conditional_policy_candidate": (
            "Apply reranker only to natural_language/ambiguous queries or when the "
            "top Hybrid scores are close; skip exact_error queries with strong exact matches."
        ),
    }


def _write_summary(path: Path, *, metrics: dict[str, Any], analysis: dict[str, Any]) -> None:
    lines = [
        "# Reranker Ablation",
        "",
        "## Setup",
        "",
        "- RR0: Query Analyzer -> Query Rewrite -> Hybrid Retrieval(Vector + BM25 + Equal Weight RRF).",
        "- RR1: RR0 Hybrid Top-K candidates only -> LLM reranker.",
        "- Evaluation dataset, excluded query handling, Query Analyzer, Query Rewrite, RRF k, embedding model, incident dataset, and Top-K were kept unchanged.",
        "- The reranker only changes candidate order; it does not retrieve new candidates.",
        "",
        "## Metrics 비교",
        "",
        "| Group | Top-1 | Recall@3 | Recall@5 | MRR | Retrieval(ms) | Reranker(ms) | Total(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in ("RR0", "RR1"):
        item = metrics["overall"][group]
        lines.append(
            f"| {group} | {_pct(item['top1_accuracy'])} | {_pct(item['recall_at_3'])} | "
            f"{_pct(item['recall_at_5'])} | {_num(item['mrr'])} | "
            f"{_num(item['average_retrieval_latency_ms'])} | "
            f"{_num(item['average_reranker_latency_ms'])} | "
            f"{_num(item['average_total_latency_ms'])} |"
        )
    delta = metrics["overall"]["delta"]
    lines.extend(
        [
            "",
            f"- Top-1 delta: {_signed_pct(delta['top1_accuracy'])}",
            f"- Recall@3 delta: {_signed_pct(delta['recall_at_3'])}",
            f"- Recall@5 delta: {_signed_pct(delta['recall_at_5'])}",
            f"- MRR delta: {_signed_num(delta['mrr'])}",
            "",
            "## Query Type별 변화",
            "",
            "| Query Type | Count | RR0 Top-1 | RR1 Top-1 | Delta | RR0 Recall@5 | RR1 Recall@5 | MRR Delta | Rank Changed |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for query_type in QUERY_TYPES:
        rr0 = metrics["by_query_type"]["RR0"][query_type]
        rr1 = metrics["by_query_type"]["RR1"][query_type]
        qdelta = metrics["by_query_type"]["delta"][query_type]
        change = analysis["by_query_type_change_counts"][query_type]
        lines.append(
            f"| {query_type} | {rr0['query_count']} | {_pct(rr0['top1_accuracy'])} | "
            f"{_pct(rr1['top1_accuracy'])} | {_signed_pct(qdelta['top1_accuracy'])} | "
            f"{_pct(rr0['recall_at_5'])} | {_pct(rr1['recall_at_5'])} | "
            f"{_signed_num(qdelta['mrr'])} | {change['rank_changed']} |"
        )
    lines.extend(
        [
            "",
            "## Rank 변화",
            "",
            f"- 순위 변경 Query: {analysis['rank_changed_count']}",
            f"- 변화 없음: {analysis['no_change_count']}",
            f"- RR0 실패 -> RR1 성공: {analysis['counts']['rr0_fail_rr1_success']}",
            f"- RR0 성공 -> RR1 실패: {analysis['counts']['rr0_success_rr1_fail']}",
            f"- Rank만 개선: {analysis['counts']['rank_only_improved']}",
            f"- Rank만 악화: {analysis['counts']['rank_only_worsened']}",
            "",
            "## 대표 성공 사례",
            "",
            *_case_table(analysis["rr0_fail_rr1_success"] or analysis["rank_only_improved"]),
            "",
            "## 대표 실패 사례",
            "",
            *_case_table(analysis["rr0_success_rr1_fail"] or analysis["rank_only_worsened"]),
            "",
            "## Latency / Token / Cost 증가",
            "",
        ]
    )
    rr1_tokens = metrics["token_usage"]["RR1"]
    rr1_cost = metrics["api_cost_usd"]["RR1"]
    lines.extend(
        [
            f"- Avg reranker latency: {_num(metrics['latency']['RR1']['average_reranker_latency_ms'])} ms",
            f"- p95 reranker latency: {_num(metrics['latency']['RR1']['p95_reranker_latency_ms'])} ms",
            f"- Prompt tokens: {_num(rr1_tokens['prompt_tokens'])}",
            f"- Completion tokens: {_num(rr1_tokens['completion_tokens'])}",
            f"- Total tokens: {_num(rr1_tokens['total_tokens'])}",
            f"- API cost: {_cost_text(rr1_cost)}",
            "",
            "## 채택 여부",
            "",
            f"- Recommendation: `{metrics['decision']['recommendation']}`",
            f"- Reason: {metrics['decision']['reason']}",
            "",
            "## 조건부 적용 가능성",
            "",
            metrics["decision"]["conditional_policy_candidate"],
            "",
            "## 예상 밖의 결과",
            "",
            _unexpected_result(metrics, analysis),
            "",
            "## AI 엔지니어 면접 / 기술 블로그 인사이트",
            "",
            _insight(metrics, analysis),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _case_table(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["No cases."]
    lines = [
        "| Query | Type | Expected Incident | Retrieval Rank | Rerank Rank | Reason |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in items[:10]:
        reason = item.get("improvement_reason") or item.get("failure_reason") or "기타"
        lines.append(
            f"| {_md(item['query'])} | {item['query_type']} | "
            f"{_md(_incident_label(item.get('expected_incident')))} | "
            f"{_rank(item['retrieval_rank'])} | {_rank(item['rerank_rank'])} | {_md(reason)} |"
        )
    return lines


def _unexpected_result(metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    recall_delta = metrics["overall"]["delta"]["recall_at_5"] or 0.0
    if recall_delta == 0.0:
        return (
            "Recall@5는 변하지 않았다. 이는 reranker가 Top-K 후보 내부 순서만 바꿨기 때문에 "
            "후보 포함 여부 자체를 개선할 수 없다는 실험 설계와 일치한다."
        )
    return (
        "Recall@5가 바뀌었다. Top-K 후보 고정 실험에서 이 변화는 후보 수/평가 rank 계산을 재점검해야 하는 신호다."
    )


def _insight(metrics: dict[str, Any], analysis: dict[str, Any]) -> str:
    rr0 = metrics["overall"]["RR0"]
    rr1 = metrics["overall"]["RR1"]
    return (
        "Reranker ablation의 핵심은 retrieval recall과 ranking quality를 분리해서 보는 것이다. "
        f"이번 실험에서 RR0 Top-1={_pct(rr0['top1_accuracy'])}, RR1 Top-1={_pct(rr1['top1_accuracy'])}, "
        f"RR0 Recall@5={_pct(rr0['recall_at_5'])}, RR1 Recall@5={_pct(rr1['recall_at_5'])}였다. "
        "Top-K 후보만 rerank하면 Recall@5는 구조적으로 거의 변하지 않고, 가치는 Top-1/MRR 개선에서만 나온다. "
        f"하지만 평균 reranker latency가 {_num(metrics['latency']['RR1']['average_reranker_latency_ms'])}ms 추가되므로, "
        "면접이나 블로그에서는 'LLM을 붙였더니 좋아졌다'가 아니라 어떤 query type에서 순위 오류를 고쳤고, "
        "어떤 query type에서는 비용만 늘렸는지를 기준으로 채택/조건부 적용을 설명하는 것이 설득력 있다."
    )


def _load_pricing(model_name: str) -> dict[str, Any]:
    path = Path("evaluation/config/model_pricing.json")
    if not path.exists():
        return {
            "model": model_name,
            "input_per_1m_tokens_usd": None,
            "output_per_1m_tokens_usd": None,
            "source": str(path),
        }
    data = read_json(path)
    item = data.get(model_name) or data.get("default") or {}
    input_price = item.get("input_per_1m_tokens_usd")
    output_price = item.get("output_per_1m_tokens_usd")
    if input_price == 0.0 and output_price == 0.0:
        input_price = None
        output_price = None
    return {
        "model": model_name,
        "input_per_1m_tokens_usd": input_price,
        "output_per_1m_tokens_usd": output_price,
        "source": str(path),
    }


def _rank_of(expected_incident_id: str, results: list[dict[str, Any]]) -> int | None:
    for result in results:
        if result["incident_id"] == expected_incident_id:
            return int(result["rank"])
    return None


def _rank_better(left: int | None, right: int | None) -> bool:
    if left is None:
        return False
    if right is None:
        return True
    return int(left) < int(right)


def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
    incident = item.get("incident") or {}
    return {
        "incident_id": item.get("incident_id"),
        "rank": item.get("rank"),
        "retrieval_rank": item.get("retrieval_rank"),
        "reranker_score": item.get("reranker_score"),
        "rrf_score": item.get("rrf_score"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
        "error_message": incident.get("error_message"),
    }


def _compact_incident(incident: dict[str, Any] | None) -> dict[str, Any] | None:
    if not incident:
        return None
    return {
        "incident_id": incident.get("incident_id"),
        "summary": incident.get("summary"),
        "error_type": incident.get("error_type"),
        "error_message": incident.get("error_message"),
    }


def _incident_label(incident: dict[str, Any] | None) -> str:
    if not incident:
        return "n/a"
    return f"{incident.get('error_type')} / {incident.get('summary')}"


def _sum_or_none(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if len(clean) != len(values):
        return None
    return sum(clean)


def _sum_int(values: list[Any]) -> int | None:
    clean = [int(value) for value in values if value is not None]
    if not clean and any(value is None for value in values):
        return None
    return sum(clean)


def _mean(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _percentile(values: list[Any], pct: float) -> float | None:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    raw_index = (len(clean) - 1) * pct
    lower = int(raw_index)
    upper = min(lower + 1, len(clean) - 1)
    weight = raw_index - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _ratio(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _delta(before: Any, after: Any) -> float | None:
    if before is None or after is None:
        return None
    return float(after) - float(before)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _signed_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:+.2f}pp"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _signed_num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+.4f}"


def _rank(value: Any) -> str:
    return "None" if value is None else str(value)


def _cost_text(cost: dict[str, Any]) -> str:
    if not cost.get("priced"):
        return "n/a (pricing config missing)"
    return f"${float(cost['total_usd']):.6f}"


def _md(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")
