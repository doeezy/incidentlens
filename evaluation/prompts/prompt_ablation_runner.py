from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.incident_agent import IncidentAnswerAgent
from app.config import Settings
from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from app.services.retrieval import IncidentRetrievalService
from app.utils.json_schema_strict import strict_object_schema_from_model
from evaluation.common import EVALUATION_DATA_DIR, utc_now_iso, percentile, read_json, write_json

PromptGroup = Literal["A", "B", "C", "D"]
PROMPT_GROUPS: tuple[PromptGroup, ...] = ("A", "B", "C", "D")
QUERY_TYPES = ("exact_error", "error_type_only", "natural_language", "cause_keyword", "ambiguous")

PROMPT_DIR = Path("evaluation/prompts")
GROUND_TRUTH_CANDIDATE_PATH = EVALUATION_DATA_DIR / "prompt_ground_truth_candidate.json"
GROUND_TRUTH_FROZEN_PATH = EVALUATION_DATA_DIR / "prompt_ground_truth_frozen.json"
RETRIEVAL_SNAPSHOT_PATH = EVALUATION_DATA_DIR / "prompt_retrieval_snapshot.json"
OUTPUTS_PATH = Path("evaluation_result/prompt_ablation_outputs.json")
METRICS_PATH = Path("evaluation_result/prompt_ablation_metrics.json")
CASES_PATH = Path("evaluation_result/prompt_ablation_cases.json")
SUMMARY_PATH = Path("evaluation_result/prompt_ablation_summary.md")


class AnswerabilityOutput(BaseModel):
    root_cause: bool
    resolution: bool


class PromptAnswer(BaseModel):
    selected_incident_id: str | None = None
    answerability: AnswerabilityOutput
    error_type: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    supporting_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    notes: str | None = None


class JudgeOutput(BaseModel):
    groundedness_score: float = Field(..., ge=0.0, le=1.0)
    total_claim_count: int = Field(..., ge=0)
    unsupported_claim_count: int = Field(..., ge=0)
    unsupported_claims: list[str] = Field(default_factory=list)
    root_cause_hallucinated: bool
    resolution_hallucinated: bool
    resolution_correct: bool | None = None
    failure_reason: str | None = None


PROMPT_TEMPLATES = {
    "A": {
        "path": PROMPT_DIR / "prompt_a.txt",
        "system": (
            "You are IncidentLens. Return JSON only. Use the supplied candidate incidents."
        ),
        "user": (
            "User Query:\n{query_json}\n\n"
            "Retrieved Incident Candidates:\n{candidates_json}\n\n"
            "Pick the most relevant incident and return this JSON shape:\n"
            "{output_schema_json}"
        ),
    },
    "B": {
        "path": PROMPT_DIR / "prompt_b.txt",
        "system": (
            "You are IncidentLens, an internal incident search answer evaluator. "
            "Return JSON only and follow the requested schema exactly."
        ),
        "user": (
            "ROLE\n"
            "Incident relevance and grounded-answer judge.\n\n"
            "TASK\n"
            "Select the retrieved incident that is best supported by the user's query and answer only within the supplied evidence.\n\n"
            "RULES\n"
            "- Use only the provided Incident candidate information as evidence.\n"
            "- Do not invent or confirm a Root Cause when root_cause evidence is not provided.\n"
            "- If the supplied information is insufficient, mark the corresponding answerability field as false.\n"
            "- Rank incidents by direct query evidence: exact error, exception, class/method/API, feature, symptom, then supporting technical keywords.\n"
            "- Treat retrieval scores as ranking hints, not as ground truth.\n"
            "- Incidents unrelated to the query must be evaluated low even if they have high retrieval rank.\n"
            "- Output must comply with the schema.\n\n"
            "USER QUERY\n{query_json}\n\n"
            "EVIDENCE\n{candidates_json}\n\n"
            "OUTPUT SCHEMA\n{output_schema_json}"
        ),
    },
    "C": {
        "path": PROMPT_DIR / "prompt_c.txt",
        "system": (
            "You are IncidentLens, an evidence-first incident search evaluator. "
            "Return JSON only. Do not reveal hidden chain-of-thought."
        ),
        "user": (
            "FLOW\n"
            "1. Identify observable facts from the user query.\n"
            "2. Inspect supporting evidence for each candidate.\n"
            "3. Inspect contradictory or irrelevant evidence for each candidate.\n"
            "4. Compare candidates using only supplied evidence.\n"
            "5. Select the final incident.\n"
            "6. Answer only fields that are answerable from the supplied evidence.\n\n"
            "IMPORTANT\n"
            "- Do not expose private reasoning or chain-of-thought.\n"
            "- supporting_evidence must contain only concise user-verifiable evidence strings copied or summarized from supplied candidate fields.\n"
            "- Do not invent Root Cause, missing services, classes, configuration, or resolution details.\n"
            "- If Root Cause is not explicitly present, set answerability.root_cause=false and root_cause=null.\n"
            "- If Resolution is not explicitly present, set answerability.resolution=false and resolution=null.\n\n"
            "USER QUERY\n{query_json}\n\n"
            "CANDIDATE EVIDENCE\n{candidates_json}\n\n"
            "OUTPUT SCHEMA\n{output_schema_json}"
        ),
    },
    "D": {
        "path": PROMPT_DIR / "prompt_d.txt",
        "system": (
            "You are IncidentLens using compressed incident context. "
            "Return JSON only and do not infer omitted details."
        ),
        "user": (
            "ROLE\n"
            "Incident relevance judge using compressed context.\n\n"
            "TASK\n"
            "Select the best incident while using only compact fields needed for judgment.\n\n"
            "COMPRESSION POLICY\n"
            "- The context intentionally removes duplicate metadata and long raw records.\n"
            "- Compression does not add new facts.\n"
            "- Use only summary, primary_error_type, primary_error_message, suspected_cause, resolution_summary, key evidence, and retrieval scores.\n\n"
            "RULES\n"
            "- Do not invent information that may have been omitted by compression.\n"
            "- If compact evidence is insufficient for Root Cause or Resolution, mark that field unanswerable.\n"
            "- Every non-null answer must be supported by the compact context.\n"
            "- Output must comply with the schema.\n\n"
            "USER QUERY\n{query_json}\n\n"
            "COMPRESSED CANDIDATE EVIDENCE\n{candidates_json}\n\n"
            "OUTPUT SCHEMA\n{output_schema_json}"
        ),
    },
}

