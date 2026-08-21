"""W15 operational-incident boundary — backend contract locks.

The invariants this file exists to defend, all of them things the system got
wrong before migration 027 gave operational failures one durable home:

    detection            -> never decides (no status/assignment/resolution)
    a later good run     -> closes a collector failure, NEVER a drift alert
    resolve / suppress   -> requires a recorded decision, no silent closes
    reopen               -> clears the old verdict rather than inheriting it
    every mutation       -> an audit row with the real prior value + an actor
    retry                -> records an ATTEMPT; never delivery, never a fix
    a missing artifact   -> a reported skip, never a 500 from the monitor
    a silent scheduler   -> an incident, because absence has no log line

Supabase is stubbed exactly as tests/test_backend_api.py stubs it for the
admin routes: swap ``ops.httpx.AsyncClient`` for a recorder that answers
PostgREST-shaped requests from in-test fixtures. Nothing here touches a real
project, and no test asserts on a value the route did not have to compute.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import ops as ops_mod

client = TestClient(app)

INCIDENT_ID = "11111111-2222-3333-4444-555555555555"
REPO = Path(__file__).resolve().parents[1]


def _heartbeat(name: str = "ops_dead_man_sweep", *, overdue_seconds: int | None = None,
               never_seen: bool = False) -> dict:
    """A heartbeat row as PostgREST would return it.

    ``due_at`` is a generated column in migration 032, so the stub computes it
    the same way the database does rather than letting a test invent a
    deadline the schema would never produce.
    """
    now = datetime.now(UTC)
    if never_seen:
        last_seen, due = None, now - timedelta(seconds=1)
    elif overdue_seconds is not None:
        last_seen = now - timedelta(seconds=2400 + overdue_seconds)
        due = last_seen + timedelta(seconds=2400)
    else:
        last_seen = now - timedelta(minutes=2)
        due = last_seen + timedelta(seconds=2400)
    return {
        "name": name,
        "description": "the dead-man sweep itself",
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "due_at": due.isoformat(),
        "overdue": now > due,
        "seen_count": 0 if never_seen else 144,
    }


def _incident(**overrides) -> dict:
    row = {
        "id": INCIDENT_ID,
        "kind": "collector_failure",
        "dedup_key": "collector_failure:uiuc_faculty",
        "scope": "uiuc_faculty",
        "entity_type": None,
        "entity_id": None,
        "field": None,
        "title": "Collector 'uiuc_faculty' failed",
        "summary": "403 Forbidden",
        "detail": {"error": "403 Forbidden"},
        "priority": "normal",
        "status": "open",
        "failure_state": "blocked",
        "assigned_to": None,
        "occurrence_count": 3,
        "attempt_count": 0,
        "last_attempt_at": None,
        "resolution": None,
        "resolution_note": None,
        "resolved_by": None,
        "resolved_at": None,
    }
    row.update(overrides)
    return row


class _Resp:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


def _install_supabase(
    monkeypatch,
    *,
    incidents=None,
    events=None,
    open_rows=None,
    rpc_result=True,
    calls=None,
    patch_status: int = 200,
    patched=None,
    heartbeats=None,
    rpc_status: int = 200,
    schema_missing: bool = False,
):
    """Stub ops.httpx.AsyncClient with a PostgREST-shaped recorder.

    ``calls`` collects every outbound request as
    ``{"method", "url", "params", "json"}`` so a test can assert on the exact
    filter, patch body, audit row, or RPC payload the route produced — the
    only way to prove a detector wrote through the RPC rather than touching
    the table directly.
    """
    incidents = [] if incidents is None else incidents
    events = [] if events is None else events
    # A healthy database by default: the sweep checked in two minutes ago.
    # Every scan test runs the dead-man detector, and a stub that answered
    # "no such row" would have them all silently asserting against an extra
    # not-installed incident.
    heartbeats = [_heartbeat()] if heartbeats is None else heartbeats
    # PostgREST's answer when migration 032 has not been applied: 404 with the
    # schema-cache code, for the view (PGRST205) and the routine (PGRST202).
    missing_view = _Resp({"code": "PGRST205", "message": "Could not find the "
                          "table 'public.ops_heartbeat_status' in the schema cache"}, 404)
    missing_rpc = _Resp({"code": "PGRST202", "message": "Could not find the "
                         "function public.record_ops_heartbeat in the schema cache"}, 404)

    def _record(entry):
        if calls is not None:
            calls.append(entry)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None, **kwargs):
            _record({"method": "GET", "url": url, "params": params or {}})
            if "ops_heartbeat" in url:
                return missing_view if schema_missing else _Resp(heartbeats)
            if "ops_incident_events" in url:
                return _Resp(events)
            if "ops_incidents" in url:
                if (params or {}).get("select") in ("kind,priority", "dedup_key"):
                    return _Resp(open_rows if open_rows is not None else incidents)
                return _Resp(incidents)
            return _Resp([])

        async def post(self, url, json=None, headers=None, **kwargs):
            _record({"method": "POST", "url": url, "json": json})
            if "/rpc/" in url:
                if schema_missing and url.endswith("record_ops_heartbeat"):
                    return missing_rpc
                return _Resp(rpc_result, status_code=rpc_status)
            return _Resp([], status_code=201)

        async def patch(self, url, params=None, headers=None, json=None, **kwargs):
            _record({"method": "PATCH", "url": url, "params": params or {}, "json": json})
            if patched is not None:
                patched.append(json)
            base = incidents[0] if incidents else _incident()
            return _Resp([{**base, **(json or {})}], status_code=patch_status)

    monkeypatch.setattr(ops_mod.httpx, "AsyncClient", _Client)


def _admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")


def _hdr(**extra):
    return {"X-Admin-Token": "admin-ok", **extra}


def _rpcs(calls, fn: str) -> list[dict]:
    return [c["json"] for c in calls if c["method"] == "POST" and c["url"].endswith(f"/rpc/{fn}")]


def _incident_for(calls, dedup_key: str) -> dict:
    """The one recorded incident with this dedup_key.

    Tests used to unpack the whole list, which meant every new detector broke
    every unrelated scan assertion — twice in one day. Name what you mean.
    """
    (payload,) = (p for p in _rpcs(calls, "record_ops_incident")
                  if p["p_dedup_key"] == dedup_key)
    return payload


def _events(calls) -> list[dict]:
    rows: list[dict] = []
    for c in calls:
        if c["method"] == "POST" and c["url"].endswith("ops_incident_events"):
            rows.extend(c["json"])
    return rows


# ---------------------------------------------------------------------------
# Auth + configuration gates
# ---------------------------------------------------------------------------

class TestOpsAuthGates:
    """The queue holds every operational failure in the product: no token, no
    access, and no route may fall back to an unauthenticated read."""

    def test_list_503_when_admin_token_unset(self, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        assert client.get("/api/admin/ops/incidents").status_code == 503

    def test_list_401_when_wrong_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
        r = client.get("/api/admin/ops/incidents", headers={"X-Admin-Token": "nope"})
        assert r.status_code == 401

    def test_detail_and_mutations_are_gated(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
        bad = {"X-Admin-Token": "nope"}
        assert client.get(f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=bad).status_code == 401
        assert client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=bad, json={"priority": "high"}
        ).status_code == 401
        assert client.post(
            f"/api/admin/ops/incidents/{INCIDENT_ID}/retry", headers=bad
        ).status_code == 401

    def test_503_when_supabase_unconfigured(self, monkeypatch):
        # An empty queue would read as "nothing to do" — the exact silent
        # emptiness this feature removes. Fail loudly instead.
        monkeypatch.setenv("ADMIN_TOKEN", "admin-ok")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = client.get("/api/admin/ops/incidents", headers=_hdr())
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]

    def test_scan_503_without_cron_secret(self, monkeypatch):
        monkeypatch.delenv("CRON_SECRET", raising=False)
        assert client.post("/api/cron/ops-scan").status_code == 503

    def test_scan_401_with_wrong_secret(self, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-ok")
        r = client.post("/api/cron/ops-scan", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
        assert client.post("/api/cron/ops-scan").status_code == 401


# ---------------------------------------------------------------------------
# GET /admin/ops/incidents
# ---------------------------------------------------------------------------

class TestIncidentList:
    def test_unfiltered_default_returns_every_status(self, monkeypatch):
        """No filter means NO filter.

        The console's "Any status" option sends neither ``status`` nor
        ``unresolved_only``; if the route quietly dropped closed incidents,
        that option would show a queue with rows missing and no indication
        any were withheld.
        """
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls)

        r = client.get("/api/admin/ops/incidents", headers=_hdr())
        assert r.status_code == 200
        listing = next(c for c in calls if c["method"] == "GET" and c["params"].get("select") == "*")
        assert "status" not in listing["params"]
        assert r.json()["filters"]["excluded_statuses"] == []

    def test_unresolved_only_excludes_closed_incidents(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls)

        r = client.get(
            "/api/admin/ops/incidents", headers=_hdr(), params={"unresolved_only": "true"},
        )
        assert r.status_code == 200
        listing = next(c for c in calls if c["method"] == "GET" and c["params"].get("select") == "*")
        # "Outstanding" is two excluded values, not one selected one.
        assert listing["params"]["status"] == "not.in.(resolved,suppressed)"
        body = r.json()
        assert body["filters"]["unresolved_only"] is True
        assert body["filters"]["excluded_statuses"] == ["resolved", "suppressed"]

    def test_unresolved_only_with_explicit_status_is_a_400(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[])
        # Contradictory filters resolve to an error, never to whichever the
        # implementation happens to apply last.
        r = client.get(
            "/api/admin/ops/incidents", headers=_hdr(),
            params={"unresolved_only": "true", "status": "resolved"},
        )
        assert r.status_code == 400

    def test_filters_are_passed_through(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[], calls=calls)

        r = client.get(
            "/api/admin/ops/incidents",
            headers=_hdr(),
            params={
                "kind": "data_drift", "status": "acknowledged", "priority": "high",
                "assigned_to": "ana", "scope": "uiuc_faculty", "limit": 10,
            },
        )
        assert r.status_code == 200
        p = next(c for c in calls if c["method"] == "GET" and c["params"].get("select") == "*")["params"]
        assert p["kind"] == "eq.data_drift"
        assert p["status"] == "eq.acknowledged"
        assert p["priority"] == "eq.high"
        assert p["assigned_to"] == "eq.ana"
        assert p["scope"] == "eq.uiuc_faculty"
        assert p["limit"] == "10"

    def test_unknown_enum_is_400_not_500(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch)
        for params in ({"kind": "nope"}, {"status": "nope"}, {"priority": "nope"}):
            r = client.get("/api/admin/ops/incidents", headers=_hdr(), params=params)
            assert r.status_code == 400

    def test_limit_is_bounded(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch)
        assert client.get(
            "/api/admin/ops/incidents", headers=_hdr(), params={"limit": 500}
        ).status_code == 422
        assert client.get(
            "/api/admin/ops/incidents", headers=_hdr(), params={"limit": 0}
        ).status_code == 422

    def test_rollup_counts_open_work_per_kind(self, monkeypatch):
        _admin_env(monkeypatch)
        open_rows = [
            {"kind": "collector_failure", "priority": "high"},
            {"kind": "collector_failure", "priority": "normal"},
            {"kind": "data_drift", "priority": "high"},
            {"kind": "notification_failure", "priority": "low"},
        ]
        _install_supabase(monkeypatch, incidents=[_incident()], open_rows=open_rows)

        body = client.get(
            "/api/admin/ops/incidents", headers=_hdr(), params={"kind": "collector_failure"}
        ).json()
        rollup = body["rollup"]
        # The rollup ignores the caller's filter on purpose: narrowing to one
        # kind must never hide that another kind is on fire.
        assert rollup["open_by_kind"] == {
            "collector_failure": 2, "data_drift": 1,
            "notification_failure": 1, "manual_review": 0,
        }
        assert rollup["open_total"] == 4
        assert rollup["truncated"] is False


class TestIncidentDetail:
    def test_returns_incident_with_its_events(self, monkeypatch):
        _admin_env(monkeypatch)
        events = [
            {"action": "detected", "actor": "detector", "to_value": "blocked"},
            {"action": "assigned", "actor": "ana", "to_value": "ana"},
        ]
        _install_supabase(monkeypatch, incidents=[_incident()], events=events)

        body = client.get(f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr()).json()
        assert body["incident"]["dedup_key"] == "collector_failure:uiuc_faculty"
        assert body["event_count"] == 2
        assert [e["action"] for e in body["events"]] == ["detected", "assigned"]

    def test_404_for_unknown_incident(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[])
        r = client.get(f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr())
        assert r.status_code == 404

    def test_400_for_non_uuid(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch)
        assert client.get("/api/admin/ops/incidents/not-a-uuid", headers=_hdr()).status_code == 400


# ---------------------------------------------------------------------------
# PATCH /admin/ops/incidents/{id}
# ---------------------------------------------------------------------------

class TestIncidentMutation:
    def test_assign_writes_event_with_real_prior_value_and_actor(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(
            monkeypatch, incidents=[_incident(assigned_to="ana")], calls=calls,
        )

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}",
            headers=_hdr(**{"X-Admin-Actor": "bo"}),
            json={"assigned_to": "cleo"},
        )
        assert r.status_code == 200
        assert r.json()["changed"] == ["assigned_to"]
        (event,) = _events(calls)
        assert event["action"] == "assigned"
        # from_value is read from the row, not echoed from the request.
        assert event["from_value"] == "ana"
        assert event["to_value"] == "cleo"
        assert event["actor"] == "bo"

    def test_unassign_and_default_actor(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident(assigned_to="ana")], calls=calls)

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"assigned_to": "  "},
        )
        assert r.status_code == 200
        (event,) = _events(calls)
        assert event["action"] == "unassigned"
        assert event["actor"] == "operator"

    def test_actor_cannot_claim_the_detector_identity(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls)

        client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}",
            headers=_hdr(**{"X-Admin-Actor": "Detector"}),
            json={"priority": "urgent"},
        )
        (event,) = _events(calls)
        # 'detector' is what the RPCs write for machine sightings; a human
        # decision must not be able to wear that label.
        assert event["actor"] == "operator"

    def test_priority_change_is_logged(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        patched: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls, patched=patched)

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"priority": "urgent"},
        )
        assert r.status_code == 200
        assert patched[0]["priority"] == "urgent"
        (event,) = _events(calls)
        assert (event["action"], event["from_value"], event["to_value"]) == (
            "priority_changed", "normal", "urgent",
        )

    def test_status_change_is_logged(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls)

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(),
            json={"status": "investigating"},
        )
        assert r.status_code == 200
        (event,) = _events(calls)
        assert (event["action"], event["from_value"], event["to_value"]) == (
            "status_changed", "open", "investigating",
        )

    def test_resolve_without_resolution_is_400_and_writes_nothing(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls)

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"status": "resolved"},
        )
        assert r.status_code == 400
        assert "resolution is required" in r.json()["detail"]
        # No silent close: the row was never touched.
        assert [c for c in calls if c["method"] == "PATCH"] == []

    def test_suppress_without_resolution_is_400(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[_incident()])
        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"status": "suppressed"},
        )
        assert r.status_code == 400

    def test_resolve_with_decision_stamps_and_logs(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        patched: list = []
        _install_supabase(monkeypatch, incidents=[_incident()], calls=calls, patched=patched)

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}",
            headers=_hdr(**{"X-Admin-Actor": "ana"}),
            json={
                "status": "resolved", "resolution": "legitimate_change",
                "resolution_note": "department really did shrink",
            },
        )
        assert r.status_code == 200
        body = patched[0]
        assert body["status"] == "resolved"
        assert body["resolution"] == "legitimate_change"
        assert body["resolution_note"] == "department really did shrink"
        assert body["resolved_by"] == "ana"
        assert body["resolved_at"]
        (event,) = _events(calls)
        assert event["action"] == "resolved"
        assert event["note"] == "legitimate_change"

    def test_reopen_clears_the_previous_decision(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        patched: list = []
        resolved = _incident(
            status="resolved", resolution="wont_fix", resolution_note="ignore",
            resolved_by="ana", resolved_at="2026-08-01T00:00:00+00:00",
        )
        _install_supabase(monkeypatch, incidents=[resolved], calls=calls, patched=patched)

        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"status": "open"},
        )
        assert r.status_code == 200
        body = patched[0]
        # A reopened incident must not inherit the verdict on its old life.
        assert body["resolution"] is None
        assert body["resolution_note"] is None
        assert body["resolved_by"] is None
        assert body["resolved_at"] is None
        (event,) = _events(calls)
        assert (event["action"], event["from_value"], event["to_value"]) == (
            "reopened", "resolved", "open",
        )

    def test_reopen_refuses_a_simultaneous_resolution(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[_incident(status="resolved", resolution="fixed")])
        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(),
            json={"status": "open", "resolution": "duplicate"},
        )
        assert r.status_code == 400

    def test_resolution_without_terminal_status_is_400(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[_incident()])
        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(),
            json={"resolution": "fixed"},
        )
        assert r.status_code == 400

    def test_unknown_enum_values_are_400_not_500(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[_incident()])
        for payload in (
            {"status": "closed"},            # feedback's vocabulary, not this one
            {"priority": "critical"},
            {"status": "resolved", "resolution": "solved"},
        ):
            r = client.patch(
                f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json=payload,
            )
            assert r.status_code == 400, payload

    def test_noop_patch_writes_nothing(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, incidents=[_incident(priority="normal")], calls=calls)
        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"priority": "normal"},
        )
        assert r.status_code == 200
        assert r.json()["changed"] == []
        assert [c for c in calls if c["method"] in ("PATCH", "POST")] == []

    def test_404_for_unknown_incident(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[])
        r = client.patch(
            f"/api/admin/ops/incidents/{INCIDENT_ID}", headers=_hdr(), json={"priority": "high"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /admin/ops/incidents/{id}/retry
# ---------------------------------------------------------------------------

class TestIncidentRetry:
    def test_retry_records_an_attempt_and_investigating_status(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        patched: list = []
        _install_supabase(
            monkeypatch,
            incidents=[_incident(kind="notification_failure", attempt_count=2)],
            calls=calls, patched=patched,
        )

        r = client.post(
            f"/api/admin/ops/incidents/{INCIDENT_ID}/retry",
            headers=_hdr(**{"X-Admin-Actor": "ana"}),
        )
        assert r.status_code == 200
        body = patched[0]
        assert body["attempt_count"] == 3
        assert body["last_attempt_at"]
        assert body["status"] == "investigating"
        (event,) = _events(calls)
        assert event["action"] == "retried"
        assert event["actor"] == "ana"

    def test_retry_never_resolves_or_claims_delivery(self, monkeypatch):
        _admin_env(monkeypatch)
        calls: list = []
        patched: list = []
        _install_supabase(
            monkeypatch,
            incidents=[_incident(kind="notification_failure", status="investigating")],
            calls=calls, patched=patched,
        )

        r = client.post(f"/api/admin/ops/incidents/{INCIDENT_ID}/retry", headers=_hdr())
        assert r.status_code == 200
        body = r.json()
        # An attempt is not an outcome.
        assert body["delivery_claimed"] is False
        assert body["resolved"] is False
        assert body["incident"]["status"] != "resolved"
        assert body["incident"]["resolution"] is None
        written = patched[0]
        assert "resolution" not in written
        assert "resolved_at" not in written
        assert "last_success_at" not in written
        # failure_state is detector evidence; an operator retry cannot flip it
        # to 'recovered'.
        assert "failure_state" not in written
        # An already-triaged incident keeps its status.
        assert "status" not in written
        # Nothing was sent: the only outbound writes are the bookkeeping PATCH
        # and its audit row.
        assert _rpcs(calls, "record_ops_recovery") == []

    def test_retry_rejected_for_non_retryable_kinds(self, monkeypatch):
        _admin_env(monkeypatch)
        for kind in ("data_drift", "manual_review"):
            _install_supabase(monkeypatch, incidents=[_incident(kind=kind)])
            r = client.post(f"/api/admin/ops/incidents/{INCIDENT_ID}/retry", headers=_hdr())
            assert r.status_code == 400, kind

    def test_retry_rejected_on_a_closed_incident(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(
            monkeypatch,
            incidents=[_incident(status="resolved", resolution="fixed")],
        )
        r = client.post(f"/api/admin/ops/incidents/{INCIDENT_ID}/retry", headers=_hdr())
        assert r.status_code == 409

    def test_retry_404_for_unknown_incident(self, monkeypatch):
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, incidents=[])
        r = client.post(f"/api/admin/ops/incidents/{INCIDENT_ID}/retry", headers=_hdr())
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/cron/ops-scan — the detector
# ---------------------------------------------------------------------------

def _scan_env(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")


def _write_artifacts(monkeypatch, tmp_path, *, snapshot=None, history=None, tracking=None):
    """Point the detector at tmp artifacts; omit one to simulate it missing."""
    status_path = tmp_path / "collector_status.json"
    history_path = tmp_path / "collector_status_history.jsonl"
    tracking_path = tmp_path / "professor_tracking.json"
    if snapshot is not None:
        status_path.write_text(json.dumps(snapshot), encoding="utf-8")
    if history is not None:
        history_path.write_text(
            "".join(json.dumps(e) + "\n" for e in history), encoding="utf-8"
        )
    if tracking is not None:
        tracking_path.write_text(json.dumps(tracking), encoding="utf-8")
    monkeypatch.setattr(ops_mod, "_COLLECTOR_STATUS_PATH", status_path)
    monkeypatch.setattr(ops_mod, "_COLLECTOR_HISTORY_PATH", history_path)
    monkeypatch.setattr(ops_mod, "_TRACKING_PATH", tracking_path)


def _run_scan():
    return client.post("/api/cron/ops-scan", headers={"Authorization": "Bearer cron-ok"})


class TestOpsScanCollectors:
    def test_errored_source_opens_an_incident(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "2026-08-07T03:00:00+00:00",
            "sources": {
                "uiuc_faculty": {"status": "error", "error": "403 Forbidden (WAF)", "fetched": 0},
            },
        })

        r = _run_scan()
        assert r.status_code == 200
        payload = _incident_for(calls, "collector_failure:uiuc_faculty")
        assert payload["p_kind"] == "collector_failure"
        assert payload["p_scope"] == "uiuc_faculty"
        assert payload["p_failure_state"] == "blocked"
        assert payload["p_detail"]["error"] == "403 Forbidden (WAF)"
        assert payload["p_detail"]["run_timestamp"] == "2026-08-07T03:00:00+00:00"

    def test_failure_state_classification_and_truncation(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {
                "a_blocked": {"status": "error", "error": "Cloudflare challenge page"},
                "b_timeout": {"status": "error", "error": "Read timed out after 30s"},
                "c_other": {"status": "error", "error": "x" * 900},
            },
        })
        _run_scan()

        by_key = {p["p_dedup_key"]: p for p in _rpcs(calls, "record_ops_incident")}
        assert by_key["collector_failure:a_blocked"]["p_failure_state"] == "blocked"
        assert by_key["collector_failure:b_timeout"]["p_failure_state"] == "timed_out"
        other = by_key["collector_failure:c_other"]
        assert other["p_failure_state"] == "failed"
        # Evidence is bounded: an incident payload is not a log sink.
        assert len(other["p_detail"]["error"]) <= 300

    def test_ok_source_records_a_verified_recovery(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(
            monkeypatch, open_rows=[{"dedup_key": "collector_failure:uiuc_faculty"}], calls=calls,
        )
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {"uiuc_faculty": {"status": "ok", "fetched": 120}},
        })

        r = _run_scan()
        (payload,) = _rpcs(calls, "record_ops_recovery")
        assert payload["p_dedup_key"] == "collector_failure:uiuc_faculty"
        assert payload["p_auto_resolve"] is True
        assert payload["p_note"] == "verified successful run"
        assert r.json()["recovered"] == 1
        assert _rpcs(calls, "record_ops_incident") == []

    def test_healthy_source_without_an_incident_makes_no_rpc_call(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t", "sources": {"fine": {"status": "ok", "fetched": 10}},
        })
        _run_scan()
        assert _rpcs(calls, "record_ops_recovery") == []
        assert _rpcs(calls, "record_ops_incident") == []

    def test_fatal_error_is_surfaced_as_an_incident(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t", "fatal_error": "MemoryError during assembly", "sources": {},
        })
        _run_scan()

        (payload,) = _rpcs(calls, "record_ops_incident")
        assert payload["p_dedup_key"] == "collector_failure:refresh_run"
        assert payload["p_priority"] == "urgent"
        assert "MemoryError" in payload["p_detail"]["error"]


class TestOpsScanReleaseDegradation:
    """#725 stopped an unreachable host from vetoing publication. This is what
    replaced the veto: the gap becomes a tracked incident instead of one line
    in a run log nobody reads."""

    def test_a_dark_school_opens_a_high_priority_incident(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "2026-08-08T06:12:00+00:00",
            "sources": {"campus_graph:umich": {"status": "ok", "fetched": 12}},
            "release": {
                "ready": True,
                "degradations": [{
                    "kind": "dark_crawl",
                    "source": "campus_graph:umich",
                    "detail": "0/9 seed pages, 0/6 crawl sources",
                }],
            },
        })

        r = _run_scan()
        assert r.status_code == 200
        payload = _incident_for(
            calls, "collector_failure:degraded:dark_crawl:campus_graph:umich")
        assert payload["p_kind"] == "collector_failure"
        assert payload["p_scope"] == "campus_graph:umich"
        assert payload["p_priority"] == "high"
        assert payload["p_detail"]["published"] is True
        assert "0/9 seed pages" in payload["p_detail"]["detail"]

    def test_lesser_gaps_open_at_normal_priority(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {"campus_graph:caltech": {"status": "ok", "fetched": 31}},
            "release": {"ready": True, "degradations": [
                {"kind": "seed_pages_unreached", "source": "campus_graph:caltech",
                 "detail": "15/17, 2 failed"},
                {"kind": "crawl_errors", "source": "campus_graph:caltech",
                 "detail": "seed fetch failed"},
            ]},
        })

        _run_scan()
        opened = _rpcs(calls, "record_ops_incident")
        assert {p["p_dedup_key"] for p in opened} == {
            "collector_failure:degraded:seed_pages_unreached:campus_graph:caltech",
            "collector_failure:degraded:crawl_errors:campus_graph:caltech",
        }
        assert {p["p_priority"] for p in opened} == {"normal"}

    def test_a_clean_run_of_that_source_closes_it(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, calls=calls, open_rows=[
            {"dedup_key": "collector_failure:degraded:dark_crawl:campus_graph:umich"},
        ])
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {"campus_graph:umich": {"status": "ok", "fetched": 40}},
            "release": {"ready": True, "degradations": []},
        })

        r = _run_scan()
        (payload,) = _rpcs(calls, "record_ops_recovery")
        assert payload["p_dedup_key"] == (
            "collector_failure:degraded:dark_crawl:campus_graph:umich"
        )
        assert payload["p_auto_resolve"] is True
        assert r.json()["recovered"] == 1

    def test_a_shard_that_never_touched_the_source_closes_nothing(
        self, monkeypatch, tmp_path
    ):
        """THE rotation trap: Monday's run says nothing about Michigan.

        Absence from a shard is not evidence of recovery, and treating it as
        such would silently clear every school's incident once a week.
        """
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, calls=calls, open_rows=[
            {"dedup_key": "collector_failure:degraded:dark_crawl:campus_graph:umich"},
        ])
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {"campus_graph:uiuc": {"status": "ok", "fetched": 40}},
            "release": {"ready": True, "degradations": []},
        })

        _run_scan()
        assert _rpcs(calls, "record_ops_recovery") == []

    def test_a_source_that_ran_and_failed_closes_nothing(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, calls=calls, open_rows=[
            {"dedup_key": "collector_failure:degraded:dark_crawl:campus_graph:umich"},
        ])
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {"campus_graph:umich": {"status": "error", "error": "boom"}},
            "release": {"ready": False, "degradations": []},
        })

        _run_scan()
        assert _rpcs(calls, "record_ops_recovery") == []

    def test_a_snapshot_predating_the_field_is_skipped_not_guessed_at(
        self, monkeypatch, tmp_path
    ):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t",
            "sources": {"campus_graph:umich": {"status": "ok", "fetched": 12}},
            "release": {"ready": True, "warnings": ["something"]},
        })

        r = _run_scan()
        skipped = {s["detector"] for s in r.json()["skipped"]}
        assert "release_degradation" in skipped
        assert _rpcs(calls, "record_ops_incident") == []


class TestOpsScanDrift:
    def test_large_fetched_drop_opens_a_high_priority_drift_incident(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(
            monkeypatch, tmp_path,
            snapshot={
                "timestamp": "2026-08-07T03:00:00+00:00",
                "sources": {"purdue": {"status": "ok", "fetched": 40}},
            },
            history=[
                {"t": "2026-08-06T03:00:00+00:00", "sources": {"purdue": {"fetched": 200}}},
                # The current run appends its own row; comparing against it
                # would always show zero change.
                {"t": "2026-08-07T03:00:00+00:00", "sources": {"purdue": {"fetched": 40}}},
            ],
        )

        r = _run_scan()
        payload = _incident_for(calls, "data_drift:purdue:fetched")
        assert payload["p_kind"] == "data_drift"
        assert payload["p_priority"] == "high"
        detail = payload["p_detail"]
        assert detail["metric"] == "fetched"
        assert detail["previous"] == 200
        assert detail["current"] == 40
        assert detail["threshold_pct"] == -30.0
        assert r.json()["detectors"]["data_drift"]["drifted"] == 1

    def test_small_or_shallow_drops_are_ignored(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(
            monkeypatch, tmp_path,
            snapshot={"timestamp": "now", "sources": {
                # 50% down but only 6 records: a tiny department wobbling.
                "tiny": {"status": "ok", "fetched": 6},
                # 100 records down but only 20%: within normal churn.
                "shallow": {"status": "ok", "fetched": 400},
            }},
            history=[{"t": "before", "sources": {
                "tiny": {"fetched": 12}, "shallow": {"fetched": 500},
            }}],
        )
        _run_scan()
        assert _rpcs(calls, "record_ops_incident") == []

    def test_recovered_counts_never_auto_resolve_a_drift_alert(self, monkeypatch, tmp_path):
        """A later successful run must NOT suppress a drift alert (027 §17).

        The source below runs green and its count is back to normal — the very
        situation that would silently clear the alert if drift recoveries were
        auto-resolved. The only recovery permitted here is the collector-level
        one; the drift dedup_key must be left for a human.
        """
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[
            {"dedup_key": "collector_failure:purdue"},
            {"dedup_key": "data_drift:purdue:fetched"},
        ], calls=calls)
        _write_artifacts(
            monkeypatch, tmp_path,
            snapshot={"timestamp": "now", "sources": {"purdue": {"status": "ok", "fetched": 200}}},
            history=[{"t": "before", "sources": {"purdue": {"fetched": 40}}}],
        )
        _run_scan()

        recoveries = _rpcs(calls, "record_ops_recovery")
        assert [r["p_dedup_key"] for r in recoveries] == ["collector_failure:purdue"]
        assert all(r["p_auto_resolve"] is True for r in recoveries)
        assert not any("data_drift" in r["p_dedup_key"] for r in recoveries)


class TestOpsScanProfessorTracking:
    def test_not_release_ready_opens_an_incident_with_failing_reasons(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, tracking={
            "schema_version": 2,
            "profiles": {},
            "release": {
                "release_ready": False,
                "freshness_pct": 81.2,
                "fully_stale_school_count": 2,
                "fully_stale_schools": ["ucsd", "unc"],
                "computed_at": "2026-08-06T11:02:08+00:00",
                "checks": {
                    "schema_v2": True, "events_valid": True,
                    "freshness_min_pct": False, "no_fully_stale_school": False,
                    "refresh_ok": True,
                },
            },
        })

        _run_scan()
        (payload,) = _rpcs(calls, "record_ops_incident")
        assert payload["p_kind"] == "data_drift"
        assert payload["p_dedup_key"] == "data_drift:professor_tracking:release_ready"
        assert payload["p_detail"]["failing_checks"] == [
            "freshness_min_pct", "no_fully_stale_school",
        ]
        assert payload["p_detail"]["freshness_pct"] == 81.2

    def test_release_ready_again_needs_human_confirmation(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(
            monkeypatch,
            open_rows=[{"dedup_key": "data_drift:professor_tracking:release_ready"}],
            calls=calls,
        )
        _write_artifacts(monkeypatch, tmp_path, tracking={
            "schema_version": 2,
            "release": {"release_ready": True, "checks": {"schema_v2": True}},
        })

        _run_scan()
        (payload,) = _rpcs(calls, "record_ops_recovery")
        assert payload["p_dedup_key"] == "data_drift:professor_tracking:release_ready"
        # Evidence, not a verdict: a passing gate does not vouch for what
        # shipped while it was failing.
        assert payload["p_auto_resolve"] is False


class TestOpsScanResilience:
    def test_missing_artifacts_are_reported_not_fatal(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path)  # nothing on disk at all

        r = _run_scan()
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["opened"] == 0
        detectors = {s["detector"] for s in body["skipped"]}
        assert detectors == {
            "collector_failure",
            "data_drift",
            "release_degradation",
            "professor_tracking",
        }
        assert _rpcs(calls, "record_ops_incident") == []

    def test_corrupt_snapshot_is_skipped_not_a_500(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        _install_supabase(monkeypatch, open_rows=[])
        _write_artifacts(monkeypatch, tmp_path)
        (tmp_path / "collector_status.json").write_text("{not json", encoding="utf-8")

        r = _run_scan()
        assert r.status_code == 200
        reasons = {s["detector"]: s["reason"] for s in r.json()["skipped"]}
        assert "unreadable" in reasons["collector_failure"]

    def test_missing_history_skips_only_drift(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t", "sources": {"x": {"status": "error", "error": "boom"}},
        })

        body = _run_scan().json()
        # The collector detector still did its job.
        assert len(_rpcs(calls, "record_ops_incident")) == 1
        assert any(s["detector"] == "data_drift" for s in body["skipped"])

    def test_rpc_failure_is_counted_not_raised(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)

        class _Broken:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *a, **k):
                return _Resp([])

            async def post(self, *a, **k):
                return _Resp({"message": "permission denied"}, status_code=403)

        monkeypatch.setattr(ops_mod.httpx, "AsyncClient", _Broken)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t", "sources": {"x": {"status": "error", "error": "boom"}},
        })

        r = _run_scan()
        assert r.status_code == 200
        body = r.json()
        assert body["opened"] == 0  # nothing was actually recorded
        assert body["errors"] and body["errors"][0]["status"] == 403

    def test_scan_skips_without_supabase_env(self, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-ok")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = _run_scan()
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"


# ---------------------------------------------------------------------------
# The reminders cron feeds the same queue (backend/routes/push.py)
# ---------------------------------------------------------------------------

_DUE = {
    "device_id": "dev-1", "opportunity_id": "opp-42",
    "remind_at": "2026-08-01", "interaction_type": "applied", "notes": "",
}
_SUB = {
    "device_id": "dev-1",
    # A push endpoint is a bearer-capability URL: it must never reach the
    # incident payload.
    "endpoint": "https://push.example.test/wpush/v2/SECRET-CAPABILITY-TOKEN",
    "p256dh": "k", "auth": "a",
}


def _install_cron_stubs(monkeypatch, *, webpush_impl=None, open_keys=(), calls=None,
                        rpc_raises=False):
    import httpx
    import pywebpush

    from backend.routes import push as push_mod

    # Incident tests deliberately reach the delivery path. Keep that target
    # visibly in release scope instead of depending on the assembled corpus.
    monkeypatch.setattr(
        push_mod,
        "load_opportunities_by_id",
        lambda: {
            _DUE["opportunity_id"]: {
                "id": _DUE["opportunity_id"],
                "source_type": "campus_program",
                "opportunity_type": "research",
                "metadata": {"is_active": True},
            }
        },
    )

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None, **kwargs):
            if "/auth/v1/admin/users/" in url:
                return _Resp({}, status_code=404)
            if "ops_incidents" in url:
                return _Resp([{"dedup_key": k} for k in open_keys])
            if "push_subscriptions" in url:
                return _Resp([_SUB])
            return _Resp([_DUE])

        async def post(self, url, json=None, headers=None, **kwargs):
            if rpc_raises:
                raise RuntimeError("supabase unreachable")
            if calls is not None:
                calls.append({"url": url, "json": json})
            return _Resp(True)

        async def patch(self, url, **kwargs):
            return _Resp({}, status_code=204)

        async def delete(self, url, **kwargs):
            return _Resp({}, status_code=204)

    async def _passthrough(**kwargs):
        return kwargs["webpush_func"](
            subscription_info=kwargs["subscription_info"], data=kwargs["data"],
            vapid_private_key=kwargs["vapid_private_key"], vapid_claims=kwargs["vapid_claims"],
        )

    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pywebpush, "webpush", webpush_impl or (lambda **kw: None))
    monkeypatch.setattr(push_mod, "send_webpush_safely", _passthrough)


def _run_reminders():
    return client.get("/api/cron/reminders", headers={"Authorization": "Bearer cron-ok"})


class TestReminderCronIncidents:
    """A failed reminder used to live only in this run's response counter."""

    def test_provider_rejection_records_an_incident_without_secrets(self, monkeypatch):
        from pywebpush import WebPushException

        class _Rejected:
            status_code = 500

        def _boom(**kwargs):
            raise WebPushException("rejected", response=_Rejected())

        calls: list = []
        _install_cron_stubs(monkeypatch, webpush_impl=_boom, calls=calls)

        body = _run_reminders().json()
        assert body["failed"] == 1
        assert body["incidents_recorded"] == 1
        assert body["incident_errors"] == 0

        (rpc,) = (c["json"] for c in calls if c["url"].endswith("/rpc/record_ops_incident"))
        assert rpc["p_kind"] == "notification_failure"
        assert rpc["p_dedup_key"] == "notification_failure:dev-1:opp-42"
        # The provider's status was read and discarded before W15; it is the
        # most useful triage field there is.
        assert rpc["p_detail"]["provider_status"] == 500
        assert rpc["p_detail"]["error_category"] == "provider_error"
        # No capability URL, no message body, anywhere in the payload.
        serialized = json.dumps(rpc)
        assert "SECRET-CAPABILITY-TOKEN" not in serialized
        assert "wpush" not in serialized
        assert "Reminder due" not in serialized
        assert len(rpc["p_detail"]["endpoint_fingerprint"]) == 16

    def test_timeout_and_blocked_endpoint_carry_their_failure_state(self, monkeypatch):
        from backend.lib.safe_webpush import WebPushDeliveryTimeout
        from backend.routes import push as push_mod

        calls: list = []
        _install_cron_stubs(monkeypatch, calls=calls)

        async def _timeout(**_kwargs):
            raise WebPushDeliveryTimeout("deadline exceeded")

        monkeypatch.setattr(push_mod, "send_webpush_safely", _timeout)
        assert _run_reminders().json()["failed"] == 1
        (rpc,) = (c["json"] for c in calls if c["url"].endswith("/rpc/record_ops_incident"))
        assert rpc["p_failure_state"] == "timed_out"
        assert rpc["p_detail"]["error_category"] == "delivery_timeout"

    def test_delivery_recovers_an_open_incident(self, monkeypatch):
        calls: list = []
        _install_cron_stubs(
            monkeypatch, calls=calls, open_keys=("notification_failure:dev-1:opp-42",),
        )

        body = _run_reminders().json()
        assert body["sent"] == 1
        assert body["incidents_recovered"] == 1
        (rpc,) = (c["json"] for c in calls if c["url"].endswith("/rpc/record_ops_recovery"))
        assert rpc["p_dedup_key"] == "notification_failure:dev-1:opp-42"
        # The evidence IS the outcome here: the notification was delivered.
        assert rpc["p_auto_resolve"] is True

    def test_healthy_run_without_history_makes_no_rpc_calls(self, monkeypatch):
        calls: list = []
        _install_cron_stubs(monkeypatch, calls=calls)
        body = _run_reminders().json()
        assert body["sent"] == 1
        assert calls == []  # nothing failed and nothing was open to recover

    def test_incident_write_failure_never_breaks_the_cron(self, monkeypatch):
        from pywebpush import WebPushException

        def _boom(**kwargs):
            raise WebPushException("rejected")

        _install_cron_stubs(monkeypatch, webpush_impl=_boom, rpc_raises=True)

        r = _run_reminders()
        assert r.status_code == 200
        body = r.json()
        # The run's own counters stay authoritative and the batch completes.
        assert body["status"] == "ok"
        assert body["failed"] == 1
        assert body["incidents_recorded"] == 0
        assert body["incident_errors"] == 1


