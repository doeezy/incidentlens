from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket

PromptVariant = Literal["prompt_a", "prompt_b", "prompt_c", "prompt_d"]

RAW_CONTEXT_FIELDS = [
    "raw_log",
    "error_message",
    "error_summary",
    "keywords",
    "domain_tags",
    "suspected_cause",
    "root_cause",
    "fix_summary",
    "tickets",
    "prs",
    "vector_score",
    "bm25_score",
    "rrf_score",
]

COMPRESSED_CONTEXT_FIELDS = [
    "error_message",
    "error_summary",
    "keywords",
    "domain_tags",
    "root_cause",
    "fix_summary",
    "tickets",
    "prs",
    "vector_score",
    "bm25_score",
    "rrf_score",
]


def build_prompt_messages(
    *,
    session: Session,
    variant: PromptVariant,
    query: dict[str, Any],
    retrieval_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    raw_context = _candidate_contexts(
        session=session,
        retrieval_results=retrieval_results,
        compressed=variant == "prompt_d",
    )
    context_fields = COMPRESSED_CONTEXT_FIELDS if variant == "prompt_d" else RAW_CONTEXT_FIELDS
    payload = {
        "user_query": {
            "query_id": query["query_id"],
            "query_text": query["query_text"],
            "query_type": query["query_type"],
            "project_name": query["project_name"],
        },
        "candidate_incidents": raw_context,
        "context_fields": context_fields,
        "output_schema": _output_schema_description(),
    }
    if variant == "prompt_a":
        messages = _prompt_a(payload)
    elif variant == "prompt_b":
        messages = _prompt_b(payload)
    elif variant == "prompt_c":
        messages = _prompt_c(payload)
    elif variant == "prompt_d":
        messages = _prompt_d(payload)
    else:
        raise ValueError(f"Unknown prompt variant: {variant}")
    return messages, context_fields, payload


def _prompt_a(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _developer_message(),
        {
            "role": "user",
            "content": (
                "Find the most relevant incident and generate a hypothesis from this raw context:\n"
                + _json(payload)
            ),
        },
    ]


def _prompt_b(payload: dict[str, Any]) -> list[dict[str, Any]]:
    structured = {
        "ROLE": "Incident relevance judge",
        "TASK": "Select the candidate incident most directly supported by the query evidence.",
        "USER_QUERY": payload["user_query"],
        "CANDIDATE_INCIDENTS": payload["candidate_incidents"],
        "EVIDENCE": "Use candidate fields only. Retrieval scores are ranking signals, not truth.",
        "JUDGEMENT_RULES": [
            "Prefer evidence directly related to the query.",
            "Do not infer causes that are not present in candidate evidence.",
            "Every judgement must cite incident evidence.",
            "If evidence is weak, lower confidence and say it is uncertain.",
        ],
        "OUTPUT_SCHEMA": payload["output_schema"],
    }
    return [
        _developer_message(),
        {"role": "user", "content": _json(structured)},
    ]


def _prompt_c(payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_first = {
        "ROLE": "Evidence-first IncidentLens evaluator",
        "STEP_1_EVIDENCE_ANALYSIS": [
            "For each incident, summarize query-matching error evidence.",
            "Summarize related class, method, symptom, root cause, and fix evidence.",
            "Summarize why the incident may be weakly related.",
        ],
        "STEP_2_FINAL_JUDGEMENT": [
            "Use only the explicit evidence analysis to select the incident.",
            "Generate a concise hypothesis with citations to candidate fields.",
        ],
        "IMPORTANT": (
            "Do not reveal hidden reasoning. evidence_analysis must be a user-verifiable "
            "summary of supplied evidence only."
        ),
        "USER_QUERY": payload["user_query"],
        "CANDIDATE_INCIDENTS": payload["candidate_incidents"],
        "OUTPUT_SCHEMA": payload["output_schema"],
    }
    return [
        _developer_message(),
        {"role": "user", "content": _json(evidence_first)},
    ]


def _prompt_d(payload: dict[str, Any]) -> list[dict[str, Any]]:
    compressed = {
        "ROLE": "Incident relevance judge using compressed context",
        "TASK": "Select the candidate incident using compact evidence only.",
        "USER_QUERY": payload["user_query"],
        "CANDIDATE_INCIDENTS": payload["candidate_incidents"],
        "CONTEXT_POLICY": [
            "Raw logs and duplicate descriptions are intentionally omitted.",
            "Use primary_error, summaries, keywords, root cause, fix, tickets, PRs, and retrieval scores.",
            "If compact evidence is insufficient, mark uncertainty.",
        ],
        "JUDGEMENT_RULES": [
            "Do not invent missing details from omitted raw fields.",
            "Every claim must cite a supplied compact field.",
        ],
        "OUTPUT_SCHEMA": payload["output_schema"],
    }
    return [
        _developer_message(),
        {"role": "user", "content": _json(compressed)},
    ]


def _candidate_contexts(
    *,
    session: Session,
    retrieval_results: list[dict[str, Any]],
    compressed: bool,
) -> list[dict[str, Any]]:
    incident_ids = [item["incident_id"] for item in retrieval_results]
    incidents = {
        str(incident.id): incident
        for incident in session.scalars(select(Incident).where(Incident.id.in_(incident_ids))).all()
    }
    return [
        _incident_context(
            session=session,
            incident=incidents[str(item["incident_id"])],
            retrieval=item,
            compressed=compressed,
        )
        for item in retrieval_results
        if str(item["incident_id"]) in incidents
    ]


def _incident_context(
    *,
    session: Session,
    incident: Incident,
    retrieval: dict[str, Any],
    compressed: bool,
) -> dict[str, Any]:
    logs = list(
        session.scalars(
            select(RawLog).where(RawLog.incident_id == incident.id).order_by(RawLog.occurred_at.asc()).limit(3)
        ).all()
    )
    tickets = list(
        session.scalars(
            select(RawTicket).where(RawTicket.incident_id == incident.id).order_by(RawTicket.ticket_created_at.asc()).limit(3)
        ).all()
    )
    prs = list(
        session.scalars(
            select(RawPr).where(RawPr.incident_id == incident.id).order_by(RawPr.pr_created_at.asc()).limit(3)
        ).all()
    )
    base: dict[str, Any] = {
        "incident_id": str(incident.id),
        "rank": retrieval.get("rank"),
        "project_name": incident.project_name,
        "module_name": incident.module_name,
        "class_name": incident.class_name,
        "method_name": incident.method_name,
        "primary_error": {
            "type": incident.primary_error_type,
            "message": incident.primary_error_message,
        },
        "error_summary": incident.primary_error_summary,
        "keywords": incident.error_keywords or [],
        "domain_tags": incident.domain_tags or [],
        "root_cause": incident.root_cause_summary,
        "fix_summary": incident.resolution_summary,
        "retrieval_scores": {
            "vector_score": retrieval.get("vector_score"),
            "bm25_score": retrieval.get("bm25_score"),
            "rrf_score": retrieval.get("rrf_score"),
        },
        "tickets": [
            {
                "ticket_key": ticket.ticket_key,
                "title": ticket.title,
                "summary": ticket.normalized_summary,
                "suspected_cause": ticket.suspected_cause,
                "resolution_note": ticket.resolution_note,
            }
            for ticket in tickets
        ],
        "prs": [
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
    if not compressed:
        base["suspected_cause"] = incident.suspected_cause
        base["raw_log"] = [
            {
                "log_level": log.log_level,
                "raw_message": log.raw_message,
                "error_type": log.error_type,
                "error_message": log.error_message,
                "summary": log.normalized_summary,
            }
            for log in logs
        ]
    return base


def _output_schema_description() -> dict[str, Any]:
    return {
        "selected_incident_id": "string or null",
        "confidence": "0.0~1.0",
        "hypothesis": "string",
        "evidence_analysis": "array of per-incident evidence summaries",
        "evidence_used": "array of {incident_id, field, quote_or_summary}",
        "claims": "array of generated factual claims",
        "unsupported_claims": "array of claims not supported by supplied context",
        "uncertainty": "string or null",
    }


def _developer_message() -> dict[str, str]:
    return {
        "role": "developer",
        "content": (
            "You are evaluating IncidentLens search candidates. Return JSON only. "
            "Use only the supplied incidents and evidence. Retrieval scores are "
            "ranking signals, not ground truth. Do not infer hidden causes or fixes."
        ),
    }


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