JUDGE_TEMPLATE = {
    "path": PROMPT_DIR / "judge_prompt.txt",
    "system": (
        "You are a strict evaluator for IncidentLens prompt experiments. Return JSON only."
    ),
    "user": (
        "Evaluate whether the model output is grounded in the supplied retrieval context and ground truth.\n\n"
        "RULES\n"
        "- A claim is grounded only if it is directly supported by supplied candidate context or ground truth fields.\n"
        "- Do not reward plausible but unstated Root Cause or Resolution claims.\n"
        "- If ground_truth.root_cause_answerability=false, any non-null root_cause or answerability.root_cause=true is a hallucination.\n"
        "- If ground_truth.resolution_answerability=false, any non-null resolution or answerability.resolution=true is a hallucination.\n"
        "- If resolution is answerable, resolution_correct should be true only when the output resolution matches the stored resolution in meaning.\n"
        "- Count concise factual claims in the output and count unsupported claims.\n\n"
        "QUERY\n{query_json}\n\n"
        "GROUND TRUTH\n{ground_truth_json}\n\n"
        "RETRIEVAL CONTEXT\n{candidates_json}\n\n"
        "MODEL OUTPUT\n{output_json}\n\n"
        "OUTPUT SCHEMA\n{judge_schema_json}"
    ),
}


