"""OpenAI json_schema(strict) 등용 Pydantic JSON 스키마 보정."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel


def strict_object_schema_from_model(model: type[BaseModel]) -> dict[str, Any]:
    """모든 object 노드에 additionalProperties=False, required=전체 프로퍼티."""
    return apply_strict_object_schema(model.model_json_schema())


def apply_strict_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """스키마 dict 복사본에 동일 규칙 적용(원본 불변)."""
    schema = copy.deepcopy(schema)

    def fix(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                props = node.get("properties")
                if isinstance(props, dict):
                    node["required"] = list(props.keys())
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for item in node:
                fix(item)

    fix(schema)
    return schema
