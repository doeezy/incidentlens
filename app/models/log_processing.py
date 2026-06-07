from __future__ import annotations

from dataclasses import dataclass, field
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
class TicketPatternParsed:
    """티켓 본문 규칙 기반 추출."""

    error_type: str | None


@dataclass(frozen=True)
class LlmEnrichedTicket:
    """Law Ticket LLM 생성/추론."""

    error_type: str | None = None
    normalized_summary: str | None = None
    extracted_keywords: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    suspected_cause: str | None = None
    resolution_note: str | None = None
    correction_notes: str | None = None
    parser_confidence: ParserConfidence = "low"


@dataclass(frozen=True)
class LlmEnrichedLog:
    """Raw Log LLM 보정/생성 결과(문맥 기반)."""

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
    parser_confidence: ParserConfidence = "low"
