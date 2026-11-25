import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import restore_drill as drill
from scripts import restore_schema_evidence as schema
from scripts.check_migration_parity import Committed


def test_digests_come_from_observed_columns_and_applied_migrations(monkeypatch):
    observed = {"ddl_sha256": "d" * 64, "ddl_count": 2, "columns": [{"table_name": "sample", "column_name": "title"}],
                "migrations": [{"version": "001", "name": "sample"}]}
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs["env"]))
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(observed))

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("PGHOSTADDR", "unused-override")
    monkeypatch.setattr(schema, "committed_migrations",
                        lambda: [Committed("001_sample.sql", "001", "sample", "0" * 32)])
    source = schema.observe("original", "example-point")
    restored = schema.observe("scratch", "example-point")
    assert source["history_sha256"] == restored["history_sha256"]
    assert source["columns_sha256"] == restored["columns_sha256"]
    assert source["migration_parity"] is True
    assert source["migration_count"] == source["column_count"] == 1
    assert "db.original.supabase.co" in calls[0][0] and "db.scratch.supabase.co" in calls[1][0]
    assert "PGHOSTADDR" not in calls[1][1]
    assert calls[1][1]["PGSSLMODE"] == "verify-full"
    observed["columns"][0]["column_name"] = "alt"
    observed["migrations"].append({"version": "002", "name": "next"})
    changed = schema.observe("scratch", "example-point")
    assert changed["history_sha256"] != restored["history_sha256"]
    assert changed["columns_sha256"] != restored["columns_sha256"]
    assert changed["migration_parity"] is False
    assert "table_name" not in json.dumps(changed)


def test_schema_capture_needs_separately_retained_digest_and_project_binding(tmp_path):
    now = datetime.now(UTC).isoformat()
    captured = {"method": schema.METHOD, "project_ref": "original", "source_backup_id": "point",
                "observed_at": now, "columns_sha256": "a" * 64, "ddl_sha256": "d" * 64, "ddl_count": 2,
                "history_sha256": "b" * 64,
                "column_count": 1, "migration_count": 1, "migration_parity": True,
                "matched_filenames_digest": "c" * 16}
    path = tmp_path / "source.json"
    path.write_bytes(schema.manifest_bytes(captured))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert schema.read_source_manifest(path, None) is None
    assert schema.read_source_manifest(path, "f" * 64) is None
    assert schema.read_source_manifest(path, digest) == captured
    expected = {"digest": "c" * 16, "count": 1}
    record = {"source_schema_version": captured, "restored_schema_version": captured | {"project_ref": "scratch"},
              "source_schema_manifest_sha256": digest, "source_backup_id": "point", "source_environment": "original",
              "scratch_environment": "scratch", "restore_started_at": now, "performed_at": now}
    assert schema.schema_verdict(record, expected)[0] == "PASS"
    different_ddl = record["restored_schema_version"] | {"ddl_sha256": "e" * 64}
    assert schema.schema_verdict(record | {"restored_schema_version": different_ddl}, expected)[0] == "FAIL"
    older = record["restored_schema_version"] | {"method": "postgres-public-columns-and-migrations-v1"}
    assert schema.schema_verdict(record | {"restored_schema_version": older}, expected)[0] == "UNVERIFIED"
    assert schema.schema_verdict(record | {"source_schema_manifest_sha256": "0" * 64}, expected)[0] == "UNVERIFIED"
    assert schema.schema_verdict(record | {"source_backup_id": "other"}, expected)[0] == "UNVERIFIED"
    assert schema.schema_verdict(record | {"restored_schema_version": captured}, expected)[0] == "UNVERIFIED"
    assert schema.schema_verdict(record | {"restore_started_at": "2000-01-01T00:00:00Z"}, expected)[0] == "UNVERIFIED"


