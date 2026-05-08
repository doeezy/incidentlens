from __future__ import annotations

import re

from app.models.log_processing import PatternParsedLog


class LogParseService:
    """raw_message 기반 규칙형 파서.

    - 확실한 패턴 기반으로 추출 가능한 값만 추출한다.
    - summary/keywords/tags 같은 문맥 기반 값은 LLM 단계에서 담당한다.
    """

    # Exception 또는 Error 타입을 추출하고 에러 메세지를 추출하는 정규식
    # (예: "java.lang.ClassNotFoundException: com.acme.auth.TokenVerifier") => ("ClassNotFoundException", "com.acme.auth.TokenVerifier")
    _exception_line = re.compile(
        r"(?P<etype>[A-Za-z_][\w]*(?:Exception|Error))\s*:\s*(?P<emsg>.+)$",
        re.MULTILINE,
    )
    # 에러 타입 추출 정규식
    _bare_type = re.compile(r"\b([A-Za-z_][\w]*(?:Exception|Error))\b")
    # 로그 레벨 추출 정규식
    _log_level = re.compile(
        r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\b", re.IGNORECASE
    )

    # TODO:
    # 현재는 com.example 기반 애플리케이션 패키지 구조를 전제로 파싱함.
    # 향후 base package 설정 기반 구조로 확장 가능.
    _app_call_path = re.compile(
        r"\bcom\.example\.(?P<module>[a-zA-Z0-9_.]+)\.(?P<class>[A-Z][A-Za-z0-9_$]*)\.(?P<method>[a-zA-Z_][A-Za-z0-9_]*)\b"
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
    _skip_fqn_prefixes = (
        "java.",
        "javax.",
        "jdk.",
        "sun.",
        "com.sun.",
        "org.junit.",
        "org.mockito.",
    )

    def parse(self, raw_message: str) -> PatternParsedLog:
        text = raw_message.strip()
        lines = text.splitlines()

        # stack trace 시작 줄 인덱스 탐색
        stack_start = None
        for i, line in enumerate(lines):
            t = line.lstrip()
            if t.startswith("at ") and "(" in line:
                stack_start = i

        if stack_start is not None:
            # head: 로그 레벨 이후 첫 번째 줄부터 stack trace 시작 줄 이전까지
            # stack_trace: stack trace 시작 줄부터 마지막 줄까지
            head = "\n".join(lines[:stack_start]).strip()
            stack_trace = "\n".join(lines[stack_start:]).strip() or None
        else:
            head = text
            stack_trace = None

        # 로그 레벨 추출
        log_level = None
        for line in head.splitlines()[:12]:
            m = self._log_level.search(line)
            if not m:
                continue
            lvl = m.group(1).upper()
            if lvl == "WARNING":
                lvl = "WARN"
            log_level = lvl

        # 모듈 이름, 클래스 이름, 메서드 이름 추출
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

    # 전체 경로가 애플리케이션 경로에 해당하는지 판단
    def _fqn_is_application(self, fqn: str) -> bool:
        lower = fqn.lower()
        return not any(lower.startswith(p) for p in self._skip_fqn_prefixes)

    def _from_app_call_path(
        self,
        text: str,
    ) -> tuple[str | None, str | None, str | None]:
        match = self._app_call_path.search(text)
        if not match:
            return None, None, None

        module_name = match.group("module")
        class_name = match.group("class").replace("$", ".")
        method_name = match.group("method")

        return module_name, class_name, method_name

    def _from_fqn_and_method(
        self, fqn_raw: str, method: str
    ) -> tuple[str | None, str | None, str | None]:
        """com.example.[모듈 경로].[클래스 단순명] + 메서드 (FQN은 최소 com.example.x.y 4단)."""
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

        # 1. stack trace 우선
        if stack_trace:
            for m in self._at_frame.finditer(stack_trace):
                fqn = m.group("fqn")
                meth = m.group("method")
                if not self._fqn_is_application(fqn):
                    continue

                mod, cls, meth_name = self._from_fqn_and_method(fqn, meth)
                if mod and cls:
                    return mod, cls, meth_name

        # 2. raw/head에서 com.example.[module].[class].[method] 직접 추출
        mod, cls, meth_name = self._from_app_call_path(head)
        if mod and cls:
            return mod, cls, meth_name

        # 3. 기존 logger fallback 유지
        lm = self._logger_after_level.search(head)
        if lm:
            fqn = lm.group("logger")
            if self._fqn_is_application(fqn):
                mod, cls, _ = self._from_fqn_and_method(fqn, "")
                if mod and cls:
                    return mod, cls, None

        return None, None, None

    def _extract_exception(self, text: str) -> tuple[str | None, str | None]:
        # 로그에서 에러타입과 에러 메세지 추출
        m = self._exception_line.search(text)
        if m:
            # 에러타입 추출 후 공백 제거
            etype = m.group("etype").strip()
            # 에러 메세지 추출 후 첫 번째 줄만 추출
            emsg = m.group("emsg").strip().splitlines()[0].strip()
            return etype, emsg or None
        m2 = self._bare_type.search(text)
        if m2:
            # 에러타입 추출 후 공백 제거
            etype = m2.group(1).strip()
            # 로그에서 첫 번째 줄 추출 후 : 뒤의 문자열을 에러 메세지로 추출
            line = text.splitlines()[0] if text else ""
            if ":" in line:
                rest = line.split(":", 1)[1].strip()
                return etype, rest or None
            return etype, None
        return None, None
