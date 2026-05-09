from __future__ import annotations

import json
import logging
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


class _LlmTicketSchema(BaseModel):
    module_name: str | None = Field(
        default=None,
        description="규칙 추출값 보정 또는 확인된 모듈. 불명확하면 null.",
    )
    class_name: str | None = Field(
        default=None,
        description="규칙 추출값 보정 또는 확인된 클래스. 불명확하면 null.",
    )
    method_name: str | None = Field(
        default=None,
        description="규칙 추출값 보정 또는 확인된 메서드. 불명확하면 null.",
    )
    error_type: str | None = Field(
        default=None,
        description="규칙 추출값 보정 또는 확인된 오류 유형. 불명확하면 null.",
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
    ) -> dict[str, Any]:
        return {
            "task": "enrich_ticket",
            "rules": {
                "module_name": "pattern_extracted와 본문 근거로 확정·보정. 불명확하면 null.",
                "class_name": "pattern_extracted와 본문 근거로 확정·보정. 불명확하면 null.",
                "method_name": "pattern_extracted와 본문 근거로 확정·보정. 불명확하면 null.",
                "error_type": "pattern_extracted와 본문 근거로 확정·보정. 불명확하면 null.",
                "normalized_summary": "제목과 본문에 근거한 한국어 1문장. 추측 금지.",
                "extracted_keywords": "본문/제목에서 확인 가능한 짧은 키워드만.",
                "domain_tags": "명확할 때만. 예: auth, login",
                "suspected_cause": (
                    "티켓 본문에 원인 근거가 명시된 경우에만 작성. "
                    "추측이나 일반론이면 null."
                ),
                "resolution_note": "본문에 해결/조치 내용이 있으면 요약. 없으면 null.",
                "correction_notes": "패턴 추출 대비 보정 사유 등. 없으면 null.",
                "parser_confidence": "high | medium | low",
            },
            "pattern_extracted": {
                "module_name": parsed.module_name,
                "class_name": parsed.class_name,
                "method_name": parsed.method_name,
                "error_type": parsed.error_type,
            },
            "input": {
                "project_name": project_name,
                "title": title,
                "description": description,
            },
            "output_contract": {
                "must_be_json_only": True,
                "fields": [
                    "module_name",
                    "class_name",
                    "method_name",
                    "error_type",
                    "normalized_summary",
                    "extracted_keywords",
                    "domain_tags",
                    "suspected_cause",
                    "resolution_note",
                    "correction_notes",
                    "parser_confidence",
                ],
            },
        }

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
        return LlmEnrichedTicket(
            module_name=model.module_name,
            class_name=model.class_name,
            method_name=model.method_name,
            error_type=model.error_type,
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
                "후보 incident는 이미 코드에서 project_name, 시간, module, class, method, error_type 기준으로 필터링 및 스코어링된 결과다.",
                "LLM은 project_name, 시간, module, class, method 일치 여부를 다시 판단하지 않는다.",
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
                        "reason": "한국어 한 줄. project/time/module/class/method 판단은 쓰지 말고, 의미 유사도 근거만 작성.",
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
                    "The system already handled project, time, module, class, method, and error_type scoring. "
                    "Do not reject candidates based on project, time, module, class, method, or missing details. "
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
