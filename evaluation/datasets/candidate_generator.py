from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm import OpenAiChatClient
from app.models.incident import Incident
from app.models.raw_log import RawLog
from app.models.raw_pr import RawPr
from app.models.raw_ticket import RawTicket
from evaluation.common import EVALUATION_DATA_DIR, utc_now_iso, write_json
from evaluation.datasets.models import QueryType, RetrievalDataset, RetrievalQuery


REVIEW_POLICY = [
    "Query가 실제 사용자 질문으로 자연스러운가",
    "IncidentLens가 현재 장애를 모르는 상태에서 검색창/Slack에 입력할 법한 문장인가",
    "사용자가 텍스트로 관찰할 수 있는 Exception, Error Message, Error Code, 기능, API, 클래스/메서드, 증상만 포함했는가",
    "Root Cause, Suspected Cause, Resolution, Fix Summary, Ticket에서 확인된 최종 원인을 포함하지 않았는가",
    "정답 Incident가 명확한가",
    "Incident의 문장을 지나치게 그대로 복사하지 않았는가",
    "Query Type 분류가 적절한가",
    "특정 Retrieval 방식에 유리하도록 만들어지지 않았는가",
    "ambiguous 외 Query에서 여러 Incident가 정답일 수 있는 표현은 없는가",
    "부적합한 Query는 excluded=true와 exclude_reason으로 표시했는가",
]

GENERATOR_RULES = """
IncidentLens is not a real-time monitoring agent and does not know the current
incident state. It only receives text typed by a developer and searches for
similar past internal incidents.

Generate candidate retrieval queries that a real developer would type into
Slack, an internal search box, a messenger, or an IDE while looking for past
incident examples.

Hard constraints:
- The user can provide text only. There are no screenshots, attachments,
  auto-collected logs, monitoring data, dashboards, metrics, or live system
  state.
- A query may contain only observable information: copied exception text, error
  message, error code, feature/API/controller/class/method names, timing,
  operation being attempted, intermittent behavior, timeout, HTTP status codes,
  or symptoms the developer can see.
- Do not write natural_language queries as if the user already knows the final
  root cause.
- For natural_language, avoid causal wording such as "때문에", "없어서",
  "누락돼서", "문제로", "원인", or "이유". Prefer symptom wording:
  "안 돼", "실패해", "오류가 나", "타임아웃돼", "500이 떠", "403이 떠",
  "클래스를 못 찾는다고 나와", "가끔 실패해".
- Do not use Root Cause, Suspected Cause, Resolution, Fix Summary, ticket cause,
  or PR fix details in query_text. These fields are supplied only so you can
  understand which incident the query should target.
- Avoid repetitive endings such as "원인이 무엇인가요?" or "이유가 무엇인가요?".
  Use natural Korean developer phrasing such as "비슷한 사례 있었어?",
  "전에 이런 적 있었나?", "혹시 예전 장애 있어?", "검색해줘", "왜 이러지?",
  or short search-keyword style phrases.
- Do not overfit a query to Vector, BM25, or Hybrid retrieval.

Query type rules:
- exact_error: Use a real exact error message or highly exact copied log line.
- error_type_only: Use only exact identifiers such as exception names, error
  codes, class names, controller names, or method names. Keep it terse.
- natural_language: Describe only visible symptoms or what the developer was
  doing. Never include root cause/suspected cause/resolution/fix details.
- cause_keyword: Use broad technical keywords a developer could plausibly guess
  from symptoms, such as JWT, Kafka, Redis, Timeout, Cache, Authentication,
  Webhook, JSON, 동시 처리. Do not use final root-cause labels such as
  Concurrent Update Conflict, REPORT_ADMIN Missing, Missing Column,
  Serialization Root Cause, Bean registration failure, missing role names,
  missing column/file names, "누락", or "required role".
- ambiguous: Searchable but intentionally broad and possibly confused with
  multiple incidents, such as "로그인이 안 된다", "배치가 실패한다", "조회가 안 된다".

If a type cannot be generated without leaking root cause or sounding unnatural,
omit that query type instead of forcing it.
Return JSON only.
""".strip()


class _GeneratedQuery(BaseModel):
    query_text: str
    query_type: QueryType
    note: str | None = None


class _GeneratedQueries(BaseModel):
    queries: list[_GeneratedQuery] = Field(default_factory=list)


def generate_candidate_dataset(
    *,
    session: Session,
    settings: Settings,
    output_path: Path | None = None,
    project_name: str | None = None,
    limit: int | None = None,
) -> RetrievalDataset:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to generate LLM candidates.")

    stmt = select(Incident).order_by(Incident.project_name.asc(), Incident.id.asc())
    if project_name:
        stmt = stmt.where(Incident.project_name == project_name)
    if limit:
        stmt = stmt.limit(limit)
    incidents = list(session.scalars(stmt).all())

    llm = OpenAiChatClient(settings)
    queries: list[RetrievalQuery] = []
    for incident in incidents:
        generated = _generate_queries_for_incident(
            session=session,
            llm=llm,
            incident=incident,
        )
        seen_types: dict[str, int] = {}
        for item in generated:
            seen_types[item.query_type] = seen_types.get(item.query_type, 0) + 1
            suffix = seen_types[item.query_type]
            exclude_reason = _candidate_exclude_reason(item)
            queries.append(
                RetrievalQuery(
                    query_id=_query_id(incident, item.query_type, suffix),
                    query_text=item.query_text,
                    query_type=item.query_type,
                    expected_incident_id=str(incident.id),
                    project_name=incident.project_name,
                    note=item.note,
                    generated_by_llm=True,
                    excluded=exclude_reason is not None,
                    exclude_reason=exclude_reason,
                )
            )

    dataset = RetrievalDataset(
        status="candidate",
        generated_at=utc_now_iso(),
        source={
            "incident_count": len(incidents),
            "generator": "evaluation.datasets.candidate_generator",
            "model": settings.llm_model_name,
        },
        review_policy=REVIEW_POLICY,
        queries=queries,
    )
    write_json(
        output_path or EVALUATION_DATA_DIR / "retrieval_queries_candidate.json",
        dataset.model_dump(),
    )
    return dataset


