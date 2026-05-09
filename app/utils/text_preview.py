"""로그 프리뷰용 짧은 문자열 변환."""

from __future__ import annotations


def preview_truncated(value: str | None, limit: int = 500) -> str:
    """개행을 이스케이프 표시로 바꾼 뒤 길이 제한."""
    text = (value or "").replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "...(truncated)"
