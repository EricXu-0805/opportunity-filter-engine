"""W15 operational-incident queue: read, triage, and detect.

Migration 027 gave operational failures one durable home (``ops_incidents``
plus the append-only ``ops_incident_events``). This module is the only
sanctioned API over it:

* the operator half — list / inspect / mutate incidents behind ADMIN_TOKEN;
* the detector half — ``POST /api/cron/ops-scan``, which reads the artifacts
  the backend already has (collector_status.json, its history JSONL, the
  professor-tracking release block) and upserts through the SECURITY DEFINER
  RPCs.

Two invariants shape everything below and are worth stating once:

1. **A detector never decides.** Every automated write goes through
   ``record_ops_incident`` / ``record_ops_recovery``, which cannot touch
   status, assignment, or resolution (027 §CORE INVARIANT). A later
   successful collector run is *evidence*, not a verdict — only
   ``record_ops_recovery(p_auto_resolve => true)`` closes anything, and drift
   detection deliberately never asks for that.
2. **An operator decision is always recorded.** Mutations are read-then-write
   so the ``from_value`` in the audit trail is the real prior value, not a
   guess, and resolving/suppressing without a resolution is refused rather
   than written as a silent close.

Both tables are service-role only (no RLS policies), so this module holds the
service-role key and is itself gated: ADMIN_TOKEN for the operator routes,
CRON_SECRET for the detector route.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from backend.routes.admin import require_admin
from backend.routes.push import _required_env

router = APIRouter()
logger = logging.getLogger("ofe.ops")

# --- enums, mirrored from 031_ops_incidents.sql ----------------------------
# Validated here so a typo returns 400 with a usable message instead of
# bubbling a Postgres CHECK violation out as a 500.
KINDS = ("collector_failure", "data_drift", "notification_failure", "manual_review")
STATUSES = ("open", "acknowledged", "investigating", "resolved", "suppressed")
PRIORITIES = ("low", "normal", "high", "urgent")
RESOLUTIONS = (
    "auto_recovered", "fixed", "legitimate_change", "wont_fix",
    "duplicate", "not_reproducible", "suppressed",
    "verified", "rejected", "unknown", "conflicting", "needs_more_evidence",
)
TERMINAL_STATUSES = ("resolved", "suppressed")
_NOT_TERMINAL = f"not.in.({','.join(TERMINAL_STATUSES)})"

# Kinds where "try it again" is a meaningful operator action at all.
RETRYABLE_KINDS = ("notification_failure", "collector_failure")

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_LABEL_MAX = 80
_NOTE_MAX = 2000
_DETAIL_TEXT_MAX = 300
_EVENT_LIMIT = 200
_ROLLUP_LIMIT = 1000

# Artifact paths. Deliberately local copies of admin.py's constants rather
# than imports: these are monkeypatched per-test and owning them here keeps
# the detector independent of the admin dashboard module.
_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
_COLLECTOR_STATUS_PATH = _PROCESSED_DIR / "collector_status.json"
_COLLECTOR_HISTORY_PATH = _PROCESSED_DIR / "collector_status_history.jsonl"
_TRACKING_PATH = _PROCESSED_DIR / "professor_tracking.json"

# Drift thresholds. Both must trip: the percentage catches a real collapse,
# the absolute floor stops a 12 -> 7 wobble on a tiny department from paging
# anyone.
_DRIFT_DROP_PCT = 30.0
_DRIFT_MIN_ABSOLUTE_DROP = 20

# professor_tracking.json is ~30 MB and the backend runs on a 2 GB instance;
# json.loads on the whole artifact just to read one small block is a memory
# hazard the detector does not need to take. The release block is the last
# top-level key the writer emits, so a bounded tail read finds it.
_TRACKING_TAIL_BYTES = 65536

_BLOCKED_RE = re.compile(r"\b403\b|forbidden|blocked|challenge", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"timeout|timed[ _-]?out", re.IGNORECASE)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean_label(value: str | None, limit: int = _LABEL_MAX) -> str | None:
    """Collapse whitespace, drop control characters, bound the length."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    cleaned = cleaned[:limit].strip()
    return cleaned or None


def _operator(actor: str) -> str:
    """Narrow admin.require_admin's label for the ops audit trail.

    require_admin already authenticates and sanitizes the self-declared
    X-Admin-Actor header (unverified by design — one shared ADMIN_TOKEN, same
    documented residual as 026). This adds one ops-specific rule: 'detector'
    is the label the RPCs write for automated sightings, so a human must not
    be able to borrow it and make a manual decision look machine-observed.
    """
    return "operator" if (actor or "").strip().lower() == "detector" else (actor or "operator")


def _truncate(value: object, limit: int = _DETAIL_TEXT_MAX) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 1)] + "..."


def _require_uuid(incident_id: str) -> None:
    if not _UUID_RE.match(incident_id or ""):
        raise HTTPException(status_code=400, detail="Invalid incident id")


def _require_enum(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    if value is None:
        return None
    if value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown {field} '{_truncate(value, 40)}' (expected one of: {', '.join(allowed)})",
        )
    return value


def _supabase() -> tuple[str, dict]:
    """Service-role Supabase handle, or 503.

    ops_incidents lives only in Supabase. Returning an empty queue when the
    connection is unconfigured would read as "nothing to do", which is the
    exact silent-empty lie this feature exists to remove — so reads fail
    loudly too.
    """
    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        raise HTTPException(
            status_code=503,
            detail=f"Incident storage not configured (missing: {', '.join(missing)})",
        )
    env = env_result
    return env["SUPABASE_URL"].rstrip("/"), {
        "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
    }


def _verify_cron_secret(secret: str | None) -> None:
    """Constant-time bearer check, mirroring push._verify_cron_secret.

    Copied rather than imported so the ops cron owns its own failure message
    and cannot be silently re-gated by a change to the push cron.
    """
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Ops scan not configured (CRON_SECRET missing)")
    provided = (secret or "").encode("utf-8")
    expected_bytes = f"Bearer {expected}".encode()
    if not hmac.compare_digest(provided, expected_bytes):
        raise HTTPException(status_code=401, detail="Invalid cron secret")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20.0, trust_env=False, follow_redirects=False)


