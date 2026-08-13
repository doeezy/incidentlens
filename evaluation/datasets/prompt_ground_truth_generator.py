from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from evaluation.common import EVALUATION_DATA_DIR, read_json, utc_now_iso, write_json
from evaluation.datasets.models import RetrievalDataset


DEFAULT_OUTPUT_PATH = EVALUATION_DATA_DIR / "prompt_ground_truth_candidate.json"
DEFAULT_RETRIEVAL_CANDIDATE_PATH = EVALUATION_DATA_DIR / "retrieval_queries_candidate.json"
EVIDENCE_LIMIT = 10


def generate_prompt_ground_truth_candidate(
    *,
    session: Session,
    retrieval_candidate_path: Path = DEFAULT_RETRIEVAL_CANDIDATE_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    retrieval_dataset = RetrievalDataset.model_validate(read_json(retrieval_candidate_path))
    approved_queries = [query for query in retrieval_dataset.queries if not query.excluded]
    excluded_queries = [query for query in retrieval_dataset.queries if query.excluded]
    incident_ids = sorted({query.expected_incident_id for query in approved_queries})

    incidents = _load_incidents(session=session, incident_ids=incident_ids)
    raw_logs = _load_raw_logs(session=session, incidents=incidents)
    raw_tickets = _load_raw_tickets(session=session, incidents=incidents)
    raw_prs = _load_raw_prs(session=session, incidents=incidents)

    items = []
    difficult_cases = []
    for query in approved_queries:
        incident = incidents.get(query.expected_incident_id)
        if incident is None:
            items.append(_missing_incident_item(query))
            difficult_cases.append(
                {
                    "query_id": query.query_id,
                    "expected_incident_id": query.expected_incident_id,
                    "reason": "expected_incident_id not found in incidents table",
                }
            )
            continue
        item = _ground_truth_item(
            query=query,
            incident=incident,
            raw_logs=raw_logs.get(str(incident.id), []),
            raw_tickets=raw_tickets.get(str(incident.id), []),
            raw_prs=raw_prs.get(str(incident.id), []),
        )
        items.append(item)
        if item["root_cause_answerability"] is False and _has_suspected_cause_only(
            incident=incident,
            raw_tickets=raw_tickets.get(str(incident.id), []),
            raw_prs=raw_prs.get(str(incident.id), []),
        ):
            difficult_cases.append(
                {
                    "query_id": query.query_id,
                    "expected_incident_id": query.expected_incident_id,
                    "reason": "suspected_cause exists but explicit root_cause does not; keep root_cause unanswerable",
                }
            )

    validation = _validate_items(
        items=items,
        incidents=incidents,
        raw_logs=raw_logs,
        raw_tickets=raw_tickets,
        raw_prs=raw_prs,
    )
    payload = {
        "dataset_name": "prompt_ground_truth",
        "status": "candidate",
        "generated_at": utc_now_iso(),
        "source": {
            "retrieval_candidate_path": str(retrieval_candidate_path),
            "query_policy": "uses retrieval_queries_candidate.json with excluded=true queries skipped",
            "total_retrieval_queries": len(retrieval_dataset.queries),
            "included_query_count": len(approved_queries),
            "skipped_excluded_query_count": len(excluded_queries),
            "unique_expected_incident_count": len(incident_ids),
            "data_sources": ["incidents", "raw_logs", "raw_tickets", "raw_prs"],
            "grounding_policy": (
                "Do not infer root cause or resolution. Use only values stored in Incident or linked Raw data."
            ),
        },
        "summary": _summary(
            items=items,
            validation=validation,
            excluded_queries=excluded_queries,
            difficult_cases=difficult_cases,
        ),
        "validation": validation,
        "items": items,
    }
    write_json(output_path, payload)
    return payload


def _load_incidents(*, session: Session, incident_ids: list[str]) -> dict[str, Incident]:
    rows = session.query(Incident).filter(Incident.id.in_(incident_ids)).all()
    return {str(row.id): row for row in rows}


def _load_raw_logs(
    *,
    session: Session,
    incidents: dict[str, Incident],
) -> dict[str, list[RawLog]]:
    incident_ids = list(incidents)
    related_ids = _collect_related_ids(incidents.values(), "related_log_ids")
    filters = [RawLog.incident_id.in_(incident_ids)]
    if related_ids:
        filters.append(RawLog.id.in_(related_ids))
    rows = session.query(RawLog).filter(or_(*filters)).all()
    return _group_raw_rows(rows=rows, incidents=incidents, related_field="related_log_ids")


def _load_raw_tickets(
    *,
    session: Session,
    incidents: dict[str, Incident],
) -> dict[str, list[RawTicket]]:
    incident_ids = list(incidents)
    related_ids = _collect_related_ids(incidents.values(), "related_ticket_ids")
    filters = [RawTicket.incident_id.in_(incident_ids)]
    if related_ids:
        filters.append(RawTicket.id.in_(related_ids))
    rows = session.query(RawTicket).filter(or_(*filters)).all()
    return _group_raw_rows(rows=rows, incidents=incidents, related_field="related_ticket_ids")


def _load_raw_prs(
    *,
    session: Session,
    incidents: dict[str, Incident],
) -> dict[str, list[RawPr]]:
    incident_ids = list(incidents)
    related_ids = _collect_related_ids(incidents.values(), "related_pr_ids")
    filters = [RawPr.incident_id.in_(incident_ids)]
    if related_ids:
        filters.append(RawPr.id.in_(related_ids))
    rows = session.query(RawPr).filter(or_(*filters)).all()
    return _group_raw_rows(rows=rows, incidents=incidents, related_field="related_pr_ids")


def _group_raw_rows(
    *,
    rows: list[Any],
    incidents: dict[str, Incident],
    related_field: str,
) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    related_index: dict[str, str] = {}
    for incident in incidents.values():
        for related_id in _as_list(getattr(incident, related_field)):
            related_index[str(related_id)] = str(incident.id)
    for row in rows:
        if row.incident_id:
            grouped[str(row.incident_id)].append(row)
            continue
        incident_id = related_index.get(str(row.id))
        if incident_id:
            grouped[incident_id].append(row)
    return grouped


def _ground_truth_item(
    *,
    query: Any,
    incident: Incident,
    raw_logs: list[RawLog],
    raw_tickets: list[RawTicket],
    raw_prs: list[RawPr],
) -> dict[str, Any]:
    root_cause = _clean(incident.root_cause_summary)
    resolution = _first_nonempty(
        incident.resolution_summary,
        *[ticket.resolution_note for ticket in raw_tickets],
        *[pr.resolution_note for pr in raw_prs],
    )
    evidence = _supported_evidence(
        incident=incident,
        raw_logs=raw_logs,
        raw_tickets=raw_tickets,
        raw_prs=raw_prs,
    )
    return {
        "query_id": query.query_id,
        "query_text": query.query_text,
        "query_type": query.query_type,
        "project_name": query.project_name,
        "expected_incident_id": query.expected_incident_id,
        "expected_error_type": _clean(incident.primary_error_type),
        "expected_error_message": _clean(incident.primary_error_message),
        "supported_evidence": evidence,
        "root_cause": root_cause,
        "root_cause_answerability": root_cause is not None,
        "resolution_summary": resolution,
        "resolution_answerability": resolution is not None,
        "reviewed_by_human": False,
        "excluded": False,
        "exclude_reason": None,
        "review_note": None,
    }


def _missing_incident_item(query: Any) -> dict[str, Any]:
    return {
        "query_id": query.query_id,
        "query_text": query.query_text,
        "query_type": query.query_type,
        "project_name": query.project_name,
        "expected_incident_id": query.expected_incident_id,
        "expected_error_type": None,
        "expected_error_message": None,
        "supported_evidence": [],
        "root_cause": None,
        "root_cause_answerability": False,
        "resolution_summary": None,
        "resolution_answerability": False,
        "reviewed_by_human": False,
        "excluded": True,
        "exclude_reason": "expected_incident_id not found in incidents table",
        "review_note": None,
    }


def _supported_evidence(
    *,
    incident: Incident,
    raw_logs: list[RawLog],
    raw_tickets: list[RawTicket],
    raw_prs: list[RawPr],
) -> list[str]:
    values: list[Any] = [
        incident.primary_error_type,
        incident.primary_error_message,
        incident.primary_error_summary,
    ]
    values.extend(_as_list(incident.error_keywords)[:4])
    values.extend(_as_list(incident.domain_tags)[:3])
    values.extend([incident.suspected_cause, incident.resolution_summary])
    for log in raw_logs[:2]:
        values.extend(
            [
                log.error_type,
                log.error_message,
                log.normalized_summary,
            ]
        )
        values.extend(_as_list(log.extracted_keywords)[:3])
    for ticket in raw_tickets[:2]:
        values.extend(
            [
                ticket.error_type,
                ticket.title,
                ticket.normalized_summary,
                ticket.suspected_cause,
                ticket.resolution_note,
            ]
        )
        values.extend(_as_list(ticket.extracted_keywords)[:3])
    for pr in raw_prs[:2]:
        values.extend(
            [
                pr.title,
                pr.normalized_summary,
                pr.suspected_fix_for,
                pr.resolution_note,
            ]
        )
        values.extend(_as_list(pr.extracted_keywords)[:3])
    return _unique_clean(values)[:EVIDENCE_LIMIT]


def _validate_items(
    *,
    items: list[dict[str, Any]],
    incidents: dict[str, Incident],
    raw_logs: dict[str, list[RawLog]],
    raw_tickets: dict[str, list[RawTicket]],
    raw_prs: dict[str, list[RawPr]],
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    for item in items:
        incident = incidents.get(item["expected_incident_id"])
        if incident is None:
            violations.append(_violation(item, "missing_incident", "expected_incident_id does not exist"))
            continue
        if item["expected_error_type"] != _clean(incident.primary_error_type):
            violations.append(_violation(item, "error_type_mismatch", "expected_error_type differs from incident"))
        if item["expected_error_message"] != _clean(incident.primary_error_message):
            violations.append(_violation(item, "error_message_mismatch", "expected_error_message differs from incident"))
        source_values = _source_values(
            incident=incident,
            raw_logs=raw_logs.get(str(incident.id), []),
            raw_tickets=raw_tickets.get(str(incident.id), []),
            raw_prs=raw_prs.get(str(incident.id), []),
        )
        for evidence in item["supported_evidence"]:
            if evidence not in source_values:
                violations.append(_violation(item, "unsupported_evidence", evidence))
        if item["root_cause_answerability"] and not _clean(incident.root_cause_summary):
            violations.append(_violation(item, "root_cause_answerability_without_root_cause", "root_cause_summary empty"))
        if item["root_cause"] is not None and item["root_cause"] not in source_values:
            violations.append(_violation(item, "root_cause_not_from_source", item["root_cause"]))
        if item["resolution_answerability"] and item["resolution_summary"] not in source_values:
            violations.append(_violation(item, "resolution_not_from_source", item["resolution_summary"]))
    return {
        "passed": not violations,
        "violation_count": len(violations),
        "violations": violations,
        "checks": [
            "expected_incident_id exists in incidents",
            "expected_error_type/message match Incident fields exactly",
            "supported_evidence values come from Incident or linked Raw data fields",
            "root_cause_answerability=true requires explicit Incident.root_cause_summary",
            "resolution_answerability=true requires explicit Incident/Raw resolution field",
            "root_cause/resolution values are not inferred",
        ],
    }


def _source_values(
    *,
    incident: Incident,
    raw_logs: list[RawLog],
    raw_tickets: list[RawTicket],
    raw_prs: list[RawPr],
) -> set[str]:
    values: list[Any] = [
        incident.primary_error_type,
        incident.primary_error_message,
        incident.primary_error_summary,
        incident.suspected_cause,
        incident.root_cause_summary,
        incident.resolution_summary,
    ]
    values.extend(_as_list(incident.error_keywords))
    values.extend(_as_list(incident.domain_tags))
    for log in raw_logs:
        values.extend(
            [
                log.log_level,
                log.raw_message,
                log.stack_trace,
                log.error_type,
                log.error_message,
                log.normalized_summary,
            ]
        )
        values.extend(_as_list(log.extracted_keywords))
        values.extend(_as_list(log.domain_tags))
    for ticket in raw_tickets:
        values.extend(
            [
                ticket.ticket_key,
                ticket.repository_name,
                ticket.module_name,
                ticket.class_name,
                ticket.method_name,
                ticket.error_type,
                ticket.title,
                ticket.description,
                ticket.status,
                ticket.priority,
                ticket.normalized_summary,
                ticket.suspected_cause,
                ticket.resolution_note,
            ]
        )
        values.extend(_as_list(ticket.extracted_keywords))
        values.extend(_as_list(ticket.domain_tags))
    for pr in raw_prs:
        values.extend(
            [
                pr.pr_key,
                pr.repository_name,
                pr.module_name,
                pr.class_name,
                pr.method_name,
                pr.title,
                pr.description,
                pr.status,
                pr.source_branch,
                pr.target_branch,
                pr.diff_summary,
                pr.normalized_summary,
                pr.suspected_fix_for,
                pr.resolution_note,
            ]
        )
        values.extend(_as_list(pr.changed_files))
        values.extend(_as_list(pr.commit_messages))
        values.extend(_as_list(pr.extracted_keywords))
        values.extend(_as_list(pr.domain_tags))
    return set(_unique_clean(values))


def _summary(
    *,
    items: list[dict[str, Any]],
    validation: dict[str, Any],
    excluded_queries: list[Any],
    difficult_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    root_counter = Counter(item["root_cause_answerability"] for item in items)
    resolution_counter = Counter(item["resolution_answerability"] for item in items)
    error_type_counter = Counter(item["expected_error_type"] is not None for item in items)
    return {
        "item_count": len(items),
        "root_cause_answerability": {
            "true": root_counter[True],
            "false": root_counter[False],
        },
        "resolution_answerability": {
            "true": resolution_counter[True],
            "false": resolution_counter[False],
        },
        "expected_error_type": {
            "exists": error_type_counter[True],
            "missing": error_type_counter[False],
        },
        "excluded_source_queries": [
            {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "expected_incident_id": query.expected_incident_id,
                "exclude_reason": query.exclude_reason,
            }
            for query in excluded_queries
        ],
        "human_review_special_cases": difficult_cases,
        "difficult_case_count": len(difficult_cases),
        "validation_passed": validation["passed"],
        "validation_violation_count": validation["violation_count"],
    }


def _has_suspected_cause_only(
    *,
    incident: Incident,
    raw_tickets: list[RawTicket],
    raw_prs: list[RawPr],
) -> bool:
    if _clean(incident.root_cause_summary):
        return False
    values: list[Any] = [incident.suspected_cause]
    values.extend(ticket.suspected_cause for ticket in raw_tickets)
    values.extend(pr.suspected_fix_for for pr in raw_prs)
    return any(_clean(value) for value in values)


def _collect_related_ids(incidents: Any, field_name: str) -> list[str]:
    values: list[str] = []
    for incident in incidents:
        values.extend(str(value) for value in _as_list(getattr(incident, field_name)))
    return values


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return None


def _unique_clean(values: list[Any]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        cleaned = _clean(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _violation(item: dict[str, Any], code: str, detail: str) -> dict[str, Any]:
    return {
        "query_id": item["query_id"],
        "expected_incident_id": item["expected_incident_id"],
        "code": code,
        "detail": detail,
    }
