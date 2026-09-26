"""Strict whole-document selection-plan wire contract; no implicit trimming."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PIPELINE_VERSION = "full-target-plan-v1"
MAX_PROMPT_CHARACTERS = 120000
MAX_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024


class PlanOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_pages: Literal[1, 2]

    @field_validator("target_pages", mode="before")
    @classmethod
    def integer_pages(cls, value):
        if type(value) is not int:
            raise ValueError("invalid_target_pages")
        return value


class FullTargetPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    request_id: str = Field(min_length=1, max_length=80)
    locale: Literal["en", "zh"]
    draft: dict[str, Any]
    document_signature: str = Field(pattern=r"^v1:sha256:[0-9a-f]{64}$")
    options: PlanOptions

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
