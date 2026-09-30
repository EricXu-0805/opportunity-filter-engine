"""Owner-checked private review and Tracker identity; no writing or model input.

A private import is never normalized into a public listing. The full description
below is readable source material for its owner, not provider-ready evidence.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from backend.lib import private_import_targets as storage
from backend.lib.private_import_targets_schema import PrivateTargetError, Scope, identifier
from backend.lib.public_projection import safe_public_http_url
from src.collectors.url_parser import is_safe_url

_VERSION = re.compile(r"^pit1:[0-9a-f]{64}$")
_RAW_RECORD_FIELDS = {"id", "owner_id", "revision", "opportunity", "created_at", "updated_at", "deleted_at"}


def private_target_namespace(value: object) -> bool:
    """Recognize the namespace before any public lookup; validity is separate."""
    return isinstance(value, str) and value.startswith("private-import:")


def _expected_version(value: object) -> None:
    if value is not None and (not isinstance(value, str) or not _VERSION.fullmatch(value)):
        raise PrivateTargetError("private_target_invalid_request", 422)


def safe_private_source_link(value: object) -> str | None:
    """Pure link syntax gate, not source verification or a DNS/network probe."""
    # Python urlsplit tolerates raw controls/backslashes that a browser either
    # rewrites or the client receipt validator rejects. Preserve them in the
    # original record, but never offer them as a resolved browser link.
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f\\]", value):
        return None
    browser_safe = safe_public_http_url(value)
    if browser_safe is None or not is_safe_url(browser_safe)[0]:
        return None
    parsed = urlsplit(browser_safe)
    hostname = parsed.hostname or ""
    # Literal IP links are already rejected above. IPvFuture brackets and a
    # malformed/forbidden percent-decoded hostname also fail browser parsing.
    if "[" in parsed.netloc or "]" in parsed.netloc or re.search(r"%(?![0-9a-fA-F]{2})", hostname):
        return None
    try:
        decoded_host = unquote(hostname, encoding="utf-8", errors="strict")
    except UnicodeError:
        return None
    if re.search(r"[\x00-\x20\x7f%/\\:#?@<>^|\[\]]", decoded_host):
        return None
    return browser_safe


@dataclass(frozen=True)
class PrivateResolvedTarget:
    id: str
    owner_id: str
    revision: int
    target_version: str
    detail: dict
    tracker: dict

    def as_dict(self) -> dict:
        return {
            "version": 1,
            "target_scope": "private_import",
            "verification": "unverified",
            "id": self.id,
            "owner_id": self.owner_id,
            "revision": self.revision,
            "target_version": self.target_version,
            "detail": deepcopy(self.detail),
            "tracker": deepcopy(self.tracker),
            "capabilities": {"read": True, "tracker_identity": True, "writes": False},
        }


def project_private_target(target: dict, *, expected_owner_id: str, target_id: str) -> PrivateResolvedTarget:
    """Project a service receipt through an explicit private-only field list.

    Revalidate the stored row and recompute decorations; even a cached receipt's
    verification, labels, version or capabilities cannot promote its authority.
    """
    if not isinstance(target, dict) or not _RAW_RECORD_FIELDS <= target.keys():
        raise PrivateTargetError("private_target_invalid_receipt", 502)
    record = storage.target_receipt({key: target[key] for key in _RAW_RECORD_FIELDS}, expected_owner_id, target_id)
    if record["deleted_at"] is not None:
        raise PrivateTargetError("private_target_deleted", 409)
    raw = record["opportunity"]
    source_url = safe_private_source_link(raw.get("source_url"))
    url = safe_private_source_link(raw.get("url"))
    detail = {
        "title": raw["title"],
        "organization": raw.get("organization"),
        "description_raw": raw["description_raw"],
        "source_url": source_url,
        "url": url,
        "location": raw.get("location"),
        "deadline": raw.get("deadline"),
        "posted_date": raw.get("posted_date"),
        "import_source": deepcopy(record["import_source"]),
    }
    tracker = {
        "id": record["id"],
        "title": detail["title"],
        "organization": detail["organization"],
        "source_url": source_url,
        "url": url,
        "target_scope": "private_import",
        "verification": "unverified",
        "target_version": record["target_version"],
    }
    return PrivateResolvedTarget(
        id=record["id"],
        owner_id=record["owner_id"],
        revision=record["revision"],
        target_version=record["target_version"],
        detail=detail,
        tracker=tracker,
    )


async def resolve_private_import_target(
    target_id: str,
    *,
    authorization: str | None,
    expected_owner_id: str,
    expected_target_version: str | None = None,
) -> PrivateResolvedTarget:
    """Read the current owned row and enforce deletion/version before projection.

    No public corpus lookup or fallback exists here. A future writing consumer
    must explicitly choose its own purpose gate and input scope; this resolver
    grants only read and Tracker identity capabilities.
    """
    identifier(target_id)
    scope = Scope(expected_owner_id=expected_owner_id)
    _expected_version(expected_target_version)
    url, key = storage.settings()
    async with storage.new_client() as client:
        service = storage.PrivateTargetService(client, url, key, authorization)
        await service.authenticate(scope)
        response = await service.read(target_id, scope)
    target = response["target"]
    if target["deleted_at"] is not None:
        raise PrivateTargetError("private_target_deleted", 409)
    if expected_target_version is not None and expected_target_version != target["target_version"]:
        raise PrivateTargetError("private_target_changed", 409)
    return project_private_target(target, expected_owner_id=scope.expected_owner_id, target_id=target_id)
