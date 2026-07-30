"""Record-scoped faculty tracking ids and profile-verified change events.

The opportunity corpus is refreshed from public sources, but a refresh is not
itself evidence that something changed.  This module keeps a compact baseline
of profile-verified faculty snapshots and emits an event only when:

* the record is an actual faculty-research record;
* both snapshots came from successful individual-profile fetches
  (``metadata.verification_scope == "profile"``, stamped by the harvest
  engine after a real per-profile page fetch);
* the new verification timestamp is valid and strictly newer;
* a public source URL is present; and
* one of the tracked public fields really changed.

Records without ``verification_scope`` (every legacy record) are simply not
trackable yet — never an error, never an event.  Contact details and URL query
strings are deliberately excluded from both the baseline and the event log.
Event ids are content-derived so replaying the same refresh is idempotent.

Serving stays per-record (an event serves iff its own evidence validates, see
``validate_tracking_event_evidence``), so the ledger is useful from the very
first verified change.  Schema v2 additionally stamps an artifact-level
``release`` block (see ``compute_release_status``): an honest, recomputed-
every-write summary of whether the artifact as a whole is release-ready —
schema valid, every stored event evidence-valid, baseline freshness >=
``FRESHNESS_MIN_PCT``, zero fully-stale schools, and the producing refresh run
free of collector errors.  ``release_ready`` is a marker for consumers and
ops; it never gates per-record serving (v1's global gate shipped the feature
permanently dead — see #661).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# v2 = v1 (profiles + events, unchanged shapes) + top-level "release" block.
# v1 artifacts are read-migrated (per-record salvage, same as any prior state)
# but every write is v2 — no production path emits v1 anymore.
TRACKING_SCHEMA_VERSION = 2
TRACKING_EVENT_EVIDENCE_VERSION = 1
_READABLE_SCHEMA_VERSIONS = frozenset({1, TRACKING_SCHEMA_VERSION})

# Freshness reuses the corpus's existing per-record verification semantics:
# metadata.last_verified is stamped only when a collector actually fetched the
# source this run, and a baseline's last_verified only ever advances from a
# strictly-newer profile-verified snapshot (update_tracking_state).  The 60-day
# TTL mirrors the admin data-quality "stale_verify" threshold
# (backend/routes/admin.py) — the project's one existing staleness definition
# for last_verified.  A failed or skipped fetch leaves the old timestamp in
# place, so freshness here can only be improved by real successful checks.
FRESHNESS_TTL_DAYS = 60
FRESHNESS_MIN_PCT = 95.0

# Only real changes become events, but a systemic engine change (e.g. a
# corpus-wide keyword cleanup) can legitimately touch every professor at once.
# Bounding the ledger per professor keeps the artifact's size proportional to
# the follow-worthy history instead of the corpus.
MAX_EVENTS_PER_PROFESSOR = 20

PROFESSOR_ID_PATTERN = re.compile(r"^prof:v1:[a-z0-9-]{1,48}:[0-9a-f]{20}$")
EVENT_ID_PATTERN = re.compile(r"^prof-event:v1:[0-9a-f]{24}$")

TRACKING_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "professor_id",
        "professor_name",
        "school",
        "verified_at",
        "source_url",
        "change_types",
        "project_became_available",
        "evidence",
    }
)
_EVENT_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "before",
        "after",
        "before_content_hash",
        "after_content_hash",
        "fingerprint",
    }
)
_CONTENT_PAYLOAD_FIELDS = frozenset(
    {
        "school",
        "title",
        "organization",
        "professor_name",
        "department",
        "lab_or_program",
        "research_focus",
        "availability",
        "source_url",
    }
)

CHANGE_TYPES = frozenset(
    {
        "research_focus",
        "department_or_lab",
        "project_availability",
        "public_source",
    }
)

_OPEN_STATUSES = frozenset(
    {
        "accepting",
        "accepting students",
        "available",
        "open",
        "open to students",
        "recruiting",
    }
)


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _identity_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", _clean_text(value)).casefold()
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def _school_slug(value: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _identity_text(value)).strip("-")
    return slug[:48]


def canonical_professor_id(opportunity: dict) -> str | None:
    """Return the v1 opaque tracking id for one faculty corpus record.

    This is deliberately *not* a resolved professor entity.  School, professor
    name, and the corpus record id form a conservative record-scoped key so two
    different people with the same name at one school are never merged.
    Enrichment fields such as email, profile URL, and lab are intentionally
    excluded because they routinely change between collectors and refreshes.
    """

    if not isinstance(opportunity, dict):
        return None
    if opportunity.get("source_type") != "faculty_research":
        return None

    school = _school_slug(opportunity.get("school"))
    professor_name = _identity_text(opportunity.get("pi_name"))
    record_id = _identity_text(opportunity.get("id"))
    if not school or not professor_name or not record_id:
        return None

    digest = hashlib.sha256(
        f"{school}\0{professor_name}\0{record_id}".encode()
    ).hexdigest()[:20]
    return f"prof:v1:{school}:{digest}"


def _safe_public_url(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""

    host = parsed.hostname.casefold()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.casefold(), host, path, "", ""))


def _parse_verified_at(value: object) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # The collector contract serializes UTC as a naive ISO timestamp
    # (``datetime.now(UTC).replace(tzinfo=None)``).  Treat that established
    # wire format as UTC rather than rejecting every real faculty snapshot.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_verified_at(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    unique: dict[str, str] = {}
    for item in value:
        cleaned = _clean_text(item)
        if cleaned:
            unique.setdefault(cleaned.casefold(), cleaned)
    return sorted(unique.values(), key=str.casefold)


def _research_focus(opportunity: dict) -> list[str]:
    values: list[str] = []
    for key in ("keywords", "research_areas", "research_interests"):
        values.extend(_string_list(opportunity.get(key)))

    metadata = opportunity.get("metadata")
    if isinstance(metadata, dict):
        for key in ("keywords", "research_areas", "research_interests"):
            values.extend(_string_list(metadata.get(key)))
    return _string_list(values)


def _availability(opportunity: dict) -> dict[str, object]:
    metadata = opportunity.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    raw_status = metadata.get("project_availability", metadata.get("status"))
    status = _clean_text(raw_status).casefold() or "unknown"
    is_active = metadata.get("is_active")
    return {
        "status": status,
        "is_active": is_active if isinstance(is_active, bool) else None,
    }


def _content_payload(profile: dict) -> dict:
    return {
        "school": profile["school"],
        "title": profile["title"],
        "organization": profile["organization"],
        "professor_name": profile["professor_name"],
        "department": profile["department"],
        "lab_or_program": profile["lab_or_program"],
        "research_focus": profile["research_focus"],
        "availability": profile["availability"],
        "source_url": profile["source_url"],
    }


def _content_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _event_evidence_fingerprint(
    professor_id: str,
    verified_at: str,
    before_content_hash: str,
    after_content_hash: str,
) -> str:
    encoded = json.dumps(
        {
            "after_content_hash": after_content_hash,
            "before_content_hash": before_content_hash,
            "evidence_schema_version": TRACKING_EVENT_EVIDENCE_VERSION,
            "professor_id": professor_id,
            "verified_at": verified_at,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _snapshot(opportunity: dict, professor_id: str) -> dict:
    metadata = opportunity.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    verified_at = _parse_verified_at(metadata.get("last_verified"))
    verification_scope = metadata.get("verification_scope")
    # A "profile" claim without a usable timestamp cannot participate in an
    # event chain; every other value (incl. absence on legacy records) is
    # simply "not profile-verified" — tracked as nothing, never an error.
    if verification_scope != "profile" or verified_at is None:
        verification_scope = "unverified"
    profile = {
        "professor_id": professor_id,
        "school": _school_slug(opportunity.get("school")),
        "title": _clean_text(opportunity.get("title")),
        "organization": _clean_text(opportunity.get("organization")),
        "professor_name": _clean_text(opportunity.get("pi_name")),
        "department": _clean_text(opportunity.get("department")),
        "lab_or_program": _clean_text(opportunity.get("lab_or_program")),
        "research_focus": _research_focus(opportunity),
        "availability": _availability(opportunity),
        "source_url": _safe_public_url(
            opportunity.get("source_url") or opportunity.get("url")
        ),
        "verification_scope": verification_scope,
        "last_verified": _format_verified_at(verified_at),
    }
    profile["content_hash"] = _content_hash(_content_payload(profile))
    return profile


def _changed_fields(before: dict, after: dict) -> list[str]:
    changes: list[str] = []
    if before.get("research_focus") != after.get("research_focus"):
        changes.append("research_focus")
    if (
        before.get("department") != after.get("department")
        or before.get("lab_or_program") != after.get("lab_or_program")
    ):
        changes.append("department_or_lab")
    if before.get("availability") != after.get("availability"):
        changes.append("project_availability")
    if before.get("source_url") != after.get("source_url"):
        changes.append("public_source")
    return changes


def _is_open(profile: dict) -> bool:
    availability = profile.get("availability")
    if not isinstance(availability, dict):
        return False
    return availability.get("status") in _OPEN_STATUSES


def _build_event(before: dict, after: dict, change_types: list[str]) -> dict:
    fingerprint = _event_evidence_fingerprint(
        after["professor_id"],
        after["last_verified"],
        before["content_hash"],
        after["content_hash"],
    )
    return {
        "event_id": f"prof-event:v1:{fingerprint[:24]}",
        "professor_id": after["professor_id"],
        "professor_name": after["professor_name"],
        "school": after["school"],
        "verified_at": after["last_verified"],
        "source_url": after["source_url"],
        "change_types": change_types,
        "project_became_available": (
            "project_availability" in change_types
            and not _is_open(before)
            and _is_open(after)
        ),
        "evidence": {
            "schema_version": TRACKING_EVENT_EVIDENCE_VERSION,
            "before": _content_payload(before),
            "after": _content_payload(after),
            "before_content_hash": before["content_hash"],
            "after_content_hash": after["content_hash"],
            "fingerprint": fingerprint,
        },
    }


def _valid_content_evidence(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _CONTENT_PAYLOAD_FIELDS:
        return False
    text_fields = {
        "school",
        "title",
        "organization",
        "professor_name",
        "department",
        "lab_or_program",
        "source_url",
    }
    if any(not isinstance(value.get(field), str) for field in text_fields):
        return False
    research_focus = value.get("research_focus")
    availability = value.get("availability")
    if (
        not isinstance(research_focus, list)
        or any(not isinstance(item, str) or not item for item in research_focus)
        or not isinstance(availability, dict)
        or set(availability) != {"status", "is_active"}
        or not isinstance(availability.get("status"), str)
        or (
            availability.get("is_active") is not None
            and type(availability.get("is_active")) is not bool
        )
    ):
        return False
    source_url = value["source_url"]
    return not source_url or _safe_public_url(source_url) == source_url


def validate_tracking_event_evidence(event: object) -> bool:
    """Verify one durable event purely from its own canonical evidence.

    Per-record eligibility: an event is trusted only when its public evidence
    deterministically reproduces the hashes, change semantics, fingerprint,
    and event id.  There is no cross-check against any global state — a valid
    event serves even when it is the only one in the file.
    """

    if not isinstance(event, dict) or set(event) != TRACKING_EVENT_FIELDS:
        return False
    professor_id = event.get("professor_id")
    if (
        not isinstance(professor_id, str)
        or PROFESSOR_ID_PATTERN.fullmatch(professor_id) is None
    ):
        return False

    verified_at = _parse_verified_at(event.get("verified_at"))
    if verified_at is None:
        return False

    evidence = event.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != _EVENT_EVIDENCE_FIELDS:
        return False
    if evidence.get("schema_version") != TRACKING_EVENT_EVIDENCE_VERSION:
        return False
    before = evidence.get("before")
    after = evidence.get("after")
    if not _valid_content_evidence(before) or not _valid_content_evidence(after):
        return False
    assert isinstance(before, dict) and isinstance(after, dict)

    before_hash = evidence.get("before_content_hash")
    after_hash = evidence.get("after_content_hash")
    fingerprint = evidence.get("fingerprint")
    if (
        not isinstance(before_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", before_hash)
        or not isinstance(after_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", after_hash)
        or not isinstance(fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        or _content_hash(before) != before_hash
        or _content_hash(after) != after_hash
    ):
        return False

    canonical_verified_at = _format_verified_at(verified_at)
    expected_fingerprint = _event_evidence_fingerprint(
        professor_id,
        canonical_verified_at,
        before_hash,
        after_hash,
    )
    school = event.get("school")
    id_parts = professor_id.split(":", 3)
    if (
        fingerprint != expected_fingerprint
        or event.get("event_id") != f"prof-event:v1:{fingerprint[:24]}"
        or event.get("verified_at") != canonical_verified_at
        or not isinstance(school, str)
        or len(id_parts) != 4
        or id_parts[2] != school
        or before.get("school") != school
        or after.get("school") != school
        or event.get("professor_name") != after.get("professor_name")
        or event.get("source_url") != after.get("source_url")
        or not after.get("source_url")
    ):
        return False

    change_types = _changed_fields(before, after)
    return (
        bool(change_types)
        and event.get("change_types") == change_types
        and type(event.get("project_became_available")) is bool
        and event.get("project_became_available")
        == (
            "project_availability" in change_types
            and not _is_open(before)
            and _is_open(after)
        )
    )


def _empty_state() -> dict:
    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "profiles": {},
        "events": [],
    }


# Bound the fully-stale-school list so a systemic outage can't balloon the
# artifact; the count is always exact.
_MAX_FULLY_STALE_SCHOOLS_LISTED = 20


def compute_release_status(
    profiles: dict[str, dict],
    events: list[dict],
    *,
    refresh_ok: bool,
    now: datetime | None = None,
) -> dict:
    """Compute the artifact-level ``release`` block from real state only.

    ``release_ready`` is true iff every check holds:

    * ``schema_v2`` — this writer only emits v2, recorded for consumers;
    * ``events_valid`` — every stored event re-validates against its own
      evidence (the project's existing validator, nothing waived);
    * ``freshness_min_pct`` — >= ``FRESHNESS_MIN_PCT`` of profile baselines
      were successfully profile-verified within ``FRESHNESS_TTL_DAYS``.  A
      baseline's ``last_verified`` only advances from a real, strictly-newer
      profile fetch, so this cannot be gamed by pipeline execution alone.
      An artifact with zero baselines has nothing verified — freshness is
      ``None`` and the check fails (fail-closed, never vacuously fresh);
    * ``no_fully_stale_school`` — no school whose *entire* baseline set is
      stale.  The global percentage alone would mask a school-wide outage
      (one dead school among many fresh ones still averages above 95%);
    * ``refresh_ok`` — the producing refresh run reported no collector
      errors.  Passed in by the caller from the run summary; a standalone
      recompute must derive it from the run's real recorded statuses, never
      assume success.
    """

    now = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    ttl = timedelta(days=FRESHNESS_TTL_DAYS)

    total = 0
    fresh = 0
    school_totals: dict[str, int] = {}
    school_fresh: dict[str, int] = {}
    for profile in profiles.values():
        verified_at = _parse_verified_at(profile.get("last_verified"))
        school = profile.get("school")
        if not isinstance(school, str) or verified_at is None:
            # _valid_previous_state / update_tracking_state never store such a
            # profile; a hand-edited artifact counts it as stale, not fresh.
            is_fresh = False
            school = school if isinstance(school, str) and school else "?"
        else:
            is_fresh = now - verified_at <= ttl
        total += 1
        school_totals[school] = school_totals.get(school, 0) + 1
        if is_fresh:
            fresh += 1
            school_fresh[school] = school_fresh.get(school, 0) + 1

    freshness_pct = (100.0 * fresh / total) if total else None
    fully_stale = sorted(
        school for school, n in school_totals.items()
        if n > 0 and school_fresh.get(school, 0) == 0
    )
    events_valid = all(validate_tracking_event_evidence(event) for event in events)

    checks = {
        "schema_v2": True,
        "events_valid": events_valid,
        "freshness_min_pct": freshness_pct is not None
        and freshness_pct >= FRESHNESS_MIN_PCT,
        "no_fully_stale_school": not fully_stale,
        "refresh_ok": bool(refresh_ok),
    }
    return {
        "computed_at": now.isoformat(),
        "freshness_ttl_days": FRESHNESS_TTL_DAYS,
        "freshness_min_pct": FRESHNESS_MIN_PCT,
        "freshness_pct": round(freshness_pct, 2) if freshness_pct is not None else None,
        "fresh_profiles": fresh,
        "total_profiles": total,
        "schools_tracked": len(school_totals),
        "fully_stale_school_count": len(fully_stale),
        "fully_stale_schools": fully_stale[:_MAX_FULLY_STALE_SCHOOLS_LISTED],
        "checks": checks,
        "release_ready": all(checks.values()),
    }


def artifact_release_ready(state: object) -> bool:
    """True iff ``state`` is a v2 artifact whose stored release block passed
    every check.  v1 artifacts (no release block) are never release-ready."""

    if not isinstance(state, dict) or state.get("schema_version") != TRACKING_SCHEMA_VERSION:
        return False
    release = state.get("release")
    return isinstance(release, dict) and release.get("release_ready") is True


def _profile_observation(profile: object) -> bool:
    return (
        isinstance(profile, dict)
        and profile.get("verification_scope") == "profile"
        and _parse_verified_at(profile.get("last_verified")) is not None
    )


def _valid_previous_state(previous_state: object) -> dict:
    """Salvage everything valid from a prior artifact; drop only what isn't.

    A single corrupt event must not erase the verified history of every other
    professor — invalid entries are dropped individually and logged.  v1
    artifacts are explicitly read-migrated here (profile and event shapes are
    identical; every entry re-validates individually either way) so bumping
    the schema never erases verified history — but the WRITE side is always
    v2, so no production path can re-emit v1.
    """

    if (
        not isinstance(previous_state, dict)
        or previous_state.get("schema_version") not in _READABLE_SCHEMA_VERSIONS
        or not isinstance(previous_state.get("profiles"), dict)
        or not isinstance(previous_state.get("events"), list)
    ):
        return _empty_state()
    if previous_state.get("schema_version") != TRACKING_SCHEMA_VERSION:
        logger.info(
            "professor tracking: migrating stored artifact from schema v%s to v%s",
            previous_state.get("schema_version"), TRACKING_SCHEMA_VERSION,
        )

    profiles: dict[str, dict] = {}
    for professor_id, profile in previous_state["profiles"].items():
        if (
            isinstance(professor_id, str)
            and PROFESSOR_ID_PATTERN.fullmatch(professor_id)
            and _profile_observation(profile)
            and profile.get("professor_id") == professor_id
        ):
            profiles[professor_id] = deepcopy(profile)

    events: list[dict] = []
    dropped = 0
    for event in previous_state["events"]:
        if validate_tracking_event_evidence(event):
            events.append(deepcopy(event))
        else:
            dropped += 1
    if dropped:
        logger.warning("professor tracking: dropped %d invalid stored event(s)", dropped)

    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "profiles": profiles,
        "events": events,
    }


def _cap_events_per_professor(events: list[dict]) -> list[dict]:
    """Keep only the newest MAX_EVENTS_PER_PROFESSOR events per professor.

    Events arrive sorted ascending by (verified_at, event_id), so a reverse
    scan sees each professor's newest events first.
    """

    kept_reversed: list[dict] = []
    counts: dict[str, int] = {}
    for event in reversed(events):
        professor_id = event["professor_id"]
        if counts.get(professor_id, 0) >= MAX_EVENTS_PER_PROFESSOR:
            continue
        counts[professor_id] = counts.get(professor_id, 0) + 1
        kept_reversed.append(event)
    kept_reversed.reverse()
    return kept_reversed


def update_tracking_state(
    opportunities: list[dict], previous_state: dict | None = None
) -> dict:
    """Apply verified faculty snapshots to a tracking state.

    Only profile-verified snapshots are stored as baselines — a record that
    was never individually fetched can never participate in an event, so
    persisting it would only grow the artifact.  Missing records are retained
    rather than interpreted as removals: a failed or sharded collector run is
    not proof that a professor disappeared.  A stale changed record likewise
    cannot overwrite the last verified baseline.
    """

    state = _valid_previous_state(previous_state)
    profiles: dict[str, dict] = state["profiles"]
    events: list[dict] = state["events"]
    known_event_ids = {event["event_id"] for event in events}

    current_by_id: dict[str, dict] = {}
    for opportunity in opportunities:
        professor_id = canonical_professor_id(opportunity)
        if professor_id is None:
            continue
        candidate = _snapshot(opportunity, professor_id)
        if not _profile_observation(candidate):
            continue
        existing = current_by_id.get(professor_id)
        if existing is None:
            current_by_id[professor_id] = candidate
            continue
        candidate_time = _parse_verified_at(candidate.get("last_verified"))
        existing_time = _parse_verified_at(existing.get("last_verified"))
        if existing_time is None or (
            candidate_time is not None and candidate_time > existing_time
        ):
            current_by_id[professor_id] = candidate

    for professor_id in sorted(current_by_id):
        current = current_by_id[professor_id]
        previous = profiles.get(professor_id)
        if previous is None:
            profiles[professor_id] = current
            continue

        current_time = _parse_verified_at(current.get("last_verified"))
        previous_time = _parse_verified_at(previous.get("last_verified"))
        content_changed = current.get("content_hash") != previous.get("content_hash")

        if not content_changed:
            if current_time is not None and (
                previous_time is None or current_time > previous_time
            ):
                profiles[professor_id] = current
            continue

        # A changed snapshot that is not strictly newer than the verified
        # baseline is stale replay, not an update.
        if current_time is None or previous_time is None or current_time <= previous_time:
            continue
        if not current.get("source_url"):
            continue

        change_types = _changed_fields(previous, current)
        # Title/organization/name drift updates the baseline but is not a
        # student-facing research/project update on its own.
        if change_types:
            event = _build_event(previous, current, change_types)
            if event["event_id"] not in known_event_ids:
                events.append(event)
                known_event_ids.add(event["event_id"])
        profiles[professor_id] = current

    events.sort(key=lambda event: (event.get("verified_at", ""), event.get("event_id", "")))
    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "profiles": profiles,
        "events": _cap_events_per_professor(events),
    }


def load_tracking_state(path: str | Path) -> dict | None:
    """Best-effort read of a prior artifact; None on any problem."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def update_tracking_file(
    opportunities: list[dict],
    path: str | Path,
    *,
    refresh_ok: bool = False,
    now: datetime | None = None,
) -> dict:
    """Refresh the on-disk tracking artifact from the assembled corpus.

    ``refresh_ok`` is the caller's honest verdict on the producing refresh run
    (refresh_all: no collector reported an error).  It deliberately defaults
    to False — release readiness must be asserted from the run's real recorded
    statuses, never assumed because this function happened to execute.

    Returns run stats for the refresh summary.  Written compact (no indent):
    the artifact is machine-read only and the baseline grows with the
    profile-verified share of the corpus.
    """

    from src.collectors.atomic_json import atomic_write_json

    previous = load_tracking_state(path)
    previous_event_ids: set[str] = set()
    if isinstance(previous, dict) and isinstance(previous.get("events"), list):
        previous_event_ids = {
            event.get("event_id")
            for event in previous["events"]
            if isinstance(event, dict) and isinstance(event.get("event_id"), str)
        }

    state = update_tracking_state(opportunities, previous)
    state["release"] = compute_release_status(
        state["profiles"], state["events"], refresh_ok=refresh_ok, now=now,
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, state, indent=None, separators=(",", ":"))

    new_events = sum(
        1 for event in state["events"] if event["event_id"] not in previous_event_ids
    )
    return {
        "profiles": len(state["profiles"]),
        "events": len(state["events"]),
        "new_events": new_events,
        "release_ready": state["release"]["release_ready"],
        "freshness_pct": state["release"]["freshness_pct"],
        "fully_stale_school_count": state["release"]["fully_stale_school_count"],
    }