def run_prompt_ablation_experiment(
    *,
    session: Session,
    settings: Settings,
    candidate_path: Path = GROUND_TRUTH_CANDIDATE_PATH,
    frozen_path: Path = GROUND_TRUTH_FROZEN_PATH,
    snapshot_path: Path = RETRIEVAL_SNAPSHOT_PATH,
    output_dir: Path = Path("evaluation_result"),
    model: str | None = None,
    judge_model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 900,
    retrieval_top_k: int = 5,
    candidate_limit: int = 20,
    rrf_k: int = 60,
    run_judge: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_prompt_template_files()
    frozen_payload = freeze_prompt_ground_truth(
        candidate_path=candidate_path,
        frozen_path=frozen_path,
    )
    snapshot_payload = create_prompt_retrieval_snapshot(
        session=session,
        settings=settings,
        frozen_payload=frozen_payload,
        snapshot_path=snapshot_path,
        top_k=retrieval_top_k,
        candidate_limit=candidate_limit,
        rrf_k=rrf_k,
    )
    outputs = _load_or_init_outputs(
        model=model or settings.llm_model_name,
        judge_model=judge_model or settings.llm_model_name,
        frozen_path=frozen_path,
        snapshot_path=snapshot_path,
        run_judge=run_judge,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    client = OpenAI(api_key=settings.openai_api_key, timeout=40.0, max_retries=0)
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for Prompt A/B/C/D evaluation.")

    frozen_by_id = {item["query_id"]: item for item in frozen_payload["items"]}
    snapshot_by_id = {item["query_id"]: item for item in snapshot_payload["items"]}
    for group in PROMPT_GROUPS:
        completed = {case["query_id"] for case in outputs["groups"].setdefault(group, [])}
        for index, truth in enumerate(frozen_payload["items"], start=1):
            if truth["query_id"] in completed:
                continue
            snapshot = snapshot_by_id[truth["query_id"]]
            case = _run_one_case(
                client=client,
                group=group,
                model=model or settings.llm_model_name,
                judge_model=judge_model or settings.llm_model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                truth=truth,
                snapshot=snapshot,
                run_judge=run_judge,
            )
            outputs["groups"][group].append(case)
            outputs["updated_at"] = utc_now_iso()
            write_json(output_dir / "prompt_ablation_outputs.json", outputs)
            done = len(outputs["groups"][group])
            if done == 1 or done % 10 == 0 or done == len(frozen_payload["items"]):
                print(f"prompt {group} completed {done}/{len(frozen_payload['items'])}", flush=True)

    evaluated = _evaluate_outputs(
        outputs=outputs,
        frozen_by_id=frozen_by_id,
    )
    metrics = _build_metrics(
        evaluated=evaluated,
        frozen_payload=frozen_payload,
        snapshot_payload=snapshot_payload,
        model=model or settings.llm_model_name,
        judge_model=judge_model or settings.llm_model_name,
        run_judge=run_judge,
        temperature=temperature,
        max_tokens=max_tokens,
        pricing_path=Path("evaluation/config/model_pricing.json"),
    )
    cases = _build_case_analysis(evaluated=evaluated, frozen_by_id=frozen_by_id, snapshot_by_id=snapshot_by_id)
    write_json(output_dir / "prompt_ablation_metrics.json", metrics)
    write_json(output_dir / "prompt_ablation_cases.json", cases)
    _write_summary(output_dir / "prompt_ablation_summary.md", metrics=metrics, cases=cases)
    return {
        "frozen": frozen_payload,
        "snapshot": snapshot_payload,
        "outputs": outputs,
        "metrics": metrics,
        "cases": cases,
    }


def freeze_prompt_ground_truth(*, candidate_path: Path, frozen_path: Path) -> dict[str, Any]:
    candidate = read_json(candidate_path)
    reviewed = [
        item
        for item in candidate.get("items", [])
        if item.get("reviewed_by_human") is True and not item.get("excluded")
    ]
    frozen_items = []
    for item in reviewed:
        frozen = dict(item)
        for key in ("reviewed_by_human", "review_note", "excluded", "exclude_reason"):
            frozen.pop(key, None)
        frozen_items.append(frozen)
    payload = {
        "dataset_name": "prompt_ground_truth",
        "status": "frozen",
        "generated_at": candidate.get("generated_at"),
        "frozen_at": utc_now_iso(),
        "source": {
            "candidate_path": str(candidate_path),
            "candidate_item_count": len(candidate.get("items", [])),
            "reviewed_by_human_true_count": sum(
                1 for item in candidate.get("items", []) if item.get("reviewed_by_human") is True
            ),
            "excluded_reviewed_count": sum(
                1
                for item in candidate.get("items", [])
                if item.get("reviewed_by_human") is True and item.get("excluded")
            ),
            "freeze_policy": "include reviewed_by_human=true and excluded=false only",
            "removed_human_review_fields": [
                "reviewed_by_human",
                "review_note",
                "excluded",
                "exclude_reason",
            ],
        },
        "items": frozen_items,
    }
    write_json(frozen_path, payload)
    return payload


def create_prompt_retrieval_snapshot(
    *,
    session: Session,
    settings: Settings,
    frozen_payload: dict[str, Any],
    snapshot_path: Path,
    top_k: int,
    candidate_limit: int,
    rrf_k: int,
) -> dict[str, Any]:
    retrieval_service = IncidentRetrievalService.from_session(session=session, settings=settings)
    agent = IncidentAnswerAgent(settings=settings, retrieval_service=retrieval_service)
    items = []
    for index, truth in enumerate(frozen_payload["items"], start=1):
        started = perf_counter()
        analysis = agent.analyze_query(truth["query_text"])
        analyzer_latency_ms = (perf_counter() - started) * 1000.0
        rewritten_query = analysis.rewritten_query or truth["query_text"]
        started = perf_counter()
        candidates = retrieval_service.search_hybrid_candidates_for_evaluation(
            query=rewritten_query,
            limit=top_k,
            candidate_limit=candidate_limit,
            rrf_k=rrf_k,
            project_name=truth["project_name"],
        )
        retrieval_latency_ms = (perf_counter() - started) * 1000.0
        candidate_payloads = [
            _snapshot_candidate(
                session=session,
                rank=rank,
                candidate=candidate,
            )
            for rank, candidate in enumerate(candidates, start=1)
        ]
        expected_rank = _rank_of(truth["expected_incident_id"], candidate_payloads)
        items.append(
            {
                "query_id": truth["query_id"],
                "query_text": truth["query_text"],
                "query_type": truth.get("query_type"),
                "project_name": truth["project_name"],
                "expected_incident_id": truth["expected_incident_id"],
                "rewritten_query": rewritten_query,
                "retrieval_policy": {
                    "query_analyzer": "IncidentAnswerAgent.analyze_query",
                    "query_rewrite": "QueryAnalysis.rewritten_query",
                    "retrieval": "Equal Weight Hybrid Retrieval(Vector + BM25 + RRF)",
                    "top_k": top_k,
                    "candidate_limit": candidate_limit,
                    "rrf_k": rrf_k,
                    "embedding_model": settings.embedding_model_name,
                },
                "query_analyzer_latency_ms": analyzer_latency_ms,
                "retrieval_latency_ms": retrieval_latency_ms,
                "expected_incident_rank": expected_rank,
                "retrieved_candidates": candidate_payloads,
            }
        )
        if index == 1 or index % 25 == 0 or index == len(frozen_payload["items"]):
            print(f"retrieval snapshot {index}/{len(frozen_payload['items'])}", flush=True)
    payload = {
        "dataset_name": "prompt_retrieval_snapshot",
        "status": "snapshot",
        "generated_at": utc_now_iso(),
        "source": {
            "ground_truth_frozen_path": str(GROUND_TRUTH_FROZEN_PATH),
            "query_count": len(frozen_payload["items"]),
            "candidate_order_fixed": True,
        },
        "items": items,
    }
    write_json(snapshot_path, payload)
    return payload


def _snapshot_candidate(*, session: Session, rank: int, candidate: Any) -> dict[str, Any]:
    incident = session.get(Incident, candidate.incident_id)
    if incident is None:
        return {"rank": rank, "incident_id": str(candidate.incident_id), "supported_context_fields": {}}
    logs = list(
        session.scalars(
            select(RawLog).where(RawLog.incident_id == incident.id).order_by(RawLog.occurred_at.asc()).limit(2)
        )
    )
    tickets = list(
        session.scalars(
            select(RawTicket).where(RawTicket.incident_id == incident.id).order_by(RawTicket.ticket_created_at.asc()).limit(2)
        )
    )
    prs = list(
        session.scalars(
            select(RawPr).where(RawPr.incident_id == incident.id).order_by(RawPr.pr_created_at.asc()).limit(2)
        )
    )
    context = {
        "summary": incident.primary_error_summary,
        "primary_error_type": incident.primary_error_type,
        "primary_error_message": incident.primary_error_message,
        "module_name": incident.module_name,
        "class_name": incident.class_name,
        "method_name": incident.method_name,
        "error_keywords": incident.error_keywords or [],
        "domain_tags": incident.domain_tags or [],
        "suspected_cause": incident.suspected_cause,
        "root_cause_summary": incident.root_cause_summary,
        "resolution_summary": incident.resolution_summary,
        "raw_logs": [
            {
                "error_type": log.error_type,
                "error_message": log.error_message,
                "summary": log.normalized_summary,
                "keywords": log.extracted_keywords or [],
            }
            for log in logs
        ],
        "raw_tickets": [
            {
                "ticket_key": ticket.ticket_key,
                "title": ticket.title,
                "summary": ticket.normalized_summary,
                "suspected_cause": ticket.suspected_cause,
                "resolution_note": ticket.resolution_note,
            }
            for ticket in tickets
        ],
        "raw_prs": [
            {
                "pr_key": pr.pr_key,
                "title": pr.title,
                "diff_summary": pr.diff_summary,
                "suspected_fix_for": pr.suspected_fix_for,
                "resolution_note": pr.resolution_note,
            }
            for pr in prs
        ],
    }
    return {
        "rank": rank,
        "incident_id": str(candidate.incident_id),
        "summary": incident.primary_error_summary,
        "primary_error_type": incident.primary_error_type,
        "primary_error_message": incident.primary_error_message,
        "retrieval_score": candidate.raw_score,
        "vector_score": candidate.vector_score,
        "bm25_score": candidate.bm25_score,
        "rrf_score": candidate.rrf_score,
        "supported_context_fields": context,
    }


def _run_one_case(
    *,
    client: OpenAI,
    group: PromptGroup,
    model: str,
    judge_model: str,
    temperature: float,
    max_tokens: int,
    truth: dict[str, Any],
    snapshot: dict[str, Any],
    run_judge: bool,
) -> dict[str, Any]:
    candidates = _prompt_candidates(group=group, snapshot=snapshot)
    query_payload = {
        "query_id": truth["query_id"],
        "query_text": truth["query_text"],
        "query_type": truth.get("query_type"),
    }
    messages = _prompt_messages(group=group, query=query_payload, candidates=candidates)
    started = perf_counter()
    raw_output = None
    output = None
    prompt_tokens = None
    completion_tokens = None
    error_message = None
    try:
        request = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if group == "A":
            request["response_format"] = {"type": "json_object"}
        else:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "PromptAnswer",
                    "schema": strict_object_schema_from_model(PromptAnswer),
                    "strict": True,
                },
            }
        response = client.chat.completions.create(**request)
        raw_output = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        output = PromptAnswer.model_validate_json(raw_output).model_dump()
    except (ValidationError, json.JSONDecodeError, Exception) as exc:
        error_message = f"{type(exc).__name__}: {exc}"
    latency_ms = (perf_counter() - started) * 1000.0
    judge = None
    if run_judge and output is not None:
        judge = _run_judge(
            client=client,
            model=judge_model,
            truth=truth,
            snapshot=snapshot,
            candidates=candidates,
            output=output,
        )
    return {
        "query_id": truth["query_id"],
        "query_text": truth["query_text"],
        "query_type": truth.get("query_type"),
        "expected_incident_id": truth["expected_incident_id"],
        "prompt_group": group,
        "prompt_file": str(PROMPT_TEMPLATES[group]["path"]),
        "schema_compliance": output is not None,
        "output": output,
        "raw_output": raw_output,
        "judge": judge,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": _sum_optional(prompt_tokens, completion_tokens),
        "latency_ms": latency_ms,
        "error_message": error_message,
    }