@pytest.mark.parametrize("mode", ["transport", "redirect", "missing-count"])
def test_table_and_row_checks_require_successful_responses(mode):
    def respond(request):
        if request.url.path.endswith("/profiles"):
            if mode == "transport":
                raise httpx.ConnectError("synthetic", request=request)
            if mode == "redirect":
                return httpx.Response(302, headers={"location": "https://example.invalid/"})
            return httpx.Response(200)
        return httpx.Response(200, headers={"content-range": "*/1"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tables = drill.validate_schema(client, "https://example.invalid", "test")
        rows = drill.validate_data(client, "https://example.invalid", "test")
    if mode != "missing-count":
        assert tables["result"] == "FAIL" and tables["present"] == len(drill._REQUIRED_TABLES) - 1
    assert rows["result"] == "FAIL" and rows["unreadable_tables"] == ["profiles"]


def test_build_record_does_not_fill_unknown_database_versions_from_checkout():
    args = SimpleNamespace(drill_id="synthetic", source_backup_id="point", source_environment="original",
                           scratch_environment="scratch", operator="test")
    record = drill.build_record(args, *[{"result": "PASS"} for _ in range(4)], started_at=drill._now())
    assert record["source_schema_version"] is record["restored_schema_version"] is None
    assert record["attachment_validation"] == record["final_result"] == "UNVERIFIED"


def test_cli_produces_gate_accepted_record_only_with_independent_evidence(tmp_path, monkeypatch):
    import sys

    from scripts import release_gate

    base = "https://scratch.supabase.co"
    candidate = release_gate.migration_set_identity()
    at = datetime.now(UTC).isoformat()
    part = {"method": schema.METHOD, "project_ref": "source", "source_backup_id": "point",
            "observed_at": at, "columns_sha256": "a" * 64, "ddl_sha256": "d" * 64, "ddl_count": 2,
                "history_sha256": "b" * 64,
            "column_count": 23, "migration_count": candidate["count"], "migration_parity": True,
            "matched_filenames_digest": candidate["digest"]}
    source_path = tmp_path / "source-schema.json"
    source_path.write_bytes(schema.manifest_bytes(part))
    body = b"synthetic"
    bucket = "tracker-attachments"
    manifest = {"version": 1, "source_environment": "source", "source_backup_id": "point", "buckets": {
        bucket: [{"key": "private.txt", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}],
        "application-materials": []}}
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(manifest))
    requests = []
    stored_bytes = body

    def reply(req):
        path = req.url.path
        requests.append(path)
        if path.startswith("/storage/v1/bucket/"):
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[1]})
        if path.startswith("/storage/v1/object/list/"):
            files = [{"id": "example", "name": "private.txt"}] if path.endswith(bucket) else []
            files = files[json.loads(req.content)["offset"]:]
            return httpx.Response(200, json=files)
        if path == f"/storage/v1/object/{bucket}/private.txt":
            return httpx.Response(200, content=stored_bytes)
        if path in ("/api/ready", "/auth/v1/health", "/rest/v1/"):
            return httpx.Response(200, json={})
        assert path.startswith("/rest/v1/")
        total = 0 if req.headers["apikey"] == "anon" else 1
        return httpx.Response(200, headers={"content-range": f"*/{total}"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setattr(schema, "observe", lambda project, point: part | {"project_ref": project,
                            "source_backup_id": point, "observed_at": datetime.now(UTC).isoformat()})
    monkeypatch.setenv("DRILL_SUPABASE_URL", base)
    monkeypatch.setenv("DRILL_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("DRILL_ANON_KEY", "anon")
    monkeypatch.setattr(sys, "argv", ["restore_drill", "--source-backup-id", "point", "--source-environment", "source",
        "--scratch-environment", "scratch", "--drill-id", "synthetic", "--restore-started-at", at,
        "--source-schema-manifest", str(source_path), "--source-schema-manifest-sha256",
        hashlib.sha256(source_path.read_bytes()).hexdigest(), "--attachment-manifest", str(inventory),
        "--attachment-manifest-sha256", hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "--out-dir", str(tmp_path / "records"), "--api-base", "https://app.example"])
    out = tmp_path / "records" / "synthetic.json"
    monkeypatch.setattr(release_gate, "load_latest_drill", lambda: (json.loads(out.read_text()), None))
    assert drill.main() == 0
    assert release_gate.check_restore_drill()["status"] == "PASS"
    assert "private.txt" not in out.read_text() and body.decode() not in json.dumps(json.loads(out.read_text())["evidence"])
    assert any(path.endswith("/private.txt") for path in requests)
    stored_bytes = b"different"
    assert drill.main() == 1
    assert release_gate.check_restore_drill()["status"] == "FAIL"


def test_postgres_ddl_changes_are_observed_with_identical_columns_and_ledger(tmp_path):
    config = shutil.which("pg_config")
    if not config or getattr(os, "geteuid", lambda: 0)() == 0:
        pytest.skip("isolated PostgreSQL cluster needs local binaries and an unprivileged user")
    bindir = Path(subprocess.check_output([config, "--bindir"], text=True).strip())
    if not all((bindir / binary).is_file() for binary in ("initdb", "pg_ctl", "psql")):
        pytest.skip("PostgreSQL server tools unavailable")
    data = tmp_path / "db"
    subprocess.run([bindir / "initdb", "-D", data, "-U", "drill", "-A", "trust", "--no-locale"],
                   check=True, capture_output=True, timeout=30)
    ctl = [bindir / "pg_ctl", "-D", data, "-w"]
    subprocess.run([*ctl, "-o", f"-k {tmp_path} -c listen_addresses=''", "-l", tmp_path / "log", "start"],
                   check=True, capture_output=True, timeout=30)
    try:
        def sql(statement):
            return subprocess.check_output(
                [bindir / "psql", "-XAtw", "-v", "ON_ERROR_STOP=1", "-h", tmp_path, "-U", "drill",
                 "-d", "postgres", "-c", statement], text=True, timeout=15,
            )

        sql("CREATE SCHEMA supabase_migrations; CREATE TABLE supabase_migrations.schema_migrations"
            "(version text, name text); INSERT INTO supabase_migrations.schema_migrations VALUES ('1','initial');"
            "CREATE SCHEMA private; CREATE TABLE public.sample(n int, m int)")
        first = previous = json.loads(sql(schema.QUERY))
        for statement, changed in (
            ("INSERT INTO public.sample VALUES (1,2)", False),
            ("CREATE INDEX by_value ON public.sample(n)", True),
            ("DROP INDEX public.by_value; CREATE INDEX by_value ON public.sample(m)", True),
            ("ALTER TABLE public.sample ADD CONSTRAINT positive CHECK(m > 0)", True),
            ("CREATE FUNCTION private.answer() RETURNS int LANGUAGE sql AS 'SELECT 1'", True),
            ("CREATE OR REPLACE FUNCTION private.answer() RETURNS int LANGUAGE sql AS 'SELECT 2'", True),
            ("CREATE FUNCTION private.capture() RETURNS trigger LANGUAGE plpgsql AS "
             "'BEGIN RETURN NEW; END'; CREATE TRIGGER capture BEFORE INSERT ON public.sample "
             "FOR EACH ROW EXECUTE FUNCTION private.capture()", True),
            ("ALTER TABLE public.sample DISABLE TRIGGER capture", True),
            ("UPDATE public.sample SET n = 3", False),
        ):
            sql(statement)
            current = json.loads(sql(schema.QUERY))
            assert current["columns"] == first["columns"]
            assert current["migrations"] == first["migrations"]
            assert (current["ddl_sha256"] != previous["ddl_sha256"]) == changed, statement
            previous = current
    finally:
        subprocess.run([*ctl, "-m", "immediate", "stop"], check=True, capture_output=True, timeout=30)
