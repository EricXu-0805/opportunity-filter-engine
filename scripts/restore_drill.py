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
import hashlib
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
from scripts.restore_attachment_evidence import (  # noqa: E402
    bound_attachment_verdict,
    hidden_prompt,
    run_guarded,
    scrub,
    validate_attachments,
)

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
           *, bearer: str | None = None, secrets: tuple = ()) -> tuple[int | None, int, str]:
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
        # A library's message can quote what it was given: h11 prints the whole header value it refuses.
        return None, 0, f"transport error: {scrub(str(exc), (key, bearer, *secrets))}"
    content_range = resp.headers.get("content-range", "")
    total: int | None = None
    match = re.fullmatch(r"(?:\*|[0-9]+-[0-9]+)/([0-9]+)", content_range)
    if match:
        total = int(match.group(1))
    # Scrub before cutting: the cut can fall inside a key the server repeated, leaving a part scrub() would not match.
    return total, resp.status_code, scrub(resp.text, (key, bearer, *secrets))[:200] if resp.status_code >= 400 else ""


def validate_schema(client: httpx.Client, base: str, service_key: str, secrets: tuple = ()) -> dict:
    """Every required table exists and is reachable by the service role."""
    missing: list[str] = []
    errors: list[dict] = []
    present: list[str] = []
    for table in _REQUIRED_TABLES:
        _, status, note = _count(client, base, service_key, table, secrets=secrets)
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


def validate_data(client: httpx.Client, base: str, service_key: str, expected_counts: dict | None = None,
                  stamped_after: dict | None = None) -> dict:
    """Read every application table and compare its total with what existed at the recovery point."""
    counts: dict[str, int | None] = {}
    unreadable = []
    for table in _REQUIRED_TABLES:
        total, status, _note = _count(client, base, service_key, table)
        if not 200 <= status < 300 or total is None:
            unreadable.append(table)
            total = None
        counts[table] = total
    result, findings = restore_row_evidence.compare(expected_counts, counts, stamped_after)
    return {
        "result": "FAIL" if unreadable else result,
        "tables_compared": len(_REQUIRED_TABLES),
        "different_tables": [finding["table"] for finding in findings],
        "observed": {finding["table"]: finding["observed"] for finding in findings},
        "unreadable_tables": unreadable,
        # Private: main() moves these two out before anything is written to the repository.
        "row_counts": counts,
        "findings": findings,
    }


