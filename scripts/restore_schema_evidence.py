"""Capture application columns, DDL and applied migration identities for a recovery point."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.check_migration_parity import applied_rows, committed_migrations, compare

METHOD = "postgres-application-ddl-and-migrations-v2"
QUERY = """
WITH application_schema AS (
  SELECT oid, nspname FROM pg_namespace WHERE nspname IN ('public', 'private')
), definitions(kind, schema_name, definition) AS (
  SELECT 'index', n.nspname, jsonb_build_array(pg_get_indexdef(i.indexrelid), i.indisvalid, i.indisready)
  FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid
  JOIN application_schema n ON n.oid = t.relnamespace
  UNION ALL
  SELECT 'view', n.nspname, jsonb_build_array(t.relkind, t.relname, pg_get_viewdef(t.oid), t.reloptions)
  FROM pg_class t JOIN application_schema n ON n.oid = t.relnamespace
  WHERE t.relkind IN ('v','m')
  UNION ALL
  SELECT 'trigger', n.nspname, jsonb_build_array(pg_get_triggerdef(g.oid), g.tgenabled)
  FROM pg_trigger g JOIN pg_class t ON t.oid = g.tgrelid
  JOIN application_schema n ON n.oid = t.relnamespace WHERE NOT g.tgisinternal
  UNION ALL
  SELECT 'routine', n.nspname, to_jsonb(pg_get_functiondef(p.oid))
  FROM pg_proc p JOIN application_schema n ON n.oid = p.pronamespace WHERE p.prokind IN ('f','p','w')
  UNION ALL
  SELECT 'constraint', n.nspname, jsonb_build_array(t.relname, c.conname, pg_get_constraintdef(c.oid), c.convalidated)
  FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
  JOIN application_schema n ON n.oid = t.relnamespace
)
SELECT json_build_object(
  'ddl_count', (SELECT count(*) FROM definitions),
  'ddl_sha256', (SELECT encode(sha256(convert_to(COALESCE(jsonb_agg(
    jsonb_build_array(kind, schema_name, definition)
    ORDER BY kind COLLATE "C", schema_name COLLATE "C", definition::text COLLATE "C"
  ), '[]'::jsonb)::text, 'UTF8')), 'hex') FROM definitions),
  'columns', (SELECT json_agg(row_to_json(c) ORDER BY table_schema COLLATE "C", table_name COLLATE "C", ordinal_position)
    FROM (SELECT table_schema, table_name, ordinal_position, column_name, is_nullable, udt_schema, udt_name,
                 column_default, character_maximum_length, numeric_precision, numeric_scale,
                 datetime_precision, is_identity, identity_generation, is_generated,
                 generation_expression, collation_schema, collation_name, domain_schema, domain_name
          FROM information_schema.columns WHERE table_schema IN ('public', 'private')) AS c),
  'migrations', (SELECT json_agg(json_build_object('version', version, 'name', name)
                                 ORDER BY version COLLATE "C")
                 FROM supabase_migrations.schema_migrations)
)
"""


def _digest(value: list) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


class CatalogueConnectionError(ValueError):
    """Operator-visible database connection detail, safe for the drill log."""


def observe(project: str, backup: str, session_pooler_host: str | None = None) -> dict:
    """Read the named project's catalogue directly or through its shared session pooler."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project) or not backup.strip():
        raise ValueError("a project ref and recovery point are required")

    host, user = f"db.{project}.supabase.co", "postgres"
    if session_pooler_host:
        if not re.fullmatch(r"[a-z0-9-]+\.pooler\.supabase\.com", session_pooler_host):
            raise CatalogueConnectionError("use the shared session pooler hostname from the project Connect dialog")
        host, user = session_pooler_host, f"postgres.{project}"

    # Credentials may come from .pgpass or PGPASSWORD. Never include them on argv
    # or pass ambient libpq service/host overrides into a project-bound observation.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")
           or k in {"PGPASSWORD", "PGPASSFILE", "PGSSLROOTCERT"}}
    env.update(PGSSLMODE="verify-full", PGCONNECT_TIMEOUT="10", LC_ALL="C")
    try:
        result = subprocess.run(
            ["psql", "-XqAtw", "-v", "ON_ERROR_STOP=1", "-h", host, "-p", "5432", "-U", user,
             "-d", "postgres", "-c", "BEGIN READ ONLY", "-c", "SET LOCAL statement_timeout = 20000",
             "-c", "SET LOCAL search_path = pg_catalog", "-c", QUERY, "-c", "COMMIT"],
            capture_output=True, text=True, timeout=35, check=True, env=env,
        )
    except FileNotFoundError:
        raise CatalogueConnectionError("psql executable not found; install the PostgreSQL client") from None
    except subprocess.TimeoutExpired:
        raise CatalogueConnectionError("catalogue read timed out; check the database route and server load") from None
    except subprocess.CalledProcessError as exc:
        # Report an actionable category without copying server-controlled text to a public run log.
        message = (exc.stderr or "").lower()
        if "certificate" in message or "ssl" in message:
            hint = "verify PGSSLROOTCERT and the endpoint hostname"
        elif "password" in message or "authentication" in message or "tenant or user not found" in message:
            hint = "verify the project and password-file entry for this host and user"
        elif "permission denied" in message or "does not exist" in message:
            hint = "verify catalogue and migration ledger access"
        else:
            hint = "verify the database route; use the session pooler on an IPv4-only network"
        raise CatalogueConnectionError(f"psql exited {exc.returncode} for {user}@{host}:5432; {hint}") from None
    except OSError:
        raise CatalogueConnectionError("could not execute psql; check the PostgreSQL client installation") from None
    catalogue = json.loads(result.stdout)
    columns = catalogue["columns"]
    migrations = catalogue["migrations"]
    if not isinstance(columns, list) or not columns or not isinstance(migrations, list) or not migrations:
        raise ValueError("application columns and the migration ledger must both be populated")
    ddl_digest = catalogue.get("ddl_sha256")
    ddl_count = catalogue.get("ddl_count")
    if (not isinstance(ddl_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", ddl_digest)
            or type(ddl_count) is not int or ddl_count < 0):
        raise ValueError("application DDL observation missing")
    comparison = compare(committed_migrations(), applied_rows(migrations))
    # Use only filenames matched to actually observed rows. Comparing against the
    # gate's candidate hash is meaningful only when parity was one-to-one.
    names = sorted(item["file"] for item in comparison["matched"])
    return {"method": METHOD, "project_ref": project, "source_backup_id": backup,
            "observed_at": datetime.now(UTC).isoformat(),
            "columns_sha256": _digest(columns), "column_count": len(columns),
            "ddl_sha256": ddl_digest, "ddl_count": ddl_count,
            "history_sha256": _digest(migrations), "migration_count": len(migrations),
            "migration_parity": comparison["in_parity"],
            "matched_filenames_digest": hashlib.sha256("\n".join(names).encode()).hexdigest()[:16]}


def manifest_bytes(observation: dict) -> bytes:
    return (json.dumps(observation, sort_keys=True, indent=2) + "\n").encode()


def read_source_manifest(path: Path | None, expected_sha256: str | None) -> dict | None:
    """The separately retained backup receipt supplies the digest of the capture file."""
    if path is None or not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        return None
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            return None
        part = json.loads(raw)
    except (ValueError, OSError):
        return None
    if not isinstance(part, dict) or not _valid_shape(part):
        return None
    # A source-supplied JSON file is private. Copy only validated metadata.
    return {key: part[key] for key in ("method", "project_ref", "source_backup_id", "observed_at",
                                        "columns_sha256", "column_count", "ddl_sha256", "ddl_count", "history_sha256", "migration_count",
                                        "migration_parity", "matched_filenames_digest")}


def _valid_shape(part: dict) -> bool:
    return (
        part.get("method") == METHOD and isinstance(part.get("project_ref"), str)
        and isinstance(part.get("source_backup_id"), str) and aware_timestamp(part.get("observed_at")) is not None
        and all(isinstance(part.get(k), str) and re.fullmatch(r"[a-f0-9]{64}", part[k])
                for k in ("columns_sha256", "ddl_sha256", "history_sha256"))
        and type(part.get("ddl_count")) is int and part["ddl_count"] >= 0
        and all(type(part.get(k)) is int and part[k] > 0 for k in ("column_count", "migration_count"))
        and type(part.get("migration_parity")) is bool
        and isinstance(part.get("matched_filenames_digest"), str)
        and re.fullmatch(r"[a-f0-9]{16}", part["matched_filenames_digest"]) is not None
    )


def aware_timestamp(value: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value) if isinstance(value, str) else None
        return dt if dt is not None and dt.utcoffset() is not None else None
    except ValueError:
        return None


def schema_verdict(record: dict, expected: dict) -> tuple[str, str]:
    """Check current and historical records without trusting a stored PASS."""
    source = record.get("source_schema_version")
    restored = record.get("restored_schema_version")
    if not all(isinstance(part, dict) and part.get("method") == METHOD
               for part in (source, restored)):
        return "UNVERIFIED", "schema_observation_missing"

    source_ref, scratch_ref = record.get("source_environment"), record.get("scratch_environment")
    backup = record.get("source_backup_id")
    if not source_ref or not scratch_ref or source_ref == scratch_ref or not backup:
        return "UNVERIFIED", "schema_observation_unbound"
    for part, project in ((source, source_ref), (restored, scratch_ref)):
        if part.get("project_ref") != project or part.get("source_backup_id") != backup:
            return "UNVERIFIED", "schema_observation_unbound"
        if not _valid_shape(part):
            return "UNVERIFIED", "schema_observation_incomplete"
    if hashlib.sha256(manifest_bytes(source)).hexdigest() != record.get("source_schema_manifest_sha256"):
        return "UNVERIFIED", "schema_observation_unbound"

    times = [aware_timestamp(v) for v in (source.get("observed_at"), record.get("restore_started_at"),
                                     restored.get("observed_at"), record.get("performed_at"))]
    if any(t is None for t in times) or times != sorted(times) or times[-1] > datetime.now(UTC):
        return "UNVERIFIED", "schema_observation_time_unbound"
    if any(source[k] != restored[k] for k in (
            "columns_sha256", "column_count", "ddl_sha256", "ddl_count", "history_sha256", "migration_count")):
        return "FAIL", "source_restored_schema_mismatch"
    if any(not part["migration_parity"] or part["matched_filenames_digest"] != expected.get("digest")
           or part["migration_count"] != expected.get("count") for part in (source, restored)):
        return "UNVERIFIED", "schema_state_advanced"
    return "PASS", "schema_observations_match"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-ref", required=True)
    ap.add_argument("--session-pooler-host", help="shared session pooler hostname from Supabase Connect")
    ap.add_argument("--source-backup-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        observation = observe(args.project_ref, args.source_backup_id, args.session_pooler_host)
        with args.out.open("xb") as dest:
            dest.write(manifest_bytes(observation))
    except (ValueError, OSError) as exc:
        ap.exit(1, f"Schema observation unavailable: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
