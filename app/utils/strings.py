"""문자열 리스트·비교 공통 유틸."""

from __future__ import annotations


def union_unique_strings(
    base: list[str] | None,
    extra: list[str] | None,
) -> list[str]:
    """두 리스트를 이어붙인 뒤, 앞에서부터 공백 트림·중복 제거한 순서 유지 리스트."""
    seen: set[str] = set()
    out: list[str] = []
    for item in list(base or []) + list(extra or []):
        key = str(item).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def normalize_lower_trim(value: str | None) -> str | None:
    """앞뒤 공백 제거 후 소문자. 빈 문자열이면 None."""
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def equal_normalized(a: str | None, b: str | None) -> bool:
    """normalize_lower_trim 기준 동등 여부."""
    return normalize_lower_trim(a) == normalize_lower_trim(b)
