from __future__ import annotations

import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.database import SessionLocal
from app.models.incident import Incident
from app.models.incident_embedding import IncidentEmbedding
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from app.repositories.incident_embedding_repository import IncidentEmbeddingRepository
from app.services.embedding.service import EmbeddingService

SOURCE_REPORT_PATH = ROOT_DIR / "docs" / "evaluation" / "rrf_ranking_miss_analysis.json"
MD_REPORT_PATH = ROOT_DIR / "docs" / "evaluation" / "retrieval_input_diagnosis_v1.md"
JSON_REPORT_PATH = ROOT_DIR / "docs" / "evaluation" / "retrieval_input_diagnosis_v1.json"

INTENDED_BM25_FIELDS = [
    "primary_error_summary",
    "primary_error_type",
    "primary_error_message",
    "error_keywords",
    "domain_tags",
    "suspected_cause",
    "root_cause_summary",
    "resolution_summary",
]

KOREAN_STOPWORDS = {
    "장애",
    "사례",
    "원인",
    "해결",
    "방법",
    "내용",
    "설명",
    "찾아줘",
    "뭐야",
    "에서",
    "으로",
    "때문",
    "때문에",
    "있는",
    "없는",
    "실패",
    "오류",
}


@dataclass(frozen=True)
class FieldState:
    state: str
    searchable: bool


def to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(stringify(item) for item in value)
    if isinstance(value, dict):
        return " ".join(stringify(item) for item in value.values())
    return str(value)


def field_state(value: Any) -> FieldState:
    if value is None:
        return FieldState("null", False)
    if isinstance(value, str) and not value.strip():
        return FieldState("empty_string", False)
    if isinstance(value, list) and not value:
        return FieldState("empty_array", False)
    return FieldState("present", bool(stringify(value).strip()))


def normalize_token(token: str) -> str:
    return token.strip().lower()


def tokenize(text_value: str | None) -> list[str]:
    if not text_value:
        return []
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*|[0-9]+|[가-힣]+", text_value)
    tokens: list[str] = []
    for raw in raw_tokens:
        pieces = re.findall(
            r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+|[가-힣]+",
            raw,
        )
        for piece in pieces or [raw]:
            token = normalize_token(piece)
            if len(token) < 2:
                continue
            if token in KOREAN_STOPWORDS:
                continue
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def find_token_hits(tokens: list[str], text_value: str | None) -> list[str]:
    haystack = (text_value or "").lower()
    hits: list[str] = []
    for token in tokens:
        if token.lower() in haystack:
            hits.append(token)
    return hits