class TestReleaseBlockReader:
    def test_tail_read_finds_the_block_in_a_large_artifact(self, tmp_path):
        """The real artifact is ~30 MB; the reader must not parse all of it."""
        path = tmp_path / "professor_tracking.json"
        filler = {f"prof:{i}": {"school": "x" * 200} for i in range(2000)}
        path.write_text(
            json.dumps({"schema_version": 2, "profiles": filler,
                        "release": {"release_ready": True, "checks": {"schema_v2": True}}}),
            encoding="utf-8",
        )
        assert path.stat().st_size > ops_mod._TRACKING_TAIL_BYTES

        block, err = ops_mod._read_release_block(path)
        assert err is None
        assert block["release_ready"] is True

    def test_absent_block_reports_instead_of_guessing(self, tmp_path):
        path = tmp_path / "professor_tracking.json"
        path.write_text(json.dumps({"schema_version": 1, "profiles": {}}), encoding="utf-8")
        block, err = ops_mod._read_release_block(path)
        assert block is None
        assert "release block" in err


# ---------------------------------------------------------------------------
# The dead man's switch (migration 032)
# ---------------------------------------------------------------------------
# Everything above detects a job that RAN and went wrong. None of it can see a
# job that never ran at all — the refresh was dead for 8 days in August and 18
# days before that with no red run, no alert, and no incident, because every
# detector we own lives inside the thing that stopped.
#
# The switch is mutual on purpose: pg_cron sweeps the heartbeats that GitHub
# writes, and this scan (which runs from GitHub) reads the sweep's own
# heartbeat. Whichever side dies, the other is the one that files. The tests
# below lock both directions plus the registry that ties them together.

