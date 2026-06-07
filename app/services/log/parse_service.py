from __future__ import annotations

import re

from app.models.log_processing import PatternParsedLog
from app.utils.com_example_call_path import extract_module_class_method


class LogParseService:
    """raw_message 기반 규칙형 파서.

    - 확실한 패턴 기반으로 추출 가능한 값만 추출한다.
    - summary/keywords/tags 같은 문맥 기반 값은 LLM 단계에서 담당한다.
    """

    _exception_line = re.compile(
        r"(?P<etype>[A-Za-z_][\w]*(?:Exception|Error))\s*:\s*(?P<emsg>.+)$",
        re.MULTILINE,
    )
    _bare_type = re.compile(r"\b([A-Za-z_][\w]*(?:Exception|Error))\b")
    _log_level = re.compile(
        r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\b", re.IGNORECASE
    )

    _at_frame = re.compile(
        r"at\s+(?P<fqn>[\w$]+(?:\.[\w$]+)+)\.(?P<method>\w+)\s*\([^)\n]*\)"
    )
    _logger_after_level = re.compile(
        r"\b(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\b\s+"
        r"(?:\d+\s+---\s+\[[^\]]+\]\s+)?"
        r"(?P<logger>(?:[a-zA-Z_][\w$]*\.)+[a-zA-Z_][\w$]*)\s*[-:]\s*",
        re.IGNORECASE,
    )

    def parse(self, raw_message: str) -> PatternParsedLog:
        text = raw_message.strip()
        lines = text.splitlines()

        stack_start = None
        for i, line in enumerate(lines):
            t = line.lstrip()
            if t.startswith("at ") and "(" in line:
                stack_start = i
                break

        if stack_start is not None:
            head = "\n".join(lines[:stack_start]).strip()
            stack_trace = "\n".join(lines[stack_start:]).strip() or None
        else:
            head = text
            stack_trace = None

        log_level = None
        for line in head.splitlines()[:12]:
            m = self._log_level.search(line)
            if not m:
                continue
            lvl = m.group(1).upper()
            if lvl == "WARNING":
                lvl = "WARN"
            log_level = lvl

        module_name, class_name, method_name = self._extract_module_class_method(
            head, stack_trace
        )

        error_src = head or text
        error_type, error_message = self._extract_exception(error_src)
        return PatternParsedLog(
            log_level=log_level,
            module_name=module_name,
            class_name=class_name,
            method_name=method_name,
            error_type=error_type,
            error_message=error_message,
            stack_trace=stack_trace,
        )

    def _fqn_is_application(self, fqn: str) -> bool:
        lower = fqn.lower()
        return lower.startswith("com.example.")

    def _from_fqn_and_method(
        self, fqn_raw: str, method: str
    ) -> tuple[str | None, str | None, str | None]:
        fqn_clean = fqn_raw.replace("$", ".")
        class_parts = fqn_clean.split(".")
        if len(class_parts) < 4:
            return None, None, method or None
        module_name = ".".join(class_parts[2:-1])
        class_name = fqn_raw.rsplit(".", 1)[-1].replace("$", ".")
        return module_name, class_name, method or None

    def _extract_module_class_method(
        self, head: str, stack_trace: str | None
    ) -> tuple[str | None, str | None, str | None]:
        if stack_trace:
            for m in self._at_frame.finditer(stack_trace):
                fqn = m.group("fqn")
                meth = m.group("method")
                if not self._fqn_is_application(fqn):
                    continue

                mod, cls, meth_name = self._from_fqn_and_method(fqn, meth)
                if mod and cls:
                    return mod, cls, meth_name

        mod, cls, meth_name = extract_module_class_method(head)
        if mod and cls:
            return mod, cls, meth_name

        lm = self._logger_after_level.search(head)
        if lm:
            fqn = lm.group("logger")
            if self._fqn_is_application(fqn):
                mod, cls, _ = self._from_fqn_and_method(fqn, "")
                if mod and cls:
                    return mod, cls, None

        return None, None, None

    def _extract_exception(self, text: str) -> tuple[str | None, str | None]:
        m = self._exception_line.search(text)
        if m:
            etype = m.group("etype").strip()
            emsg = m.group("emsg").strip().splitlines()[0].strip()
            return etype, emsg or None
        m2 = self._bare_type.search(text)
        if m2:
            etype = m2.group(1).strip()
            line = text.splitlines()[0] if text else ""
            if ":" in line:
                rest = line.split(":", 1)[1].strip()
                return etype, rest or None
            return etype, None
        return None, None
