from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.llm import OpenAiChatClient
from app.models.log_processing import (
    LlmEnrichedTicket,
    ParserConfidence,
    TicketPatternParsed,
)
from app.services.ticket.rule_match_service import RuleScoredIncident

from app.utils.json_text import extract_first_json_object
from app.utils.text_preview import preview_truncated

logger = logging.getLogger(__name__)


_EXPLICIT_ERROR_TYPE = re.compile(r"^[A-Z][A-Za-z0-9_]*(?:Exception|Error)$")


class _LlmTicketSchema(BaseModel):
    error_type: str | None = Field(
        default=None,
        description="본문에 명시된 Exception/Error 클래스명. 불명확하면 null.",
    )
    normalized_summary: str | None = Field(
        default=None,
        description="티켓 제목/본문에 근거한 한국어 1문장 요약.",
    )
    extracted_keywords: list[str] = Field(
        default_factory=list,
        description="검색용 짧은 키워드",
    )
    domain_tags: list[str] = Field(
        default_factory=list,
        description="도메인 태그",
    )
    suspected_cause: str | None = Field(
        default=None,
        description="본문에 근거가 있을 때만 원인 추정. 없으면 null.",
    )
    resolution_note: str | None = Field(
        default=None,
        description="해결/조치 메모. 본문 근거 없으면 null.",
    )
    correction_notes: str | None = Field(
        default=None,
        description="규칙 추출 대비 보정·주석. 없으면 null.",
    )
    parser_confidence: ParserConfidence = Field(
        default="low",
        description="위 필드(특히 패턴 관련)의 신뢰도 high|medium|low.",
    )


class SemanticEvalItem(BaseModel):
    incident_id: str = Field(..., description="UUID 문자열")
    semantic_score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    should_match: bool


class _SemanticEvalResponse(BaseModel):
    evaluations: list[SemanticEvalItem]


class LlmTicketEnrichmentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = OpenAiChatClient(settings)

    def _build_prompt(
        self,
        project_name: str,
        title: str,
        description: str | None,
        parsed: TicketPatternParsed,
    ) -> str:
        return f"""
        다음 장애 티켓을 분석하여 검색 및 장애 분석에 사용할 메타데이터를 생성한다.

        [작업 목적]
        - 제목과 본문을 읽고 장애 내용을 이해한다.
        - 1차 규칙 기반 파싱 결과를 참고하여 필요한 경우 보정한다.
        - 티켓에서 확인 가능한 정보만 사용한다.
        - 추측하거나 일반적인 원인을 만들어내지 않는다.
        - 근거가 부족한 값은 null 또는 빈 배열을 반환한다.

        [작성 규칙]
        1. error_type
        - 제목 또는 본문에 Exception 또는 Error 클래스명이 명시된 경우만 작성한다.
        - 명확하지 않으면 null을 반환한다.

        2. normalized_summary
        - 제목과 본문을 기반으로 한국어 1문장으로 요약한다.
        - 추측하지 않는다.

        3. extracted_keywords
        - 검색에 도움이 되는 짧은 키워드를 작성한다.
        - 제목과 본문에 실제 존재하는 내용만 사용한다.

        4. domain_tags
        - auth, login, payment 등 명확한 도메인만 작성한다.
        - 확실하지 않으면 빈 배열을 반환한다.

        5. suspected_cause
        - 본문에 원인이나 장애 원인이 명시된 경우만 작성한다.
        - 추측하지 않는다.

        6. resolution_note
        - 본문에 해결 방법이나 조치 내용이 있는 경우만 작성한다.
        - 없으면 null을 반환한다.

        7. correction_notes
        - pattern_extracted 값을 수정하거나 보정한 이유를 간단히 작성한다.
        - 수정 사항이 없으면 null을 반환한다.

        8. parser_confidence
        - high / medium / low 중 하나를 반환한다.

        [입력]
        project_name:
        {project_name}

        title:
        {title}

        description:
        {description or ""}

        pattern_extracted:
        ```json
        {
            json.dumps(
                {
                    "error_type": parsed.error_type,
                },
                ensure_ascii=False,
                indent=2,
            )
        }
        ```

        [반환 형식]
        반드시 JSON만 반환한다.
        아래 필드만 포함한다.
        * error_type
        * normalized_summary
        * extracted_keywords
        * domain_tags
        * suspected_cause
        * resolution_note
        * correction_notes
        * parser_confidence
        
        """.strip()

    def _build_messages(
        self,
        project_name: str,
        title: str,
        description: str | None,
        parsed: TicketPatternParsed,
    ) -> list[dict[str, str]]:
        prompt = self._build_prompt(project_name, title, description, parsed)
        return [
            {
                "role": "developer",
                "content": (
                    "You enrich IT incident tickets. Return only JSON matching the schema. "
                    "Do not invent suspected_cause or resolution_note without ticket evidence."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]

    def _parse_model_output(
        self, text: str, *, allow_json_extraction: bool
    ) -> _LlmTicketSchema | None:
        if not text.strip():
            return None
        try:
            json_text = (
                extract_first_json_object(text) if allow_json_extraction else text
            )
            data = json.loads(json_text or text)
            return _LlmTicketSchema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.debug(
                "LLM ticket enrich parse failed: %s preview=%s",
                e,
                preview_truncated(text, 800),
            )
            return None

    def _normalize(self, model: _LlmTicketSchema) -> LlmEnrichedTicket:
        kws = sorted(
            {str(x).strip() for x in model.extracted_keywords if str(x).strip()}
        )
        tags = sorted({str(x).strip() for x in model.domain_tags if str(x).strip()})
        error_type = model.error_type.strip() if model.error_type else None
        if error_type and not _EXPLICIT_ERROR_TYPE.fullmatch(error_type):
            error_type = None
        return LlmEnrichedTicket(
            error_type=error_type,
            normalized_summary=model.normalized_summary.strip()
            if model.normalized_summary
            else None,
            extracted_keywords=kws,
            domain_tags=tags,
            suspected_cause=model.suspected_cause.strip()
            if model.suspected_cause
            else None,
            resolution_note=model.resolution_note.strip()
            if model.resolution_note
            else None,
            correction_notes=model.correction_notes.strip()
            if model.correction_notes
            else None,
            parser_confidence=model.parser_confidence,
        )

    def enrich(
        self,
        project_name: str,
        title: str,
        description: str | None,
        parsed: TicketPatternParsed,
    ) -> LlmEnrichedTicket | None:
        if not self._settings.openai_api_key:
            logger.debug("LLM ticket enrich skipped: no API key")
            return None

        messages = self._build_messages(project_name, title, description, parsed)
        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=_LlmTicketSchema,
            schema_name="EnrichedTicket",
        )
        model = self._parse_model_output(text or "", allow_json_extraction=False)

        if model is None:
            text = self._llm.chat_json_object(messages)
            model = self._parse_model_output(text or "", allow_json_extraction=True)

        if model is None:
            return None
        return self._normalize(model)

    def _parse_response(
        self, text: str | None, *, allow_extract: bool
    ) -> _SemanticEvalResponse | None:
        if not text or not text.strip():
            return None
        try:
            blob = extract_first_json_object(text) if allow_extract else text
            data = json.loads(blob or text)
            return _SemanticEvalResponse.model_validate(data)
        except (json.JSONDecodeError, ValidationError, Exception) as e:
            logger.debug("semantic response parse failed: %s", e)
            return None

    def evaluate_top_candidates(
        self,
        *,
        ticket_payload: dict[str, Any],
        candidates: list[RuleScoredIncident],
    ) -> dict[uuid.UUID, SemanticEvalItem]:
        """
        프로젝트명으로 1차 필터링, 스코어링은 코드에서 판단하기때문에 LLM은
        ticket의 title/description이 각 incident의 summary와 동일한 장애인지에 대한 가능성만 판단한다.
        """
        if not self._settings.openai_api_key:
            logger.debug(
                "ticket_semantic_eval skipped: openai_api_key unset (semantic_map empty)"
            )
            return {}

        if not candidates:
            logger.debug("ticket_semantic_eval skipped: empty candidates list")
            return {}

        cand_lines = []
        for c in candidates:
            inc = c.incident
            cand_lines.append(
                {
                    "incident_id": str(inc.id),
                    "rule_score": c.rule_score,
                    "incident_summary": inc.primary_error_summary,
                    "primary_error_message": inc.primary_error_message,
                    "primary_error_type": inc.primary_error_type,
                    "error_keywords": inc.error_keywords,
                    "domain_tags": inc.domain_tags,
                }
            )

        prompt = {
            "task": "semantic_similarity_eval",
            "question": (
                "티켓의 title/description/normalized_summary가 "
                "각 incident의 summary/error information과 의미적으로 얼마나 유사한지 평가한다."
            ),
            "important_context": [
                "후보 incident는 이미 코드에서 project_name, 시간, error_type, domain tag, keyword 기준으로 필터링 및 스코어링된 결과다.",
                "LLM은 project_name, 시간, error_type, domain tag, keyword 일치 여부를 다시 판단하지 않는다.",
                "LLM은 오직 ticket의 title, description, normalized_summary가 incident의 summary/error information의 의미적 유사도만 평가한다.",
                "티켓은 incident보다 정보가 적을 수 있으므로, 티켓에 없는 세부 정보만으로 낮은 점수를 주지 않는다.",
            ],
            "ticket": {
                "title": ticket_payload.get("title"),
                "description": ticket_payload.get("description"),
                "normalized_summary": ticket_payload.get("normalized_summary"),
                "extracted_keywords": ticket_payload.get("extracted_keywords"),
                "domain_tags": ticket_payload.get("domain_tags"),
                "suspected_cause": ticket_payload.get("suspected_cause"),
                "resolution_note": ticket_payload.get("resolution_note"),
            },
            "candidates": cand_lines,
            "output_contract": {
                "must_be_json_only": True,
                "evaluations": [
                    {
                        "incident_id": "candidate incident_id",
                        "semantic_score": "0.0~1.0 float. 의미적으로 매우 유사하면 1.0에 가깝게. ticket text와 incident summary/error information이 의미적으로 유사할수록 높게.",
                        "reason": "한국어 한 줄. 규칙 점수 판단은 쓰지 말고, 의미 유사도 근거만 작성.",
                        "should_match": "semantic_score가 0.65 이상이면 true, 아니면 false",
                    }
                ],
            },
        }

        messages = [
            {
                "role": "developer",
                "content": (
                    "Return JSON only. "
                    "You are a semantic similarity evaluator, not a final incident matcher. "
                    "The system already handled project, time, error_type, domain tag, and keyword scoring. "
                    "Do not reject candidates based on rule scoring or missing details. "
                    "Evaluate only the semantic similarity between the ticket text and the incident summary/error information. "
                    "Missing details in the ticket are not evidence of mismatch. "
                    "semantic_score must be a float between 0.0 and 1.0. 0.0 means completely unrelated. 1.0 means almost certainly the same incident."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ]

        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=_SemanticEvalResponse,
            schema_name="TicketSemanticEval",
        )
        parsed = self._parse_response(text, allow_extract=False)

        if parsed is None:
            text = self._llm.chat_json_object(messages)
            parsed = self._parse_response(text, allow_extract=True)

        if parsed is None:
            logger.debug(
                "ticket_semantic_eval parse_failed: LLM response could not be parsed "
                "(semantic_map empty)"
            )
            return {}

        out: dict[uuid.UUID, SemanticEvalItem] = {}
        for ev in parsed.evaluations:
            try:
                uid = uuid.UUID(str(ev.incident_id))
            except ValueError:
                logger.debug(
                    "ticket_semantic_eval skip_bad_incident_id raw=%r", ev.incident_id
                )
                continue
            out[uid] = ev
            logger.debug(
                "ticket_semantic_eval incident_id=%s semantic_score=%s "
                "should_match=%s reason=%s",
                uid,
                ev.semantic_score,
                ev.should_match,
                ev.reason,
            )
        logger.debug(
            "ticket_semantic_eval done evaluations_count=%s unique_ids=%s",
            len(parsed.evaluations),
            len(out),
        )
        return out