def _run_judge(
    *,
    client: OpenAI,
    model: str,
    truth: dict[str, Any],
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    output: dict[str, Any],
) -> dict[str, Any] | None:
    messages = [
        {"role": "system", "content": JUDGE_TEMPLATE["system"]},
        {
            "role": "user",
            "content": JUDGE_TEMPLATE["user"].format(
                query_json=_json({"query_id": truth["query_id"], "query_text": truth["query_text"]}),
                ground_truth_json=_json(truth),
                candidates_json=_json(candidates),
                output_json=_json(output),
                judge_schema_json=_json(_judge_schema_description()),
            ),
        },
    ]
    started = perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=600,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "JudgeOutput",
                    "schema": strict_object_schema_from_model(JudgeOutput),
                    "strict": True,
                },
            },
        )
        raw_text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        parsed = JudgeOutput.model_validate_json(raw_text).model_dump()
        return {
            **parsed,
            "raw_output": raw_text,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": _sum_optional(
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            ),
            "latency_ms": (perf_counter() - started) * 1000.0,
            "error_message": None,
        }
    except (ValidationError, json.JSONDecodeError, Exception) as exc:
        return {
            "groundedness_score": None,
            "total_claim_count": None,
            "unsupported_claim_count": None,
            "unsupported_claims": [],
            "root_cause_hallucinated": None,
            "resolution_hallucinated": None,
            "resolution_correct": None,
            "failure_reason": None,
            "raw_output": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "latency_ms": (perf_counter() - started) * 1000.0,
            "error_message": f"{type(exc).__name__}: {exc}",
        }