SWEEP = ops_mod._SWEEP_HEARTBEAT
SWEEP_KEY = f"dead_man:{SWEEP}"

MIGRATION_032 = REPO / "supabase" / "migrations" / "032_dead_man_switch.sql"
WORKFLOW_DIR = REPO / ".github" / "workflows"


def _seeded_heartbeat_names() -> set[str]:
    """Heartbeat names the migration registers, read from the migration."""
    sql = MIGRATION_032.read_text(encoding="utf-8")
    body = sql.split("INSERT INTO ops_heartbeats", 1)[1].split("ON CONFLICT", 1)[0]
    return set(re.findall(r"^\s*\('([a-z0-9_]+)',", body, re.MULTILINE))


def _scheduled_workflows() -> dict[Path, dict]:
    """Every workflow with a `schedule:` trigger, parsed."""
    found = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        # PyYAML resolves the bare key `on` to the boolean True.
        triggers = doc.get("on") or doc.get(True) or {}
        if isinstance(triggers, dict) and "schedule" in triggers:
            found[path] = doc
    return found


def _checkin_steps(doc: dict) -> list[dict]:
    return [
        step
        for job in (doc.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if "dead man" in str(step.get("name", "")).lower()
    ]


# The payload is a shell heredoc, so a workflow that interpolates ${{ }} into
# it writes \"name\" while one that does not writes "name". Both are the same
# JSON key; the drift check must not depend on which quoting a step happened
# to need.
_POSTED_NAME_RE = re.compile(r'\\?"name\\?"\s*:\s*\\?"([a-z0-9_]+)\\?"')


def _posted_names(steps: list[dict]) -> list[str]:
    return _POSTED_NAME_RE.findall(" ".join(str(s.get("run", "")) for s in steps))


class TestTheScanKnowsHowOldItsEvidenceIs:
    """The 07:30 scan read yesterday's snapshot for weeks and reported clean.

    The refresh publishes through an auto-merged PR, so the artifact reaches
    main hours after the run starts; a detector reading its own checkout was
    always judging the previous day. Retiming the cron narrows the window.
    Only this makes the miss visible when the retiming is wrong again.
    """

    STALE_KEY = "collector_failure:ops_scan:stale_snapshot"

    def _scan_with_snapshot_age(self, monkeypatch, tmp_path, hours, calls, open_rows=None):
        _scan_env(monkeypatch)
        _install_supabase(monkeypatch, open_rows=open_rows or [], calls=calls)
        ts = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": ts,
            "sources": {"uiuc_faculty": {"status": "ok", "fetched": 10}},
        })
        return _run_scan()

    def test_a_days_old_snapshot_is_fine(self, monkeypatch, tmp_path):
        calls: list = []
        r = self._scan_with_snapshot_age(monkeypatch, tmp_path, 5, calls)
        det = r.json()["detectors"]["collector_failure"]
        assert det["snapshot_stale"] is False
        assert 4.5 <= det["snapshot_age_hours"] <= 5.5
        assert [p for p in _rpcs(calls, "record_ops_incident")
                if p["p_dedup_key"] == self.STALE_KEY] == []

    def test_a_two_day_old_snapshot_opens_an_incident(self, monkeypatch, tmp_path):
        calls: list = []
        r = self._scan_with_snapshot_age(monkeypatch, tmp_path, 48, calls)
        assert r.json()["detectors"]["collector_failure"]["snapshot_stale"] is True
        payload = _incident_for(calls, self.STALE_KEY)
        assert payload["p_priority"] == "high"
        assert payload["p_scope"] == "ops_scan"
        assert payload["p_detail"]["snapshot_age_hours"] >= 47

    def test_a_fresh_snapshot_closes_the_open_one(self, monkeypatch, tmp_path):
        """A timestamp is complete evidence, so this recovery auto-resolves."""
        calls: list = []
        self._scan_with_snapshot_age(monkeypatch, tmp_path, 2, calls,
                                     open_rows=[{"dedup_key": self.STALE_KEY}])
        (payload,) = (p for p in _rpcs(calls, "record_ops_recovery")
                      if p["p_dedup_key"] == self.STALE_KEY)
        assert payload["p_auto_resolve"] is True

    def test_an_unparseable_timestamp_reports_unknown_rather_than_fine(
            self, monkeypatch, tmp_path):
        """Most fixtures carry timestamp "t". Unknown age must not read as
        fresh, and must not invent an incident either."""
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path, snapshot={
            "timestamp": "t", "sources": {"x": {"status": "ok", "fetched": 1}},
        })
        det = _run_scan().json()["detectors"]["collector_failure"]
        assert det["snapshot_stale"] is None
        assert det["snapshot_age_hours"] is None
        assert [p for p in _rpcs(calls, "record_ops_incident")
                if p["p_dedup_key"] == self.STALE_KEY] == []