async def _fetch_incident(client, base: str, headers: dict, incident_id: str) -> dict | None:
    resp = await client.get(
        f"{base}/rest/v1/ops_incidents",
        params={"id": f"eq.{incident_id}", "select": "*", "limit": "1"},
        headers=headers,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def _write_events(client, base: str, headers: dict, rows: list[dict]) -> bool:
    """Append audit rows. Returns False (never raises) if the log write fails.

    The caller has already mutated the incident by this point; pretending the
    audit landed would be worse than reporting it didn't, so the response
    carries ``audit_recorded`` rather than a rollback we cannot perform.
    """
    if not rows:
        return True
    try:
        resp = await client.post(
            f"{base}/rest/v1/ops_incident_events",
            headers={**headers, "Prefer": "return=minimal"},
            json=rows,
        )
    except httpx.HTTPError:
        logger.exception("ops: audit event insert failed (transport)")
        return False
    if resp.status_code >= 400:
        logger.error("ops: audit event insert failed (%s)", resp.status_code)
        return False
    return True


# ---------------------------------------------------------------------------
# GET /admin/ops/incidents
# ---------------------------------------------------------------------------

@router.get("/admin/ops/incidents")
async def list_incidents(
    _actor: str = Depends(require_admin),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    unresolved_only: bool = Query(default=False),
    priority: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Operator queue, newest sighting first.

    STATUS FILTERING, stated explicitly because a wrong assumption here shows
    an operator a queue that is quietly missing rows:

    * no ``status`` and no ``unresolved_only`` -> EVERY status is returned,
      resolved and suppressed included. "No filter" means no filter; a
      client's "Any status" option gets exactly that.
    * ``unresolved_only=true`` -> status NOT IN (resolved, suppressed). This
      is the working-queue view, and it needs its own flag because
      "outstanding" is two excluded values, not one selected one.
    * ``status=<one value>`` -> exactly that status. Combining it with
      ``unresolved_only=true`` is a contradiction and returns 400 rather than
      silently letting one win.

    The ``rollup`` block always counts UNRESOLVED incidents regardless of the
    caller's filters, so narrowing the list to one kind (or to closed rows)
    never hides that another kind is on fire.
    """
    _require_enum(kind, KINDS, "kind")
    _require_enum(status, STATUSES, "status")
    _require_enum(priority, PRIORITIES, "priority")
    if unresolved_only and status:
        raise HTTPException(
            status_code=400,
            detail="unresolved_only cannot be combined with an explicit status filter",
        )

    base, headers = _supabase()

    params: dict[str, str] = {
        "select": "*",
        "order": "last_detected_at.desc",
        "limit": str(limit),
    }
    if status:
        params["status"] = f"eq.{status}"
    elif unresolved_only:
        params["status"] = _NOT_TERMINAL
    if kind:
        params["kind"] = f"eq.{kind}"
    if priority:
        params["priority"] = f"eq.{priority}"
    assignee = _clean_label(assigned_to)
    if assignee:
        params["assigned_to"] = f"eq.{assignee}"
    scope_filter = _clean_label(scope)
    if scope_filter:
        params["scope"] = f"eq.{scope_filter}"

    try:
        async with _client() as client:
            resp = await client.get(
                f"{base}/rest/v1/ops_incidents", params=params, headers=headers
            )
            resp.raise_for_status()
            incidents = resp.json()

            rollup_resp = await client.get(
                f"{base}/rest/v1/ops_incidents",
                params={
                    "select": "kind,priority",
                    "status": _NOT_TERMINAL,
                    "limit": str(_ROLLUP_LIMIT),
                },
                headers=headers,
            )
            rollup_resp.raise_for_status()
            open_rows = rollup_resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    open_by_kind = {k: 0 for k in KINDS}
    open_by_priority = {p: 0 for p in PRIORITIES}
    for row in open_rows if isinstance(open_rows, list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("kind") in open_by_kind:
            open_by_kind[row["kind"]] += 1
        if row.get("priority") in open_by_priority:
            open_by_priority[row["priority"]] += 1

    return {
        "status": "ok",
        "incidents": incidents,
        "count": len(incidents) if isinstance(incidents, list) else 0,
        "rollup": {
            "open_by_kind": open_by_kind,
            "open_by_priority": open_by_priority,
            "open_total": sum(open_by_kind.values()),
            # The rollup reads at most _ROLLUP_LIMIT rows; say so rather than
            # letting a capped count masquerade as the true total.
            "truncated": isinstance(open_rows, list) and len(open_rows) >= _ROLLUP_LIMIT,
        },
        "filters": {
            "kind": kind, "status": status, "priority": priority,
            "assigned_to": assignee, "scope": scope_filter, "limit": limit,
            "unresolved_only": unresolved_only,
            # What the caller did NOT see, spelled out: an empty list means
            # this really is every status.
            "excluded_statuses": list(TERMINAL_STATUSES) if unresolved_only else [],
        },
        "generated_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /admin/ops/incidents/{id}
# ---------------------------------------------------------------------------

@router.get("/admin/ops/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    _actor: str = Depends(require_admin),
):
    """One incident plus its full handling history, newest event first."""
    _require_uuid(incident_id)

    base, headers = _supabase()
    try:
        async with _client() as client:
            incident = await _fetch_incident(client, base, headers, incident_id)
            if incident is None:
                raise HTTPException(status_code=404, detail="Incident not found")
            ev_resp = await client.get(
                f"{base}/rest/v1/ops_incident_events",
                params={
                    "incident_id": f"eq.{incident_id}",
                    "select": "*",
                    "order": "created_at.desc",
                    "limit": str(_EVENT_LIMIT),
                },
                headers=headers,
            )
            ev_resp.raise_for_status()
            events = ev_resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e

    return {
        "status": "ok",
        "incident": incident,
        "events": events,
        "event_count": len(events) if isinstance(events, list) else 0,
    }


# ---------------------------------------------------------------------------
# PATCH /admin/ops/incidents/{id}
# ---------------------------------------------------------------------------

class IncidentPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    # "" (or whitespace) means unassign — an explicit hand-back, distinct from
    # omitting the field, which leaves the assignment alone.
    assigned_to: str | None = None
    resolution: str | None = None
    resolution_note: str | None = None


@router.patch("/admin/ops/incidents/{incident_id}")
async def patch_incident(
    incident_id: str,
    body: IncidentPatch,
    actor: str = Depends(require_admin),
):
    """Operator mutation: assign, prioritise, transition, resolve.

    Rules (the same ones the feedback tickets follow):

    * read-then-write, so every event's ``from_value`` is the value that was
      actually there — not what the client believed;
    * resolving or suppressing REQUIRES a resolution (400 otherwise). The DB
      CHECK would refuse it anyway; refusing here turns a 500 into a usable
      error and keeps the audit trail consistent with the row;
    * moving off resolved/suppressed clears the whole decision
      (resolution, note, resolved_by, resolved_at) and logs 'reopened' — a
      reopened incident must not carry a verdict from its previous life;
    * an unknown enum value is a 400, never a Postgres CHECK 500.
    """
    _require_uuid(incident_id)
    actor = _operator(actor)

    new_status = _require_enum(body.status, STATUSES, "status")
    new_priority = _require_enum(body.priority, PRIORITIES, "priority")
    new_resolution = _require_enum(body.resolution, RESOLUTIONS, "resolution")
    new_note = None if body.resolution_note is None else _truncate(body.resolution_note, _NOTE_MAX)
    # None = untouched; "" = explicit unassign.
    assignee_given = body.assigned_to is not None
    new_assignee = _clean_label(body.assigned_to) if assignee_given else None

    base, headers = _supabase()

    async with _client() as client:
        try:
            current = await _fetch_incident(client, base, headers, incident_id)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e
        if current is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        cur_status = current.get("status")
        cur_priority = current.get("priority")
        cur_assignee = current.get("assigned_to")
        cur_resolution = current.get("resolution")
        cur_note = current.get("resolution_note")

        target_status = new_status or cur_status
        reopening = (
            cur_status in TERMINAL_STATUSES
            and new_status is not None
            and new_status not in TERMINAL_STATUSES
        )
        if reopening and new_resolution is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot set a resolution while reopening — reopening clears the decision",
            )

        terminal_target = target_status in TERMINAL_STATUSES
        effective_resolution = None if reopening else (new_resolution or cur_resolution)

        if terminal_target and not effective_resolution:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A resolution is required to resolve or suppress an incident "
                    f"(one of: {', '.join(RESOLUTIONS)})"
                ),
            )
        if new_resolution is not None and not terminal_target:
            raise HTTPException(
                status_code=400,
                detail="resolution can only be set together with status 'resolved' or 'suppressed'",
            )
        if new_note is not None and not terminal_target:
            raise HTTPException(
                status_code=400,
                detail="resolution_note requires a resolution",
            )

        fields: dict[str, Any] = {}
        events: list[dict] = []
        changed: list[str] = []
        now = _now_iso()

        if assignee_given and new_assignee != cur_assignee:
            fields["assigned_to"] = new_assignee
            changed.append("assigned_to")
            events.append({
                "incident_id": incident_id,
                "actor": actor,
                "action": "assigned" if new_assignee else "unassigned",
                "from_value": cur_assignee,
                "to_value": new_assignee,
            })

        if new_priority is not None and new_priority != cur_priority:
            fields["priority"] = new_priority
            changed.append("priority")
            events.append({
                "incident_id": incident_id,
                "actor": actor,
                "action": "priority_changed",
                "from_value": cur_priority,
                "to_value": new_priority,
            })

        status_changed = new_status is not None and new_status != cur_status
        resolution_changed = new_resolution is not None and new_resolution != cur_resolution
        note_changed = new_note is not None and new_note != cur_note

        if status_changed:
            fields["status"] = new_status
            changed.append("status")
        if reopening:
            fields.update({
                "resolution": None, "resolution_note": None,
                "resolved_by": None, "resolved_at": None,
            })
            changed.append("resolution_cleared")
        elif terminal_target and (status_changed or resolution_changed or note_changed):
            # Stamp the decision on every write that establishes or revises it.
            fields["resolution"] = effective_resolution
            if new_note is not None:
                fields["resolution_note"] = new_note
            fields["resolved_by"] = actor
            fields["resolved_at"] = now
            if resolution_changed:
                changed.append("resolution")
            if note_changed:
                changed.append("resolution_note")

        if status_changed:
            if terminal_target:
                action = "resolved"
            elif cur_status in TERMINAL_STATUSES:
                action = "reopened"
            else:
                action = "status_changed"
            events.append({
                "incident_id": incident_id,
                "actor": actor,
                "action": action,
                "from_value": cur_status,
                "to_value": new_status,
                "note": effective_resolution if action == "resolved" else None,
            })
        elif resolution_changed:
            events.append({
                "incident_id": incident_id,
                "actor": actor,
                "action": "resolved",
                "from_value": cur_resolution,
                "to_value": new_resolution,
                "note": new_note,
            })
        elif note_changed:
            events.append({
                "incident_id": incident_id,
                "actor": actor,
                "action": "note_added",
                "to_value": None,
                "note": new_note,
            })

        if not fields:
            return {
                "status": "ok",
                "incident": current,
                "changed": [],
                "events_recorded": 0,
                "audit_recorded": True,
                "note": "no-op: submitted values already match the incident",
            }

        fields["updated_at"] = now
        try:
            patch_resp = await client.patch(
                f"{base}/rest/v1/ops_incidents",
                params={"id": f"eq.{incident_id}"},
                headers={**headers, "Prefer": "return=representation"},
                json=fields,
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e
        if patch_resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Incident update rejected by storage ({patch_resp.status_code})",
            )
        rows = patch_resp.json()
        updated = rows[0] if isinstance(rows, list) and rows else current

        audit_ok = await _write_events(client, base, headers, events)

    return {
        "status": "ok",
        "incident": updated,
        "changed": changed,
        "events_recorded": len(events) if audit_ok else 0,
        # Surfaced rather than swallowed: the mutation landed, so a 5xx would
        # be a lie, but an un-logged operator action must still be visible.
        "audit_recorded": audit_ok,
    }


# ---------------------------------------------------------------------------
# POST /admin/ops/incidents/{id}/retry
# ---------------------------------------------------------------------------

class RetryRequest(BaseModel):
    note: str | None = None


@router.post("/admin/ops/incidents/{incident_id}/retry")
async def retry_incident(
    incident_id: str,
    body: RetryRequest | None = None,
    actor: str = Depends(require_admin),
):
    """Record an operator-initiated retry ATTEMPT. Nothing more.

    This endpoint bumps ``attempt_count``/``last_attempt_at``, logs a
    'retried' event, and moves an untriaged incident to 'investigating'.

    It deliberately does NOT:

    * re-send the notification or re-run the collector itself — the next cron
      run does the work; this only records that an operator asked for it;
    * claim delivery, success, or recovery. ``failure_state`` stays where it
      was, ``last_success_at`` is untouched, and only a detector that
      observes a real successful run (``record_ops_recovery``) may say
      otherwise;
    * resolve the incident. An attempt is not an outcome — the response
      returns ``delivery_claimed: false`` and ``resolved: false`` so a UI
      cannot render "retried" as "fixed".
    """
    _require_uuid(incident_id)
    actor = _operator(actor)
    note = _truncate(body.note, _NOTE_MAX) if (body and body.note) else None

    base, headers = _supabase()

    async with _client() as client:
        try:
            current = await _fetch_incident(client, base, headers, incident_id)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e
        if current is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        kind = current.get("kind")
        if kind not in RETRYABLE_KINDS:
            raise HTTPException(
                status_code=400,
                detail=f"Retry is only meaningful for {', '.join(RETRYABLE_KINDS)} incidents (this is '{kind}')",
            )
        if current.get("status") in TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Incident is {current.get('status')} — reopen it before retrying",
            )

        now = _now_iso()
        attempts = current.get("attempt_count")
        attempts = (attempts if isinstance(attempts, int) else 0) + 1
        fields: dict[str, Any] = {
            "attempt_count": attempts,
            "last_attempt_at": now,
            "updated_at": now,
        }
        # An open incident someone is actively retrying is being investigated;
        # an already-acknowledged/investigating one keeps its state.
        promoted = current.get("status") == "open"
        if promoted:
            fields["status"] = "investigating"

        try:
            patch_resp = await client.patch(
                f"{base}/rest/v1/ops_incidents",
                params={"id": f"eq.{incident_id}"},
                headers={**headers, "Prefer": "return=representation"},
                json=fields,
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Supabase unreachable: {e}") from e
        if patch_resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Retry bookkeeping rejected by storage ({patch_resp.status_code})",
            )
        rows = patch_resp.json()
        updated = rows[0] if isinstance(rows, list) and rows else current

        events = [{
            "incident_id": incident_id,
            "actor": actor,
            "action": "retried",
            "from_value": current.get("status"),
            "to_value": "investigating" if promoted else current.get("status"),
            "note": note or f"attempt {attempts} requested by operator",
        }]
        audit_ok = await _write_events(client, base, headers, events)

    return {
        "status": "ok",
        "incident": updated,
        "attempt_count": attempts,
        "delivery_claimed": False,
        "resolved": False,
        "audit_recorded": audit_ok,
        "note": (
            "Attempt recorded. The retry itself happens on the next scheduled run; "
            "this endpoint never claims delivery, recovery, or resolution."
        ),
    }


# ---------------------------------------------------------------------------
# Detector: POST /api/cron/ops-scan
# ---------------------------------------------------------------------------

class _Recorder:
    """The detector's only write path.

    Every call goes through the SECURITY DEFINER RPCs, which by construction
    cannot change status, assignment, or resolution — a detector observes,
    it does not decide. Failures are counted, never raised: a scan that can't
    reach Supabase should report what it couldn't do, not 500 at the
    scheduler.
    """

    def __init__(self, client, base: str, headers: dict):
        self._client = client
        self._base = base
        self._headers = headers
        self.opened = 0
        self.recovered = 0
        self.opened_keys: list[str] = []
        self.errors: list[dict] = []

    async def _rpc(self, fn: str, payload: dict) -> tuple[bool, Any]:
        try:
            resp = await self._client.post(
                f"{self._base}/rest/v1/rpc/{fn}", headers=self._headers, json=payload
            )
        except Exception as e:  # transport, stub mismatch, anything
            logger.exception("ops-scan: %s transport failure", fn)
            self.errors.append({"rpc": fn, "error": _truncate(f"{type(e).__name__}: {e}", 120)})
            return False, None
        if getattr(resp, "status_code", 500) >= 400:
            self.errors.append({"rpc": fn, "status": resp.status_code})
            logger.error("ops-scan: %s rejected (%s)", fn, resp.status_code)
            return False, None
        try:
            return True, resp.json()
        except Exception:
            return True, None

    async def record(
        self, *, kind: str, dedup_key: str, title: str, summary: str | None = None,
        detail: dict | None = None, scope: str | None = None, priority: str = "normal",
        failure_state: str | None = None, entity_type: str | None = None,
        entity_id: str | None = None, field: str | None = None,
    ) -> bool:
        ok, _ = await self._rpc("record_ops_incident", {
            "p_kind": kind,
            "p_dedup_key": dedup_key,
            "p_title": _truncate(title, 200),
            "p_summary": _truncate(summary, 400) if summary else None,
            "p_detail": detail or {},
            "p_scope": scope,
            "p_priority": priority,
            "p_failure_state": failure_state,
            "p_entity_type": entity_type,
            "p_entity_id": entity_id,
            "p_field": field,
        })
        if ok:
            self.opened += 1
            if len(self.opened_keys) < 50:
                self.opened_keys.append(dedup_key)
        return ok

    async def recover(self, dedup_key: str, *, auto_resolve: bool, note: str | None = None) -> bool:
        ok, result = await self._rpc("record_ops_recovery", {
            "p_dedup_key": dedup_key,
            "p_auto_resolve": auto_resolve,
            "p_note": note,
        })
        # The RPC returns false when there was no live incident to recover;
        # counting that as a recovery would inflate the summary.
        if ok and result is not False:
            self.recovered += 1
        return ok

    async def open_keys(self, kinds: tuple[str, ...]) -> set[str]:
        """dedup_keys with a live (non-terminal) incident.

        Lets the scan skip a recovery RPC for the ~hundred sources that are
        simply fine and have never failed.
        """
        try:
            resp = await self._client.get(
                f"{self._base}/rest/v1/ops_incidents",
                params={
                    "select": "dedup_key",
                    "kind": f"in.({','.join(kinds)})",
                    "status": _NOT_TERMINAL,
                    "limit": str(_ROLLUP_LIMIT),
                },
                headers=self._headers,
            )
            rows = resp.json()
        except Exception:
            logger.exception("ops-scan: open-incident prefetch failed")
            return set()
        if not isinstance(rows, list):
            return set()
        return {
            row["dedup_key"] for row in rows
            if isinstance(row, dict) and isinstance(row.get("dedup_key"), str)
        }


# ---------------------------------------------------------------------------
# Detector: is the in-database dead man's switch itself alive?
# ---------------------------------------------------------------------------
# Migration 032 gives every scheduled workflow a heartbeat and has pg_cron
# sweep them every ten minutes. That covers "GitHub stopped running things".
# It cannot cover "pg_cron stopped running things" — a sweep that never fires
# also never notices that it never fired. So the watch is mutual: the sweep
# records its own heartbeat, and this detector, which runs from GitHub, is
# what reads it. Neither side can go quiet without the other filing.
#
# The two directions have different resolutions on purpose: the sweep catches
# a dead scheduler within its grace window, this catches a dead sweeper within
# one day, because that is this cron's period and inventing a tighter claim
# would be a number we cannot back.
_SWEEP_HEARTBEAT = "ops_dead_man_sweep"


# PostgREST's two "that object is not in the schema cache" codes: PGRST202
# for an undefined routine, PGRST205 for an undefined table or view. Both mean
# migration 032 has not been applied here. Matching the codes rather than the
# bare 404 keeps a genuine not-found loud.
_SCHEMA_MISSING_CODES = frozenset({"PGRST202", "PGRST205"})


def _schema_object_missing(resp) -> bool:
    if getattr(resp, "status_code", None) != 404:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    return isinstance(body, dict) and str(body.get("code", "")).upper() in _SCHEMA_MISSING_CODES


def _parse_ts(value: object) -> datetime | None:
    """Parse a PostgREST timestamptz. Returns None rather than raising."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _scan_dead_man(rec: _Recorder, summary: dict, client, base: str, headers: dict) -> None:
    dedup_key = f"dead_man:{_SWEEP_HEARTBEAT}"
    try:
        resp = await client.get(
            f"{base}/rest/v1/ops_heartbeat_status",
            params={
                "name": f"eq.{_SWEEP_HEARTBEAT}",
                "select": "name,description,last_seen_at,due_at,overdue,seen_count",
                "limit": "1",
            },
            headers=headers,
        )
        # The view being absent is the same fact as the row being absent —
        # migration 032 has not reached this database — so it takes the same
        # path below rather than a quiet skip. The check-in route's one
        # tolerant answer is only defensible because this fires.
        rows = [] if _schema_object_missing(resp) else (
            resp.json() if resp.status_code < 400 else None
        )
    except Exception as e:
        summary["skipped"].append({
            "detector": "dead_man",
            "reason": _truncate(f"heartbeat read failed: {type(e).__name__}", 120),
        })
        return
    if not isinstance(rows, list):
        summary["skipped"].append({"detector": "dead_man", "reason": "heartbeat read rejected"})
        return

    summary["scanned"] += 1

    # No row at all means migration 032 has not reached this database. That is
    # not "nothing to report" — it means nothing is watching the schedulers.
    if not rows:
        await rec.record(
            kind="collector_failure", dedup_key=dedup_key,
            title="Dead man's switch is not installed",
            summary=("ops_heartbeat_status has no row for the sweep: migration 032 has not been "
                     "applied to this database, so no scheduler is being watched."),
            detail={"heartbeat": _SWEEP_HEARTBEAT, "detected_by": "ops-scan"},
            scope=_SWEEP_HEARTBEAT, priority="urgent", failure_state="blocked",
        )
        summary["detectors"]["dead_man"] = {"installed": False}
        return

    row = rows[0] if isinstance(rows[0], dict) else {}
    due = _parse_ts(row.get("due_at"))
    last_seen = _parse_ts(row.get("last_seen_at"))
    now = datetime.now(UTC)

    # The view's own verdict wins: it is the single definition of "overdue"
    # and it is evaluated against the database's clock rather than this
    # instance's, so a skewed Render container cannot invent or hide an
    # outage. Falling back to our own comparison is a degradation worth
    # naming rather than a silent equivalent.
    clock = "database"
    if isinstance(row.get("overdue"), bool):
        overdue = row["overdue"]
    else:
        clock = "backend"
        overdue = due is None or now > due

    summary["detectors"]["dead_man"] = {
        "installed": True,
        "last_seen_at": row.get("last_seen_at"),
        "due_at": row.get("due_at"),
        "seen_count": row.get("seen_count"),
        "overdue": overdue,
        "judged_by_clock": clock,
    }

    if overdue:
        late = int((now - due).total_seconds()) if due else None
        await rec.record(
            kind="collector_failure", dedup_key=dedup_key,
            title="Dead man's switch has stopped sweeping",
            summary=("pg_cron is no longer running ops_dead_man_sweep — last check-in "
                     f"{row.get('last_seen_at') or 'never'}. Nothing is watching the "
                     "scheduled workflows until it is rescheduled."),
            detail={
                "heartbeat": _SWEEP_HEARTBEAT,
                "last_seen_at": row.get("last_seen_at"),
                "due_at": row.get("due_at"),
                "overdue_seconds": late,
                "seen_count": row.get("seen_count"),
                "detected_by": "ops-scan",
            },
            scope=_SWEEP_HEARTBEAT, priority="urgent",
            failure_state="blocked" if last_seen is None else "failed",
        )
    elif dedup_key in summary.get("_open_keys", ()):
        await rec.recover(
            dedup_key, auto_resolve=True,
            note=f"sweep heartbeat received at {row.get('last_seen_at')}",
        )


def _read_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, "artifact not present"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, json.JSONDecodeError) as e:
        return None, f"unreadable ({type(e).__name__})"


def _read_release_block(path: Path) -> tuple[dict | None, str | None]:
    """Extract professor_tracking.json's ``release`` block via a tail read.

    See _TRACKING_TAIL_BYTES: parsing the whole 30 MB artifact to read five
    booleans would be the biggest allocation this process makes all day. The
    block is the last top-level key the writer emits, so scanning the tail
    finds it; if it doesn't (v1 artifact, unexpected layout), the detector
    reports that it could not check instead of guessing.
    """
    if not path.exists():
        return None, "artifact not present"
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > _TRACKING_TAIL_BYTES:
                f.seek(-_TRACKING_TAIL_BYTES, os.SEEK_END)
            chunk = f.read()
    except OSError as e:
        return None, f"unreadable ({type(e).__name__})"

    text = chunk.decode("utf-8", errors="ignore")
    marker = text.rfind('"release"')
    if marker == -1:
        return None, "no release block in artifact tail (pre-v2 artifact?)"
    start = text.find("{", marker)
    if start == -1:
        return None, "malformed release block"
    try:
        block, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None, "release block did not parse"
    if not isinstance(block, dict):
        return None, "release block is not an object"
    return block, None


def _classify_failure_state(error_text: str) -> str:
    if _BLOCKED_RE.search(error_text):
        return "blocked"
    if _TIMEOUT_RE.search(error_text):
        return "timed_out"
    return "failed"


def _previous_fetched(history_path: Path, current_timestamp: object) -> tuple[dict[str, int], str | None]:
    """Per-source ``fetched`` from the most recent PRIOR history entry.

    write_status appends the current run to the history file, so the last
    line is this snapshot — comparing against it would always show zero
    change. Entries carrying the snapshot's timestamp are therefore skipped,
    and each source takes its value from the newest older entry that has one
    (a source missing from one run still has a real baseline).
    """
    if not history_path.exists():
        return {}, "history not present"
    try:
        with history_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return {}, f"history unreadable ({type(e).__name__})"

    previous: dict[str, int] = {}
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if current_timestamp and entry.get("t") == current_timestamp:
            continue  # this run's own row
        sources = entry.get("sources")
        if not isinstance(sources, dict):
            continue
        for name, info in sources.items():
            if name in previous or not isinstance(info, dict):
                continue
            fetched = info.get("fetched")
            if isinstance(fetched, bool) or not isinstance(fetched, int):
                continue
            previous[name] = fetched
    if not previous:
        return {}, "no prior history entry with per-source counts"
    return previous, None


async def _scan_collectors(rec: _Recorder, summary: dict) -> dict | None:
    """collector_status.json -> collector_failure incidents + recoveries."""
    payload, err = _read_json(_COLLECTOR_STATUS_PATH)
    if err or not isinstance(payload, dict):
        summary["skipped"].append({
            "detector": "collector_failure",
            "reason": err or "snapshot is not an object",
        })
        return None

    run_ts = payload.get("timestamp")
    sources = payload.get("sources")
    sources = sources if isinstance(sources, dict) else {}

    fatal = payload.get("fatal_error")
    if fatal:
        summary["scanned"] += 1
        await rec.record(
            kind="collector_failure",
            dedup_key="collector_failure:refresh_run",
            title="Refresh run aborted before completion",
            summary=_truncate(fatal, 200),
            detail={
                "error": _truncate(fatal),
                "run_timestamp": run_ts,
                "sources_in_snapshot": len(sources),
            },
            scope="refresh_all",
            priority="urgent",
            failure_state=_classify_failure_state(str(fatal)),
        )
    else:
        # A completed run is evidence the aborted-run incident is over, but a
        # human still closes it: auto_resolve stays off for run-level failures.
        if "collector_failure:refresh_run" in summary["_open_keys"]:
            await rec.recover(
                "collector_failure:refresh_run",
                auto_resolve=False,
                note="a later refresh run completed without a fatal error",
            )

    errored, ok_sources = 0, 0
    for name, info in sorted(sources.items()):
        if not isinstance(info, dict):
            continue
        summary["scanned"] += 1
        state = info.get("status")
        dedup_key = f"collector_failure:{name}"
        if state == "error":
            errored += 1
            error_text = _truncate(info.get("error") or "collector reported an error")
            await rec.record(
                kind="collector_failure",
                dedup_key=dedup_key,
                title=f"Collector '{name}' failed",
                summary=error_text,
                detail={
                    "error": error_text,
                    "fetched": info.get("fetched"),
                    "run_timestamp": run_ts,
                },
                scope=name,
                priority="high" if not info.get("fetched") else "normal",
                failure_state=_classify_failure_state(error_text),
            )
        elif state == "ok":
            ok_sources += 1
            # Verified successful run: the ONE place auto-resolve is honest,
            # because the evidence is exactly "this collector ran clean".
            if dedup_key in summary["_open_keys"]:
                await rec.recover(
                    dedup_key, auto_resolve=True, note="verified successful run",
                )

    age = _snapshot_age(run_ts)
    summary["detectors"]["collector_failure"] = {
        "sources": len(sources),
        "errored": errored,
        "ok": ok_sources,
        "fatal_error": bool(fatal),
        "run_timestamp": run_ts,
        **age,
    }
    await _report_snapshot_age(rec, summary, age, run_ts, len(sources))
    return payload


# How old the snapshot may be before scanning it is scanning yesterday.
# The refresh runs daily at 06:00 UTC, so anything past ~a day and a half
# means this scan did not see the most recent run at all.
_SNAPSHOT_STALE_HOURS = 36.0


def _snapshot_age(run_ts: object) -> dict:
    """Report how old the evidence is, and say so when it is too old.

    The detector reads ``collector_status.json`` from its own checkout, and
    that file only reaches main when the refresh's auto-merged PR lands —
    hours after the refresh starts. On 2026-08-14 the 07:30 scan read
    YESTERDAY's snapshot (13 sources) and reported one finding, while a
    12:19 run over the same day's real snapshot (51 sources) opened ten:
    every degraded jhu, princeton and stanford source. A scan that reads
    stale evidence does not report less confidently, it reports clean.

    Retiming the cron narrows the window; only this makes the miss visible
    when the retiming is wrong again.
    """
    parsed = _parse_ts(run_ts)
    if parsed is None:
        return {"snapshot_age_hours": None, "snapshot_stale": None}
    age = (datetime.now(UTC) - parsed).total_seconds() / 3600.0
    return {
        "snapshot_age_hours": round(age, 1),
        "snapshot_stale": age > _SNAPSHOT_STALE_HOURS,
    }


_STALE_SNAPSHOT_KEY = "collector_failure:ops_scan:stale_snapshot"


async def _report_snapshot_age(
    rec: _Recorder, summary: dict, age: dict, run_ts: object, sources: int
) -> None:
    """Make "this scan judged yesterday" durable, not just printed.

    It goes in ops_incidents rather than the response body because the
    response is read once by a workflow step and thrown away, while the whole
    point is that nobody was watching. Recovery auto-resolves: a fresh
    timestamp is complete evidence, unlike drift.
    """
    if age.get("snapshot_stale") is not True:
        if _STALE_SNAPSHOT_KEY in summary["_open_keys"]:
            await rec.recover(
                _STALE_SNAPSHOT_KEY, auto_resolve=True,
                note=f"snapshot is {age.get('snapshot_age_hours')}h old",
            )
        return
    summary["scanned"] += 1
    await rec.record(
        kind="collector_failure", dedup_key=_STALE_SNAPSHOT_KEY,
        title="Ops scan is reading a stale collector snapshot",
        summary=(f"collector_status.json is {age['snapshot_age_hours']}h old "
                 f"({sources} sources). This scan judged an earlier run, so a "
                 "clean result here says nothing about the most recent one."),
        detail={
            "run_timestamp": run_ts,
            "sources_in_snapshot": sources,
            "detected_by": "ops-scan",
            **age,
            "stale_after_hours": _SNAPSHOT_STALE_HOURS,
        },
        scope="ops_scan", priority="high", failure_state="partial",
    )


async def _scan_drift(rec: _Recorder, summary: dict, payload: dict | None) -> None:
    """Per-source ``fetched`` collapse vs the previous run -> data_drift.

    NOTE the asymmetry with collector failures: drift NEVER auto-resolves. A
    later run fetching a normal count does not prove the missing records came
    back (the source may simply have shrunk permanently), so 027 §17 requires
    a human to accept the change or the data to be restored. This detector
    therefore calls record_ops_recovery for drift not at all.
    """
    if payload is None:
        summary["skipped"].append({"detector": "data_drift", "reason": "no collector snapshot"})
        return
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        summary["skipped"].append({"detector": "data_drift", "reason": "snapshot has no sources"})
        return

    previous, err = _previous_fetched(_COLLECTOR_HISTORY_PATH, payload.get("timestamp"))
    if err:
        summary["skipped"].append({"detector": "data_drift", "reason": err})
        return

    compared, drifted = 0, 0
    for name, info in sorted(sources.items()):
        if not isinstance(info, dict):
            continue
        current = info.get("fetched")
        prior = previous.get(name)
        if isinstance(current, bool) or not isinstance(current, int):
            continue
        if not isinstance(prior, int) or prior <= 0:
            continue
        compared += 1
        drop = prior - current
        if drop < _DRIFT_MIN_ABSOLUTE_DROP:
            continue
        drop_pct = (drop / prior) * 100
        if drop_pct <= _DRIFT_DROP_PCT:
            continue
        drifted += 1
        summary["scanned"] += 1
        await rec.record(
            kind="data_drift",
            dedup_key=f"data_drift:{name}:fetched",
            title=f"'{name}' fetched {prior} -> {current} ({drop_pct:.0f}% drop)",
            summary=f"fetched dropped by {drop} records ({drop_pct:.0f}%) versus the previous run",
            detail={
                "metric": "fetched",
                "previous": prior,
                "current": current,
                "change_pct": round(-drop_pct, 1),
                "threshold_pct": -_DRIFT_DROP_PCT,
                "min_absolute_drop": _DRIFT_MIN_ABSOLUTE_DROP,
                "run_timestamp": payload.get("timestamp"),
            },
            scope=name,
            field="fetched",
            priority="high",
        )

    summary["detectors"]["data_drift"] = {
        "compared": compared,
        "drifted": drifted,
        "threshold_pct": -_DRIFT_DROP_PCT,
        "auto_resolve": False,
    }


_DEGRADATION_TITLES = {
    "dark_crawl": "loaded no live page at all",
    "crawl_sources_unreached": "could not reach every crawl source",
    "seed_pages_unreached": "could not load every configured seed page",
    "crawl_errors": "reported crawl errors",
    "time_budget": "stopped at the run time budget",
}


async def _scan_release_degradation(
    rec: _Recorder, summary: dict, payload: dict | None
) -> None:
    """release.degradations -> one tracked incident per coverage gap.

    The release contract stopped vetoing publication over a host it could
    not reach, because refusing to publish protected nothing — the merge
    layers already preserve everything behind an incomplete crawl. What that
    left behind was a gap visible only as prose in a run log. These are the
    same facts, keyed, so a school that has gone dark stays on the operator's
    queue until someone looks at it.

    Recovery needs the source to have actually run clean: a Monday shard
    says nothing about Michigan, so absence alone never closes an incident.
    """
    if not isinstance(payload, dict):
        summary["skipped"].append({
            "detector": "release_degradation",
            "reason": "no collector snapshot",
        })
        return

    release = payload.get("release")
    if not isinstance(release, dict) or "degradations" not in release:
        summary["skipped"].append({
            "detector": "release_degradation",
            "reason": "snapshot predates release.degradations",
        })
        return

    degradations = release.get("degradations")
    degradations = degradations if isinstance(degradations, list) else []
    sources = payload.get("sources")
    sources = sources if isinstance(sources, dict) else {}
    run_ts = payload.get("timestamp")

    seen_keys: set[str] = set()
    for item in degradations:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "unknown")
        source = str(item.get("source") or "unknown")
        dedup_key = f"collector_failure:degraded:{kind}:{source}"
        seen_keys.add(dedup_key)
        summary["scanned"] += 1
        await rec.record(
            kind="collector_failure",
            dedup_key=dedup_key,
            title=f"'{source}' {_DEGRADATION_TITLES.get(kind, kind)}",
            summary=_truncate(str(item.get("detail") or kind), 200),
            detail={
                "degradation": kind,
                "detail": _truncate(str(item.get("detail") or "")),
                "run_timestamp": run_ts,
                "published": release.get("ready") is True,
            },
            scope=source,
            priority="high" if kind == "dark_crawl" else "normal",
        )

    recovered = 0
    prefix = "collector_failure:degraded:"
    for dedup_key in summary["_open_keys"]:
        if not dedup_key.startswith(prefix) or dedup_key in seen_keys:
            continue
        # kind never contains a colon; source does ("campus_graph:umich").
        _kind, _, source = dedup_key[len(prefix):].partition(":")
        info = sources.get(source)
        if not isinstance(info, dict) or info.get("status") != "ok":
            # Out of this run's shard, or it failed outright. Either way this
            # run is not evidence the gap closed.
            continue
        recovered += 1
        await rec.recover(
            dedup_key,
            auto_resolve=True,
            note="a later run exercised this source with no degradation",
        )

    summary["detectors"]["release_degradation"] = {
        "degradations": len(degradations),
        "recovered": recovered,
        "release_ready": release.get("ready"),
        "run_timestamp": run_ts,
    }


