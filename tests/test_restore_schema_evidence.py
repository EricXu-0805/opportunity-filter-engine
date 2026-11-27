import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import restore_drill as drill
from scripts import restore_schema_evidence as schema
from scripts.check_migration_parity import Committed


def test_digests_come_from_observed_columns_and_applied_migrations(monkeypatch):
    observed = {"bucket_catalog_unfiltered": True, "ddl_sha256": "d" * 64, "ddl_count": 2, "columns": [{"table_name": "sample", "column_name": "title"}],
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
    observed["bucket_catalog_unfiltered"] = False
    with pytest.raises(ValueError, match="unfiltered"):
        schema.observe("scratch", "example-point")


def test_session_pooler_uses_the_project_role_and_safe_diagnostics(monkeypatch):
    host = "aws-1-us-east-1.pooler.supabase.com"
    calls = []

    def deny(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(2, command, stderr="password authentication failed: private-message")

    monkeypatch.setattr(subprocess, "run", deny)
    with pytest.raises(schema.CatalogueConnectionError, match="password-file entry") as failed:
        schema.observe("scratch", "point", host)
    command, = calls
    assert command[command.index("-h") + 1] == host
    assert command[command.index("-U") + 1] == "postgres.scratch"
    assert command[command.index("-p") + 1] == "5432"
    assert command.index("BEGIN READ ONLY") < command.index(schema.QUERY)
    assert "private-message" not in str(failed.value)

    with pytest.raises(schema.CatalogueConnectionError, match="pooler hostname"):
        schema.observe("scratch", "point", "not-a-pooler.invalid")
    assert len(calls) == 1


def test_runbook_attachment_manifest_matches_reader(tmp_path):
    from scripts import restore_attachment_evidence as attachments

    runbook = Path(__file__).resolve().parents[1] / "docs" / "DISASTER_RECOVERY.md"
    manifest = re.search(r"```json\n(.*?)\n```", runbook.read_text(), re.DOTALL).group(1)
    path = tmp_path / "inventory.json"
    path.write_text(manifest)
    fields = json.loads(manifest)
    inventory = attachments._manifest(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                                      fields["source_environment"], fields["source_backup_id"])
    assert inventory["tracker-attachment-versions"] is None
    assert inventory["tracker-attachments"]["example.pdf"] == (3, hashlib.sha256(b"abc").hexdigest())


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
    older = record["restored_schema_version"] | {"method": "postgres-application-ddl-and-migrations-v2"}
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
    part["row_counts"] = dict.fromkeys(drill._REQUIRED_TABLES, 1)
    part["rows_stamped_after"] = dict.fromkeys(drill._REQUIRED_TABLES, 0)
    part["recovery_point_time"] = at
    from scripts.restore_attachment_evidence import catalogue_bytes

    expected_storage = {name: {"public": False, "objects": {}} for name in (
        "tracker-attachments", "application-materials", "tracker-attachment-versions")}
    expected_storage["tracker-attachments"]["objects"]["private.txt"] = len(b"synthetic")
    part["storage_catalogue_sha256"] = hashlib.sha256(catalogue_bytes("source", "point", expected_storage)).hexdigest()
    source_path = tmp_path / "source-schema.json"
    source_path.write_bytes(schema.manifest_bytes(part))
    body = b"synthetic"
    bucket = "tracker-attachments"
    manifest = {"version": 2, "source_environment": "source", "source_backup_id": "point", "buckets": {
        bucket: [{"key": "private.txt", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}],
        "application-materials": [], "tracker-attachment-versions": []}}
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
    monkeypatch.setattr(schema, "observe", lambda project, point, pooler: part | {"project_ref": project,
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


@pytest.fixture
def pg_socket_dir():
    # pytest's nested temporary path can exceed sockaddr_un.sun_path on macOS.
    with tempfile.TemporaryDirectory(prefix="ofe-pg-", dir="/tmp") as directory:
        yield directory


def test_postgres_ddl_changes_are_observed_with_identical_columns_and_ledger(tmp_path, pg_socket_dir):
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
    subprocess.run([*ctl, "-o", f"-k {pg_socket_dir} -c listen_addresses=''", "-l", tmp_path / "log", "start"],
                   check=True, capture_output=True, timeout=30)
    try:
        def sql(statement):
            return subprocess.check_output(
                [bindir / "psql", "-XAtw", "-v", "ON_ERROR_STOP=1", "-h", pg_socket_dir, "-U", "drill",
                 "-d", "postgres", "-c", statement], text=True, timeout=15,
            )

        sql("CREATE SCHEMA supabase_migrations; CREATE TABLE supabase_migrations.schema_migrations"
            "(version text, name text); INSERT INTO supabase_migrations.schema_migrations VALUES ('1','initial');"
            "CREATE SCHEMA private; CREATE TABLE public.sample(n int, m int); CREATE ROLE reader; "
            "CREATE SCHEMA storage; CREATE TABLE storage.objects(id int); "
            "CREATE TABLE storage.buckets(id text, public bool); "
            "INSERT INTO storage.buckets VALUES ('tracker-attachments', false), ('unrelated', false)")
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
            ("ALTER TABLE public.sample ENABLE ROW LEVEL SECURITY", True),
            ("ALTER TABLE public.sample FORCE ROW LEVEL SECURITY", True),
            ("CREATE POLICY reader_rows ON public.sample FOR SELECT TO reader USING (n > 2)", True),
            ("ALTER POLICY reader_rows ON public.sample USING (n > 5)", True),
            ("DROP POLICY reader_rows ON public.sample", True),
            ("GRANT USAGE ON SCHEMA storage TO reader", True),
            ("GRANT SELECT ON public.sample TO reader", True),
            ("GRANT UPDATE(n) ON public.sample TO reader", True),
            ("REVOKE EXECUTE ON FUNCTION private.answer() FROM PUBLIC", True),
            ("GRANT EXECUTE ON FUNCTION private.answer() TO reader", True),
            ("CREATE TRIGGER track BEFORE INSERT ON storage.objects FOR EACH ROW "
             "EXECUTE FUNCTION private.capture()", True),
            ("DROP TRIGGER track ON storage.objects", True),
            ("CREATE POLICY own_file ON storage.objects FOR SELECT TO reader USING (id = 1)", True),
            ("DROP POLICY own_file ON storage.objects", True),
            ("UPDATE storage.buckets SET public = true WHERE id = 'tracker-attachments'", True),
            ("INSERT INTO storage.buckets VALUES ('tracker-attachment-versions', false)", True),
            ("UPDATE storage.buckets SET public = true WHERE id = 'unrelated'", False),
            ("UPDATE public.sample SET n = 3", False),
        ):
            sql(statement)
            current = json.loads(sql(schema.QUERY))
            assert current["columns"] == first["columns"]
            assert current["migrations"] == first["migrations"]
            assert (current["ddl_sha256"] != previous["ddl_sha256"]) == changed, statement
            previous = current

        sql("CREATE TABLE private.sample(n int); CREATE VIEW public.sample_view AS SELECT n FROM public.sample")
        before = json.loads(sql(schema.QUERY))
        sql("ALTER TABLE private.sample ADD COLUMN owner_id uuid")
        after_column = json.loads(sql(schema.QUERY))
        assert after_column["columns"] != before["columns"]
        assert any(c["table_schema"] == "private" and c["column_name"] == "owner_id"
                   for c in after_column["columns"])
        sql("CREATE OR REPLACE VIEW public.sample_view AS SELECT m AS n FROM public.sample")
        after_view = json.loads(sql(schema.QUERY))
        assert after_view["columns"] == after_column["columns"]
        assert after_view["ddl_sha256"] != after_column["ddl_sha256"]

        # The same psql session fixture exercises both backup capture queries on synthetic tables.
        from scripts import restore_row_evidence

        sql(";".join(f"CREATE TABLE public.{table}(n integer, {stamp} timestamptz DEFAULT now())"
                     for table, stamp in restore_row_evidence.STAMPS.items()))
        point = datetime(2026, 11, 27, 7, 31, 2, tzinfo=UTC)
        sql("INSERT INTO public.favorites VALUES (1, '2026-11-27 07:16:02+00'), (2, '2026-11-27 07:16:03+00'), "
            "(3, '2026-11-27 12:00:00+00'), (4, NULL); INSERT INTO public.profiles VALUES (9, '2026-01-01 00:00:00+00')")
        row_capture = json.loads(sql(restore_row_evidence.capture_query(schema.QUERY, point)))["row_counts"]
        # Counted as possibly later than the backup: stamped inside the margin, after the point, or unstamped.
        assert row_capture == dict.fromkeys(restore_row_evidence.TABLES, [0, 0]) | {"favorites": [4, 3], "profiles": [1, 0]}
        sql("CREATE DATABASE private_archive_fixture")
        db = [bindir / "psql", "-XqAtw", "-v", "ON_ERROR_STOP=1", "-h", pg_socket_dir, "-U", "drill",
              "-d", "private_archive_fixture"]
        subprocess.run([*db, "-c", "CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text, public boolean);"
                        "CREATE TABLE storage.objects(bucket_id text, name text, metadata jsonb);"
                        "INSERT INTO storage.buckets VALUES ('tracker-attachments', false), ('application-materials', false);"
                        "INSERT INTO storage.objects VALUES ('tracker-attachments', 'mock/user.pdf',"
                        "jsonb_build_object('size', 17))"], check=True, capture_output=True, timeout=15)
        command = [*db, "-f", Path(__file__).resolve().parents[1] / "scripts/restore_storage_catalogue.sql"]
        exported = json.loads(subprocess.check_output(command, text=True, timeout=15))
        assert exported == {"tracker-attachments": {"public": False, "objects": {"mock/user.pdf": 17}},
                            "application-materials": {"public": False, "objects": {}}}
    finally:
        subprocess.run([*ctl, "-m", "immediate", "stop"], check=True, capture_output=True, timeout=30)


_EMPTY_BUCKETS = {name: {"public": False, "objects": {}} for name in ("tracker-attachments", "application-materials")}


def _capture_cli(monkeypatch, tmp_path, argv, storage=_EMPTY_BUCKETS):
    import sys

    catalogue = {"bucket_catalog_unfiltered": True, "ddl_sha256": "d" * 64, "ddl_count": 1,
                 "columns": [{"table_name": "sample"}], "migrations": [{"version": "001", "name": "sample"}],
                 "row_counts": dict.fromkeys(drill._REQUIRED_TABLES, [0, 0]),
                 "storage_catalogue": storage}
    connections = []

    def run(args, **kwargs):
        connections.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(catalogue))

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["restore_schema_evidence", "--project-ref", "source",
                                      "--source-backup-id", "point",
                                      "--recovery-point-time", "2026-11-27T07:31:02Z", *argv])
    try:
        code = schema.main()
    except SystemExit as stop:
        code = stop.code
    return code, connections


def test_capture_refuses_used_output_paths_before_connecting_and_leaves_no_stray_file(tmp_path, monkeypatch, capsys):
    receipt, catalogue = tmp_path / "source-schema.json", tmp_path / "catalogue.json"
    argv = ["--out", str(receipt), "--storage-catalogue-out", str(catalogue)]
    receipt.write_text("an earlier capture")
    code, connections = _capture_cli(monkeypatch, tmp_path, argv)
    assert code == 1 and connections == []
    assert receipt.read_text() == "an earlier capture" and not catalogue.exists()
    assert "source-schema.json" in capsys.readouterr().err

    receipt.unlink()
    catalogue.write_text("an earlier catalogue")
    code, connections = _capture_cli(monkeypatch, tmp_path, argv)
    assert code == 1 and connections == [] and not receipt.exists()

    catalogue.unlink()
    code, connections = _capture_cli(monkeypatch, tmp_path, argv)
    assert code == 0 and len(connections) == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["catalogue.json", "source-schema.json"]


def test_capture_receipt_is_owner_only_whatever_the_umask(tmp_path, monkeypatch):
    previous = os.umask(0o022)
    try:
        code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "source-schema.json")])
    finally:
        os.umask(previous)
    assert code == 0
    assert (tmp_path / "source-schema.json").stat().st_mode & 0o077 == 0


