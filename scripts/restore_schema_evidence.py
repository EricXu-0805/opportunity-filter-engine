"""Capture application columns, DDL and applied migration identities for a recovery point."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scripts import restore_row_evidence
from scripts.check_migration_parity import applied_rows, committed_migrations, compare
from scripts.restore_attachment_evidence import ALL_BUCKETS, BUCKETS, catalogue_bytes, hidden_prompt

METHOD = "postgres-application-access-ddl-and-migrations-v3"
QUERY = """
WITH application_schema AS (
  SELECT oid, nspname FROM pg_namespace WHERE nspname IN ('public', 'private')
), access_relations AS (
  SELECT c.*, n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname IN ('public','private') AND c.relkind IN ('r','p','v','m','f','S'))
     OR (n.nspname = 'storage' AND c.relname IN ('objects','buckets'))
), access_objects(kind, schema_name, identity, owner_oid, acl) AS (
  SELECT 'schema', nspname, to_jsonb(nspname), nspowner, COALESCE(nspacl, acldefault('n', nspowner))
  FROM pg_namespace WHERE nspname IN ('public','private','storage')
  UNION ALL
  SELECT 'relation', nspname, jsonb_build_array(relkind, relname), relowner,
         COALESCE(relacl, acldefault(CASE WHEN relkind = 'S' THEN 's' ELSE 'r' END::"char", relowner))
  FROM access_relations
  UNION ALL
  SELECT 'column', c.nspname, jsonb_build_array(c.relname, a.attname), c.relowner, a.attacl
  FROM access_relations c JOIN pg_attribute a ON a.attrelid = c.oid
  WHERE a.attnum > 0 AND NOT a.attisdropped AND cardinality(a.attacl) > 0
  UNION ALL
  SELECT 'routine', n.nspname, jsonb_build_array(p.proname, pg_get_function_identity_arguments(p.oid)),
         p.proowner, COALESCE(p.proacl, acldefault('f', p.proowner))
  FROM pg_proc p JOIN application_schema n ON n.oid = p.pronamespace
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
  FROM pg_trigger g JOIN access_relations n ON n.oid = g.tgrelid WHERE NOT g.tgisinternal
  UNION ALL
  SELECT 'routine', n.nspname, to_jsonb(pg_get_functiondef(p.oid))
  FROM pg_proc p JOIN application_schema n ON n.oid = p.pronamespace WHERE p.prokind IN ('f','p','w')
  UNION ALL
  SELECT 'constraint', n.nspname, jsonb_build_array(t.relname, c.conname, pg_get_constraintdef(c.oid), c.convalidated)
  FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
  JOIN application_schema n ON n.oid = t.relnamespace
  UNION ALL
  SELECT 'row-security', nspname, jsonb_build_array(relname, relrowsecurity, relforcerowsecurity)
  FROM access_relations WHERE relkind IN ('r','p')
  UNION ALL
  SELECT 'policy', c.nspname, jsonb_build_array(c.relname, p.polname, p.polcmd, p.polpermissive,
         ARRAY(SELECT (CASE WHEN r = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(r)::text END) COLLATE "C"
               FROM unnest(p.polroles) AS r ORDER BY 1),
         pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid))
  FROM pg_policy p JOIN access_relations c ON c.oid = p.polrelid
  UNION ALL
  SELECT 'access', schema_name, jsonb_build_array(kind, identity, pg_get_userbyid(owner_oid),
         ARRAY(SELECT item::text FROM unnest(acl) AS item ORDER BY item::text COLLATE "C"))
  FROM access_objects
  UNION ALL
  SELECT 'bucket-public', 'storage', jsonb_build_array(id, public) FROM storage.buckets
  WHERE id IN ('tracker-attachments','tracker-attachment-versions','application-materials')
)
SELECT json_build_object(
  'bucket_catalog_unfiltered', NOT row_security_active('storage.buckets'),
  'ddl_count', (SELECT count(*) FROM definitions),
  'ddl_sha256', (SELECT encode(sha256(convert_to(COALESCE(jsonb_agg(
    jsonb_build_array(kind, schema_name, definition)
    ORDER BY kind COLLATE "C", schema_name COLLATE "C", definition::text COLLATE "C"
  ), '[]'::jsonb)::text, 'UTF8')), 'hex') FROM definitions),
  'ddl_parts', (SELECT jsonb_object_agg(part, summary) FROM (
    SELECT kind || '/' || schema_name AS part, jsonb_build_array(count(*), encode(sha256(convert_to(
      jsonb_agg(definition ORDER BY definition::text COLLATE "C")::text, 'UTF8')), 'hex')) AS summary
    FROM definitions GROUP BY kind, schema_name) AS parts),
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


def _storage_problem(buckets: object) -> str | None:
    """Say which bucket is unusable, by name and count only: object keys are private."""
    if not isinstance(buckets, dict):
        return "row security hides storage.buckets or storage.objects from this database role"
    for name in BUCKETS:
        if name not in buckets:
            return f"bucket {name} does not exist"
    for name, bucket in buckets.items():
        if name not in ALL_BUCKETS or not isinstance(bucket, dict) or not isinstance(bucket.get("objects"), dict):
            return f"bucket {name} could not be read"
        if bucket.get("public") is not False:
            return f"bucket {name} is public"
        unsized = sum(type(size) is not int or size < 0 for size in bucket["objects"].values())
        if unsized:
            return f"{unsized} object{' in' if unsized == 1 else 's in'} bucket {name} {'has' if unsized == 1 else 'have'} no recorded size"
    return None


def observe(project: str, backup: str, session_pooler_host: str | None = None, *,
            include_row_counts: bool = False, storage_catalogue_out: Path | None = None,
            recovery_point_time: datetime | None = None, notes: list[str] | None = None,
            row_counts_out: Path | None = None, password: str | None = None) -> dict:
    """Read the named project's catalogue directly or through its shared session pooler.

    ``notes`` collects what an operator should read before paying for a restore.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project) or not backup.strip():
        raise ValueError("a project ref and recovery point are required")
    if include_row_counts and (recovery_point_time is None or recovery_point_time.utcoffset() is None
                               or recovery_point_time > datetime.now(UTC)):
        raise ValueError("the recovery point time must be a past time with a timezone")

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
    if password:
        env["PGPASSWORD"] = password
    query = QUERY
    if include_row_counts:
        row_query = restore_row_evidence.capture_query(QUERY, recovery_point_time)
        storage_query = Path(__file__).with_name("restore_storage_catalogue.sql").read_text()
        query = (f"SELECT snapshot || jsonb_build_object('storage_catalogue', ({storage_query})) "
                 f"FROM ({row_query}) AS backup(snapshot)")
    try:
        result = subprocess.run(
            ["psql", "-XqAtw", "-v", "ON_ERROR_STOP=1", "-h", host, "-p", "5432", "-U", user,
             "-d", "postgres", "-c", "BEGIN READ ONLY", "-c", "SET LOCAL statement_timeout = 20000",
             "-c", "SET LOCAL search_path = pg_catalog", "-c", query, "-c", "COMMIT"],
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
    if catalogue.get("bucket_catalog_unfiltered") is not True:
        raise ValueError("an unfiltered Storage bucket catalogue is required to verify bucket visibility")
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
    if notes is not None:
        if comparison["in_parity"]:
            notes.append(f"migrations: this project's ledger matches the {len(names)} files in this checkout")
        else:
            notes.append(
                "WARNING migrations: this project's ledger and this checkout differ "
                f"(committed and not applied: {comparison['missing'] or 'none'}; applied rows without a file here: "
                f"{len(comparison['extra'])}; duplicated or ambiguous: {len(comparison['duplicates']) + len(comparison['ambiguous'])}). "
                "A drill from this capture can still show that the restore reproduces this project; the release "
                "gate will answer schema_state_advanced until the ledger and the checkout agree and a new drill is run.")
    observation = {
        "method": METHOD, "project_ref": project, "source_backup_id": backup,
        "observed_at": datetime.now(UTC).isoformat(),
        "columns_sha256": _digest(columns), "column_count": len(columns),
        "ddl_sha256": ddl_digest, "ddl_count": ddl_count,
        "history_sha256": _digest(migrations), "migration_count": len(migrations),
        "migration_parity": comparison["in_parity"],
        "matched_filenames_digest": hashlib.sha256("\n".join(names).encode()).hexdigest()[:16],
    }
    # Per kind and schema, so that a mismatch between source and restore can be located.
    parts = catalogue.get("ddl_parts") or {}
    if _valid_parts(parts):
        observation["ddl_parts"] = parts
    if include_row_counts:
        pairs = catalogue.get("row_counts")
        if (not isinstance(pairs, dict) or set(pairs) != set(restore_row_evidence.TABLES)
                or any(not isinstance(pair, list) or len(pair) != 2 for pair in pairs.values())):
            raise ValueError("source table counts incomplete")
        counts = {table: pair[0] for table, pair in pairs.items()}
        stamped_after = {table: pair[1] for table, pair in pairs.items()}
        if not restore_row_evidence.complete(counts) or not restore_row_evidence.complete(stamped_after):
            raise ValueError("source table counts incomplete")
        # The receipt may end up in a public drill record, so it pins the counts instead of holding them.
        rows = restore_row_evidence.evidence_bytes(project, backup, recovery_point_time.isoformat(), counts, stamped_after)
        observation["row_evidence_sha256"] = hashlib.sha256(rows).hexdigest()
        observation["recovery_point_time"] = recovery_point_time.isoformat()
        buckets = catalogue.get("storage_catalogue")
        if storage_catalogue_out is not None:
            problem = _storage_problem(buckets)
            if problem:
                raise ValueError(f"the private Storage catalogue cannot be captured: {problem}. For a database-only "
                                 "drill, run the capture again without --storage-catalogue-out")
            private = catalogue_bytes(project, backup, buckets)
            observation["storage_catalogue_sha256"] = hashlib.sha256(private).hexdigest()
        for path, raw in ((row_counts_out, rows), (storage_catalogue_out, private if storage_catalogue_out else None)):
            if path is not None:
                with tempfile.NamedTemporaryFile(dir=path.parent) as tmp:
                    tmp.write(raw)
                    tmp.flush()
                    os.link(tmp.name, path)
        if storage_catalogue_out is None:
            if notes is not None:
                notes.append("storage catalogue: not captured (no --storage-catalogue-out); with this receipt "
                             "attachments can only be declared out of scope")
            return observation
        if notes is not None:
            notes.append(f"storage catalogue: buckets {len(buckets)}, objects "
                         f"{sum(len(b['objects']) for b in buckets.values())}; "
                         f"storage_catalogue_sha256={observation['storage_catalogue_sha256']}")
    return observation


def database_password(project: str) -> str | None:
    """Ask at a hidden prompt unless the operator already keeps a libpq password file or variable."""
    if os.environ.get("PGPASSFILE") or os.environ.get("PGPASSWORD"):
        return None
    return hidden_prompt(f"{project} database password")


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
    validated = {key: part[key] for key in ("method", "project_ref", "source_backup_id", "observed_at",
                                        "columns_sha256", "column_count", "ddl_sha256", "ddl_count", "history_sha256", "migration_count",
                                        "migration_parity", "matched_filenames_digest")}
    if "ddl_parts" in part:
        if not _valid_parts(part["ddl_parts"]):
            return None
        validated["ddl_parts"] = part["ddl_parts"]
    if "recovery_point_time" in part:
        if aware_timestamp(part["recovery_point_time"]) is None:
            return None
        validated["recovery_point_time"] = part["recovery_point_time"]
    for name in ("row_evidence_sha256", "storage_catalogue_sha256"):
        if name in part:
            pin = part[name]
            if not isinstance(pin, str) or not re.fullmatch(r"[a-f0-9]{64}", pin):
                return None
            validated[name] = pin
    return validated


def _valid_parts(parts: object) -> bool:
    return isinstance(parts, dict) and all(
        isinstance(name, str) and isinstance(row, list) and len(row) == 2 and type(row[0]) is int
        and isinstance(row[1], str) and re.fullmatch(r"[a-f0-9]{64}", row[1]) for name, row in parts.items())


def differing_parts(source: dict, restored: dict) -> list[str]:
    """Which kinds of definition, in which schema, differ between two observations."""
    a, b = source.get("ddl_parts"), restored.get("ddl_parts")
    if not _valid_parts(a) or not _valid_parts(b):
        return []
    return [f"{name} ({a.get(name, [0])[0]} on the source, {b.get(name, [0])[0]} restored)"
            for name in sorted(set(a) | set(b)) if a.get(name) != b.get(name)]


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
    ap.add_argument("--recovery-point-time", required=True,
                    help="when the dashboard says the backup was taken, ISO 8601 with timezone, e.g. 2026-11-27T07:31:02Z")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--row-counts-out", type=Path, required=True, help="new private file with per-table row counts")
    ap.add_argument("--storage-catalogue-out", type=Path, help="new private file with source object keys and sizes")
    args = ap.parse_args()
    recovery_point_time = aware_timestamp(args.recovery_point_time)
    if recovery_point_time is None:
        ap.error("--recovery-point-time must be an ISO 8601 timestamp with a timezone (Z or ±HH:MM)")
    # Each run is a connection to the source project, so refuse a used path before making one.
    private_files = [path for path in (args.row_counts_out, args.storage_catalogue_out) if path is not None]
    for path in (args.out, *private_files):
        if path.exists() or path.is_symlink():
            ap.exit(1, f"Nothing captured: {path} already exists. Captures are never overwritten; "
                       "move the files of the earlier capture away or choose new paths.\n")
    notes: list[str] = []
    try:
        observation = observe(args.project_ref, args.source_backup_id, args.session_pooler_host, include_row_counts=True,
                              storage_catalogue_out=args.storage_catalogue_out, recovery_point_time=recovery_point_time,
                              notes=notes, row_counts_out=args.row_counts_out, password=database_password("Source"))
        receipt = manifest_bytes(observation)
        with os.fdopen(os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as dest:
            dest.write(receipt)
    except (ValueError, OSError) as exc:
        # None of these existed before this run. Private files without the receipt that pins them belong to no capture.
        for path in private_files:
            path.unlink(missing_ok=True)
        ap.exit(1, f"Schema observation unavailable: {exc}\n")
    print(f"receipt: {args.out}")
    print(f"receipt_sha256={hashlib.sha256(receipt).hexdigest()}")
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
