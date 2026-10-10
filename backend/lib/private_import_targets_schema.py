"""Private import persistence only. No publication or model-input authority."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from backend.lib.request_body import known_keys

MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_BODY_BYTES = MAX_PAYLOAD_BYTES + 65536
MAX_EXTRA_BYTES = 256 * 1024
PRIVATE = {"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
PREFIX = "private-import:"


class PrivateTargetError(Exception):
    def __init__(self, code="private_target_unavailable", status=503):
        self.code, self.status = code, status
        super().__init__(code)


def identifier(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        raise ValueError("Invalid private target identifier")
    suffix = value[len(PREFIX) :]
    if str(UUID(suffix)) != suffix:
        raise ValueError("Invalid private target identifier")
    return value


def owner(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid owner")
    return value


def timestamp(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 40
        or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None
    ):
        raise ValueError("Invalid timestamp")
    return value


def encoded(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid JSON") from None


# A lone surrogate, found by the regex engine's C loop rather than by a Python loop over every character.
_SURROGATE = re.compile("[\ud800-\udfff]")


def _depth(value: Any, depth: int = 0) -> None:
    if isinstance(value, str) and ("\x00" in value or _SURROGATE.search(value)):
        raise ValueError("Invalid JSON text")
    if depth > 32:
        raise ValueError("Invalid JSON nesting")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Invalid JSON key")
            _depth(key, depth + 1)
            _depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _depth(child, depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("Invalid JSON value")


def opportunity(value: object) -> dict:
    required = {"source", "title", "description_raw"}
    optional = {"source_url", "url", "organization", "deadline", "posted_date", "location", "raw_html", "extra_fields"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise ValueError("Invalid import")
    if value.get("source") not in ("url_parser", "text_parser"):
        raise ValueError("Invalid import source")
    for key in required | (set(value) - {"extra_fields"}):
        item = value.get(key)
        if item is None and key in {"organization", "deadline", "posted_date", "location", "raw_html"}:
            continue
        if not isinstance(item, str):
            raise ValueError("Invalid import field")
        item.encode("utf-8")
    if not value["title"].strip() or len(value["title"]) > 1000 or not value["description_raw"].strip():
        raise ValueError("Invalid import content")
    if len(value["description_raw"]) > 5 * 1024 * 1024:
        raise PrivateTargetError("private_target_too_large", 413)
    for key in ("source_url", "url"):
        if len(value.get(key, "")) > 8192:
            raise ValueError("Invalid source address")
    for key, limit in [("organization", 2000), ("location", 2000), ("deadline", 128), ("posted_date", 128)]:
        if isinstance(value.get(key), str) and len(value[key]) > limit:
            raise ValueError("Invalid import field")
    extra = value.get("extra_fields", {})
    if not isinstance(extra, dict):
        raise ValueError("Invalid import metadata")
    _depth(value)
    if len(encoded(extra)) > MAX_EXTRA_BYTES or len(encoded(value)) > MAX_PAYLOAD_BYTES:
        raise PrivateTargetError("private_target_too_large", 413)
    return value


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    _known_keys = model_validator(mode="before")(known_keys)
    expected_owner_id: str
    _owner = field_validator("expected_owner_id")(owner)


class SaveRequest(Scope):
    expected_revision: StrictInt = Field(ge=0, le=9007199254740990)
    opportunity: dict
    _opportunity = field_validator("opportunity")(opportunity)


class DeleteRequest(Scope):
    expected_revision: StrictInt = Field(ge=1, le=9007199254740990)
