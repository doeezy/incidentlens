from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.utils.json_schema_strict import strict_object_schema_from_model

logger = logging.getLogger(__name__)

TSchema = TypeVar("TSchema", bound=BaseModel)


@dataclass(frozen=True)
class ChatCompletionResult:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None


class OpenAiChatClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat_json_schema_strict(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_model: type[TSchema],
        schema_name: str,
    ) -> str | None:
        """OpenAI ``response_format=json_schema`` (strict). 실패 시 None."""
        result = self.chat_json_schema_strict_with_usage(
            messages,
            schema_model=schema_model,
            schema_name=schema_name,
        )
        return result.text if result else None

    def chat_json_schema_strict_with_usage(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_model: type[TSchema],
        schema_name: str,
    ) -> ChatCompletionResult | None:
        """OpenAI ``response_format=json_schema`` (strict). 실패 시 None."""
        if not self._settings.openai_api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._settings.openai_api_key)
            response = client.chat.completions.create(
                model=self._settings.llm_model_name,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": strict_object_schema_from_model(schema_model),
                        "strict": True,
                    },
                },
            )
            out = (response.choices[0].message.content or "").strip()
            if not out:
                return None
            usage = getattr(response, "usage", None)
            return ChatCompletionResult(
                text=out,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            )
        except Exception as e:
            logger.debug("chat_json_schema_strict failed: %s", e)
            return None

    def chat_json_object(self, messages: list[dict[str, Any]]) -> str | None:
        """OpenAI ``response_format=json_object``. 실패 시 None."""
        result = self.chat_json_object_with_usage(messages)
        return result.text if result else None

    def chat_json_object_with_usage(
        self,
        messages: list[dict[str, Any]],
    ) -> ChatCompletionResult | None:
        """OpenAI ``response_format=json_object``. 실패 시 None."""
        if not self._settings.openai_api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._settings.openai_api_key)
            response = client.chat.completions.create(
                model=self._settings.llm_model_name,
                messages=messages,
                response_format={"type": "json_object"},
            )
            out = (response.choices[0].message.content or "").strip()
            if not out:
                return None
            usage = getattr(response, "usage", None)
            return ChatCompletionResult(
                text=out,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            )
        except Exception as e:
            logger.debug("chat_json_object failed: %s", e)
            return None

    def chat_json_schema_then_json_object(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_model: type[TSchema],
        schema_name: str,
    ) -> str | None:
        """strict 스키마 우선, 실패 시 ``json_object`` 폴백. 내용 문자열만 반환."""
        text = self.chat_json_schema_strict(
            messages,
            schema_model=schema_model,
            schema_name=schema_name,
        )
        if text:
            return text
        return self.chat_json_object(messages)
