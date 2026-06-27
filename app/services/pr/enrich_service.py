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

        incident_json = json.dumps(
            {
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
            ensure_ascii=False,
            indent=2,
        )

        pr_json = json.dumps(
            {
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
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""
            아래 Pull Request는 이미 특정 incident와 연결된 상태이다.
            제공된 incident 정보와 PR 정보만 사용해서 PR 내용을 보강한다.

            [작업 목적]
            - 이 PR이 어떤 변경을 했는지 요약한다.
            - 이 PR이 연결된 incident의 어떤 증상 또는 실패를 해결하려는지 정리한다.
            - PR의 변경 파일, patch, commit message, PR 본문에 근거하여 해결 내용을 요약한다.
            - 제공되지 않은 원인, 해결책, 파일, 의존성, 비즈니스 맥락은 새로 만들어내지 않는다.
            - 근거가 부족한 필드는 null 또는 빈 배열로 반환한다.

            [작성 규칙]
            1. normalized_summary
            - PR이 수행한 변경을 한국어 1문장으로 요약한다.

            2. extracted_keywords
            - incident 또는 PR에서 직접 확인 가능한 검색용 키워드만 포함한다.
            - 클래스명, 에러 타입, 파일명, 도메인 키워드처럼 검색에 유용한 값을 우선한다.

            3. domain_tags
            - incident 또는 PR에서 명확히 확인되는 도메인 태그만 포함한다.
            - 명확하지 않으면 빈 배열을 반환한다.

            4. suspected_fix_for
            - 이 PR이 해결하려는 장애 증상, 실패 지점, 또는 원인을 작성한다.
            - incident와 PR 정보로 뒷받침되지 않으면 null을 반환한다.

            5. resolution_note
            - PR이 장애를 어떻게 해결했는지 조치 중심으로 요약한다.
            - 변경 내용이 불명확하면 null을 반환한다.

            6. diff_summary
            - changed_files, files.patch, commit_messages, mvp_diff_summary에 근거해 주요 코드 변경을 요약한다.
            - patch에 없는 세부 구현은 추측하지 않는다.

            [입력]
            Incident:
            ```json
            {incident_json}
            ```

            Pull Request:
            ```json
            {pr_json}
            ```

            [반환 형식]
            반드시 JSON만 반환한다.
            아래 필드만 포함한다.

            * normalized_summary
            * extracted_keywords
            * domain_tags
            * suspected_fix_for
            * resolution_note
            * diff_summary 
        """.strip()

        return [
            {
                "role": "developer",
                "content": (
                    "You are an experienced software engineer analyzing a pull request "
                    "that is already linked to a production incident. "
                    "Use only the provided incident and pull request evidence. "
                    "Do not invent causes, fixes, files, dependencies, or business context. "
                    "If evidence is insufficient, return null or an empty array. "
                    "Return only valid JSON matching the schema."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
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
