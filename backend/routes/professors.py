"""Read-only professor updates: verified change events for followed faculty.

Serves the ``data/processed/professor_tracking.json`` artifact the collector
refresh maintains. Only a schema-v2 artifact whose release contract passes is
served. Anything else (including a partial-school baseline, a leftover v1
file, or stale/error-producing refresh) is an honest ``available: false`` empty
response, never an error. Within an available artifact, each event must still
pass its own stored evidence validation (hashes, fingerprint, and event id).

Events never contain contact details: the pipeline's evidence payload
excludes them by construction and this layer re-projects a fixed field set.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.tracking.professor_profiles import (
    PROFESSOR_ID_PATTERN,
    TRACKING_SCHEMA_VERSION,
    artifact_release_ready,
    load_tracking_state,
    validate_tracking_event_evidence,
)

router = APIRouter()
logger = logging.getLogger("ofe.professors")

TRACKING_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "processed" / "professor_tracking.json"
)

MAX_IDS_PER_REQUEST = 200
MAX_EVENT_LIMIT = 200
_MAX_TEXT = 200

_cache_lock = threading.Lock()
_cache_signature: tuple | None = None
_cache_available = False
_cache_release_ready = False
_cache_expires_at: datetime | None = None
# professor_id -> events newest-first, already projected to the serving shape.
_cache_events_by_professor: dict[str, list[dict]] = {}


def reset_tracking_cache() -> None:
    global _cache_signature, _cache_available, _cache_release_ready
    global _cache_expires_at, _cache_events_by_professor
    with _cache_lock:
        _cache_signature = None
        _cache_available = False
        _cache_release_ready = False
        _cache_expires_at = None
        _cache_events_by_professor = {}


def _path_signature() -> tuple:
    try:
        stat = TRACKING_PATH.stat()
    except OSError:
        return (None, None)
    return (
        stat.st_size,
        stat.st_mtime_ns,
    )


def _bounded_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned or len(cleaned) > _MAX_TEXT:
        return None
    return cleaned


def _project_event(event: dict) -> dict | None:
    """Serving projection: public fields only, evidence stays server-side."""

    professor_name = _bounded_text(event.get("professor_name"))
    school = _bounded_text(event.get("school"))
    if professor_name is None or school is None:
        return None
    return {
        "event_id": event["event_id"],
        "professor_id": event["professor_id"],
        "professor_name": professor_name,
        "school": school,
        "verified_at": event["verified_at"],
        "source_url": event["source_url"],
        "change_types": list(event["change_types"]),
        "project_became_available": event["project_became_available"],
    }


def _load_events() -> tuple[bool, bool, dict[str, list[dict]]]:
    global _cache_signature, _cache_available, _cache_release_ready
    global _cache_expires_at, _cache_events_by_professor
    signature = _path_signature()
    with _cache_lock:
        if signature == _cache_signature:
            if (
                _cache_release_ready
                and _cache_expires_at is not None
                and datetime.now(UTC) > _cache_expires_at
            ):
                _cache_available = False
                _cache_release_ready = False
                _cache_events_by_professor = {}
            return _cache_available, _cache_release_ready, _cache_events_by_professor

        available = False
        by_professor: dict[str, list[dict]] = {}
        state = load_tracking_state(TRACKING_PATH)
        release_ready = artifact_release_ready(state)
        expires_at = None
        if release_ready and isinstance(state, dict):
            release = state.get("release")
            if isinstance(release, dict):
                try:
                    freshness_expiry = datetime.fromisoformat(
                        str(release["freshness_valid_until"]).replace("Z", "+00:00")
                    )
                    computed_at = datetime.fromisoformat(
                        str(release["computed_at"]).replace("Z", "+00:00")
                    )
                    expires_at = min(
                        freshness_expiry.astimezone(UTC),
                        computed_at.astimezone(UTC)
                        + timedelta(days=int(release["freshness_ttl_days"])),
                    )
                except (KeyError, TypeError, ValueError):
                    release_ready = False
        # Schema v2 + passing artifact contract only: coverage/freshness gaps
        # disable the feature instead of serving a misleading partial feed.
        if (
            isinstance(state, dict)
            and state.get("schema_version") == TRACKING_SCHEMA_VERSION
            and isinstance(state.get("events"), list)
            and release_ready
        ):
            available = True
            skipped = 0
            projected: list[dict] = []
            for event in state["events"]:
                # Per-record eligibility: each event stands or falls on its
                # own evidence; one bad entry never disables the feature.
                if not validate_tracking_event_evidence(event):
                    skipped += 1
                    continue
                served = _project_event(event)
                if served is None:
                    skipped += 1
                    continue
                projected.append(served)
            if skipped:
                logger.warning(
                    "professor tracking: skipped %d invalid event(s) at serve time",
                    skipped,
                )
                # A stored release marker cannot waive serve-time evidence
                # validation. Any corrupt event invalidates this artifact until
                # the producer rebuilds it.
                available = False
                release_ready = False
            else:
                projected.sort(
                    key=lambda event: (event["verified_at"], event["event_id"]),
                    reverse=True,
                )
                for event in projected:
                    by_professor.setdefault(event["professor_id"], []).append(event)

        _cache_signature = signature
        _cache_available = available
        _cache_release_ready = release_ready
        _cache_expires_at = expires_at
        _cache_events_by_professor = by_professor
        return available, _cache_release_ready, by_professor


class ProfessorUpdatesRequest(BaseModel):
    ids: list[str] = Field(..., max_length=MAX_IDS_PER_REQUEST)
    limit: int = Field(default=50, ge=1, le=MAX_EVENT_LIMIT)


@router.post("/professors/updates")
async def professor_updates(body: ProfessorUpdatesRequest):
    """Verified update events for the requested professor ids, newest first.

    Malformed ids are ignored (the frontend validates before persisting a
    follow, but old rows must never 500 the feed); professors with no
    tracking data simply contribute no events.
    """
    requested = {
        pid for pid in body.ids
        if isinstance(pid, str) and PROFESSOR_ID_PATTERN.fullmatch(pid)
    }

    available, release_ready, by_professor = _load_events()
    if not available or not requested:
        return {
            "available": available,
            "release_ready": release_ready,
            "events": [],
            "requested": len(body.ids),
            "has_more": False,
        }

    merged: list[dict] = []
    for professor_id in requested:
        merged.extend(by_professor.get(professor_id, ()))
    merged.sort(key=lambda event: (event["verified_at"], event["event_id"]), reverse=True)
    has_more = len(merged) > body.limit
    return {
        "available": True,
        "release_ready": release_ready,
        "events": merged[: body.limit],
        "requested": len(body.ids),
        "has_more": has_more,
    }