def _pinned_rows(path: Path | None, pin: object) -> dict:
    """The capture's private row counts, accepted only when the pinned receipt names their digest."""
    try:
        raw = path.read_bytes()
        rows = json.loads(raw) if hashlib.sha256(raw).hexdigest() == pin else None
    except (AttributeError, OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def validate_rls(client: httpx.Client, base: str, anon_key: str, secrets: tuple = ()) -> dict:
    """An anonymous caller must see no user-owned rows.

    This is the check a service-role-only drill cannot make. Restoring the
    tables without their policies leaves a database that reads fine to an
    admin probe and exposes every student's rows to the internet.
    """
    leaked: list[dict] = []
    checked: list[str] = []
    visible: dict[str, int | None] = {}
    for table in _USER_OWNED_TABLES:
        total, status, note = _count(client, base, anon_key, table, secrets=secrets)
        if status in (401, 403) or (status == 200 and total == 0):
            checked.append(table)
            continue
        if status >= 400:
            # An unexpected error is not a pass: we did not establish the
            # property either way.
            leaked.append({"table": table, "status": status,
                           "note": note or "unexpected status"})
            continue
        leaked.append({"table": table, "status": status})
        visible[table] = total
    return {
        "result": "PASS" if not leaked else "FAIL",
        "tables_checked": checked,
        "anon_readable": leaked,
        # Private, like the row counts of the data step: main() moves it out of the committed record.
        "anon_visible_rows": visible,
    }


def validate_application(client: httpx.Client, base: str, anon_key: str,
                         api_base: str | None, secrets: tuple = ()) -> dict:
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
        checks["postgrest_status"] = f"transport error: {scrub(str(exc), (anon_key, *secrets))}"
    try:
        auth = client.get(f"{base}/auth/v1/health",
                          headers={"apikey": anon_key})
        checks["gotrue_status"] = auth.status_code
    except httpx.HTTPError as exc:
        checks["gotrue_status"] = f"transport error: {scrub(str(exc), (anon_key, *secrets))}"

    ready_ok: bool | None = None
    if api_base:
        try:
            ready = client.get(f"{api_base.rstrip('/')}/api/ready")
            checks["api_ready_status"] = ready.status_code
            # Private: main() moves it out of the committed record. Scrubbed before the cut, as in _count().
            checks["api_ready_body"] = scrub(ready.text, (anon_key, *secrets))[:400]
            ready_ok = ready.status_code == 200
        except httpx.HTTPError as exc:
            checks["api_ready_status"] = f"transport error: {scrub(str(exc), (anon_key, *secrets))}"
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
        issues.extend(f"data: {table} {restore_row_evidence.OBSERVED[kind]} (the counts are in the private record)"
                      for table, kind in data.get("observed", {}).items())
        if data["unreadable_tables"]:
            issues.append(f"data: scratch gave no row count for {data['unreadable_tables']}")
        if data["result"] == "UNVERIFIED":
            issues.append("data: no pinned source row counts to compare with")
    if rls["result"] != "PASS":
        issues.append(f"rls: anon could read {rls['anon_readable']}")
    if app["result"] != "PASS":
        issues.append(f"application: {app['result']} — PostgREST {app.get('postgrest_status')}, "
                      f"GoTrue {app.get('gotrue_status')}, /api/ready {app.get('api_ready_status')}")

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
        "procedure": "docs/DISASTER_RECOVERY.md §3",
        "evidence": {"schema": schema, "data": data, "rls": rls,
                     "application": app, "attachments": attachments},
        # Deliberately no credential of any kind: the record names WHICH
        # project was used, never how to reach it.
        "generated_by": "scripts/restore_drill.py",
    }
    candidate = migration_set_identity()
    schema_status, reason = restore_schema_evidence.schema_verdict(record, candidate)
    # What the drill did not test is recorded, never folded into a PASS or left unsaid.
    not_covered: list[str] = []
    if reason == "schema_state_advanced":
        # Source and restore agree; it is this checkout's migration set they both differ from.
        schema_status = "PASS"
        not_covered.append(
            f"this checkout's migrations: the source project and its restore carry the same "
            f"{source_schema['migration_count']} applied migrations, which are not the {candidate['count']} "
            "committed here, so the release gate will not accept this drill for this checkout")
    statuses = [schema["result"], data["result"], rls["result"], app["result"], schema_status]
    if schema_status != "PASS":
        parts = (restore_schema_evidence.differing_parts(source_schema, scratch_schema)
                 if reason == "source_restored_schema_mismatch" else [])
        issues.append(f"schema observations: {reason}{' in ' + ', '.join(parts) if parts else ''}")
    if getattr(args, "attachments_out_of_scope", False):
        storage_status = "NOT_COVERED"
        not_covered.append("attachment bytes: declared out of scope with --attachments-out-of-scope; "
                           "no storage object was listed, read or compared")
    else:
        storage_status = bound_attachment_verdict(attachments, record)
        statuses.append(storage_status)
        if storage_status != "PASS":
            issues.append(f"attachment bytes: {storage_status}")
    record["attachment_validation"] = storage_status
    record["not_covered"] = not_covered
    if any(status in {"FAIL", "PARTIAL"} for status in statuses):
        record["final_result"] = "FAIL"
    elif all(status == "PASS" for status in statuses):
        record["final_result"] = "PASS"
    else:
        record["final_result"] = "UNVERIFIED"
    return record