def load_source_cases() -> list[dict[str, Any]]:
    payload = json.loads(SOURCE_REPORT_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


def load_incident(session, incident_id: uuid.UUID) -> Incident:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise RuntimeError(f"incident not found: {incident_id}")
    return incident


def latest_embedding(session, incident_id: uuid.UUID) -> IncidentEmbedding | None:
    return session.scalars(
        select(IncidentEmbedding)
        .where(IncidentEmbedding.incident_id == incident_id)
        .order_by(IncidentEmbedding.updated_at.desc())
        .limit(1)
    ).first()


def vector_dimension(session, embedding_id: uuid.UUID | None) -> int | None:
    if embedding_id is None:
        return None
    row = session.execute(
        text("SELECT vector_dims(embedding_vector) FROM incident_embeddings WHERE id = :id"),
        {"id": embedding_id},
    ).first()
    return int(row[0]) if row and row[0] is not None else None


def searchable_text(session, incident_id: uuid.UUID) -> str | None:
    row = session.execute(
        text("""
            SELECT public.incident_searchable_text(
                primary_error_summary,
                primary_error_type,
                primary_error_message,
                error_keywords::jsonb,
                domain_tags::jsonb,
                suspected_cause,
                root_cause_summary,
                resolution_summary
            )
            FROM incidents
            WHERE id = :incident_id
        """),
        {"incident_id": incident_id},
    ).first()
    return None if row is None else row[0]


def bm25_rank_for_expected(
    session,
    *,
    project_name: str,
    query: str,
    incident_id: uuid.UUID,
) -> tuple[int | None, float | None]:
    row = session.execute(
        text("""
            WITH bm25_hits AS (
                SELECT
                    id AS incident_id,
                    pdb.score(id) AS bm25_score
                FROM incidents
                WHERE project_name = :project_name
                  AND public.incident_searchable_text(
                        primary_error_summary,
                        primary_error_type,
                        primary_error_message,
                        error_keywords::jsonb,
                        domain_tags::jsonb,
                        suspected_cause,
                        root_cause_summary,
                        resolution_summary
                      ) ||| :query
                ORDER BY pdb.score(id) DESC, id ASC
                LIMIT 100
            ),
            ranked AS (
                SELECT
                    incident_id,
                    bm25_score,
                    rank() OVER (ORDER BY bm25_score DESC, incident_id ASC) AS rank
                FROM bm25_hits
            )
            SELECT rank, bm25_score
            FROM ranked
            WHERE incident_id = :incident_id
        """),
        {
            "project_name": project_name,
            "query": query,
            "incident_id": incident_id,
        },
    ).first()
    if row is None:
        return None, None
    return int(row[0]), float(row[1])


def vector_distance_for_query(
    session,
    embedding_service: EmbeddingService,
    *,
    query: str,
    incident_id: uuid.UUID,
) -> dict[str, float | None]:
    query_vector = embedding_service.embed_text(query)
    query_vector_str = "[" + ",".join(map(str, query_vector)) + "]"
    row = session.execute(
        text("""
            SELECT embedding_vector <=> CAST(:query_vector AS vector) AS distance
            FROM incident_embeddings
            WHERE incident_id = :incident_id
            ORDER BY updated_at DESC
            LIMIT 1
        """),
        {
            "query_vector": query_vector_str,
            "incident_id": incident_id,
        },
    ).first()
    if row is None or row[0] is None:
        return {
            "distance": None,
            "cosine_similarity": None,
            "vector_score": None,
            "clipped": None,
        }
    distance = float(row[0])
    similarity = 1.0 - distance
    return {
        "distance": distance,
        "cosine_similarity": similarity,
        "vector_score": max(0.0, similarity),
        "clipped": similarity <= 0.0,
    }


def raw_evidence(session, incident_id: uuid.UUID) -> dict[str, Any]:
    logs = list(
        session.scalars(select(RawLog).where(RawLog.incident_id == incident_id)).all()
    )
    tickets = list(
        session.scalars(
            select(RawTicket).where(RawTicket.incident_id == incident_id)
        ).all()
    )
    prs = list(
        session.scalars(select(RawPr).where(RawPr.incident_id == incident_id)).all()
    )
    return {
        "raw_logs": [
            {
                "id": str(log.id),
                "error_type": log.error_type,
                "error_message": log.error_message,
                "normalized_summary": log.normalized_summary,
                "extracted_keywords": log.extracted_keywords,
                "domain_tags": log.domain_tags,
                "raw_message": log.raw_message,
            }
            for log in logs
        ],
        "raw_tickets": [
            {
                "id": str(ticket.id),
                "ticket_key": ticket.ticket_key,
                "title": ticket.title,
                "normalized_summary": ticket.normalized_summary,
                "extracted_keywords": ticket.extracted_keywords,
                "domain_tags": ticket.domain_tags,
                "suspected_cause": ticket.suspected_cause,
                "resolution_note": ticket.resolution_note,
            }
            for ticket in tickets
        ],
        "raw_prs": [
            {
                "id": str(pr.id),
                "pr_key": pr.pr_key,
                "title": pr.title,
                "diff_summary": pr.diff_summary,
                "normalized_summary": pr.normalized_summary,
                "extracted_keywords": pr.extracted_keywords,
                "domain_tags": pr.domain_tags,
                "suspected_fix_for": pr.suspected_fix_for,
                "resolution_note": pr.resolution_note,
            }
            for pr in prs
        ],
    }


def evidence_has_more_searchable_data(incident: Incident, evidence: dict[str, Any]) -> bool:
    incident_text = stringify(
        [
            incident.primary_error_summary,
            incident.error_keywords,
            incident.domain_tags,
            incident.suspected_cause,
            incident.root_cause_summary,
            incident.resolution_summary,
        ]
    )
    evidence_text = stringify(evidence)
    return bool(evidence_text.strip()) and len(evidence_text) > len(incident_text) + 30


def evidence_signal_counts(evidence: dict[str, Any]) -> dict[str, int]:
    return {
        "raw_logs_with_summary": sum(
            1 for item in evidence["raw_logs"] if item.get("normalized_summary")
        ),
        "raw_logs_with_keywords": sum(
            1 for item in evidence["raw_logs"] if item.get("extracted_keywords")
        ),
        "raw_logs_with_domain_tags": sum(
            1 for item in evidence["raw_logs"] if item.get("domain_tags")
        ),
        "raw_tickets_with_summary": sum(
            1 for item in evidence["raw_tickets"] if item.get("normalized_summary")
        ),
        "raw_tickets_with_keywords": sum(
            1 for item in evidence["raw_tickets"] if item.get("extracted_keywords")
        ),
        "raw_tickets_with_cause_or_resolution": sum(
            1
            for item in evidence["raw_tickets"]
            if item.get("suspected_cause") or item.get("resolution_note")
        ),
        "raw_prs_with_summary": sum(
            1 for item in evidence["raw_prs"] if item.get("normalized_summary")
        ),
        "raw_prs_with_keywords": sum(
            1 for item in evidence["raw_prs"] if item.get("extracted_keywords")
        ),
        "raw_prs_with_fix_or_diff": sum(
            1
            for item in evidence["raw_prs"]
            if item.get("suspected_fix_for")
            or item.get("resolution_note")
            or item.get("diff_summary")
        ),
    }


def incident_record(
    session,
    embedding_service: EmbeddingService,
    *,
    case: dict[str, Any],
    incident_id: uuid.UUID,
    role: str,
    rank: int | None = None,
) -> dict[str, Any]:
    incident = load_incident(session, incident_id)
    embedding = latest_embedding(session, incident_id)
    indexed_text = searchable_text(session, incident_id)
    evidence = raw_evidence(session, incident_id)
    rewritten_query = case["rewritten_query"] or case["original_query"]
    query_tokens = tokenize(rewritten_query)
    indexed_tokens = tokenize(indexed_text)
    embedding_text = embedding.embedding_text if embedding else None
    embedding_tokens = tokenize(embedding_text)
    vector = vector_distance_for_query(
        session,
        embedding_service,
        query=rewritten_query,
        incident_id=incident_id,
    )
    bm25_rank, bm25_score = bm25_rank_for_expected(
        session,
        project_name=case["project_name"],
        query=rewritten_query,
        incident_id=incident_id,
    )

    fields = {
        "primary_error_type": incident.primary_error_type,
        "primary_error_message": incident.primary_error_message,
        "primary_error_summary": incident.primary_error_summary,
        "error_keywords": incident.error_keywords,
        "domain_tags": incident.domain_tags,
        "suspected_cause": incident.suspected_cause,
        "root_cause_summary": incident.root_cause_summary,
        "resolution_summary": incident.resolution_summary,
        "related_log_ids": incident.related_log_ids,
        "related_ticket_ids": incident.related_ticket_ids,
        "related_pr_ids": incident.related_pr_ids,
    }
    field_states = {name: field_state(value).__dict__ for name, value in fields.items()}

    source_updated_at = embedding.source_updated_at if embedding else None
    incident_updated_at = incident.updated_at
    stale = None
    if source_updated_at is not None and incident_updated_at is not None:
        if source_updated_at.tzinfo is None:
            source_updated_at = source_updated_at.replace(tzinfo=timezone.utc)
        if incident_updated_at.tzinfo is None:
            incident_updated_at = incident_updated_at.replace(tzinfo=timezone.utc)
        stale = source_updated_at < incident_updated_at

    query_hits_embedding = find_token_hits(query_tokens, embedding_text)
    query_hits_indexed = find_token_hits(query_tokens, indexed_text)
    missing_indexed = [token for token in query_tokens if token not in query_hits_indexed]

    embedding_field_inclusion = {}
    for field in INTENDED_BM25_FIELDS:
        value = getattr(incident, field)
        value_text = stringify(value)
        if not value_text:
            embedding_field_inclusion[field] = "source_empty"
        else:
            embedding_field_inclusion[field] = (
                "included" if value_text.lower() in (embedding_text or "").lower() else "partial_or_missing"
            )

    return {
        "role": role,
        "rank": rank,
        "id": str(incident.id),
        "project_name": incident.project_name,
        "status": incident.status,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
        "fields": {name: stringify(value) if not isinstance(value, list) else value for name, value in fields.items()},
        "field_states": field_states,
        "raw_evidence": evidence,
        "raw_evidence_counts": {
            "raw_logs": len(evidence["raw_logs"]),
            "raw_tickets": len(evidence["raw_tickets"]),
            "raw_prs": len(evidence["raw_prs"]),
        },
        "raw_evidence_signal_counts": evidence_signal_counts(evidence),
        "raw_evidence_has_more_searchable_data": evidence_has_more_searchable_data(
            incident,
            evidence,
        ),
        "searchable_text": indexed_text,
        "searchable_text_length": len(indexed_text or ""),
        "searchable_text_tokens": indexed_tokens,
        "embedding": {
            "exists": embedding is not None,
            "id": str(embedding.id) if embedding else None,
            "embedding_text": embedding_text,
            "embedding_text_length": len(embedding_text or ""),
            "embedding_vector_exists": embedding is not None,
            "embedding_vector_dimension": vector_dimension(
                session,
                embedding.id if embedding else None,
            ),
            "embedding_model": embedding.embedding_model if embedding else None,
            "embedding_version": embedding.embedding_version if embedding else None,
            "source_updated_at": (
                embedding.source_updated_at.isoformat() if embedding else None
            ),
            "created_at": embedding.created_at.isoformat() if embedding else None,
            "updated_at": embedding.updated_at.isoformat() if embedding else None,
            "stale_vs_incident_updated_at": stale,
            "field_inclusion": embedding_field_inclusion,
            "tokens": embedding_tokens,
        },
        "query_analysis": {
            "original_query": case["original_query"],
            "rewritten_query": case["rewritten_query"],
            "bm25_actual_query": rewritten_query,
            "query_tokens": query_tokens,
            "embedding_token_hits": query_hits_embedding,
            "indexed_token_hits": query_hits_indexed,
            "indexed_token_misses": missing_indexed,
        },
        "vector": vector,
        "bm25": {
            "rank": bm25_rank,
            "score": bm25_score,
        },
    }


def load_index_metadata(session) -> dict[str, Any]:
    index_rows = session.execute(
        text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'incidents'
              AND indexname LIKE '%bm25%'
            ORDER BY indexname
        """)
    ).mappings().all()
    function_row = session.execute(
        text("""
            SELECT pg_get_functiondef('public.incident_searchable_text(
                text,text,text,jsonb,jsonb,text,text,text
            )'::regprocedure)
        """)
    ).first()
    return {
        "bm25_indexes": [dict(row) for row in index_rows],
        "incident_searchable_text_function": function_row[0] if function_row else None,
    }


def load_dataset_overview(session) -> dict[str, Any]:
    by_project_rows = session.execute(
        text("""
            SELECT
                project_name,
                count(*) AS total,
                count(primary_error_summary) AS summary_present,
                count(resolution_summary) AS resolution_present,
                count(*) FILTER (
                    WHERE error_keywords IS NOT NULL
                      AND jsonb_array_length(error_keywords) > 0
                ) AS keywords_present,
                count(*) FILTER (
                    WHERE domain_tags IS NOT NULL
                      AND jsonb_array_length(domain_tags) > 0
                ) AS domain_tags_present
            FROM incidents
            GROUP BY project_name
            ORDER BY project_name
        """)
    ).mappings().all()
    first_rows = session.execute(
        text("""
            SELECT
                id,
                project_name,
                primary_error_summary IS NOT NULL AS summary_present,
                error_keywords,
                domain_tags,
                created_at
            FROM incidents
            ORDER BY created_at ASC
            LIMIT 8
        """)
    ).mappings().all()
    latest_rows = session.execute(
        text("""
            SELECT
                id,
                project_name,
                primary_error_summary IS NOT NULL AS summary_present,
                error_keywords,
                domain_tags,
                created_at
            FROM incidents
            ORDER BY created_at DESC
            LIMIT 8
        """)
    ).mappings().all()
    raw_counts = session.execute(
        text("""
            SELECT
                (SELECT count(*) FROM raw_logs) AS raw_logs,
                (SELECT count(*) FROM raw_tickets) AS raw_tickets,
                (SELECT count(*) FROM raw_prs) AS raw_prs
        """)
    ).mappings().first()
    return {
        "by_project": [dict(row) for row in by_project_rows],
        "first_incidents": [dict(row) for row in first_rows],
        "latest_incidents": [dict(row) for row in latest_rows],
        "raw_counts": dict(raw_counts or {}),
    }


def classify_root_cause(expected: dict[str, Any]) -> tuple[str, str]:
    states = expected["field_states"]
    summary_missing = states["primary_error_summary"]["state"] != "present"
    keywords_missing = states["error_keywords"]["state"] != "present"
    tags_missing = states["domain_tags"]["state"] != "present"
    cause_missing = states["suspected_cause"]["state"] != "present"
    root_missing = states["root_cause_summary"]["state"] != "present"
    resolution_missing = states["resolution_summary"]["state"] != "present"
    bm25_miss = expected["bm25"]["rank"] is None
    vector_score = expected["vector"]["vector_score"]
    embedding_exists = expected["embedding"]["exists"]
    stale = expected["embedding"]["stale_vs_incident_updated_at"]
    raw_more = expected["raw_evidence_has_more_searchable_data"]
    token_hits = expected["query_analysis"]["indexed_token_hits"]
    token_misses = expected["query_analysis"]["indexed_token_misses"]

    if not embedding_exists:
        return "EMBEDDING_MISSING", "embedding row가 없어 vector 검색 입력이 누락됐다."
    if stale:
        return "EMBEDDING_STALE", "incident.updated_at 이후 embedding이 갱신되지 않았다."
    if summary_missing and keywords_missing and tags_missing and cause_missing and root_missing and resolution_missing:
        return (
            "INCIDENT_ENRICHMENT_MISSING",
            "incident에는 error_type/message 외 검색 보강 필드가 대부분 비어 있다.",
        )
    if raw_more and (summary_missing or keywords_missing or tags_missing or resolution_missing):
        return (
            "RAW_EVIDENCE_NOT_PROPAGATED",
            "raw_*에는 추가 정보가 있으나 incidents 검색 필드에 충분히 반영되지 않았다.",
        )
    if bm25_miss and not token_hits:
        return (
            "KOREAN_TOKENIZATION_OR_SYNONYM_MISMATCH",
            "BM25 indexed text와 query 사이에 직접 일치 token이 거의 없다.",
        )
    if bm25_miss and token_hits and token_misses:
        return (
            "BM25_QUERY_TEXT_MISMATCH",
            "일부 token은 겹치지만 핵심 query token이 indexed text에 부족하다.",
        )
    if vector_score == 0.0:
        return (
            "VECTOR_INPUT_WEAK_OR_NEGATIVE_SIMILARITY",
            "cosine similarity가 0 이하로 clip되어 vector_score가 0.0이다.",
        )
    return "SEARCH_ALGORITHM_RANKING", "데이터는 일부 존재하지만 검색 순위 산식에서 Top3까지 못 올라왔다."


def bm25_failure_reasons(expected: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    states = expected["field_states"]
    if states["primary_error_summary"]["state"] != "present":
        reasons.append("INCIDENT_DATA_MISSING")
    if (
        states["error_keywords"]["state"] != "present"
        or states["domain_tags"]["state"] != "present"
    ):
        reasons.append("ARRAY_JSON_NOT_INDEXED")
    if not expected["searchable_text"]:
        reasons.append("SEARCH_TEXT_MISSING_FIELD")
    if expected["embedding"]["stale_vs_incident_updated_at"]:
        reasons.append("INDEX_STALE")
    if not expected["query_analysis"]["indexed_token_hits"]:
        reasons.append("KOREAN_TOKENIZATION_MISMATCH")
    if expected["query_analysis"]["indexed_token_misses"]:
        reasons.append("ENGLISH_KOREAN_SYNONYM_MISMATCH")
    if len(expected["query_analysis"]["query_tokens"]) <= 2:
        reasons.append("QUERY_TOO_GENERIC")
    return list(dict.fromkeys(reasons or ["OTHER"]))


def build_payload() -> dict[str, Any]:
    cases = load_source_cases()
    settings = get_settings()
    with SessionLocal() as session:
        embedding_service = EmbeddingService(
            settings,
            IncidentEmbeddingRepository(session),
        )
        index_metadata = load_index_metadata(session)
        dataset_overview = load_dataset_overview(session)
        diagnosed_cases: list[dict[str, Any]] = []
        for case in cases:
            expected_id = to_uuid(case["expected_incident_id"])
            expected = incident_record(
                session,
                embedding_service,
                case=case,
                incident_id=expected_id,
                role="expected",
            )
            top3 = [
                incident_record(
                    session,
                    embedding_service,
                    case=case,
                    incident_id=to_uuid(candidate["incident_id"]),
                    role="rrf_top3",
                    rank=candidate["rank"],
                )
                for candidate in case["stored_rrf_top3_candidates"]
            ]
            primary_root_cause, recommended_fix = classify_root_cause(expected)
            diagnosed_cases.append(
                {
                    "case_key": case["case_key"],
                    "category": case["category"],
                    "project_name": case["project_name"],
                    "expected_incident_id": case["expected_incident_id"],
                    "stored_rewritten_ranks": case["stored_rewritten_ranks"],
                    "expected": expected,
                    "rrf_top3_wrong_candidates": top3,
                    "bm25_failure_reasons": bm25_failure_reasons(expected),
                    "primary_root_cause": primary_root_cause,
                    "recommended_fix": recommended_fix,
                }
            )

        summary_none_count = sum(
            1
            for case in diagnosed_cases
            if case["expected"]["field_states"]["primary_error_summary"]["state"]
            != "present"
        )
        top3_summary_none_count = sum(
            1
            for case in diagnosed_cases
            for candidate in case["rrf_top3_wrong_candidates"]
            if candidate["field_states"]["primary_error_summary"]["state"] != "present"
        )
        vector_zero_count = sum(
            1
            for case in diagnosed_cases
            if case["expected"]["vector"]["vector_score"] == 0.0
        )
        root_cause_counts = Counter(
            case["primary_root_cause"] for case in diagnosed_cases
        )
        bm25_reason_counts = Counter(
            reason
            for case in diagnosed_cases
            for reason in case["bm25_failure_reasons"]
        )
        return {
            "source_report": str(SOURCE_REPORT_PATH),
            "scope": {
                "target_failure_type": "RRF_RANKING_MISS",
                "case_count": len(diagnosed_cases),
            },
            "index_metadata": index_metadata,
            "dataset_overview": dataset_overview,
            "summary": {
                "expected_summary_missing_count": summary_none_count,
                "top3_wrong_candidate_summary_missing_count": top3_summary_none_count,
                "expected_vector_score_zero_count": vector_zero_count,
                "primary_root_cause_counts": dict(root_cause_counts),
                "bm25_failure_reason_counts": dict(bm25_reason_counts),
            },
            "cases": diagnosed_cases,
        }


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, bool):
        return "Y" if value else "N"
    return str(value)


def yes_no(condition: bool) -> str:
    return "Y" if condition else "N"


def short(value: str | None, limit: int = 120) -> str:
    if not value:
        return "-"
    one_line = " ".join(str(value).split())
    return one_line if len(one_line) <= limit else one_line[: limit - 3] + "..."


def write_markdown(payload: dict[str, Any]) -> None:
    lines: list[str] = [
        "# Retrieval Input Diagnosis v1",
        "",
        f"- source_report: `{payload['source_report']}`",
        f"- 분석 대상: `{payload['scope']['target_failure_type']}`",
        f"- 케이스 수: `{payload['scope']['case_count']}`",
        "",
        "## Executive Summary",
        "",
        (
            "- 17건 모두 정답 Incident가 BM25 후보에 없고, Vector에서는 후보에 존재하지만 Top3 밖입니다."
        ),
        (
            f"- expected Incident의 primary_error_summary 누락: "
            f"`{payload['summary']['expected_summary_missing_count']}` / 17"
        ),
        (
            f"- RRF Top3 오답 후보의 primary_error_summary 누락: "
            f"`{payload['summary']['top3_wrong_candidate_summary_missing_count']}` / 51"
        ),
        (
            f"- expected Incident vector_score=0.0: "
            f"`{payload['summary']['expected_vector_score_zero_count']}` / 17"
        ),
        "",
        "## 데이터 완성도 Overview",
        "",
        "| project_name | total | summary_present | keywords_present | domain_tags_present | resolution_present |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["dataset_overview"]["by_project"]:
        lines.append(
            "| "
            f"{row['project_name']} | "
            f"{row['total']} | "
            f"{row['summary_present']} | "
            f"{row['keywords_present']} | "
            f"{row['domain_tags_present']} | "
            f"{row['resolution_present']} |"
        )

    lines.extend(
        [
            "",
            f"- raw table row counts: `{payload['dataset_overview']['raw_counts']}`",
            "- 생성 시점 기준 초반 incident에는 summary/keywords/domain_tags가 채워진 사례가 있으나, 이후 seed incident는 대부분 비어 있습니다.",
            "- 이는 report 조회 문제가 아니라 데이터 생성/enrichment 경로 차이입니다.",
            "",
            "초기 incident 샘플:",
            "",
            "| id | project | summary_present | keywords | domain_tags | created_at |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["dataset_overview"]["first_incidents"]:
        lines.append(
            "| "
            f"`{row['id']}` | {row['project_name']} | "
            f"{yes_no(row['summary_present'])} | "
            f"{short(stringify(row['error_keywords']), 80)} | "
            f"{short(stringify(row['domain_tags']), 60)} | "
            f"{row['created_at']} |"
        )
    lines.extend(
        [
            "",
            "최근 incident 샘플:",
            "",
            "| id | project | summary_present | keywords | domain_tags | created_at |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["dataset_overview"]["latest_incidents"]:
        lines.append(
            "| "
            f"`{row['id']}` | {row['project_name']} | "
            f"{yes_no(row['summary_present'])} | "
            f"{short(stringify(row['error_keywords']), 80)} | "
            f"{short(stringify(row['domain_tags']), 60)} | "
            f"{row['created_at']} |"
        )

    lines.extend(
        [
            "",
            "### Primary Root Cause Counts",
            "",
            "| root cause | count |",
            "| --- | ---: |",
        ]
    )
    for name, count in sorted(payload["summary"]["primary_root_cause_counts"].items()):
        lines.append(f"| `{name}` | {count} |")

    lines.extend(
        [
            "",
            "### BM25 Failure Reason Counts",
            "",
            "| reason | count |",
            "| --- | ---: |",
        ]
    )
    for name, count in sorted(payload["summary"]["bm25_failure_reason_counts"].items()):
        lines.append(f"| `{name}` | {count} |")

    lines.extend(
        [
            "",
            "## BM25 Index 점검",
            "",
            "현재 BM25 document는 `public.incident_searchable_text(...)` 함수 결과를 `pdb.simple`로 인덱싱합니다.",
            "",
            "의도 검색 필드 포함 여부:",
            "",
            "| field | 포함 여부 | 비고 |",
            "| --- | --- | --- |",
        ]
    )
    function_def = payload["index_metadata"]["incident_searchable_text_function"] or ""
    for field in INTENDED_BM25_FIELDS:
        included = field in function_def
        note = "함수 정의에 포함" if included else "함수 정의에서 누락"
        if field in {"error_keywords", "domain_tags"}:
            note += ", jsonb_array_elements_text로 배열 문자열화"
        lines.append(f"| `{field}` | {yes_no(included)} | {note} |")

    lines.extend(
        [
            "",
            "BM25 인덱스 정의:",
            "",
        ]
    )
    for index in payload["index_metadata"]["bm25_indexes"]:
        lines.append(f"- `{index['indexname']}`: `{index['indexdef']}`")

    lines.extend(
        [
            "",
            "판단:",
            "",
            "- `concat_ws`를 사용하므로 일부 필드가 null이어도 전체 searchable text가 null이 되지는 않습니다.",
            "- 배열 필드는 함수 정의상 문자열화됩니다. 다만 값 자체가 빈 배열이면 인덱싱할 token이 없습니다.",
            "- `CREATE INDEX IF NOT EXISTS` 구조라 함수 정의가 바뀐 뒤 기존 인덱스가 자동 재생성되지는 않습니다. 이번 진단에서는 인덱스를 재생성하지 않았습니다.",
            "- project_name 필터와 BM25 조건은 같은 WHERE 절에 함께 적용됩니다.",
            "",
            "## Summary=None 원인",
            "",
            "- 리포트 코드의 조회 문제나 ORM mapping 문제라기보다, 실제 `incidents.primary_error_summary`가 null인 데이터가 많습니다.",
            "- 초기 일부 incident는 summary가 존재하지만, seed 이후 생성된 다수 incident는 error_type/message 중심으로만 채워지고 summary/keywords/domain_tags/root_cause/resolution이 비어 있습니다.",
            "- 따라서 `summary=None`은 report mapping bug가 아니라 incident enrichment 누락 또는 seed 데이터 생성 경로 차이로 보는 것이 맞습니다.",
            "",
            "## Embedding 점검",
            "",
            "- embedding_text는 incident 필드만 조합합니다: project/module/class/status/error_type/summary/message/cause/root_cause/resolution/keywords/tags.",
            "- raw_logs/raw_tickets/raw_prs 원문은 embedding_text에 직접 포함되지 않습니다.",
            "- incident의 summary, keywords, tags, cause, resolution이 비어 있으면 embedding_text도 error_type/message 위주로 짧아집니다.",
            "",
            "## Vector Score 0.0 원인",
            "",
            "- 현재 score 계산은 `max(0.0, 1.0 - cosine_distance)`입니다.",
            "- pgvector cosine distance는 `1 - cosine_similarity`이므로, distance가 1 이상이면 similarity가 0 이하입니다.",
            "- 따라서 vector_score=0.0은 표시 반올림 문제가 아니라 음수 또는 0 이하 similarity가 clipping된 결과입니다.",
            "",
            "## 실패 케이스별 진단표",
            "",
            "| case_key | expected_incident_id | summary | embedding | embedding 핵심어 | raw similarity | vector rank | BM25 doc | BM25 match token | BM25 rank | primary root cause | recommended fix |",
            "| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | ---: | --- | --- |",
        ]
    )

    for case in payload["cases"]:
        expected = case["expected"]
        stored = case["stored_rewritten_ranks"]
        summary_present = (
            expected["field_states"]["primary_error_summary"]["state"] == "present"
        )
        embedding_exists = expected["embedding"]["exists"]
        hits = expected["query_analysis"]["embedding_token_hits"]
        indexed_hits = expected["query_analysis"]["indexed_token_hits"]
        lines.append(
            "| "
            f"`{case['case_key']}` | "
            f"`{case['expected_incident_id']}` | "
            f"{yes_no(summary_present)} | "
            f"{yes_no(embedding_exists)} | "
            f"{', '.join(hits) if hits else '-'} | "
            f"{fmt(expected['vector']['cosine_similarity'])} | "
            f"{fmt(stored['vector_rank'])} | "
            f"{yes_no(bool(expected['searchable_text']))} | "
            f"{', '.join(indexed_hits) if indexed_hits else '-'} | "
            f"{fmt(expected['bm25']['rank'])} | "
            f"`{case['primary_root_cause']}` | "
            f"{case['recommended_fix']} |"
        )

    lines.extend(
        [
            "",
            "## 케이스별 상세",
            "",
        ]
    )
    for case in payload["cases"]:
        expected = case["expected"]
        q = expected["query_analysis"]
        lines.extend(
            [
                f"### {case['case_key']}",
                "",
                f"- project_name: `{case['project_name']}`",
                f"- expected_incident_id: `{case['expected_incident_id']}`",
                f"- original_query: {q['original_query']}",
                f"- rewritten_query / BM25 actual query: {q['bm25_actual_query']}",
                f"- query tokens: `{', '.join(q['query_tokens']) or '-'}`",
                f"- indexed token hits: `{', '.join(q['indexed_token_hits']) or '-'}`",
                f"- indexed token misses: `{', '.join(q['indexed_token_misses']) or '-'}`",
                f"- bm25 failure reasons: `{', '.join(case['bm25_failure_reasons'])}`",
                f"- vector distance: `{fmt(expected['vector']['distance'])}`",
                f"- cosine similarity: `{fmt(expected['vector']['cosine_similarity'])}`",
                f"- vector score: `{fmt(expected['vector']['vector_score'])}`",
                f"- vector clipped: `{fmt(expected['vector']['clipped'])}`",
                f"- BM25 rank/score: `{fmt(expected['bm25']['rank'])}` / `{fmt(expected['bm25']['score'])}`",
                f"- embedding length/dim: `{expected['embedding']['embedding_text_length']}` / `{expected['embedding']['embedding_vector_dimension']}`",
                f"- embedding stale vs incident.updated_at: `{fmt(expected['embedding']['stale_vs_incident_updated_at'])}`",
                f"- raw evidence counts: `{expected['raw_evidence_counts']}`",
                f"- raw evidence signal counts: `{expected['raw_evidence_signal_counts']}`",
                "",
                "Incident field states:",
                "",
                "| field | state | value preview |",
                "| --- | --- | --- |",
            ]
        )
        for field in [
            "primary_error_type",
            "primary_error_message",
            "primary_error_summary",
            "error_keywords",
            "domain_tags",
            "suspected_cause",
            "root_cause_summary",
            "resolution_summary",
            "related_log_ids",
            "related_ticket_ids",
            "related_pr_ids",
        ]:
            lines.append(
                f"| `{field}` | `{expected['field_states'][field]['state']}` | "
                f"{short(stringify(expected['fields'][field]))} |"
            )
        lines.extend(
            [
                "",
                f"- BM25 indexed text: {short(expected['searchable_text'], 400)}",
                f"- embedding_text: {short(expected['embedding']['embedding_text'], 400)}",
                "",
                "RRF Top3 오답 후보:",
                "",
                "| rank | incident_id | summary | error_type | vector_score | BM25 rank | BM25 token hits |",
                "| ---: | --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for candidate in case["rrf_top3_wrong_candidates"]:
            lines.append(
                "| "
                f"{candidate['rank']} | "
                f"`{candidate['id']}` | "
                f"{short(candidate['fields']['primary_error_summary'], 80)} | "
                f"{candidate['fields']['primary_error_type'] or '-'} | "
                f"{fmt(candidate['vector']['vector_score'])} | "
                f"{fmt(candidate['bm25']['rank'])} | "
                f"{', '.join(candidate['query_analysis']['indexed_token_hits']) or '-'} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 수정 우선순위 제안",
            "",
            "A. 데이터 생성/보강 오류",
            "",
            "- 최우선입니다. 실패 expected incident 대부분이 summary/keywords/domain_tags/root_cause/resolution이 비어 있어 BM25와 embedding 입력이 모두 약합니다.",
            "- raw_*에 존재하는 정규화 요약, 키워드, 도메인, PR resolution 정보를 incidents로 확실히 merge하는 경로를 점검해야 합니다.",
            "",
            "B. embedding 재생성 필요",
            "",
            "- incident 보강 이후에는 반드시 incident_embeddings를 재생성해야 합니다.",
            "- 현재 embedding row 자체는 존재하지만, 비어 있는 incident 필드를 기반으로 생성된 텍스트라 검색력이 낮습니다.",
            "",
            "C. BM25 인덱스 또는 searchable text 오류",
            "",
            "- 함수 구성 자체는 의도 필드를 포함하고 null 전체 전파 문제도 없습니다.",
            "- 다만 인덱스가 `CREATE INDEX IF NOT EXISTS`라 함수 변경 이후 재생성이 필요한 상황은 별도 migration으로 관리해야 합니다.",
            "",
            "D. 한국어/영어 표현 불일치",
            "",
            "- BM25 miss 17건 모두 query token과 indexed text token의 직접 일치가 약합니다.",
            "- 예: `권한 문제` vs `AccessDeniedException`, `Redis 접속 제한` vs 저장 message에 Redis/connection 정보 없음.",
            "",
            "E. Query Rewrite 문제",
            "",
            "- 7건에서 rewritten query가 원본 대비 rank를 낮췄지만, Top3 loss는 0건입니다.",
            "- 현재 주 원인은 Query Rewrite보다 입력 데이터 부족입니다.",
            "",
            "F. 검색 알고리즘 자체 문제",
            "",
            "- 데이터 보강 후에도 BM25/Vector가 Top3를 못 올리는 케이스에 한해 RRF 가중치, BM25 analyzer, synonym expansion, field weighting을 실험하는 순서가 맞습니다.",
        ]
    )

    MD_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    payload = build_payload()
    JSON_REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    write_markdown(payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {MD_REPORT_PATH}")
    print(f"wrote {JSON_REPORT_PATH}")


if __name__ == "__main__":
    main()