async def _scan_professor_tracking(rec: _Recorder, summary: dict) -> None:
    """professor_tracking.json release gate -> data_drift incident."""
    block, err = _read_release_block(_TRACKING_PATH)
    if err or block is None:
        summary["skipped"].append({"detector": "professor_tracking", "reason": err})
        return

    summary["scanned"] += 1
    dedup_key = "data_drift:professor_tracking:release_ready"
    checks = block.get("checks") if isinstance(block.get("checks"), dict) else {}
    failing = sorted(k for k, v in checks.items() if v is not True)
    ready = block.get("release_ready") is True

    if not ready:
        await rec.record(
            kind="data_drift",
            dedup_key=dedup_key,
            title="Professor tracking is not release-ready",
            summary=(
                f"failing checks: {', '.join(failing)}" if failing
                else "release_ready is false"
            ),
            detail={
                "metric": "release_ready",
                "current": False,
                "failing_checks": failing,
                "freshness_pct": block.get("freshness_pct"),
                "freshness_min_pct": block.get("freshness_min_pct"),
                "fresh_profiles": block.get("fresh_profiles"),
                "total_profiles": block.get("total_profiles"),
                "fully_stale_school_count": block.get("fully_stale_school_count"),
                "fully_stale_schools": (block.get("fully_stale_schools") or [])[:20],
                "computed_at": block.get("computed_at"),
            },
            scope="professor_tracking",
            field="release_ready",
            priority="high",
        )
    elif dedup_key in summary["_open_keys"]:
        # Evidence only: a passing gate does not retroactively vouch for what
        # shipped while it was failing, so a human confirms the close.
        await rec.recover(
            dedup_key,
            auto_resolve=False,
            note="release_ready is true again — confirm the gap was reviewed before closing",
        )

    summary["detectors"]["professor_tracking"] = {
        "release_ready": ready,
        "failing_checks": failing,
        "computed_at": block.get("computed_at"),
    }


