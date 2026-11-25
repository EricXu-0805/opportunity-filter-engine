"""Capture public column definitions and applied migration identities for a recovery point."""
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

METHOD = "postgres-public-columns-and-migrations-v1"
QUERY = """
SELECT json_build_object(
  'columns', (SELECT json_agg(row_to_json(c) ORDER BY table_name COLLATE "C", ordinal_position)
    FROM (SELECT table_name, ordinal_position, column_name, is_nullable, udt_schema, udt_name,
                 column_default, character_maximum_length, numeric_precision, numeric_scale,
                 datetime_precision, is_identity, identity_generation, is_generated,
                 generation_expression, collation_schema, collation_name, domain_schema, domain_name
          FROM information_schema.columns WHERE table_schema = 'public') AS c),
  'migrations', (SELECT json_agg(json_build_object('version', version, 'name', name)
                                 ORDER BY version COLLATE "C")
                 FROM supabase_migrations.schema_migrations)
)
"""


def _digest(value: list) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def observe(project: str, backup: str) -> dict:
    """Use the named project's direct DB endpoint. Read only catalogue and ledger metadata."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project) or not backup.strip():
        raise ValueError("a project ref and recovery point are required")

    # Credentials may come from .pgpass or PGPASSWORD. Never include them on argv
    # or pass ambient libpq service/host overrides into a project-bound observation.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")
           or k in {"PGPASSWORD", "PGPASSFILE", "PGSSLROOTCERT"}}
    env.update(PGSSLMODE="verify-full", PGCONNECT_TIMEOUT="10",
               PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=20000")
    try:
        result = subprocess.run(
            ["psql", "-XAtw", "-v", "ON_ERROR_STOP=1", "-h", f"db.{project}.supabase.co",
             "-p", "5432", "-U", "postgres", "-d", "postgres", "-c", QUERY],
            capture_output=True, text=True, timeout=35, check=True, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("catalogue read failed; check psql, direct database access and TLS") from None
    catalogue = json.loads(result.stdout)
    columns = catalogue["columns"]
    migrations = catalogue["migrations"]
    if not isinstance(columns, list) or not columns or not isinstance(migrations, list) or not migrations:
        raise ValueError("public columns and the migration ledger must both be populated")
    comparison = compare(committed_migrations(), applied_rows(migrations))
    # Use only filenames matched to actually observed rows. Comparing against the
    # gate's candidate hash is meaningful only when parity was one-to-one.
    names = sorted(item["file"] for item in comparison["matched"])
    return {"method": METHOD, "project_ref": project, "source_backup_id": backup,
            "observed_at": datetime.now(UTC).isoformat(),
            "columns_sha256": _digest(columns), "column_count": len(columns),
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
                                        "columns_sha256", "column_count", "history_sha256", "migration_count",
                                        "migration_parity", "matched_filenames_digest")}


def _valid_shape(part: dict) -> bool:
    return (
        part.get("method") == METHOD and isinstance(part.get("project_ref"), str)
        and isinstance(part.get("source_backup_id"), str) and _timestamp(part.get("observed_at")) is not None
        and all(isinstance(part.get(k), str) and re.fullmatch(r"[a-f0-9]{64}", part[k])
                for k in ("columns_sha256", "history_sha256"))
        and all(type(part.get(k)) is int and part[k] > 0 for k in ("column_count", "migration_count"))
        and type(part.get("migration_parity")) is bool
        and isinstance(part.get("matched_filenames_digest"), str)
        and re.fullmatch(r"[a-f0-9]{16}", part["matched_filenames_digest"]) is not None
    )


def _timestamp(value: object) -> datetime | None:
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

    times = [_timestamp(v) for v in (source.get("observed_at"), record.get("restore_started_at"),
                                     restored.get("observed_at"), record.get("performed_at"))]
    if any(t is None for t in times) or times != sorted(times) or times[-1] > datetime.now(UTC):
        return "UNVERIFIED", "schema_observation_time_unbound"
    if any(source[k] != restored[k] for k in (
            "columns_sha256", "column_count", "history_sha256", "migration_count")):
        return "FAIL", "source_restored_schema_mismatch"
    if any(not part["migration_parity"] or part["matched_filenames_digest"] != expected.get("digest")
           or part["migration_count"] != expected.get("count") for part in (source, restored)):
        return "UNVERIFIED", "schema_state_advanced"
    return "PASS", "schema_observations_match"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-ref", required=True)
    ap.add_argument("--source-backup-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        observation = observe(args.project_ref, args.source_backup_id)
        with args.out.open("xb") as dest:
            dest.write(manifest_bytes(observation))
    except (ValueError, OSError) as exc:
        ap.exit(1, f"Schema observation unavailable: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
