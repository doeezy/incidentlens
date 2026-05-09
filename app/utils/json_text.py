"""LLM 등에서 나온 텍스트 안의 첫 JSON 객체 부분 추출."""

from __future__ import annotations


def extract_first_json_object(text: str | None) -> str | None:
    """앞뒤에 설명 문구가 붙어 있어도 `{` ~ 마지막 `}` 구간만 잘라 반환."""
    value = (text or "").strip()
    if not value:
        return None
    start = value.find("{")
    end = value.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return value[start : end + 1]