def _database_only_drill(tmp_path, monkeypatch, *, ledger_matches_checkout=True, extra=()):
    """Run the drill CLI against a scratch project whose database is a faithful restore."""
    import sys

    from scripts import release_gate

    candidate = release_gate.migration_set_identity()
    at = datetime.now(UTC).isoformat()
    part = {"method": schema.METHOD, "project_ref": "source", "source_backup_id": "point", "observed_at": at,
            "columns_sha256": "a" * 64, "ddl_sha256": "d" * 64, "ddl_count": 2, "history_sha256": "b" * 64,
            "column_count": 23, "migration_count": candidate["count"], "migration_parity": True,
            "matched_filenames_digest": candidate["digest"],
            "row_counts": dict.fromkeys(drill._REQUIRED_TABLES, 1),
            "rows_stamped_after": dict.fromkeys(drill._REQUIRED_TABLES, 0), "recovery_point_time": at}
    if not ledger_matches_checkout:
        part.update(migration_count=candidate["count"] - 1, migration_parity=False, matched_filenames_digest="e" * 16)
    source_path = tmp_path / "source-schema.json"
    source_path.write_bytes(schema.manifest_bytes(part))
    storage_requests = []

    def reply(req):
        path = req.url.path
        if path.startswith("/storage/"):
            storage_requests.append(path)
            return httpx.Response(500)
        if path in ("/api/ready", "/auth/v1/health", "/rest/v1/"):
            return httpx.Response(200, json={})
        return httpx.Response(200, headers={"content-range": f"*/{0 if req.headers['apikey'] == 'anon' else 1}"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setattr(schema, "observe", lambda project, point, pooler: part | {
        "project_ref": project, "observed_at": datetime.now(UTC).isoformat()})
    monkeypatch.setenv("DRILL_SUPABASE_URL", "https://scratch.supabase.co")
    monkeypatch.setenv("DRILL_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("DRILL_ANON_KEY", "anon")
    monkeypatch.setattr(sys, "argv", [
        "restore_drill", "--source-backup-id", "point", "--source-environment", "source",
        "--scratch-environment", "scratch", "--drill-id", "synthetic", "--restore-started-at", at,
        "--source-schema-manifest", str(source_path), "--source-schema-manifest-sha256",
        hashlib.sha256(source_path.read_bytes()).hexdigest(), "--out-dir", str(tmp_path / "records"),
        "--api-base", "https://app.example", *extra])
    out = tmp_path / "records" / "synthetic.json"
    monkeypatch.setattr(release_gate, "load_latest_drill", lambda: (json.loads(out.read_text()), None))
    try:
        code = drill.main()
    except SystemExit as stop:
        return stop.code, None, None, storage_requests
    return code, json.loads(out.read_text()), release_gate.check_restore_drill(), storage_requests


def test_a_database_only_drill_passes_for_what_it_covered_and_records_what_it_did_not(tmp_path, monkeypatch, capsys):
    code, record, gate, storage_requests = _database_only_drill(
        tmp_path, monkeypatch, extra=["--attachments-out-of-scope"])
    assert code == 0 and record["final_result"] == "PASS"
    assert record["attachment_validation"] == "NOT_COVERED" and storage_requests == []
    assert len(record["not_covered"]) == 1 and record["not_covered"][0].startswith("attachment bytes:")
    printed = capsys.readouterr().out
    assert "RESULT: PASS" in printed and "attachment bytes:" in printed.split("RESULT: PASS")[1]
    # The release gate still wants attachment recovery proven before it clears.
    assert (gate["status"], gate["reason"]) == ("UNVERIFIED", "attachments_not_covered")


def test_without_the_explicit_flag_missing_attachment_evidence_still_cannot_pass(tmp_path, monkeypatch):
    code, record, gate, _ = _database_only_drill(tmp_path, monkeypatch)
    assert code == 1 and record["final_result"] == record["attachment_validation"] == "UNVERIFIED"
    assert record["not_covered"] == []


def test_out_of_scope_and_an_attachment_manifest_cannot_be_given_together(tmp_path, monkeypatch):
    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=[
        "--attachments-out-of-scope", "--attachment-manifest", str(tmp_path / "inventory.json")])
    assert code == 2 and record is None


def test_a_restore_that_reproduces_a_project_behind_the_checkout_passes_and_the_gate_still_refuses_it(
        tmp_path, monkeypatch, capsys):
    code, record, gate, _ = _database_only_drill(tmp_path, monkeypatch, ledger_matches_checkout=False,
                                                 extra=["--attachments-out-of-scope"])
    assert code == 0 and record["final_result"] == "PASS"
    assert [line.split(":")[0] for line in record["not_covered"]] == ["this checkout's migrations", "attachment bytes"]
    assert "this checkout's migrations:" in capsys.readouterr().out
    assert (gate["status"], gate["reason"]) == ("UNVERIFIED", "schema_state_advanced")


def test_capture_says_before_the_restore_is_paid_for_that_the_ledger_and_checkout_differ(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schema, "committed_migrations", lambda: [
        Committed("001_sample.sql", "001", "sample", "0" * 32), Committed("002_newer.sql", "002", "newer", "0" * 32)])
    code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "behind.json")])
    printed = capsys.readouterr().out
    assert code == 0 and "002_newer.sql" in printed and "schema_state_advanced" in printed
    digest = hashlib.sha256((tmp_path / "behind.json").read_bytes()).hexdigest()
    assert f"receipt_sha256={digest}" in printed

    monkeypatch.setattr(schema, "committed_migrations", lambda: [Committed("001_sample.sql", "001", "sample", "0" * 32)])
    code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "level.json")])
    assert code == 0 and "schema_state_advanced" not in capsys.readouterr().out