def _evaluate_outputs(
    *,
    outputs: dict[str, Any],
    frozen_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    evaluated: dict[str, list[dict[str, Any]]] = {}
    for group, cases in outputs["groups"].items():
        evaluated[group] = []
        for case in cases:
            truth = frozen_by_id[case["query_id"]]
            output = case.get("output") or {}
            answerability = output.get("answerability") or {}
            judge = case.get("judge") or {}
            schema_ok = bool(case.get("schema_compliance"))
            incident_correct = schema_ok and output.get("selected_incident_id") == truth["expected_incident_id"]
            error_type_correct = schema_ok and _norm(output.get("error_type")) == _norm(truth.get("expected_error_type"))
            root_answerability_correct = schema_ok and answerability.get("root_cause") == truth.get("root_cause_answerability")
            resolution_answerability_correct = schema_ok and answerability.get("resolution") == truth.get("resolution_answerability")
            root_hallucinated = _bool_or_fallback(
                judge.get("root_cause_hallucinated"),
                bool(not truth.get("root_cause_answerability") and (output.get("root_cause") or answerability.get("root_cause"))),
            )
            resolution_hallucinated = _bool_or_fallback(
                judge.get("resolution_hallucinated"),
                bool(not truth.get("resolution_answerability") and (output.get("resolution") or answerability.get("resolution"))),
            )
            resolution_correct = None
            if truth.get("resolution_answerability"):
                resolution_correct = _bool_or_fallback(
                    judge.get("resolution_correct"),
                    _contains_meaning(output.get("resolution"), truth.get("resolution_summary")),
                )
            unsupported_rate = _unsupported_rate(case)
            groundedness = judge.get("groundedness_score")
            if groundedness is None:
                groundedness = max(0.0, 1.0 - unsupported_rate) if schema_ok else 0.0
            overall_success = (
                incident_correct
                and error_type_correct
                and root_answerability_correct
                and resolution_answerability_correct
                and not root_hallucinated
                and not resolution_hallucinated
            )
            evaluated[group].append(
                {
                    **case,
                    "evaluation": {
                        "truth_root_cause_answerability": truth.get("root_cause_answerability"),
                        "truth_resolution_answerability": truth.get("resolution_answerability"),
                        "incident_selection_correct": incident_correct,
                        "error_type_correct": error_type_correct,
                        "root_cause_answerability_correct": root_answerability_correct,
                        "resolution_answerability_correct": resolution_answerability_correct,
                        "answerability_correct": root_answerability_correct and resolution_answerability_correct,
                        "root_cause_hallucinated": root_hallucinated,
                        "resolution_hallucinated": resolution_hallucinated,
                        "resolution_correct": resolution_correct,
                        "groundedness_score": groundedness,
                        "unsupported_claim_rate": unsupported_rate,
                        "overall_success": overall_success,
                        "failure_reason": _failure_reason(
                            incident_correct=incident_correct,
                            error_type_correct=error_type_correct,
                            root_answerability_correct=root_answerability_correct,
                            resolution_answerability_correct=resolution_answerability_correct,
                            root_hallucinated=root_hallucinated,
                            resolution_hallucinated=resolution_hallucinated,
                            schema_ok=schema_ok,
                        ),
                    },
                }
            )
    return evaluated


def _build_metrics(
    *,
    evaluated: dict[str, list[dict[str, Any]]],
    frozen_payload: dict[str, Any],
    snapshot_payload: dict[str, Any],
    model: str,
    judge_model: str,
    run_judge: bool,
    temperature: float,
    max_tokens: int,
    pricing_path: Path,
) -> dict[str, Any]:
    pricing = read_json(pricing_path)
    overall = {group: _metrics_for_cases(cases, pricing=pricing, model=model) for group, cases in evaluated.items()}
    by_query_type = {
        group: _metrics_by_query_type(cases, pricing=pricing, model=model)
        for group, cases in evaluated.items()
    }
    return {
        "experiment": "prompt_ablation_abcd",
        "generated_at": utc_now_iso(),
        "dataset": {
            "ground_truth_frozen_path": str(GROUND_TRUTH_FROZEN_PATH),
            "retrieval_snapshot_path": str(RETRIEVAL_SNAPSHOT_PATH),
            "frozen_item_count": len(frozen_payload["items"]),
            "retrieval_snapshot_count": len(snapshot_payload["items"]),
        },
        "parameters": {
            "model": model,
            "judge_model": judge_model if run_judge else None,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "prompt_files": {group: str(PROMPT_TEMPLATES[group]["path"]) for group in PROMPT_GROUPS},
            "judge_prompt_file": str(JUDGE_TEMPLATE["path"]) if run_judge else None,
            "pricing_path": str(pricing_path),
        },
        "overall": overall,
        "by_query_type": by_query_type,
        "decision": _decision(overall),
    }


def _metrics_for_cases(
    cases: list[dict[str, Any]],
    *,
    pricing: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    count = len(cases)
    evals = [case["evaluation"] for case in cases]
    resolution_answerable = [case for case in cases if _truth_resolution_answerable(case)]
    high_conf = [
        case
        for case in cases
        if isinstance((case.get("output") or {}).get("confidence"), (int, float))
        and float((case.get("output") or {}).get("confidence")) >= 0.8
    ]
    prompt_tokens = _sum_int(case.get("prompt_tokens") for case in cases)
    completion_tokens = _sum_int(case.get("completion_tokens") for case in cases)
    judge_prompt_tokens = _sum_int((case.get("judge") or {}).get("prompt_tokens") for case in cases)
    judge_completion_tokens = _sum_int((case.get("judge") or {}).get("completion_tokens") for case in cases)
    total_prompt_tokens = prompt_tokens + judge_prompt_tokens
    total_completion_tokens = completion_tokens + judge_completion_tokens
    latency_values = [float(case["latency_ms"]) for case in cases if case.get("latency_ms") is not None]
    judge_latency_values = [
        float((case.get("judge") or {}).get("latency_ms"))
        for case in cases
        if (case.get("judge") or {}).get("latency_ms") is not None
    ]
    return {
        "query_count": count,
        "incident_selection_accuracy": _ratio(sum(e["incident_selection_correct"] for e in evals), count),
        "error_type_accuracy": _ratio(sum(e["error_type_correct"] for e in evals), count),
        "answerability_accuracy": _ratio(sum(e["answerability_correct"] for e in evals), count),
        "root_cause_answerability_accuracy": _ratio(sum(e["root_cause_answerability_correct"] for e in evals), count),
        "resolution_answerability_accuracy": _ratio(sum(e["resolution_answerability_correct"] for e in evals), count),
        "groundedness": _mean(e["groundedness_score"] for e in evals),
        "unsupported_claim_rate": _mean(e["unsupported_claim_rate"] for e in evals),
        "root_cause_hallucination_rate": _ratio(sum(e["root_cause_hallucinated"] for e in evals), count),
        "resolution_hallucination_rate": _ratio(sum(e["resolution_hallucinated"] for e in evals), count),
        "resolution_accuracy": _ratio(
            sum(1 for case in resolution_answerable if case["evaluation"]["resolution_correct"] is True),
            len(resolution_answerable),
        ),
        "schema_compliance": _ratio(sum(case["schema_compliance"] for case in cases), count),
        "confidence_calibration": _confidence_calibration(cases=cases, high_conf=high_conf),
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "judge_prompt_tokens": judge_prompt_tokens,
            "judge_completion_tokens": judge_completion_tokens,
            "judge_total_tokens": judge_prompt_tokens + judge_completion_tokens,
            "combined_prompt_tokens": total_prompt_tokens,
            "combined_completion_tokens": total_completion_tokens,
            "combined_total_tokens": total_prompt_tokens + total_completion_tokens,
        },
        "latency": {
            "average_llm_latency_ms": _mean(latency_values),
            "p50_llm_latency_ms": percentile(latency_values, 0.50),
            "p95_llm_latency_ms": percentile(latency_values, 0.95),
            "average_judge_latency_ms": _mean(judge_latency_values),
        },
        "cost": _cost(
            pricing=pricing,
            model=model,
            input_tokens=total_prompt_tokens,
            output_tokens=total_completion_tokens,
            query_count=count,
        ),
    }


def _metrics_by_query_type(
    cases: list[dict[str, Any]],
    *,
    pricing: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case.get("query_type")].append(case)
    return {
        query_type: _metrics_for_cases(grouped.get(query_type, []), pricing=pricing, model=model)
        for query_type in QUERY_TYPES
    }


def _build_case_analysis(
    *,
    evaluated: dict[str, list[dict[str, Any]]],
    frozen_by_id: dict[str, dict[str, Any]],
    snapshot_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    by_group = {
        group: {case["query_id"]: case for case in cases}
        for group, cases in evaluated.items()
    }
    query_ids = sorted(frozen_by_id)
    rows = []
    for query_id in query_ids:
        row = {
            "query_id": query_id,
            "query": frozen_by_id[query_id]["query_text"],
            "query_type": frozen_by_id[query_id].get("query_type"),
            "expected_incident_id": frozen_by_id[query_id]["expected_incident_id"],
            "ground_truth": frozen_by_id[query_id],
            "retrieval_candidates": [
                {
                    "rank": candidate["rank"],
                    "incident_id": candidate["incident_id"],
                    "summary": candidate.get("summary"),
                    "error_type": candidate.get("primary_error_type"),
                }
                for candidate in snapshot_by_id[query_id]["retrieved_candidates"]
            ],
            "prompts": {
                group: _compact_case(by_group[group][query_id])
                for group in PROMPT_GROUPS
                if query_id in by_group[group]
            },
        }
        rows.append(row)
    cases = {
        "a_fail_b_success": [
            row for row in rows if _incident_fail(row, "A") and _incident_success(row, "B")
        ],
        "b_fail_c_success": [
            row for row in rows if _incident_fail(row, "B") and _incident_success(row, "C")
        ],
        "ab_root_hallucinated_c_not": [
            row
            for row in rows
            if (
                _root_hallucinated(row, "A") or _root_hallucinated(row, "B")
            )
            and not _root_hallucinated(row, "C")
        ],
        "full_success_compressed_fail": [
            row for row in rows if _overall_success(row, "B") and not _overall_success(row, "D")
        ],
        "full_fail_compressed_success": [
            row for row in rows if not _overall_success(row, "B") and _overall_success(row, "D")
        ],
        "selection_correct_low_groundedness": [
            row
            for row in rows
            for group in PROMPT_GROUPS
            if _incident_success(row, group) and _groundedness(row, group) < 0.7
        ][:30],
        "high_confidence_wrong": [
            row
            for row in rows
            for group in PROMPT_GROUPS
            if _confidence(row, group) >= 0.8 and _incident_fail(row, group)
        ][:30],
        "resolution_hallucination": [
            row
            for row in rows
            for group in PROMPT_GROUPS
            if _resolution_hallucinated(row, group)
        ][:30],
        "schema_violation": [
            row
            for row in rows
            for group in PROMPT_GROUPS
            if not _schema_ok(row, group)
        ][:30],
    }
    return {
        "generated_at": utc_now_iso(),
        "counts": {key: len(value) for key, value in cases.items()},
        "cases": cases,
        "all_rows": rows,
    }


def _write_summary(path: Path, *, metrics: dict[str, Any], cases: dict[str, Any]) -> None:
    lines = [
        "# Prompt A/B/C/D Evaluation",
        "",
        "## 1. Experiment Goal",
        "",
        "동일한 Retrieval Snapshot과 동일한 Frozen Ground Truth에서 Prompt 구조만 바꿨을 때 LLM 판단 품질이 어떻게 달라지는지 비교한다.",
        "",
        "## 2. Frozen Dataset 정보",
        "",
        f"- Frozen file: `{metrics['dataset']['ground_truth_frozen_path']}`",
        f"- Frozen item count: {metrics['dataset']['frozen_item_count']}",
        "",
        "## 3. Retrieval Snapshot 정보",
        "",
        f"- Snapshot file: `{metrics['dataset']['retrieval_snapshot_path']}`",
        f"- Snapshot query count: {metrics['dataset']['retrieval_snapshot_count']}",
        "- Query Analyzer, Query Rewrite, Equal Weight Hybrid Retrieval, 기존 RRF k, Candidate Pool 정책을 한 번만 실행해 후보 순서를 고정했다.",
        "",
        "## 4. Prompt A/B/C/D 정의",
        "",
        f"- Prompt A Minimal: `{metrics['parameters']['prompt_files']['A']}`",
        f"- Prompt B Structured: `{metrics['parameters']['prompt_files']['B']}`",
        f"- Prompt C Evidence First: `{metrics['parameters']['prompt_files']['C']}`",
        f"- Prompt D Compressed Context: `{metrics['parameters']['prompt_files']['D']}`",
        f"- Judge Prompt: `{metrics['parameters']['judge_prompt_file']}`",
        "",
        "## 5. Evaluation Metrics",
        "",
        "- Incident Selection Accuracy, Error Type Accuracy, Answerability Accuracy, Groundedness, Unsupported Claim Rate, Resolution Accuracy, Schema Compliance, Confidence Calibration, Token, Latency, Cost.",
        "",
        "## 6. Overall Results",
        "",
        *_overall_table(metrics),
        "",
        "## 7. Answerability / Groundedness / Unsupported Claim 비교",
        "",
        *_answerability_table(metrics),
        "",
        "## 8. Resolution 평가",
        "",
        *_resolution_table(metrics),
        "",
        "## 9. Schema Compliance",
        "",
        *_schema_table(metrics),
        "",
        "## 10. Token / Latency / Cost",
        "",
        *_cost_table(metrics),
        "",
        "## 11. Query Type별 결과",
        "",
        *_query_type_table(metrics),
        "",
        "## 12. 대표 성공 사례",
        "",
        *_case_table(cases["cases"].get("full_fail_compressed_success", [])[:5], "Full Fail -> Compressed Success"),
        "",
        "## 13. 대표 실패 사례",
        "",
        *_case_table(cases["cases"].get("high_confidence_wrong", [])[:5], "High Confidence Wrong"),
        "",
        "## 14. Prompt별 장단점",
        "",
        *_prompt_tradeoffs(metrics),
        "",
        "## 15. Production Prompt 추천",
        "",
        f"- Recommendation: `{metrics['decision']['recommendation']}`",
        f"- Reason: {metrics['decision']['reason']}",
        "",
        "## 16. 예상 밖의 패턴",
        "",
        *_unexpected_patterns(metrics, cases),
        "",
        "## 17. Limitations(한계)",
        "",
        "- Groundedness와 resolution semantic match는 LLM Judge를 사용하므로 judge 자체의 편향 가능성이 있다.",
        "- Prompt A는 의도적으로 구조 강제가 약하지만 JSON mode를 사용해 최소한의 파싱 가능성은 유지했다.",
        "- Frozen Dataset은 human-reviewed item만 포함하므로 전체 candidate 분포와 다를 수 있다.",
        "",
        "## 18. Next Experiment(다음 실험)",
        "",
        "- 선택된 Prompt에 대해 Reranker 적용 여부, compressed context 필드 구성, confidence threshold를 각각 분리해 후속 ablation을 수행한다.",
        "- Groundedness judge 결과 중 경계 케이스를 human review로 샘플링해 judge 기준을 보정한다.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_prompt_template_files() -> None:
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for group, template in PROMPT_TEMPLATES.items():
        template["path"].write_text(
            _template_text(system=template["system"], user=template["user"]),
            encoding="utf-8",
        )
    JUDGE_TEMPLATE["path"].write_text(
        _template_text(system=JUDGE_TEMPLATE["system"], user=JUDGE_TEMPLATE["user"]),
        encoding="utf-8",
    )


def _template_text(*, system: str, user: str) -> str:
    return f"[SYSTEM]\n{system}\n\n[USER]\n{user}\n"


def _prompt_messages(group: PromptGroup, *, query: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    template = PROMPT_TEMPLATES[group]
    return [
        {"role": "system", "content": template["system"]},
        {
            "role": "user",
            "content": template["user"].format(
                query_json=_json(query),
                candidates_json=_json(candidates),
                output_schema_json=_json(_output_schema_description()),
            ),
        },
    ]


def _prompt_candidates(*, group: PromptGroup, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for candidate in snapshot["retrieved_candidates"]:
        fields = candidate.get("supported_context_fields") or {}
        if group == "D":
            context = {
                "summary": fields.get("summary"),
                "primary_error_type": fields.get("primary_error_type"),
                "primary_error_message": fields.get("primary_error_message"),
                "suspected_cause": fields.get("suspected_cause"),
                "resolution_summary": fields.get("resolution_summary"),
                "key_evidence": _key_evidence(fields),
            }
        else:
            context = fields
        candidates.append(
            {
                "rank": candidate["rank"],
                "incident_id": candidate["incident_id"],
                "retrieval_score": candidate.get("retrieval_score"),
                "rrf_score": candidate.get("rrf_score"),
                "vector_score": candidate.get("vector_score"),
                "bm25_score": candidate.get("bm25_score"),
                "context": context,
            }
        )
    return candidates


def _key_evidence(fields: dict[str, Any]) -> list[str]:
    values = [
        fields.get("summary"),
        fields.get("primary_error_type"),
        fields.get("primary_error_message"),
        *(fields.get("error_keywords") or [])[:4],
        *(fields.get("domain_tags") or [])[:3],
    ]
    return [value for value in values if value]


def _output_schema_description() -> dict[str, Any]:
    return {
        "selected_incident_id": "string or null",
        "answerability": {
            "root_cause": "boolean; true only if explicit root cause evidence is supplied",
            "resolution": "boolean; true only if explicit resolution evidence is supplied",
        },
        "error_type": "string or null",
        "root_cause": "string or null; null when not answerable",
        "resolution": "string or null; null when not answerable",
        "supporting_evidence": "array of concise evidence strings from supplied context",
        "confidence": "number from 0.0 to 1.0",
        "notes": "string or null",
    }


def _judge_schema_description() -> dict[str, Any]:
    return {
        "groundedness_score": "0.0~1.0",
        "total_claim_count": "integer",
        "unsupported_claim_count": "integer",
        "unsupported_claims": "array of strings",
        "root_cause_hallucinated": "boolean",
        "resolution_hallucinated": "boolean",
        "resolution_correct": "boolean or null",
        "failure_reason": "string or null",
    }


def _load_or_init_outputs(
    *,
    model: str,
    judge_model: str,
    frozen_path: Path,
    snapshot_path: Path,
    run_judge: bool,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    if OUTPUTS_PATH.exists():
        payload = read_json(OUTPUTS_PATH)
        if payload.get("experiment") == "prompt_ablation_abcd":
            for group in PROMPT_GROUPS:
                payload.setdefault("groups", {}).setdefault(group, [])
            return payload
    return {
        "experiment": "prompt_ablation_abcd",
        "generated_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "ground_truth_frozen_path": str(frozen_path),
        "retrieval_snapshot_path": str(snapshot_path),
        "parameters": {
            "model": model,
            "judge_model": judge_model if run_judge else None,
            "run_judge": run_judge,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        "groups": {group: [] for group in PROMPT_GROUPS},
    }


def _overall_table(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "| Prompt | Incident Acc | Error Type Acc | Answerability Acc | Groundedness | Unsupported Rate | Resolution Acc | Schema |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in PROMPT_GROUPS:
        item = metrics["overall"][group]
        lines.append(
            f"| {group} | {_pct(item['incident_selection_accuracy'])} | {_pct(item['error_type_accuracy'])} | "
            f"{_pct(item['answerability_accuracy'])} | {_num(item['groundedness'])} | "
            f"{_pct(item['unsupported_claim_rate'])} | {_pct(item['resolution_accuracy'])} | {_pct(item['schema_compliance'])} |"
        )
    return lines


def _answerability_table(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "| Prompt | Root Ans Acc | Resolution Ans Acc | Root Hallucination | Resolution Hallucination | Groundedness | Unsupported Rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in PROMPT_GROUPS:
        item = metrics["overall"][group]
        lines.append(
            f"| {group} | {_pct(item['root_cause_answerability_accuracy'])} | "
            f"{_pct(item['resolution_answerability_accuracy'])} | "
            f"{_pct(item['root_cause_hallucination_rate'])} | {_pct(item['resolution_hallucination_rate'])} | "
            f"{_num(item['groundedness'])} | {_pct(item['unsupported_claim_rate'])} |"
        )
    return lines


def _resolution_table(metrics: dict[str, Any]) -> list[str]:
    lines = ["| Prompt | Resolution Accuracy | Resolution Answerability Acc | Resolution Hallucination |", "|---|---:|---:|---:|"]
    for group in PROMPT_GROUPS:
        item = metrics["overall"][group]
        lines.append(
            f"| {group} | {_pct(item['resolution_accuracy'])} | {_pct(item['resolution_answerability_accuracy'])} | {_pct(item['resolution_hallucination_rate'])} |"
        )
    return lines


def _schema_table(metrics: dict[str, Any]) -> list[str]:
    lines = ["| Prompt | Schema Compliance | High Confidence Accuracy | High Confidence Count |", "|---|---:|---:|---:|"]
    for group in PROMPT_GROUPS:
        item = metrics["overall"][group]
        cal = item["confidence_calibration"]
        lines.append(
            f"| {group} | {_pct(item['schema_compliance'])} | {_pct(cal['high_confidence_accuracy'])} | {cal['high_confidence_count']} |"
        )
    return lines


def _cost_table(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "| Prompt | Prompt Tok | Completion Tok | Combined Tok | Avg Latency(ms) | P50 | P95 | Cost | Avg Cost/Query |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in PROMPT_GROUPS:
        item = metrics["overall"][group]
        tokens = item["tokens"]
        latency = item["latency"]
        cost = item["cost"]
        lines.append(
            f"| {group} | {tokens['prompt_tokens']} | {tokens['completion_tokens']} | {tokens['combined_total_tokens']} | "
            f"{_num(latency['average_llm_latency_ms'])} | {_num(latency['p50_llm_latency_ms'])} | "
            f"{_num(latency['p95_llm_latency_ms'])} | ${cost['total_usd']:.6f} | ${cost['average_usd_per_query']:.6f} |"
        )
    return lines


def _query_type_table(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "| Query Type | Prompt | Incident Acc | Answerability Acc | Groundedness | Unsupported Rate |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for query_type in QUERY_TYPES:
        for group in PROMPT_GROUPS:
            item = metrics["by_query_type"][group][query_type]
            lines.append(
                f"| {query_type} | {group} | {_pct(item['incident_selection_accuracy'])} | "
                f"{_pct(item['answerability_accuracy'])} | {_num(item['groundedness'])} | {_pct(item['unsupported_claim_rate'])} |"
            )
    return lines


def _case_table(rows: list[dict[str, Any]], title: str) -> list[str]:
    if not rows:
        return [f"### {title}", "", "No cases."]
    lines = [f"### {title}", "", "| Query | Type | Expected | A | B | C | D |", "|---|---|---|---|---|---|---|"]
    for row in rows[:8]:
        lines.append(
            f"| {_md(row['query'])} | {row.get('query_type')} | {row['expected_incident_id'][:8]} | "
            f"{_selected(row, 'A')} | {_selected(row, 'B')} | {_selected(row, 'C')} | {_selected(row, 'D')} |"
        )
    return lines


def _prompt_tradeoffs(metrics: dict[str, Any]) -> list[str]:
    lines = []
    for group in PROMPT_GROUPS:
        item = metrics["overall"][group]
        lines.append(
            f"- Prompt {group}: incident={_pct(item['incident_selection_accuracy'])}, "
            f"answerability={_pct(item['answerability_accuracy'])}, groundedness={_num(item['groundedness'])}, "
            f"tokens={item['tokens']['combined_total_tokens']}, avg_latency={_num(item['latency']['average_llm_latency_ms'])}ms."
        )
    return lines


def _unexpected_patterns(metrics: dict[str, Any], cases: dict[str, Any]) -> list[str]:
    counts = cases["counts"]
    lines = [
        f"- A 실패 -> B 성공: {counts['a_fail_b_success']}건",
        f"- B 실패 -> C 성공: {counts['b_fail_c_success']}건",
        f"- Full Context 성공 -> Compressed 실패: {counts['full_success_compressed_fail']}건",
        f"- Full Context 실패 -> Compressed 성공: {counts['full_fail_compressed_success']}건",
        f"- High confidence wrong: {counts['high_confidence_wrong']}건",
        f"- Resolution hallucination: {counts['resolution_hallucination']}건",
    ]
    return lines


def _decision(overall: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for group, metrics in overall.items():
        score = (
            (metrics["incident_selection_accuracy"] or 0.0) * 0.30
            + (metrics["answerability_accuracy"] or 0.0) * 0.25
            + (metrics["groundedness"] or 0.0) * 0.20
            + (1.0 - (metrics["unsupported_claim_rate"] or 0.0)) * 0.15
            + (metrics["schema_compliance"] or 0.0) * 0.10
        )
        candidates.append((score, group, metrics))
    candidates.sort(reverse=True)
    best_score, best_group, best_metrics = candidates[0]
    cheapest = min(overall.items(), key=lambda item: item[1]["tokens"]["combined_total_tokens"])[0]
    if best_group != cheapest:
        best = overall[best_group]
        cheap = overall[cheapest]
        quality_gap = (
            (best["incident_selection_accuracy"] or 0.0) - (cheap["incident_selection_accuracy"] or 0.0)
            + (best["answerability_accuracy"] or 0.0) - (cheap["answerability_accuracy"] or 0.0)
        )
        if abs(quality_gap) < 0.02 and cheap["tokens"]["combined_total_tokens"] < best["tokens"]["combined_total_tokens"]:
            return {
                "recommendation": cheapest,
                "reason": "Compressed/cheaper prompt has nearly identical quality with lower token cost.",
                "decision_score": best_score,
            }
    return {
        "recommendation": best_group,
        "reason": "Best weighted trade-off across incident selection, answerability, groundedness, unsupported claims, and schema compliance.",
        "decision_score": best_score,
    }


def _compact_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": case.get("output"),
        "evaluation": case.get("evaluation"),
        "schema_compliance": case.get("schema_compliance"),
        "prompt_tokens": case.get("prompt_tokens"),
        "completion_tokens": case.get("completion_tokens"),
        "total_tokens": case.get("total_tokens"),
        "latency_ms": case.get("latency_ms"),
        "failure_reason": (case.get("evaluation") or {}).get("failure_reason"),
    }


def _failure_reason(**flags: Any) -> str | None:
    if not flags["schema_ok"]:
        return "schema_violation"
    if not flags["incident_correct"]:
        return "wrong_incident"
    if not flags["error_type_correct"]:
        return "wrong_error_type"
    if not flags["root_answerability_correct"]:
        return "wrong_root_answerability"
    if not flags["resolution_answerability_correct"]:
        return "wrong_resolution_answerability"
    if flags["root_hallucinated"]:
        return "root_cause_hallucination"
    if flags["resolution_hallucinated"]:
        return "resolution_hallucination"
    return None


def _confidence_calibration(*, cases: list[dict[str, Any]], high_conf: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "average_confidence": _mean((case.get("output") or {}).get("confidence") for case in cases),
        "high_confidence_count": len(high_conf),
        "high_confidence_accuracy": _ratio(
            sum(case["evaluation"]["incident_selection_correct"] for case in high_conf),
            len(high_conf),
        ),
    }


def _cost(*, pricing: dict[str, Any], model: str, input_tokens: int, output_tokens: int, query_count: int) -> dict[str, Any]:
    model_price = pricing.get(model) or pricing.get("default") or {}
    input_price = float(model_price.get("input_per_1m_tokens_usd", 0.0))
    output_price = float(model_price.get("output_per_1m_tokens_usd", 0.0))
    total = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
    return {
        "total_usd": total,
        "average_usd_per_query": total / query_count if query_count else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _unsupported_rate(case: dict[str, Any]) -> float:
    judge = case.get("judge") or {}
    unsupported = judge.get("unsupported_claim_count")
    total = judge.get("total_claim_count")
    if isinstance(unsupported, int) and isinstance(total, int) and total > 0:
        return unsupported / total
    output = case.get("output") or {}
    synthetic = 0
    if output.get("root_cause"):
        synthetic += 1
    if output.get("resolution"):
        synthetic += 1
    return float(synthetic > 0)


def _truth_resolution_answerable(case: dict[str, Any]) -> bool:
    return bool(case.get("evaluation", {}).get("truth_resolution_answerability"))


def _rank_of(expected_id: str, candidates: list[dict[str, Any]]) -> int | None:
    for candidate in candidates:
        if candidate["incident_id"] == expected_id:
            return candidate["rank"]
    return None


def _contains_meaning(value: Any, expected: Any) -> bool:
    if not value or not expected:
        return False
    left = _norm(value)
    right = _norm(expected)
    return left in right or right in left


def _bool_or_fallback(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _sum_optional(left: Any, right: Any) -> int | None:
    if left is None or right is None:
        return None
    return int(left) + int(right)


def _sum_int(values: Any) -> int:
    return sum(int(value) for value in values if value is not None)


def _mean(values: Any) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return mean(clean) if clean else None


def _ratio(numerator: float, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _md(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def _selected(row: dict[str, Any], group: PromptGroup) -> str:
    prompt = row["prompts"].get(group) or {}
    output = prompt.get("output") or {}
    selected = output.get("selected_incident_id")
    ok = (prompt.get("evaluation") or {}).get("incident_selection_correct")
    return f"{str(selected)[:8]} ({'ok' if ok else 'fail'})"


def _incident_success(row: dict[str, Any], group: PromptGroup) -> bool:
    return bool((row["prompts"].get(group) or {}).get("evaluation", {}).get("incident_selection_correct"))


def _incident_fail(row: dict[str, Any], group: PromptGroup) -> bool:
    return not _incident_success(row, group)


def _overall_success(row: dict[str, Any], group: PromptGroup) -> bool:
    return bool((row["prompts"].get(group) or {}).get("evaluation", {}).get("overall_success"))


def _root_hallucinated(row: dict[str, Any], group: PromptGroup) -> bool:
    return bool((row["prompts"].get(group) or {}).get("evaluation", {}).get("root_cause_hallucinated"))


def _resolution_hallucinated(row: dict[str, Any], group: PromptGroup) -> bool:
    return bool((row["prompts"].get(group) or {}).get("evaluation", {}).get("resolution_hallucinated"))


def _schema_ok(row: dict[str, Any], group: PromptGroup) -> bool:
    return bool((row["prompts"].get(group) or {}).get("schema_compliance"))


def _groundedness(row: dict[str, Any], group: PromptGroup) -> float:
    return float((row["prompts"].get(group) or {}).get("evaluation", {}).get("groundedness_score") or 0.0)


def _confidence(row: dict[str, Any], group: PromptGroup) -> float:
    return float(((row["prompts"].get(group) or {}).get("output") or {}).get("confidence") or 0.0)
