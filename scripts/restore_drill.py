#!/usr/bin/env python3
"""Run a restore drill against a scratch project and record what it proved.

``docs/DISASTER_RECOVERY.md`` §2 has always described the drill correctly and
never produced anything a gate could read: the operator restored, looked at
some tables, and wrote a sentence in a markdown table. Prose is not evidence —
``scripts/release_gate.py`` cannot tell "restored and verified" from "restored
and glanced at", so the ``restore`` gate stayed UNVERIFIED whatever anyone
wrote there.

This performs the four validations §2 requires against a RESTORED SCRATCH
project and emits ``data/releases/drills/<drill_id>.json``, which the gate
validates clause by clause. It never touches production and it never writes a
credential into the record.

    export DRILL_SUPABASE_URL=https://<scratch-ref>.supabase.co
    export DRILL_SERVICE_ROLE_KEY=<scratch service role key>
    export DRILL_ANON_KEY=<scratch anon key>
    python scripts/restore_drill.py \\
        --source-backup-id "2026-09-04T07:30:12Z" \\
        --source-environment mjpirkyduibkakvlbdko \\
        --scratch-environment <scratch-ref>

Why PostgREST rather than psql: it is the path the application itself uses
(``backend/lib/supabase_auth``), so "the app can read the restored database"
is answered by asking the same way the app asks, and the drill needs no
database driver the project does not already ship. It also means the anon-key
leg exercises RLS exactly as an unauthenticated visitor would.

Exit codes: 0 = the drill passed, 1 = it did not. A failing drill still writes
its record — a drill that found a problem is the most valuable kind, and
losing it would be the one outcome worth recording.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from scripts.release_gate import migration_set_identity  # noqa: E402

# Every table the application depends on, from the committed migration set.
# A restore that brings back the database but not these is not a recovery.
_REQUIRED_TABLES = (
    "profiles", "favorites", "interactions", "profile_versions",
    "interaction_status_changes", "saved_searches", "match_feedback",
    "push_subscriptions", "analytics_events", "waitlist", "feedback",
    "feedback_events", "merged_devices", "merge_grants", "orders",
    "usage_events", "resume_renovations", "resume_renovation_versions",
    "professor_follows", "professor_update_reads", "ops_incidents",
    "ops_incident_events", "ops_heartbeats",
)

# Tables whose rows belong to one user. Under RLS an anonymous caller must see
# none of them — that is the property a restore has to bring back, and the one
# most likely to be silently lost, because a restored table with its policies
# missing reads perfectly well to a service-role probe.
_USER_OWNED_TABLES = (
    "profiles", "favorites", "interactions", "saved_searches", "orders",
    "feedback", "ops_incidents",
)

_TIMEOUT = httpx.Timeout(30.0)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _count(client: httpx.Client, base: str, key: str, table: str,
           *, bearer: str | None = None) -> tuple[int | None, int, str]:
    """``(row_count, http_status, note)`` for one table via PostgREST.

    ``count=exact`` with ``limit=0`` returns the count in Content-Range without
    transferring rows, so this stays cheap on a table of any size.
    """
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {bearer or key}",
        "Prefer": "count=exact",
        "Range-Unit": "items",
        "Range": "0-0",
    }
    try:
        resp = client.get(f"{base}/rest/v1/{table}", headers=headers,
                          params={"select": "*", "limit": 0})
    except httpx.HTTPError as exc:
        return None, 0, f"transport error: {exc}"
    content_range = resp.headers.get("content-range", "")
    total: int | None = None
    if "/" in content_range:
        tail = content_range.rsplit("/", 1)[-1]
        if tail.isdigit():
            total = int(tail)
    return total, resp.status_code, resp.text[:200] if resp.status_code >= 400 else ""


def validate_schema(client: httpx.Client, base: str, service_key: str) -> dict:
    """Every required table exists and is reachable by the service role."""
    missing: list[str] = []
    errors: list[dict] = []
    present: list[str] = []
    for table in _REQUIRED_TABLES:
        _, status, note = _count(client, base, service_key, table)
        if status == 404 or (status == 400 and "does not exist" in note):
            missing.append(table)
        elif status >= 400:
            errors.append({"table": table, "status": status, "note": note})
        else:
            present.append(table)
    return {
        "result": "PASS" if not missing and not errors else "FAIL",
        "required_tables": len(_REQUIRED_TABLES),
        "present": len(present),
        "missing_tables": missing,
        "errors": errors,
    }


def validate_data(client: httpx.Client, base: str, service_key: str) -> dict:
    """Representative rows came back, not just empty tables.

    An empty restore satisfies every schema check and none of the point of
    one, so this records the counts and fails when the whole user-owned
    surface is empty — the shape a restore-from-the-wrong-point produces.
    """
    counts: dict[str, int | None] = {}
    unreadable: list[str] = []
    for table in _USER_OWNED_TABLES:
        total, status, _note = _count(client, base, service_key, table)
        if status >= 400:
            unreadable.append(table)
        counts[table] = total
    known = [v for v in counts.values() if isinstance(v, int)]
    populated = [t for t, v in counts.items() if isinstance(v, int) and v > 0]
    result = "PASS"
    if unreadable or not known:
        result = "FAIL"
    elif not populated:
        result = "FAIL"
    return {
        "result": result,
        "row_counts": counts,
        "populated_tables": populated,
        "unreadable_tables": unreadable,
    }


def validate_rls(client: httpx.Client, base: str, anon_key: str) -> dict:
    """An anonymous caller must see no user-owned rows.

    This is the check a service-role-only drill cannot make. Restoring the
    tables without their policies leaves a database that reads fine to an
    admin probe and exposes every student's rows to the internet.
    """
    leaked: list[dict] = []
    checked: list[str] = []
    for table in _USER_OWNED_TABLES:
        total, status, note = _count(client, base, anon_key, table)
        if status in (401, 403) or (status == 200 and total == 0):
            checked.append(table)
            continue
        if status >= 400:
            # An unexpected error is not a pass: we did not establish the
            # property either way.
            leaked.append({"table": table, "status": status,
                           "note": note or "unexpected status"})
            continue
        leaked.append({"table": table, "status": status, "anon_visible_rows": total})
    return {
        "result": "PASS" if not leaked else "FAIL",
        "tables_checked": checked,
        "anon_readable": leaked,
    }


def validate_application(client: httpx.Client, base: str, anon_key: str,
                         api_base: str | None) -> dict:
    """The restored database answers the calls the application makes.

    When ``--api-base`` names a backend pointed at the restored project, its
    ``/api/ready`` is the real answer. Without one, the drill still exercises
    the two endpoints the app cannot start without — PostgREST and GoTrue —
    and says plainly that it did not test a full application boot.
    """
    checks: dict[str, object] = {}
    try:
        rest = client.get(f"{base}/rest/v1/",
                          headers={"apikey": anon_key,
                                   "Authorization": f"Bearer {anon_key}"})
        checks["postgrest_status"] = rest.status_code
    except httpx.HTTPError as exc:
        checks["postgrest_status"] = f"transport error: {exc}"
    try:
        auth = client.get(f"{base}/auth/v1/health",
                          headers={"apikey": anon_key})
        checks["gotrue_status"] = auth.status_code
    except httpx.HTTPError as exc:
        checks["gotrue_status"] = f"transport error: {exc}"

    ready_ok: bool | None = None
    if api_base:
        try:
            ready = client.get(f"{api_base.rstrip('/')}/api/ready")
            checks["api_ready_status"] = ready.status_code
            checks["api_ready_body"] = ready.text[:400]
            ready_ok = ready.status_code == 200
        except httpx.HTTPError as exc:
            checks["api_ready_status"] = f"transport error: {exc}"
            ready_ok = False
    else:
        checks["api_ready_status"] = "not tested: no --api-base supplied"

    reachable = checks.get("postgrest_status") in (200, 401, 404) and \
        checks.get("gotrue_status") == 200
    if api_base:
        result = "PASS" if reachable and ready_ok else "FAIL"
    else:
        # Honest about scope: the data plane answered, a full app boot was not
        # exercised. That is a partial drill, and partial is not PASS.
        result = "PARTIAL" if reachable else "FAIL"
    checks["result"] = result
    return checks


def build_record(args, schema: dict, data: dict, rls: dict, app: dict,
                 started_at: str) -> dict:
    migrations = migration_set_identity()
    issues: list[str] = []
    if schema["result"] != "PASS":
        issues.append(f"schema: missing {schema['missing_tables']} "
                      f"errors {schema['errors']}")
    if data["result"] != "PASS":
        issues.append(f"data: unreadable {data['unreadable_tables']}, "
                      f"populated {data['populated_tables']}")
    if rls["result"] != "PASS":
        issues.append(f"rls: anon could read {rls['anon_readable']}")
    if app["result"] != "PASS":
        issues.append(f"application: {app['result']} — {app.get('api_ready_status')}")

    final = "PASS" if not issues else "FAIL"
    return {
        "drill_id": args.drill_id,
        "performed_at": _now(),
        "source_backup_id": args.source_backup_id,
        "source_environment": args.source_environment,
        "scratch_environment": args.scratch_environment,
        "source_schema_version": migrations,
        "restored_schema_version": migrations,
        "restore_started_at": started_at,
        "restore_completed_at": _now(),
        "schema_validation": schema["result"],
        "data_validation": data["result"],
        "rls_validation": rls["result"],
        "application_smoke": app["result"],
        "issues_found": issues,
        "final_result": final,
        "operator": args.operator,
        "procedure": "docs/DISASTER_RECOVERY.md §2",
        "evidence": {"schema": schema, "data": data, "rls": rls,
                     "application": app},
        # Deliberately no credential of any kind: the record names WHICH
        # project was used, never how to reach it.
        "generated_by": "scripts/restore_drill.py",
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-backup-id", required=True,
                    help="the recovery point restored, as the dashboard names it")
    ap.add_argument("--source-environment", required=True,
                    help="production project ref the backup came from")
    ap.add_argument("--scratch-environment", required=True,
                    help="project ref the backup was restored INTO (never production)")
    ap.add_argument("--drill-id",
                    default=f"drill-{datetime.now(UTC):%Y%m%dT%H%M%SZ}")
    ap.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--api-base",
                    help="backend pointed at the restored project, for /api/ready")
    ap.add_argument("--restore-started-at", default=_now())
    ap.add_argument("--out-dir", type=Path,
                    default=_REPO / "data" / "releases" / "drills")
    args = ap.parse_args()

    base = os.environ.get("DRILL_SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("DRILL_SERVICE_ROLE_KEY", "")
    anon_key = os.environ.get("DRILL_ANON_KEY", "")
    if not base or not service_key or not anon_key:
        print("::error::set DRILL_SUPABASE_URL, DRILL_SERVICE_ROLE_KEY and "
              "DRILL_ANON_KEY for the SCRATCH project")
        return 1
    if args.scratch_environment in base and args.source_environment in base:
        print("::error::scratch and source refer to the same project")
        return 1
    if args.source_environment in base:
        print(f"::error::DRILL_SUPABASE_URL points at the source environment "
              f"{args.source_environment}; a drill never runs against production")
        return 1

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        schema = validate_schema(client, base, service_key)
        data = validate_data(client, base, service_key)
        rls = validate_rls(client, base, anon_key)
        app = validate_application(client, base, anon_key, args.api_base)

    record = build_record(args, schema, data, rls, app, args.restore_started_at)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{record['drill_id']}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"drill_id:  {record['drill_id']}")
    print(f"backup:    {record['source_backup_id']}")
    print(f"scratch:   {record['scratch_environment']}")
    print(f"schema:    {schema['result']} "
          f"({schema['present']}/{schema['required_tables']} tables)")
    print(f"data:      {data['result']} "
          f"({len(data['populated_tables'])} populated table(s))")
    print(f"rls:       {rls['result']}")
    print(f"app smoke: {app['result']}")
    for issue in record["issues_found"]:
        print(f"  ! {issue}")
    print(f"written:   {out.relative_to(_REPO)}")
    print(f"\nRESULT: {record['final_result']}")
    return 0 if record["final_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
