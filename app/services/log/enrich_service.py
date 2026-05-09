from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.llm import OpenAiChatClient
from app.models.log_processing import LlmEnrichedLog, PatternParsedLog
from app.utils.json_text import extract_first_json_object
from app.utils.text_preview import preview_truncated

logger = logging.getLogger(__name__)


class _LlmEnrichedLogSchema(BaseModel):
    module_name: str | None = Field(
        default=None,
        description="com.example 이후부터 class_name 직전까지의 경로",
    )
    class_name: str | None = Field(default=None, description="클래스 단순명")
    method_name: str | None = Field(
        default=None,
        description="메서드명. 불명확하면 null",
    )
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"] | None = (
        Field(
            default=None,
            description="정규화된 로그 레벨",
        )
    )
    stack_trace: str | None = Field(
        default=None,
        description="있으면 예외 라인과 at ... 라인을 포함한 stack trace 원문",
    )
    error_type: str | None = Field(default=None, description="예외 타입명")
    error_message: str | None = Field(
        default=None,
        description="예외 타입을 제외한 핵심 메시지",
    )
    normalized_summary: str | None = Field(
        default=None,
        description="한국어 1문장 요약. 추측 금지",
    )
    extracted_keywords: list[str] = Field(
        default_factory=list,
        description="검색용 키워드 배열",
    )
    domain_tags: list[str] = Field(
        default_factory=list,
        description="명확한 경우만 포함하는 도메인 태그 배열",
    )
    correction_notes: str | None = Field(
        default=None,
        description="규칙 기반 추출값을 수정하거나 null 처리한 이유",
    )
    parser_confidence: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="파싱/보정 결과에 대한 신뢰도",
    )


class LlmLogEnrichmentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = OpenAiChatClient(settings)

    def _build_prompt(
        self,
        project_name: str,
        raw_message: str,
        parsed: PatternParsedLog,
    ) -> dict:
        return {
            "task": "validate_and_enrich_log",
            "goal": [
                "1차 규칙 기반 파싱 결과를 raw 로그와 비교해 검증/보정한다.",
                "raw 로그에서 확인 가능한 정보만 사용해 요약/키워드/태그를 생성한다.",
                "확실하지 않은 값은 추측하지 말고 null 또는 빈 배열로 반환한다.",
            ],
            "rules": {
                "package_structure": "com.example.[module_name].[class_name].[method_name]",
                "module_name": (
                    "com.example 이후부터 마지막 두 세그먼트(class_name, method_name) "
                    "직전까지의 경로. 예: com.example.user.auth.UserService.login -> user.auth"
                ),
                "class_name": "클래스 단순명. 예: UserService. 내부 클래스는 $를 .으로 정규화 가능.",
                "method_name": "메서드명. 명확하지 않으면 null.",
                "log_level": "TRACE|DEBUG|INFO|WARN|ERROR|FATAL 중 하나로 정규화. WARNING은 WARN으로 변환.",
                "stack_trace": "원문에 stack trace가 있으면 예외 라인과 'at ...' 라인을 포함해 그대로 보존. 없으면 null.",
                "error_type": "예외 타입명. 예: ClassNotFoundException",
                "error_message": "예외 타입을 제외한 핵심 메시지. 예: com.foo.AuthFilter not found",
                "normalized_summary": "normalized_summary는 '~했습니다.' 형태의 한국어 문장 1개로 작성한다. 구조 필드와 raw_message에 근거해 작성. 원인 추정은 하지 말 것.",
                "extracted_keywords": "검색에 유용한 짧은 키워드 배열. raw_message와 파싱 결과에 근거한 값만 포함.",
                "domain_tags": "도메인 태그 배열. 명확하지 않으면 빈 배열.",
                "correction_notes": "수정/보정한 내용이 있으면 간단히 설명. 없으면 null.",
                "parser_confidence": "파싱 결과가 명확하면 high, 일부 애매하면 medium, 불확실하면 low.",
            },
            "constraints": [
                "Project name is immutable. Do not modify, normalize, or suggest changes to project_name. Use it only as context.",
                "Use only information explicitly present in the raw log or clearly supported by the pattern_extracted input.",
                "Do not guess or infer missing information. If a value cannot be confirmed, return null or an empty array.",
                "The normalized_summary must describe only observable facts and must not include root cause analysis or resolution suggestions.",
                "Return only valid JSON that strictly matches the required schema. Do not include any additional text.",
            ],
            "input": {
                "project_name": project_name,
                "raw_message": raw_message,
                "pattern_extracted": {
                    "module_name": parsed.module_name,
                    "class_name": parsed.class_name,
                    "method_name": parsed.method_name,
                    "log_level": parsed.log_level,
                    "stack_trace": parsed.stack_trace,
                    "error_type": parsed.error_type,
                    "error_message": parsed.error_message,
                },
            },
            "output_contract": {
                "must_be_json_only": True,
                "fields": [
                    "module_name",
                    "class_name",
                    "method_name",
                    "log_level",
                    "stack_trace",
                    "error_type",
                    "error_message",
                    "normalized_summary",
                    "extracted_keywords",
                    "domain_tags",
                    "correction_notes",
                    "parser_confidence",
                ],
            },
        }

    def _build_messages(
        self,
        project_name: str,
        raw_message: str,
        parsed: PatternParsedLog,
    ) -> list[dict]:
        prompt = self._build_prompt(project_name, raw_message, parsed)

        return [
            {
                "role": "developer",
                "content": (
                    "You are a careful log parser and enricher. "
                    "Return only valid JSON that matches the schema exactly. "
                    "Do not guess missing values. "
                    "Use null or empty arrays when uncertain. "
                    "Use only information explicitly present in the raw log or the pattern-extracted fields. "
                    "Do not infer root cause or resolution."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ]

    def _parse_model_output(
        self, text: str, *, allow_json_extraction: bool
    ) -> _LlmEnrichedLogSchema | None:
        if not text.strip():
            return None

        try:
            json_text = (
                extract_first_json_object(text) if allow_json_extraction else text
            )
            data = json.loads(json_text or text)
            return _LlmEnrichedLogSchema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.debug(
                "LLM enrich output parse/validate failed: %s. raw_content_preview=%s",
                e,
                preview_truncated(text, 800),
            )
            return None

    def _normalize_output(self, model: _LlmEnrichedLogSchema) -> LlmEnrichedLog:
        level = model.log_level.upper() if model.log_level else None
        if level == "WARNING":
            level = "WARN"
        if level and level not in {"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"}:
            level = None

        keywords = sorted(
            {
                str(value).strip()
                for value in model.extracted_keywords
                if str(value).strip()
            }
        )
        tags = sorted(
            {str(value).strip() for value in model.domain_tags if str(value).strip()}
        )

        return LlmEnrichedLog(
            module_name=model.module_name or None,
            class_name=model.class_name or None,
            method_name=model.method_name or None,
            log_level=level,
            stack_trace=model.stack_trace or None,
            error_type=model.error_type or None,
            error_message=model.error_message or None,
            normalized_summary=model.normalized_summary or None,
            extracted_keywords=keywords,
            domain_tags=tags,
            correction_notes=model.correction_notes.strip()
            if model.correction_notes
            else None,
            parser_confidence=model.parser_confidence,
        )

    def enrich(
        self,
        project_name: str,
        raw_message: str,
        parsed: PatternParsedLog,
    ) -> LlmEnrichedLog | None:
        if not self._settings.openai_api_key:
            logger.debug("LLM enrich skipped: openai_api_key is not set")
            return None

        messages = self._build_messages(project_name, raw_message, parsed)
        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=_LlmEnrichedLogSchema,
            schema_name="EnrichedLog",
        )
        model = self._parse_model_output(text or "", allow_json_extraction=False)

        if model is None:
            text = self._llm.chat_json_object(messages)
            model = self._parse_model_output(text or "", allow_json_extraction=True)

        if model is None:
            return None

        output = self._normalize_output(model)
        logger.debug("LLM 응답 !!! %s", text)
        return output
