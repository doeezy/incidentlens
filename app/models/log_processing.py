from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ParserConfidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class PatternParsedLog:
    """규칙 기반 파싱 결과(확실한 패턴 기반으로만 추출)."""

    log_level: str | None
    module_name: str | None
    class_name: str | None
    method_name: str | None
    error_type: str | None
    error_message: str | None
    stack_trace: str | None


@dataclass(frozen=True)
class LlmEnrichedLog:
    """LLM 보정/생성 결과(문맥 기반)."""

    module_name: str | None
    class_name: str | None
    method_name: str | None
    log_level: str | None
    stack_trace: str | None
    error_type: str | None
    error_message: str | None
    normalized_summary: str | None
    extracted_keywords: list[str]
    domain_tags: list[str]
    correction_notes: str | None
    parser_confidence: ParserConfidence
