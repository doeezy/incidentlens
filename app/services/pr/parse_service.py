from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.raw_pr import GitHubPrFile, RawPrCreate

_TICKET_REFERENCE = re.compile(
    r"(?:(?<![A-Za-z0-9_./-])"
    r"(?P<repository>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)#|#)"
    r"(?P<number>\d+)"
)
_BARE_TICKET_REFERENCE = re.compile(r"#(?P<number>\d+)")


@dataclass(frozen=True)
class ParsedRawPr:
    changed_files: list[str]
    diff_summary: str | None
    commit_messages: list[str]
    related_ticket_keys: list[str]


class RawPrParseService:
    def parse(self, payload: RawPrCreate) -> ParsedRawPr:
        repository_name = payload.repository_name.strip()
        commit_messages = [
            commit.message.strip()
            for commit in payload.commits
            if commit.message.strip()
        ]
        related_ticket_keys = self._merge_unique(
            self._extract_ticket_keys(
                payload.pull_request.body or "",
                repository_name=repository_name,
            ),
            self._extract_ticket_keys(
                payload.pull_request.head.ref,
                repository_name=repository_name,
                allow_explicit_repository=False,
            ),
            self._extract_ticket_keys(
                "\n".join(commit_messages),
                repository_name=repository_name,
            ),
        )
        return ParsedRawPr(
            changed_files=[
                file.filename.strip()
                for file in payload.files
                if file.filename.strip()
            ],
            diff_summary=self._summarize_patches(payload.files),
            commit_messages=commit_messages,
            related_ticket_keys=related_ticket_keys,
        )

    def _extract_ticket_keys(
        self,
        text: str,
        *,
        repository_name: str,
        allow_explicit_repository: bool = True,
    ) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        pattern = (
            _TICKET_REFERENCE
            if allow_explicit_repository
            else _BARE_TICKET_REFERENCE
        )
        for match in pattern.finditer(text):
            referenced_repo = match.groupdict().get("repository") or repository_name
            referenced_repo = referenced_repo.rsplit("/", maxsplit=1)[-1]
            key = f"{referenced_repo}#{match.group('number')}"
            if key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def _merge_unique(self, *groups: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for key in group:
                if key not in seen:
                    seen.add(key)
                    merged.append(key)
        return merged

    def _summarize_patches(self, files: list[GitHubPrFile]) -> str | None:
        summaries: list[str] = []
        for file in files:
            patch = file.patch or ""
            added = sum(
                1
                for line in patch.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            removed = sum(
                1
                for line in patch.splitlines()
                if line.startswith("-") and not line.startswith("---")
            )
            hunks = [
                line.strip()
                for line in patch.splitlines()
                if line.startswith("@@")
            ]
            detail = f"{file.filename.strip()} ({file.status.strip()}, +{added}/-{removed})"
            if hunks:
                detail += f": {'; '.join(hunks[:3])}"
            summaries.append(detail)
        return "\n".join(summaries) or None
