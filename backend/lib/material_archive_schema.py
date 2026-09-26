"""Wire validation for user-reported PDFs. Never infer a submission or contact."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + 65536
BUCKET = "application-materials"
PRIVATE = {"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MaterialError(Exception):
    def __init__(self, code: str = "material_unavailable", status: int = 503):
        self.code, self.status = code, status
        super().__init__(code)


def uuid_text(value: object) -> str:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ValueError("Invalid identifier")
    UUID(value)
    return value


def timestamp(value: object) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timezone")
    return value


def utc_timestamp(value: str) -> str:
    timestamp(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()


def filename(value: str) -> str:
    if (not 1 <= len(value) <= 200 or not value.strip() or not value.lower().endswith(".pdf")
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in "/\\" for c in value)):
        raise ValueError("Invalid filename")
    value.encode("utf-8", errors="strict")
    return value


class _Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_owner_id: str
    opportunity_id: str = Field(min_length=1, max_length=200)
    _owner = field_validator("expected_owner_id")(uuid_text)

    @field_validator("opportunity_id")
    @classmethod
    def target(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid target")
        value.encode("utf-8", errors="strict")
        return value


class Scope(_Scope):
    material_kind: ClassVar[str] = "application"
    event_field: ClassVar[str] = "application_event_id"
    application_event_id: str
    _event = field_validator("application_event_id")(uuid_text)


class ContactScope(_Scope):
    material_kind: ClassVar[str] = "contact"
    event_field: ClassVar[str] = "contact_event_id"
    contact_event_id: str
    _event = field_validator("contact_event_id")(uuid_text)


ArchiveScope = Scope | ContactScope


class ContactMaterialDeletion(ContactScope):
    material_id: str
    _material = field_validator("material_id")(uuid_text)


class MaterialDeletion(Scope):
    material_id: str
    _material = field_validator("material_id")(uuid_text)


class _MaterialFields(BaseModel):
    version: Literal[1]
    material_id: str
    record_id: str
    filename: str
    mime_type: Literal["application/pdf"]
    byte_length: StrictInt = Field(ge=1, le=MAX_FILE_BYTES)
    bytes_sha256: str
    attested: StrictBool

    _material_ids = field_validator("material_id", "record_id")(uuid_text)
    _name = field_validator("filename")(filename)

    @field_validator("version", mode="before")
    @classmethod
    def version_number(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Invalid version")
        return value

    @field_validator("bytes_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        if not SHA_RE.fullmatch(value):
            raise ValueError("Invalid digest")
        return value

    @field_validator("attested")
    @classmethod
    def confirmed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirmation required")
        return value


class MaterialInput(_MaterialFields, Scope):
    pass


class ContactMaterialInput(_MaterialFields, ContactScope):
    pass


ArchiveInput = MaterialInput | ContactMaterialInput


SQL_FIELDS = {
    "material_id", "record_id", "application_event_id", "opportunity_id", "owner_id", "status",
    "filename", "mime_type", "byte_length", "sha256", "created_at", "expires_at",
    "archived_at", "recorded_at", "deleted_at", "confirmation_source",
}


def receipt(row: object, scope: ArchiveScope, *, record_id: str | None = None) -> dict:
    """Accept only the scoped, typed RPC receipt, never an arbitrary provider row."""
    event_field = scope.event_field
    fields = (SQL_FIELDS - {"application_event_id"}) | {event_field}
    try:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError
        for key in ("material_id", "record_id", event_field, "owner_id"):
            uuid_text(row[key])
        if (row["owner_id"] != scope.expected_owner_id or row["opportunity_id"] != scope.opportunity_id
                or row[event_field] != getattr(scope, event_field)
                or (record_id is not None and row["record_id"] != record_id)
                or row["confirmation_source"] != "user_reported"):
            raise ValueError
        timestamp(row["created_at"])
        timestamp(row["expires_at"])
        for key in ("archived_at", "recorded_at", "deleted_at"):
            if row[key] is not None:
                timestamp(row[key])
        if row["status"] == "deleted":
            if row["deleted_at"] is None or any(row[k] is not None for k in ("filename", "mime_type", "byte_length", "sha256")):
                raise ValueError
            if (row["archived_at"] is None) != (row["recorded_at"] is None):
                raise ValueError
        elif row["status"] in ("staged", "ready"):
            filename(row["filename"])
            if (row["mime_type"] != "application/pdf" or type(row["byte_length"]) is not int
                    or not 1 <= row["byte_length"] <= MAX_FILE_BYTES or row["deleted_at"] is not None):
                raise ValueError
            if row["status"] == "staged":
                if any(row[k] is not None for k in ("sha256", "archived_at", "recorded_at")):
                    raise ValueError
            elif (not isinstance(row["sha256"], str) or not SHA_RE.fullmatch(row["sha256"])
                  or row["archived_at"] is None or row["recorded_at"] is None):
                raise ValueError
        else:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise MaterialError("material_invalid_receipt", 502) from None
    return {
        "version": 1, **{k: row[k] for k in (
            "owner_id", "opportunity_id", event_field, "material_id", "record_id", "status",
            "filename", "mime_type", "byte_length", "confirmation_source",
        )},
        "bytes_sha256": row["sha256"], "staged_at": utc_timestamp(row["created_at"]),
        "archived_at": utc_timestamp(row["archived_at"]) if row["archived_at"] else None,
        "linked_at": utc_timestamp(row["recorded_at"]) if row["recorded_at"] else None,
        "deleted_at": utc_timestamp(row["deleted_at"]) if row["deleted_at"] else None,
    }


def require_input_match(record: dict, data: ArchiveInput) -> None:
    if (record["material_id"] != data.material_id or record["record_id"] != data.record_id
            or record["filename"] != data.filename or record["mime_type"] != data.mime_type
            or record["byte_length"] != data.byte_length
            or (record["status"] == "ready" and record["bytes_sha256"] != data.bytes_sha256)):
        raise MaterialError("material_conflict", 409)