def _generate_queries_for_incident(
    *,
    session: Session,
    llm: OpenAiChatClient,
    incident: Incident,
) -> list[_GeneratedQuery]:
    messages = [
        {
            "role": "developer",
            "content": GENERATOR_RULES,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "incident": _incident_payload(session, incident),
                    "query_types": {
                        "exact_error": "실제 Error Message 또는 복사한 로그 문구",
                        "error_type_only": "Exception, Error Code, Class/Controller/Method 같은 정확한 식별자",
                        "natural_language": "개발자가 증상만 설명하는 자연어. Root Cause 금지",
                        "cause_keyword": "사용자가 추측할 수 있는 넓은 기술 키워드. 최종 원인명 금지",
                        "ambiguous": "검색은 가능하지만 여러 Incident와 혼동될 수 있는 짧은 Query",
                    },
                    "output_requirements": [
                        "Create up to one query for each query type.",
                        "Prefer Korean unless the query is an exact copied error or identifier.",
                        "Keep query_text as the developer would type it.",
                        "Use note to explain why the query is observable and appropriate.",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    text = llm.chat_json_schema_strict(
        messages,
        schema_model=_GeneratedQueries,
        schema_name="IncidentEvaluationQueries",
    )
    if not text:
        raise RuntimeError(f"LLM candidate generation failed for incident {incident.id}")
    try:
        parsed = _GeneratedQueries.model_validate_json(text)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid LLM candidate JSON for incident {incident.id}: {exc}") from exc
    return parsed.queries


def _incident_payload(session: Session, incident: Incident) -> dict[str, object]:
    logs = list(
        session.scalars(
            select(RawLog).where(RawLog.incident_id == incident.id).limit(3)
        ).all()
    )
    tickets = list(
        session.scalars(
            select(RawTicket).where(RawTicket.incident_id == incident.id).limit(3)
        ).all()
    )
    prs = list(
        session.scalars(
            select(RawPr).where(RawPr.incident_id == incident.id).limit(3)
        ).all()
    )
    return {
        "incident_id": str(incident.id),
        "project_name": incident.project_name,
        "observable_context_allowed_in_queries": {
            "module_name": incident.module_name,
            "class_name": incident.class_name,
            "method_name": incident.method_name,
            "primary_error_type": incident.primary_error_type,
            "primary_error_message": incident.primary_error_message,
            "primary_error_summary": incident.primary_error_summary,
            "error_keywords": incident.error_keywords or [],
            "domain_tags": incident.domain_tags or [],
        },
        "do_not_copy_into_queries_root_cause_context": {
            "suspected_cause": incident.suspected_cause,
            "root_cause_summary": incident.root_cause_summary,
            "resolution_summary": incident.resolution_summary,
        },
        "logs": [
            {
                "error_type": log.error_type,
                "error_message": log.error_message,
                "summary": log.normalized_summary,
            }
            for log in logs
        ],
        "tickets": [
            {
                "key": ticket.ticket_key,
                "title": ticket.title,
                "summary": ticket.normalized_summary,
                "do_not_copy_cause": ticket.suspected_cause,
                "do_not_copy_resolution": ticket.resolution_note,
            }
            for ticket in tickets
        ],
        "prs": [
            {
                "key": pr.pr_key,
                "title": pr.title,
                "summary": pr.normalized_summary,
                "do_not_copy_fix": pr.suspected_fix_for,
                "do_not_copy_resolution": pr.resolution_note,
            }
            for pr in prs
        ],
    }


def _query_id(incident: Incident, query_type: str, suffix: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", incident.project_name).strip("-").lower()
    return f"{slug}-{str(incident.id)[:8]}-{query_type}-{suffix}"


def _candidate_exclude_reason(query: _GeneratedQuery) -> str | None:
    text = query.query_text.strip()
    lower_text = text.lower()
    if query.query_type == "natural_language":
        blocked_patterns = [
            r"때문에",
            r"없어서",
            r"누락돼서",
            r"문제로",
            r"원인",
            r"이유",
            r"root cause",
            r"report_admin",
            r"동시성 문제",
            r"충돌 나서",
        ]
        if any(re.search(pattern, lower_text) for pattern in blocked_patterns):
            return "natural_language query includes causal/root-cause-like wording."
    if query.query_type == "cause_keyword":
        blocked_patterns = [
            r"report_admin",
            r"concurrent update conflict",
            r"missing column",
            r"missing file",
            r"required role",
            r"root cause",
            r"누락",
            r"최종 원인",
            r"bean 등록",
            r"등록이 안",
        ]
        if any(re.search(pattern, lower_text) for pattern in blocked_patterns):
            return "cause_keyword query includes a final root-cause term instead of broad technical keywords."
    return None