class TestTheRegistryMatchesTheSchedulers:
    """A scheduled workflow with no heartbeat is an unwatched scheduler, which
    is the exact hole this feature exists to close. These are static checks:
    they hold whether or not anything is deployed."""

    def test_every_scheduled_workflow_checks_in(self):
        seeded = _seeded_heartbeat_names()
        unwatched = []
        for path, doc in _scheduled_workflows().items():
            steps = _checkin_steps(doc)
            if not steps:
                unwatched.append(f"{path.name}: no check-in step")
                continue
            names = _posted_names(steps)
            if not names:
                unwatched.append(f"{path.name}: check-in step posts no heartbeat name")
            for name in names:
                if name not in seeded:
                    unwatched.append(f"{path.name}: '{name}' is not registered in 032")
        assert unwatched == [], (
            "scheduled workflows the dead man cannot see: " + "; ".join(unwatched))

    def test_every_registered_heartbeat_has_a_writer(self):
        """The reverse drift: a registry row nothing writes goes overdue
        forever and trains the operator to ignore the queue."""
        writers = set()
        for doc in _scheduled_workflows().values():
            writers.update(_posted_names(_checkin_steps(doc)))
        # The sweep writes its own; pg_cron is its writer, not a workflow.
        orphans = _seeded_heartbeat_names() - writers - {SWEEP}
        assert orphans == set(), f"registered but never written: {sorted(orphans)}"

    def test_the_sweep_watches_itself_so_the_other_half_has_something_to_read(self):
        assert SWEEP in _seeded_heartbeat_names()

    @pytest.mark.parametrize("path", sorted(_scheduled_workflows()), ids=lambda p: p.name)
    def test_a_check_in_never_runs_on_a_failed_job(self, path):
        """`if: always()` would turn the switch into a rubber stamp: the job
        would report alive on exactly the runs where it did nothing."""
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in _checkin_steps(doc):
            cond = str(step.get("if", "")).lower()
            assert "always()" not in cond and "failure()" not in cond, (
                f"{path.name}: check-in is gated on '{cond}', so a failed run still "
                "reports itself alive")


