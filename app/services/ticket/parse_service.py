from __future__ import annotations

import re

from app.models.log_processing import TicketPatternParsed
from app.utils.com_example_call_path import extract_module_class_method


class TicketParseService:
    """티켓 title/description에서 규칙 기반으로 구조 필드를 추출한다."""

    _type_exception_or_error = re.compile(
        r"\b([A-Z][A-Za-z0-9_]*(?:Exception|Error))\b"
    )

    _error_label = re.compile(
        r"(?:발생\s*에러|에러|오류|exception|error)\s*[:：]\s*(?P<etype>[A-Z][A-Za-z0-9_]*(?:Exception|Error))",
        re.IGNORECASE,
    )

    def parse(self, title: str, description: str | None) -> TicketPatternParsed:
        text = "\n".join(
            s for s in (title or "", (description or "").strip()) if s
        ).strip()

        module_name, class_name, method_name = extract_module_class_method(text)
        error_type = self._extract_error_type(text)

        return TicketPatternParsed(
            module_name=module_name,
            class_name=class_name,
            method_name=method_name,
            error_type=error_type,
        )

    def _extract_error_type(self, text: str) -> str | None:
        for pattern in (
            self._error_label,
            self._type_exception_or_error,
        ):
            match = pattern.search(text)
            if not match:
                continue

            groups = match.groupdict()
            if "etype" in groups and groups["etype"]:
                return groups["etype"].strip()

            return match.group(1).strip()

        return None
