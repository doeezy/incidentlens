from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import Settings
from app.utils.json_schema_strict import strict_object_schema_from_model
from evaluation.common import EVALUATION_DATA_DIR, EVALUATION_RESULTS_DIR, REPORTS_DIR, read_json, utc_now_iso, write_json
from evaluation.datasets.models import LlmGroundTruth, RetrievalDataset
from evaluation.prompts.context import PromptVariant, build_prompt_messages
from evaluation.prompts.metrics import prompt_metrics
from evaluation.reports.prompt_report import write_prompt_report

PROMPT_VARIANTS: list[PromptVariant] = ["prompt_a", "prompt_b", "prompt_c", "prompt_d"]


class EvidenceAnalysis(BaseModel):
    incident_id: str
    summary: str
    weak_or_missing_evidence: str | None = None


class EvidenceUsed(BaseModel):
    incident_id: str
    field: str
    quote_or_summary: str


class PromptOutput(BaseModel):
    selected_incident_id: str | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    hypothesis: str
    evidence_analysis: list[EvidenceAnalysis] = Field(default_factory=list)
    evidence_used: list[EvidenceUsed] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    uncertainty: str | None = None


def run_prompt_experiment(
    *,
    session: Session,
    settings: Settings,
    dataset: RetrievalDataset,
    retrieval_path: Path | None = None,
    ground_truth_path: Path | None = None,
    output_dir: Path | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_output_tokens: int = 1200,
    seed: int | None = None,
    top_k: int = 5,
    pricing_path: Path | None = None,
) -> dict[str, Any]:
    if dataset.status != "frozen":
        raise ValueError("Prompt experiments must use retrieval_queries_frozen.json.")
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run prompt experiments.")

    fixed_retrieval = read_json(
        retrieval_path or EVALUATION_RESULTS_DIR / "retrieval" / "hybrid.json"
    )
    retrieval_by_query_id = {
        case["query_id"]: case["results"][:top_k]
        for case in fixed_retrieval["cases"]
    }
    query_payloads = [query.model_dump() for query in dataset.queries]
    ground_truth = _load_ground_truth(ground_truth_path)
    base_output_dir = output_dir or EVALUATION_RESULTS_DIR / "prompt"
    model_name = model or settings.llm_model_name
    price_config = _load_pricing(pricing_path)

    prompt_payloads: dict[str, dict[str, Any]] = {}
    for variant in PROMPT_VARIANTS:
        cases = []
        for query in query_payloads:
            fixed_results = retrieval_by_query_id.get(query["query_id"], [])
            cases.append(
                _run_one_prompt(
                    session=session,
                    settings=settings,
                    variant=variant,
                    query=query,
                    fixed_results=fixed_results,
                    model=model_name,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    seed=seed,
                )
            )
        metrics = prompt_metrics(cases, ground_truth=ground_truth)
        payload = {
            "experiment": "prompt_context",
            "prompt": variant,
            "generated_at": utc_now_iso(),
            "dataset": {
                "name": dataset.dataset_name,
                "status": dataset.status,
                "query_count": len(dataset.queries),
            },
            "fixed_retrieval": {
                "source_file": str(retrieval_path or EVALUATION_RESULTS_DIR / "retrieval" / "hybrid.json"),
                "method": fixed_retrieval.get("method"),
                "top_k": top_k,
            },
            "parameters": {
                "model": model_name,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "seed": seed,
            },
            "metrics": {
                **metrics,
                "estimated_cost": _estimated_cost(metrics, model_name, price_config),
            },
            "cases": cases,
        }
        prompt_payloads[variant] = payload
        write_json(base_output_dir / f"{variant}.json", payload)

    comparison = compare_prompt_outputs(prompt_payloads)
    write_json(base_output_dir / "context_sensitivity.json", comparison)
    write_prompt_report(
        prompt_payloads=prompt_payloads,
        comparison=comparison,
        output_path=REPORTS_DIR / "prompt_context_experiment.md",
    )
    return {"prompts": prompt_payloads, "context_sensitivity": comparison}