@pytest.mark.parametrize("storage, said", [
    (None, "row security hides"),
    ({"tracker-attachments": {"public": False, "objects": {}}}, "bucket application-materials does not exist"),
    ({"tracker-attachments": {"public": True, "objects": {}},
      "application-materials": {"public": False, "objects": {}}}, "bucket tracker-attachments is public"),
    ({"tracker-attachments": {"public": False, "objects": {"owner/private-name.pdf": None, "owner/b.pdf": 3}},
      "application-materials": {"public": False, "objects": {}}}, "1 object in bucket tracker-attachments has no recorded size"),
])
def test_capture_names_what_is_wrong_with_the_storage_catalogue_and_a_database_capture_does_not_need_it(
        tmp_path, monkeypatch, capsys, storage, said):
    receipt = tmp_path / "source-schema.json"
    code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(receipt), "--storage-catalogue-out",
                                                    str(tmp_path / "catalogue.json")], storage=storage)
    error = capsys.readouterr().err
    assert code == 1 and said in error and "private-name" not in error
    assert not receipt.exists() and not (tmp_path / "catalogue.json").exists()

    code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(receipt)], storage=storage)
    assert code == 0 and "storage_catalogue_sha256" not in json.loads(receipt.read_text())
    assert "attachments can only be declared out of scope" in capsys.readouterr().out