class TestTheScanWatchesTheSweep:
    """GitHub's half of the mutual watch. pg_cron going quiet is invisible from
    inside Postgres, so this is the only thing that can report it."""

    def test_a_missing_registry_row_is_urgent_not_silence(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls, heartbeats=[])
        _write_artifacts(monkeypatch, tmp_path)

        r = _run_scan()
        assert r.status_code == 200
        assert r.json()["detectors"]["dead_man"] == {"installed": False}
        (payload,) = (p for p in _rpcs(calls, "record_ops_incident")
                      if p["p_dedup_key"] == SWEEP_KEY)
        assert payload["p_priority"] == "urgent"
        assert payload["p_failure_state"] == "blocked"

    def test_an_absent_view_is_the_same_incident_as_an_absent_row(
            self, monkeypatch, tmp_path):
        """This is what makes the check-in route's tolerant answer honest: if
        the view is missing the scan must still say so, loudly, every day."""
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls, schema_missing=True)
        _write_artifacts(monkeypatch, tmp_path)

        r = _run_scan()
        assert r.json()["detectors"]["dead_man"] == {"installed": False}
        (payload,) = (p for p in _rpcs(calls, "record_ops_incident")
                      if p["p_dedup_key"] == SWEEP_KEY)
        assert payload["p_priority"] == "urgent"
        assert r.json()["skipped"] == [] or all(
            s.get("detector") != "dead_man" for s in r.json()["skipped"])

    def test_a_stalled_sweep_opens_an_incident_carrying_how_late_it_is(
            self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls,
                          heartbeats=[_heartbeat(overdue_seconds=7200)])
        _write_artifacts(monkeypatch, tmp_path)

        r = _run_scan()
        assert r.json()["detectors"]["dead_man"]["overdue"] is True
        (payload,) = (p for p in _rpcs(calls, "record_ops_incident")
                      if p["p_dedup_key"] == SWEEP_KEY)
        assert payload["p_kind"] == "collector_failure"
        assert payload["p_priority"] == "urgent"
        assert payload["p_failure_state"] == "failed"
        assert 7100 <= payload["p_detail"]["overdue_seconds"] <= 7300

    def test_a_sweep_that_never_once_ran_is_blocked_not_merely_late(
            self, monkeypatch, tmp_path):
        """Migration applied, pg_cron never armed. 'Wired up but never called'
        is this repo's most common defect; it must not read as warming up."""
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls,
                          heartbeats=[_heartbeat(never_seen=True)])
        _write_artifacts(monkeypatch, tmp_path)

        _run_scan()
        (payload,) = (p for p in _rpcs(calls, "record_ops_incident")
                      if p["p_dedup_key"] == SWEEP_KEY)
        assert payload["p_failure_state"] == "blocked"
        assert payload["p_detail"]["last_seen_at"] is None

    def test_a_live_sweep_files_nothing(self, monkeypatch, tmp_path):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls)
        _write_artifacts(monkeypatch, tmp_path)

        r = _run_scan()
        assert r.json()["detectors"]["dead_man"]["overdue"] is False
        assert [p for p in _rpcs(calls, "record_ops_incident")
                if p["p_dedup_key"] == SWEEP_KEY] == []
        assert [p for p in _rpcs(calls, "record_ops_recovery")
                if p["p_dedup_key"] == SWEEP_KEY] == []

    def test_a_sweep_that_came_back_closes_its_own_incident(self, monkeypatch, tmp_path):
        """The evidence is complete — the database timestamped the check-in —
        so unlike drift, this recovery may auto-resolve."""
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[{"dedup_key": SWEEP_KEY}], calls=calls)
        _write_artifacts(monkeypatch, tmp_path)

        _run_scan()
        (payload,) = (p for p in _rpcs(calls, "record_ops_recovery")
                      if p["p_dedup_key"] == SWEEP_KEY)
        assert payload["p_auto_resolve"] is True

    def test_an_unreadable_heartbeat_table_is_a_reported_skip_not_a_500(
            self, monkeypatch, tmp_path):
        """Same rule as every other detector: a monitor that pages on its own
        failure is one more thing to monitor."""
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], calls=calls, heartbeats=None)
        _write_artifacts(monkeypatch, tmp_path)
        monkeypatch.setattr(ops_mod, "_parse_ts", lambda _v: (_ for _ in ()).throw(RuntimeError("boom")))

        r = _run_scan()
        assert r.status_code == 200
        assert any(e.get("detector") == "dead_man" for e in r.json()["errors"])


    def test_the_databases_verdict_wins_over_this_instances_clock(
            self, monkeypatch, tmp_path):
        """`overdue` is computed by the view against the database clock. A
        Render container with a skewed clock must not be able to invent or
        hide an outage — and when the column is absent, the fallback says so
        in the summary instead of passing itself off as the same thing."""
        _scan_env(monkeypatch)
        row = _heartbeat()
        row.pop("overdue")
        _install_supabase(monkeypatch, open_rows=[], heartbeats=[row])
        _write_artifacts(monkeypatch, tmp_path)
        assert _run_scan().json()["detectors"]["dead_man"]["judged_by_clock"] == "backend"

        _install_supabase(monkeypatch, open_rows=[], heartbeats=[_heartbeat()])
        assert _run_scan().json()["detectors"]["dead_man"]["judged_by_clock"] == "database"


