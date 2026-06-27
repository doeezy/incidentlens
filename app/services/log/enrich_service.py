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
    ) -> str:
        return f"""
    다음 raw log와 1차 규칙 기반 파싱 결과를 비교하여 로그 정보를 검증하고 보강한다.

    [작업 목적]
    - raw log에서 관찰 가능한 정보만 사용한다.
    - 1차 규칙 기반 파싱 결과가 raw log와 일치하는지 확인하고, 명확히 틀린 값만 보정한다.
    - 확실하지 않은 값은 추측하지 말고 null 또는 빈 배열로 반환한다.
    - 원인 분석이나 해결 방법은 작성하지 않는다.

    [패키지 구조 규칙]
    - 기본 구조는 com.example.[module_name].[class_name].[method_name] 이다.
    - module_name은 com.example 이후부터 class_name 직전까지의 경로이다.
    예: com.example.user.auth.UserService.login -> user.auth
    - class_name은 클래스 단순명이다.
    - method_name은 메서드명이다. 명확하지 않으면 null로 반환한다.
    - stack trace가 있는 경우 첫 번째 application frame 기준으로 판단한다.
    - project_name은 절대 수정하지 말고 문맥 정보로만 사용한다.

    [필드 작성 규칙]
    - log_level은 TRACE, DEBUG, INFO, WARN, ERROR, FATAL 중 하나로 정규화한다. WARNING은 WARN으로 변환한다.
    - error_type은 예외 타입명만 작성한다. 예: ClassNotFoundException
    - error_message는 예외 타입을 제외한 핵심 메시지만 작성한다.
    - normalized_summary는 raw log와 구조 필드에 근거한 한국어 1문장으로 작성한다.
    - normalized_summary에는 root cause 추정이나 해결 제안을 포함하지 않는다.
    - extracted_keywords는 검색에 유용한 짧은 키워드만 포함한다.
    - domain_tags는 명확히 확인 가능한 도메인만 포함한다. 명확하지 않으면 빈 배열로 반환한다.
    - correction_notes는 1차 파싱 결과를 수정하거나 null 처리한 이유를 간단히 작성한다. 없으면 null로 반환한다.
    - parser_confidence는 high, medium, low 중 하나이다.

    [입력]
    project_name:
    {project_name}

    raw_message:
    {raw_message}

    pattern_extracted:
    ```json
    {
            json.dumps(
                {
                    "module_name": parsed.module_name,
                    "class_name": parsed.class_name,
                    "method_name": parsed.method_name,
                    "log_level": parsed.log_level,
                    "stack_trace": parsed.stack_trace,
                    "error_type": parsed.error_type,
                    "error_message": parsed.error_message,
                },
                ensure_ascii=False,
            )
        }
    ```

    [반환 형식]
    반드시 JSON만 반환한다.
    스키마에 정의된 필드 외의 텍스트는 절대 포함하지 않는다.
    """

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
            {"role": "user", "content": prompt},
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