@router.post("/cron/ops-scan")
async def ops_scan(authorization: str | None = Header(default=None)):
    """Detector entry point: turn the run artifacts into durable incidents.

    Invoked by the same external scheduler as the other crons and guarded by
    CRON_SECRET. Reads only artifacts the backend already has on disk, then
    upserts through the RPCs.

    Defensive by construction: a missing or unreadable artifact skips that
    detector and is reported in ``skipped``; an RPC failure is counted in
    ``errors``. The scan never 500s, because a monitoring job that pages on
    its own failure is one more thing to monitor.

    Summary semantics: ``scanned`` is the number of checks performed,
    ``opened`` the number of incidents RECORDED — new rows and re-sightings
    alike, since the upsert is idempotent by dedup_key and a recurrence is
    not a second incident — and ``recovered`` the number of live incidents a
    verified success was recorded against.
    """
    _verify_cron_secret(authorization)

    env_result = _required_env(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if isinstance(env_result, tuple):
        _, missing = env_result
        return {"status": "skipped", "reason": "supabase env not configured", "missing": missing}

    base, headers = _supabase()
    summary: dict[str, Any] = {
        "status": "ok",
        "scanned": 0,
        "opened": 0,
        "recovered": 0,
        "skipped": [],
        "errors": [],
        "detectors": {},
        "_open_keys": set(),
    }

    async with _client() as client:
        rec = _Recorder(client, base, headers)
        summary["_open_keys"] = await rec.open_keys(("collector_failure", "data_drift"))

        # Each detector is independently fenced: one crashing artifact must
        # not cost the operator the other two detectors' findings.
        try:
            payload = await _scan_collectors(rec, summary)
        except Exception as e:
            logger.exception("ops-scan: collector_failure detector crashed")
            summary["errors"].append({
                "detector": "collector_failure",
                "error": _truncate(f"{type(e).__name__}: {e}", 120),
            })
            payload = None

        try:
            await _scan_drift(rec, summary, payload)
        except Exception as e:
            logger.exception("ops-scan: data_drift detector crashed")
            summary["errors"].append({"detector": "data_drift", "error": _truncate(f"{type(e).__name__}: {e}", 120)})

        try:
            await _scan_release_degradation(rec, summary, payload)
        except Exception as e:
            logger.exception("ops-scan: release_degradation detector crashed")
            summary["errors"].append({
                "detector": "release_degradation",
                "error": _truncate(f"{type(e).__name__}: {e}", 120),
            })

        try:
            await _scan_professor_tracking(rec, summary)
        except Exception as e:
            logger.exception("ops-scan: professor_tracking detector crashed")
            summary["errors"].append({
                "detector": "professor_tracking",
                "error": _truncate(f"{type(e).__name__}: {e}", 120),
            })

        try:
            await _scan_dead_man(rec, summary, client, base, headers)
        except Exception as e:
            logger.exception("ops-scan: dead_man detector crashed")
            summary["errors"].append({
                "detector": "dead_man",
                "error": _truncate(f"{type(e).__name__}: {e}", 120),
            })

        summary["opened"] = rec.opened
        summary["recovered"] = rec.recovered
        summary["opened_keys"] = rec.opened_keys
        summary["errors"].extend(rec.errors)

    summary.pop("_open_keys", None)
    summary["checked_at"] = _now_iso()
    return summary


class HeartbeatIn(BaseModel):
    name: str
    detail: dict[str, Any] | None = None


@router.post("/cron/heartbeat")
async def cron_heartbeat(body: HeartbeatIn, authorization: str | None = Header(default=None)):
    """A scheduled job proving it is still alive.

    Called as the last step of every scheduled workflow, guarded by the same
    CRON_SECRET as the other crons. The sweep in migration 032 turns the
    absence of these calls into an incident; this route's only job is to make
    the call impossible to fake and impossible to lose.

    Two deliberate loudnesses:

    * An unknown name is 404, not an insert. The registry is the contract —
      a typo must fail the workflow step rather than create a fresh row that
      nobody watches while the real heartbeat stays overdue.
    * A storage failure is 502, not a swallowed warning. If the check-in did
      not land, the caller has to see it now; the alternative is a workflow
      that reports success while the sweep counts it as dead in six hours.

    And exactly one deliberate quiet, which is not the same thing: if
    migration 032 has not been applied yet, the RPC does not exist and this
    returns 200 ``not_installed``. That state is real and it is already
    reported — ``_scan_dead_man`` files an urgent incident for it every day,
    and it is a fact about the monitor, not about the job being monitored.
    Failing here on top of that adds no information and costs a three-hour
    data refresh over a check-in. Anything else the storage says is still a
    502.
    """
    _verify_cron_secret(authorization)
    name = _clean_label(body.name, 120)
    if not name:
        raise HTTPException(status_code=400, detail="heartbeat name is required")

    base, headers = _supabase()
    async with _client() as client:
        try:
            resp = await client.post(
                f"{base}/rest/v1/rpc/record_ops_heartbeat",
                headers=headers,
                json={"p_name": name, "p_detail": body.detail or {}},
            )
        except Exception as e:
            logger.exception("heartbeat: transport failure for %s", name)
            raise HTTPException(
                status_code=502,
                detail=f"heartbeat storage unreachable ({type(e).__name__})",
            ) from e
        if _schema_object_missing(resp):
            logger.warning("heartbeat: record_ops_heartbeat absent (migration 032 unapplied)")
            return {
                "status": "not_installed",
                "heartbeat": name,
                "detail": "migration 032 has not been applied to this database; "
                          "ops-scan reports this as an urgent incident",
                "checked_at": _now_iso(),
            }
        if resp.status_code >= 400:
            logger.error("heartbeat: storage rejected %s (%s)", name, resp.status_code)
            raise HTTPException(
                status_code=502,
                detail=f"heartbeat storage rejected the write ({resp.status_code})",
            )
        recorded = resp.json()

    if recorded is not True:
        raise HTTPException(
            status_code=404,
            detail=f"unknown heartbeat '{name}': register it in ops_heartbeats first",
        )
    return {"status": "ok", "heartbeat": name, "recorded_at": _now_iso()}