def _main(typed: list) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-backup-id", required=True,
                    help="the recovery point restored, as the dashboard names it")
    ap.add_argument("--source-environment", required=True,
                    help="production project ref the backup came from")
    ap.add_argument("--scratch-environment", required=True,
                    help="project ref the backup was restored INTO (never production)")
    ap.add_argument("--session-pooler-host", help="scratch shared session pooler hostname from Supabase Connect")
    ap.add_argument("--source-schema-manifest", type=Path,
                    help="catalogue capture bound to the selected recovery point")
    ap.add_argument("--source-schema-manifest-sha256", help="file SHA-256 retained with the backup receipt")
    ap.add_argument("--source-row-counts", type=Path,
                    help="private per-table row counts written by the capture; the full private record is written beside it")
    ap.add_argument("--attachment-manifest", type=Path, help="private backup object inventory")
    ap.add_argument("--attachment-manifest-sha256", help="trusted SHA-256 of the private inventory")
    ap.add_argument("--attachments-out-of-scope", action="store_true",
                    help="run the database legs only and record that attachment bytes were not covered")
    ap.add_argument("--drill-id",
                    default=f"drill-{datetime.now(UTC):%Y%m%dT%H%M%SZ}")
    ap.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--api-base",
                    help="backend pointed at the restored project, for /api/ready")
    ap.add_argument("--restore-started-at", default=_now(),
                    help="ISO 8601 restore start with timezone, e.g. 2026-11-25T18:00:00Z")
    ap.add_argument("--out-dir", type=Path,
                    default=_REPO / "data" / "releases" / "drills")
    args = ap.parse_args()

    if args.attachments_out_of_scope and (args.attachment_manifest or args.attachment_manifest_sha256):
        ap.error("--attachments-out-of-scope cannot be combined with an attachment manifest")
    if restore_schema_evidence.aware_timestamp(args.restore_started_at) is None:
        ap.error("--restore-started-at must be an ISO 8601 timestamp with a timezone (Z or ±HH:MM)")

    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.scratch_environment)
            or args.source_environment == args.scratch_environment):
        print("::error::--scratch-environment must name a project other than the source")
        return 1
    base = f"https://{args.scratch_environment}.supabase.co"
    if args.source_row_counts and args.source_row_counts.resolve().is_relative_to(_REPO):
        print("::error::keep the private row counts, and the private record written beside them, outside the repository")
        return 1

    source_schema = restore_schema_evidence.read_source_manifest(
        args.source_schema_manifest, args.source_schema_manifest_sha256)
    # Credentials come from hidden prompts only; nothing below writes or prints one.
    try:
        password = restore_schema_evidence.database_password("Scratch") if source_schema else None
        service_key = hidden_prompt("Scratch service-role key")
        anon_key = hidden_prompt("Scratch anon key")
    except ValueError as exc:
        print(f"::error::{exc}")
        return 1
    secrets = (password, service_key, anon_key)
    typed.extend(secrets)
    scratch_schema = None
    if source_schema:
        try:
            scratch_schema = restore_schema_evidence.observe(
                args.scratch_environment, args.source_backup_id, args.session_pooler_host, password=password)
        except restore_schema_evidence.CatalogueConnectionError as exc:
            print(scrub(f"::warning::scratch schema observation unavailable: {exc}", secrets))
        except (ValueError, KeyError, TypeError):
            print("::warning::scratch schema observation unavailable")
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
        schema = validate_schema(client, base, service_key, secrets)
        source_rows = _pinned_rows(args.source_row_counts, (source_schema or {}).get("row_evidence_sha256"))
        data = validate_data(client, base, service_key, source_rows.get("row_counts"),
                             source_rows.get("rows_stamped_after"))
        rls = validate_rls(client, base, anon_key, secrets)
        app = validate_application(client, base, anon_key, args.api_base, secrets)

        attachments = None if args.attachments_out_of_scope else validate_attachments(
            client, base, service_key, manifest_path=args.attachment_manifest,
            manifest_sha256=args.attachment_manifest_sha256, source_environment=args.source_environment,
            source_backup_id=args.source_backup_id, scratch_environment=args.scratch_environment)

    # The record below is committed to a public repository: per-table row counts and the backend's
    # reply stay in a private file beside the source counts, bound to the record by two digests.
    restored_counts, findings = data.pop("row_counts"), data.pop("findings")
    anon_visible = rls.pop("anon_visible_rows")
    private = {"source_row_counts": source_rows.get("row_counts"),
               "source_rows_stamped_after": source_rows.get("rows_stamped_after"),
               "restored_row_counts": restored_counts,
               "data_findings": [restore_row_evidence.describe(finding) for finding in findings],
               "anon_visible_rows": anon_visible,
               "api_ready_body": app.pop("api_ready_body", None)}
    data["source_rows_sha256"] = (source_schema or {}).get("row_evidence_sha256") if source_rows else None
    data["restored_rows_sha256"] = (restore_row_evidence.counts_digest(restored_counts)
                                    if restore_row_evidence.complete(restored_counts) else None)

    record = build_record(args, schema, data, rls, app, args.restore_started_at,
                          source_schema=source_schema, scratch_schema=scratch_schema, attachments=attachments)
    # A server's error text is copied into the record; make sure it did not carry a credential back.
    record = json.loads(scrub(json.dumps(record), secrets))
    private = json.loads(scrub(json.dumps(private), secrets))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{record['drill_id']}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    private_out = None
    if args.source_row_counts:
        private_out = args.source_row_counts.parent / f"{record['drill_id']}.private.json"
        with os.fdopen(os.open(private_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as dest:
            dest.write(json.dumps({"drill_id": record["drill_id"], **private, "committed_record": record}, indent=2) + "\n")

    print(f"drill_id:  {record['drill_id']}")
    print(f"backup:    {record['source_backup_id']}")
    print(f"scratch:   {record['scratch_environment']}")
    print(f"schema:    {schema['result']} "
          f"({schema['present']}/{schema['required_tables']} tables)")
    print(f"data:      {data['result']} "
          f"({len(data['different_tables'])} of {len(_REQUIRED_TABLES)} tables outside what the recovery point explains)")
    point = restore_schema_evidence.aware_timestamp((source_schema or {}).get("recovery_point_time"))
    if point and all(restore_row_evidence.complete(private[k]) for k in ("source_row_counts", "source_rows_stamped_after")):
        # Terminal only. A number near the total means the recovery point time is wrong, not that the restore is good.
        captured = restore_schema_evidence.aware_timestamp(source_schema["observed_at"])
        older = captured - point > restore_row_evidence.NEWEST_BACKUP_AGE
        print(f"           {'WARNING, an older backup: ' if older else ''}{sum(private['source_rows_stamped_after'].values())} of the "
              f"{sum(private['source_row_counts'].values())} rows the capture counted are stamped later than "
              f"{(point - restore_row_evidence.STAMP_MARGIN).isoformat()} and were not required of the restore")
    print(f"rls:       {rls['result']}")
    print(f"attachments: {record['attachment_validation']}")
    print(f"app smoke: {app['result']}")
    for issue in record["issues_found"]:
        print(f"  ! {issue}")
    for line in private["data_findings"]:
        print(f"  ! data (private): {line}")
    for table, total in anon_visible.items():
        print(f"  ! rls (private): {table}: an anonymous caller could read {'an uncounted number of' if total is None else total} rows")
    print(f"written:   {out}")
    print(f"private:   {private_out or 'not written (no --source-row-counts)'}")
    print(f"\nRESULT: {record['final_result']}")
    if record["not_covered"]:
        print("not covered by this drill:")
        for line in record["not_covered"]:
            print(f"  - {line}")
    return 0 if record["final_result"] == "PASS" else 1


def main() -> int:
    return run_guarded(_main)


if __name__ == "__main__":
    raise SystemExit(main())
