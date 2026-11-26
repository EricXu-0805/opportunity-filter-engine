#!/usr/bin/env python3
"""Run a restore drill against a scratch project and record what it proved.

See ``docs/DISASTER_RECOVERY.md`` §3 for the backup receipts, scratch
credentials and command. The drill uses PostgreSQL for catalogue and migration
identity, PostgREST and GoTrue for application reads, and Storage for object
inventories and byte comparisons. It records the result under
``data/releases/drills/<drill_id>.json``. An inconclusive or failed drill
writes its record and exits with status 1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from scripts import restore_row_evidence, restore_schema_evidence  # noqa: E402
from scripts.release_gate import migration_set_identity  # noqa: E402
from scripts.restore_attachment_evidence import bound_attachment_verdict, validate_attachments  # noqa: E402

# Every table the application depends on, from the committed migration set.
# A restore that brings back the database but not these is not a recovery.
_REQUIRED_TABLES = restore_row_evidence.TABLES

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
    match = re.fullmatch(r"(?:\*|[0-9]+-[0-9]+)/([0-9]+)", content_range)
    if match:
        total = int(match.group(1))
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
        elif not 200 <= status < 300:
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


def validate_data(client: httpx.Client, base: str, service_key: str, expected_counts: dict | None = None) -> dict:
    """Read every application table and compare exact totals with the selected recovery point."""
    counts: dict[str, int | None] = {}
    unreadable = []
    for table in _REQUIRED_TABLES:
        total, status, _note = _count(client, base, service_key, table)
        if not 200 <= status < 300 or total is None:
            unreadable.append(table)
            total = None
        counts[table] = total
    result, different = restore_row_evidence.compare(expected_counts, counts)
    return {
        "result": "FAIL" if unreadable else result,
        "row_counts": counts,
        "different_tables": different,
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
                 started_at: str, *, source_schema: dict | None = None,
                 scratch_schema: dict | None = None, attachments: dict | None = None) -> dict:
    issues: list[str] = []
    if schema["result"] != "PASS":
        issues.append(f"schema: missing {schema['missing_tables']} "
                      f"errors {schema['errors']}")
    if data["result"] != "PASS":
        issues.append(f"data: unreadable {data['unreadable_tables']}, "
                      f"different {data['different_tables']} (source totals required)")
    if rls["result"] != "PASS":
        issues.append(f"rls: anon could read {rls['anon_readable']}")
    if app["result"] != "PASS":
        issues.append(f"application: {app['result']} — {app.get('api_ready_status')}")

    record = {
        "drill_id": args.drill_id,
        "performed_at": _now(),
        "source_backup_id": args.source_backup_id,
        "source_environment": args.source_environment,
        "scratch_environment": args.scratch_environment,
        "source_schema_version": source_schema,
        "restored_schema_version": scratch_schema,
        "source_schema_manifest_sha256": getattr(args, "source_schema_manifest_sha256", None),
        "attachment_manifest_sha256": getattr(args, "attachment_manifest_sha256", None),
        "restore_started_at": started_at,
        "restore_completed_at": _now(),
        "schema_validation": schema["result"],
        "data_validation": data["result"],
        "rls_validation": rls["result"],
        "application_smoke": app["result"],
        "issues_found": issues,
        "operator": args.operator,
        "procedure": "docs/DISASTER_RECOVERY.md §2",
        "evidence": {"schema": schema, "data": data, "rls": rls,
                     "application": app, "attachments": attachments},
        # Deliberately no credential of any kind: the record names WHICH
        # project was used, never how to reach it.
        "generated_by": "scripts/restore_drill.py",
    }
    schema_status, reason = restore_schema_evidence.schema_verdict(record, migration_set_identity())
    storage_status = bound_attachment_verdict(attachments, record)
    statuses = [schema["result"], data["result"], rls["result"], app["result"], schema_status, storage_status]
    if schema_status != "PASS":
        issues.append(f"schema observations: {reason}")
    if storage_status != "PASS":
        issues.append(f"attachment bytes: {storage_status}")
    record["attachment_validation"] = storage_status
    if any(status in {"FAIL", "PARTIAL"} for status in statuses):
        record["final_result"] = "FAIL"
    elif all(status == "PASS" for status in statuses):
        record["final_result"] = "PASS"
    else:
        record["final_result"] = "UNVERIFIED"
    return record


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
    ap.add_argument("--source-schema-manifest", type=Path,
                    help="catalogue capture bound to the selected recovery point")
    ap.add_argument("--source-schema-manifest-sha256", help="file SHA-256 retained with the backup receipt")
    ap.add_argument("--attachment-manifest", type=Path, help="private backup object inventory")
    ap.add_argument("--attachment-manifest-sha256", help="trusted SHA-256 of the private inventory")
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
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.scratch_environment)
            or args.source_environment == args.scratch_environment
            or base != f"https://{args.scratch_environment}.supabase.co"):
        print("::error::the REST endpoint must name the distinct scratch project")
        return 1

    source_schema = restore_schema_evidence.read_source_manifest(
        args.source_schema_manifest, args.source_schema_manifest_sha256)
    scratch_schema = None
    if source_schema:
        try:
            scratch_schema = restore_schema_evidence.observe(args.scratch_environment, args.source_backup_id)
        except (ValueError, KeyError, TypeError):
            print("::warning::scratch schema observation unavailable")
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
        schema = validate_schema(client, base, service_key)
        data = validate_data(client, base, service_key, (source_schema or {}).get("row_counts"))
        rls = validate_rls(client, base, anon_key)
        app = validate_application(client, base, anon_key, args.api_base)

        attachments = validate_attachments(
            client, base, service_key, manifest_path=args.attachment_manifest,
            manifest_sha256=args.attachment_manifest_sha256, source_environment=args.source_environment,
            source_backup_id=args.source_backup_id, scratch_environment=args.scratch_environment)

    record = build_record(args, schema, data, rls, app, args.restore_started_at,
                          source_schema=source_schema, scratch_schema=scratch_schema, attachments=attachments)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{record['drill_id']}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"drill_id:  {record['drill_id']}")
    print(f"backup:    {record['source_backup_id']}")
    print(f"scratch:   {record['scratch_environment']}")
    print(f"schema:    {schema['result']} "
          f"({schema['present']}/{schema['required_tables']} tables)")
    print(f"data:      {data['result']} "
          f"({len(data['different_tables'])} table count differences)")
    print(f"rls:       {rls['result']}")
    print(f"attachments: {record['attachment_validation']}")
    print(f"app smoke: {app['result']}")
    for issue in record["issues_found"]:
        print(f"  ! {issue}")
    print(f"written:   {out}")
    print(f"\nRESULT: {record['final_result']}")
    return 0 if record["final_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
