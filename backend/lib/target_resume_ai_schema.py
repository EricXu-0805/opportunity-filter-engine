"""Strict wire contract for full-target résumé suggestions; no legacy trimming."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PIPELINE_VERSION = "full-target-v1"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = MAX_DOCUMENT_BYTES + 64 * 1024
MAX_UNITS = 24
MAX_ORIGINAL_CHARACTERS = 16000
MAX_EXPERIENCE_CHARACTERS = 6000
MAX_TARGET_CHARACTERS = 24000
MAX_PROMPT_CHARACTERS = 60000
MAX_SAFE_INTEGER = 9007199254740991


class FullTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    request_id: str = Field(min_length=1, max_length=80)
    locale: Literal["en", "zh"]
    draft: dict[str, Any]
    document_signature: str = Field(pattern=r"^v1:sha256:[0-9a-f]{64}$")
    selected_unit_ids: list[str] = Field(min_length=1, max_length=MAX_UNITS)

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("invalid_version")
        return value

    @field_validator("request_id")
    @classmethod
    def safe_id(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("invalid_request_id")
        value.encode("utf-8")
        return value
