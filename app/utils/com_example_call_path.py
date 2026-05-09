"""com.example 기준 호출 경로(module / class / method) 규칙 추출.

로그·티켓 파서에서 공통 사용.
"""

from __future__ import annotations

import re

APP_CALL_PATH = re.compile(
    r"\bcom\.example\.(?P<module>[a-zA-Z0-9_.]+)\.(?P<class>[A-Z][A-Za-z0-9_$]*)\.(?P<method>[a-zA-Z_][a-zA-Z0-9_]*)\b"
)

_APP_CLASS_FQN = re.compile(
    r"\bcom\.example\.(?:[a-zA-Z0-9_$]+\.)+[A-Z][A-Za-z0-9_$]*\b"
)


def split_app_call_path_match(match: re.Match[str]) -> tuple[str, str, str]:
    module_name = match.group("module")
    class_name = match.group("class").replace("$", ".")
    method_name = match.group("method")
    return module_name, class_name, method_name


def fqn_to_module_and_class(fqn: str) -> tuple[str | None, str | None]:
    """``com.example.<module path>.<ClassSimple>`` → (module, class)."""
    clean = fqn.replace("$", ".")
    parts = clean.split(".")
    if len(parts) < 4:
        return None, None
    if parts[0] != "com" or parts[1] != "example":
        return None, None
    module_name = ".".join(parts[2:-1])
    class_name = parts[-1]
    return module_name or None, class_name or None


def extract_module_class_method(text: str) -> tuple[str | None, str | None, str | None]:
    """본문에서 ``com.example`` 호출 경로 추출.

    1. ``com.example.<module>.<Class>.<method>`` 전체가 있으면 세 필드 모두.
    2. 없으면 클래스까지의 FQN만 있으면 module/class 만 (method는 None).
    """
    m = APP_CALL_PATH.search(text)
    if m:
        mod, cls, meth = split_app_call_path_match(m)
        return mod, cls, meth

    m2 = _APP_CLASS_FQN.search(text)
    if m2:
        mod, cls = fqn_to_module_and_class(m2.group(0))
        if mod and cls:
            return mod, cls, None

    return None, None, None
