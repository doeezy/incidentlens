from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.llm import OpenAiChatClient
from app.models.incident import Incident
from app.schemas.raw_pr import RawPrCreate
from app.services.pr.parse_service import ParsedRawPr
from app.utils.json_text import extract_first_json_object
from app.utils.text_preview import preview_truncated

logger = logging.getLogger(__name__)

_MAX_PATCH_CHARS = 24000


@dataclass(frozen=True)
class LlmEnrichedPr:
    normalized_summary: str | None = None
    extracted_keywords: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    suspected_fix_for: str | None = None
    resolution_note: str | None = None
    diff_summary: str | None = None


class _LlmPrSchema(BaseModel):
    normalized_summary: str | None = Field(
        default=None,
        description="PR이 수행한 변경을 설명하는 한국어 1문장 요약.",
    )
    extracted_keywords: list[str] = Field(
        default_factory=list,
        description="PR과 연결 incident에서 확인되는 검색용 짧은 키워드.",
    )
    domain_tags: list[str] = Field(
        default_factory=list,
        description="PR과 연결 incident에서 명확히 확인되는 도메인 태그.",
    )
    suspected_fix_for: str | None = Field(
        default=None,
        description="PR이 해결하려는 incident 증상이나 원인. 근거 없으면 null.",
    )
    resolution_note: str | None = Field(
        default=None,
        description="PR이 incident를 어떻게 해결했는지에 대한 조치 요약.",
    )
    diff_summary: str | None = Field(
        default=None,
        description="patch와 변경 파일에 근거한 변경 내용 요약.",
    )


class LlmPrEnrichmentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = OpenAiChatClient(settings)

    def enrich(
        self,
        *,
        payload: RawPrCreate,
        parsed: ParsedRawPr,
        incident: Incident,
    ) -> LlmEnrichedPr | None:
        if not self._settings.openai_api_key:
            logger.debug("LLM PR enrich skipped: no API key")
            return None

        messages = self._build_messages(
            payload=payload,
            parsed=parsed,
            incident=incident,
        )
        text = self._llm.chat_json_schema_strict(
            messages,
            schema_model=_LlmPrSchema,
            schema_name="EnrichedPr",
        )
        model = self._parse_model_output(text or "", allow_json_extraction=False)
        if model is None:
            text = self._llm.chat_json_object(messages)
            model = self._parse_model_output(text or "", allow_json_extraction=True)
        if model is None:
            return None
        return self._normalize(model)

    def _build_messages(
        self,
        *,
        payload: RawPrCreate,
        parsed: ParsedRawPr,
        incident: Incident,
    ) -> list[dict[str, str]]:
        pull_request = payload.pull_request
        prompt: dict[str, Any] = {
            "task": "enrich_pr_for_linked_incident",
            "rules": {
                "normalized_summary": "PR이 수행한 변경을 한국어 1문장으로 요약.",
                "extracted_keywords": "PR 및 incident 근거가 있는 짧은 키워드만.",
                "domain_tags": "PR 및 incident에서 명확히 확인되는 도메인 태그만.",
                "suspected_fix_for": "PR이 해결하려는 장애 증상이나 원인. 근거 없으면 null.",
                "resolution_note": "PR이 장애를 어떻게 해결했는지 조치 중심으로 요약.",
                "diff_summary": "patch와 변경 파일에 근거하여 주요 코드 변경을 요약.",
            },
            "incident": {
                "id": str(incident.id),
                "project_name": incident.project_name,
                "status": incident.status,
                "primary_error_type": incident.primary_error_type,
                "primary_error_message": incident.primary_error_message,
                "primary_error_summary": incident.primary_error_summary,
                "error_keywords": incident.error_keywords,
                "domain_tags": incident.domain_tags,
                "suspected_cause": incident.suspected_cause,
                "root_cause_summary": incident.root_cause_summary,
                "resolution_summary": incident.resolution_summary,
            },
            "pull_request": {
                "project_name": payload.project_name,
                "repository_name": payload.repository_name,
                "number": pull_request.number,
                "title": pull_request.title,
                "body": pull_request.body,
                "source_branch": pull_request.head.ref,
                "target_branch": pull_request.base.ref,
                "status": "merged" if pull_request.merged else pull_request.state,
                "changed_files": parsed.changed_files,
                "commit_messages": parsed.commit_messages,
                "related_ticket_keys": parsed.related_ticket_keys,
                "mvp_diff_summary": parsed.diff_summary,
                "files": self._files_for_prompt(payload),
            },
            "output_contract": {
                "must_be_json_only": True,
                "fields": [
                    "normalized_summary",
                    "extracted_keywords",
                    "domain_tags",
                    "suspected_fix_for",
                    "resolution_note",
                    "diff_summary",
                ],
            },
        }
        return [
            {
                "role": "developer",
                "content": (
                    "You enrich a pull request already linked to an incident. "
                    "Return JSON only. Use only evidence from the incident and PR. "
                    "Do not invent causes or fixes."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]

    def _files_for_prompt(self, payload: RawPrCreate) -> list[dict[str, str | None]]:
        remaining = _MAX_PATCH_CHARS
        files: list[dict[str, str | None]] = []
        for file in payload.files:
            patch = file.patch or ""
            included_patch = patch[:remaining] if remaining > 0 else ""
            remaining -= len(included_patch)
            files.append(
                {
                    "filename": file.filename,
                    "status": file.status,
                    "patch": included_patch or None,
                }
            )
        return files

    def _parse_model_output(
        self,
        text: str,
        *,
        allow_json_extraction: bool,
    ) -> _LlmPrSchema | None:
        if not text.strip():
            return None
        try:
            json_text = (
                extract_first_json_object(text) if allow_json_extraction else text
            )
            return _LlmPrSchema.model_validate(json.loads(json_text or text))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.debug(
                "LLM PR enrich parse failed: %s preview=%s",
                exc,
                preview_truncated(text, 800),
            )
            return None

    def _normalize(self, model: _LlmPrSchema) -> LlmEnrichedPr:
        return LlmEnrichedPr(
            normalized_summary=self._strip_opt(model.normalized_summary),
            extracted_keywords=self._normalize_list(model.extracted_keywords),
            domain_tags=self._normalize_list(model.domain_tags),
            suspected_fix_for=self._strip_opt(model.suspected_fix_for),
            resolution_note=self._strip_opt(model.resolution_note),
            diff_summary=self._strip_opt(model.diff_summary),
        )

    def _normalize_list(self, values: list[str]) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    def _strip_opt(self, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