def compare_prompt_outputs(prompt_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_prompt = {
        prompt: {case["query_id"]: case for case in payload["cases"]}
        for prompt, payload in prompt_payloads.items()
    }
    query_ids = sorted(next(iter(by_prompt.values())).keys()) if by_prompt else []
    comparisons = []
    for query_id in query_ids:
        outputs = {
            prompt: by_prompt[prompt][query_id].get("output") or {}
            for prompt in sorted(by_prompt)
        }
        selected = {prompt: output.get("selected_incident_id") for prompt, output in outputs.items()}
        confidences = {
            prompt: output.get("confidence")
            for prompt, output in outputs.items()
            if isinstance(output.get("confidence"), (int, float))
        }
        unsupported_counts = {
            prompt: len(output.get("unsupported_claims") or [])
            for prompt, output in outputs.items()
        }
        comparisons.append(
            {
                "query_id": query_id,
                "selected_incident_by_prompt": selected,
                "selected_incident_changed": len(set(selected.values())) > 1,
                "confidence_by_prompt": confidences,
                "confidence_delta": (max(confidences.values()) - min(confidences.values())) if confidences else None,
                "hypothesis_changed": len({str(output.get("hypothesis")) for output in outputs.values()}) > 1,
                "evidence_changed": len({json.dumps(output.get("evidence_used") or [], sort_keys=True) for output in outputs.values()}) > 1,
                "unsupported_claim_by_prompt": unsupported_counts,
                "unsupported_claim_delta": max(unsupported_counts.values()) - min(unsupported_counts.values()) if unsupported_counts else None,
                "prompts": outputs,
            }
        )
    return {
        "generated_at": utc_now_iso(),
        "query_count": len(comparisons),
        "changed_selection_count": sum(1 for item in comparisons if item["selected_incident_changed"]),
        "changed_hypothesis_count": sum(1 for item in comparisons if item["hypothesis_changed"]),
        "changed_evidence_count": sum(1 for item in comparisons if item["evidence_changed"]),
        "cases": comparisons,
    }


def _run_one_prompt(
    *,
    session: Session,
    settings: Settings,
    variant: PromptVariant,
    query: dict[str, Any],
    fixed_results: list[dict[str, Any]],
    model: str,
    temperature: float,
    max_output_tokens: int,
    seed: int | None,
) -> dict[str, Any]:
    messages, context_fields, context_payload = build_prompt_messages(
        session=session,
        variant=variant,
        query=query,
        retrieval_results=fixed_results,
    )
    started = perf_counter()
    raw_text = None
    prompt_tokens = None
    completion_tokens = None
    parsed_output: dict[str, Any] | None = None
    error_message = None
    try:
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "IncidentLensPromptExperimentOutput",
                    "schema": strict_object_schema_from_model(PromptOutput),
                    "strict": True,
                },
            },
        }
        if seed is not None:
            request["seed"] = seed
        response = OpenAI(api_key=settings.openai_api_key).chat.completions.create(**request)
        raw_text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        parsed_output = PromptOutput.model_validate_json(raw_text).model_dump()
    except (ValidationError, Exception) as exc:
        error_message = str(exc)
    latency_ms = (perf_counter() - started) * 1000.0
    return {
        "query_id": query["query_id"],
        "query_text": query["query_text"],
        "query_type": query["query_type"],
        "expected_incident_id": query["expected_incident_id"],
        "prompt": variant,
        "context_fields": context_fields,
        "fixed_retrieval_results": fixed_results,
        "context_payload": context_payload,
        "schema_compliance": parsed_output is not None,
        "output": parsed_output,
        "raw_output": raw_text,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "error_message": error_message,
        "requires_human_review": True,
    }


def _load_ground_truth(path: Path | None) -> dict[str, dict[str, Any]]:
    ground_truth_path = path or EVALUATION_DATA_DIR / "llm_ground_truth.json"
    if not ground_truth_path.exists():
        return {}
    parsed = LlmGroundTruth.model_validate(read_json(ground_truth_path))
    return {item.query_id: item.model_dump() for item in parsed.items}


def _load_pricing(path: Path | None) -> dict[str, Any]:
    pricing_path = path or Path(__file__).resolve().parents[1] / "config" / "model_pricing.json"
    if not pricing_path.exists():
        return {}
    return read_json(pricing_path)


def _estimated_cost(metrics: dict[str, Any], model: str, price_config: dict[str, Any]) -> dict[str, Any]:
    model_price = price_config.get(model) or price_config.get("default") or {}
    input_per_1m = float(model_price.get("input_per_1m_tokens_usd", 0.0))
    output_per_1m = float(model_price.get("output_per_1m_tokens_usd", 0.0))
    query_count = int(metrics.get("query_count") or 0)
    input_tokens = float(metrics.get("average_input_tokens") or 0.0) * query_count
    output_tokens = float(metrics.get("average_output_tokens") or 0.0) * query_count
    return {
        "currency": "USD",
        "pricing_source": "evaluation/config/model_pricing.json",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": input_tokens / 1_000_000 * input_per_1m,
        "output_cost": output_tokens / 1_000_000 * output_per_1m,
        "total_cost": (input_tokens / 1_000_000 * input_per_1m) + (output_tokens / 1_000_000 * output_per_1m),
    }
