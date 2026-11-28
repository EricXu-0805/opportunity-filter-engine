"""Public pull-request evidence kept with a student-reviewed experience."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.lib.request_body import known_keys

GITHUB_LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-[A-Za-z0-9]){0,38}"
GITHUB_REPO = r"[A-Za-z0-9_.-]{1,100}"


def valid_repository(value: str) -> bool:
    if len(value) > 140:
        return False
    parts = value.split("/")
    return (len(parts) == 2 and len(parts[0]) <= 39 and parts[1] not in {".", ".."}
            and bool(re.fullmatch(GITHUB_LOGIN, parts[0]) and re.fullmatch(GITHUB_REPO, parts[1])))


class GitHubPullSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    _known_keys = model_validator(mode="before")(known_keys)
    kind: Literal["github"]
    repository: str
    head_repository: str | None
    number: int = Field(gt=0, le=9007199254740991)
    author: str = Field(min_length=1, max_length=39, pattern=f"^{GITHUB_LOGIN}$")
    title: str = Field(min_length=1, max_length=512)

    @field_validator("repository", "head_repository")
    @classmethod
    def repository_name(cls, value):
        if value is not None and not valid_repository(value):
            raise ValueError("invalid GitHub repository")
        return value

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("invalid pull request title")
        value.encode("utf-8")
        return value


def names_pull(text: str, source: GitHubPullSource) -> bool:
    """Whether an entry's text still names the pull request kept as its source.

    The student may reword an imported sentence. Once it no longer names both
    the repository and the pull number it is their own statement, entered by them.
    """
    return (source.repository.lower() in text.lower()
            and re.search(rf"(?<![0-9]){source.number}(?![0-9])", text) is not None)