class TestCheckIn:
    """POST /api/cron/heartbeat — the only way a scheduler proves it is alive,
    so every way it can go wrong has to be loud."""

    def _post(self, name="refresh_data", secret="cron-ok", detail=None):
        return client.post(
            "/api/cron/heartbeat",
            headers={"Authorization": f"Bearer {secret}"},
            json={"name": name, **({"detail": detail} if detail else {})},
        )

    def test_503_without_a_configured_secret(self, monkeypatch):
        monkeypatch.delenv("CRON_SECRET", raising=False)
        assert self._post().status_code == 503

    def test_401_with_the_wrong_secret(self, monkeypatch):
        _scan_env(monkeypatch)
        assert self._post(secret="wrong").status_code == 401

    def test_a_check_in_reaches_the_rpc_with_its_evidence(self, monkeypatch):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, calls=calls, rpc_result=True)

        r = self._post(detail={"run_id": "123"})
        assert r.status_code == 200
        (payload,) = _rpcs(calls, "record_ops_heartbeat")
        assert payload == {"p_name": "refresh_data", "p_detail": {"run_id": "123"}}

    def test_an_unknown_name_is_a_404_not_a_new_row(self, monkeypatch):
        """A typo in a workflow must fail that step. Inserting on demand would
        satisfy nothing while the real heartbeat stayed overdue."""
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, calls=calls, rpc_result=False)

        r = self._post(name="refesh_data")
        assert r.status_code == 404
        assert "refesh_data" in r.json()["detail"]
        assert [c for c in calls if c["method"] == "POST" and "ops_heartbeat_status" in c["url"]] == []

    def test_a_rejected_write_is_a_502_not_a_cheerful_ok(self, monkeypatch):
        _scan_env(monkeypatch)
        _install_supabase(monkeypatch, rpc_result=None, rpc_status=500)
        assert self._post().status_code == 502

    def test_a_genuine_404_from_storage_is_still_a_502(self, monkeypatch):
        """The not-installed answer is keyed on PostgREST's schema-cache code,
        not on the bare status, so an ordinary 404 cannot borrow it."""
        _scan_env(monkeypatch)
        _install_supabase(monkeypatch, rpc_result={"message": "no"}, rpc_status=404)
        assert self._post().status_code == 502

    def test_an_unapplied_migration_reports_itself_instead_of_failing_the_job(
            self, monkeypatch):
        """Migration 032 not applied yet is a fact about the monitor, and
        _scan_dead_man already files it as an urgent incident. Failing here as
        well would cost a three-hour data refresh over a check-in."""
        _scan_env(monkeypatch)
        _install_supabase(monkeypatch, schema_missing=True)
        r = self._post()
        assert r.status_code == 200
        assert r.json()["status"] == "not_installed"

    def test_an_empty_name_is_a_400(self, monkeypatch):
        _scan_env(monkeypatch)
        _install_supabase(monkeypatch)
        assert self._post(name="   ").status_code == 400
