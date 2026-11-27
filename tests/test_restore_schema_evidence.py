import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
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
    with pytest.raises(schema.CatalogueConnectionError, match="PGPASSWORD or the PGPASSFILE entry") as failed:
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


def test_a_wrong_password_typed_at_the_prompt_is_not_blamed_on_a_password_file(monkeypatch):
    def deny(command, **kwargs):
        raise subprocess.CalledProcessError(2, command, stderr="FATAL: password authentication failed for user")

    monkeypatch.setattr(subprocess, "run", deny)
    with pytest.raises(schema.CatalogueConnectionError) as failed:
        schema.observe("scratch", "point", password="typed-wrong-password")
    assert "the database password typed at the prompt" in str(failed.value)
    assert "PGPASS" not in str(failed.value) and "typed-wrong-password" not in str(failed.value)


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


def test_runbook_starts_the_backend_and_asks_it_before_the_billed_restore():
    # Step 6 comes after the restore has been paid for, so an interpreter that cannot start the
    # backend has to show earlier: the same command, and the drill's question, before step 5.
    runbook = (Path(__file__).resolve().parents[1] / "docs" / "DISASTER_RECOVERY.md").read_text()
    before, after = runbook.split("### Step 5", 1)

    def backend_starts(text):
        return [re.sub(r'SUPABASE_URL="[^"]*"', "SUPABASE_URL", block)
                for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL) if "uvicorn" in block]

    early = backend_starts(before)
    assert len(early) == 1 and early == backend_starts(after)
    assert re.search(r"uvicorn.*```bash\ncurl [^\n]*/api/ready\n```", before, re.DOTALL)


def test_runbook_never_starts_the_backend_with_a_service_role_key():
    # backend/main.py fills unset variables from .env; with production's key and the scratch address
    # the attachment clean-up task would send that key to the scratch project every minute.
    import shlex

    runbook = (Path(__file__).resolve().parents[1] / "docs" / "DISASTER_RECOVERY.md").read_text()
    starts = [shlex.split(block) for block in re.findall(r"```bash\n(.*?)```", runbook, re.DOTALL) if "uvicorn" in block]
    assert starts
    for words in starts:
        assert "SUPABASE_SERVICE_ROLE_KEY=" in words[:words.index("python3")]


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
    rows_path, part["row_evidence_sha256"] = _row_evidence(tmp_path, dict.fromkeys(drill._REQUIRED_TABLES, 1), at)
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
    _typed_secrets(monkeypatch)
    monkeypatch.setattr(schema, "observe", lambda project, point, pooler, **_: part | {"project_ref": project,
                            "source_backup_id": point, "observed_at": datetime.now(UTC).isoformat()})
    monkeypatch.setattr(sys, "argv", ["restore_drill", "--source-backup-id", "point", "--source-environment", "source",
        "--scratch-environment", "scratch", "--drill-id", "synthetic", "--restore-started-at", at,
        "--source-schema-manifest", str(source_path), "--source-schema-manifest-sha256",
        hashlib.sha256(source_path.read_bytes()).hexdigest(), "--source-row-counts", str(rows_path),
        "--attachment-manifest", str(inventory),
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
        # A mismatch can be located: only the part that changed has another digest.
        assert sum(count for count, _ in after_view["ddl_parts"].values()) == after_view["ddl_count"]
        assert schema.differing_parts({"ddl_parts": after_column["ddl_parts"]}, {"ddl_parts": after_view["ddl_parts"]}) == [
            "view/public (1 on the source, 1 restored)"]

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


def _capture_cli(monkeypatch, tmp_path, argv, storage=_EMPTY_BUCKETS, point_time=None, rows=None):
    import sys

    catalogue = {"bucket_catalog_unfiltered": True, "ddl_sha256": "d" * 64, "ddl_count": 1,
                 "columns": [{"table_name": "sample"}], "migrations": [{"version": "001", "name": "sample"}],
                 "row_counts": dict.fromkeys(drill._REQUIRED_TABLES, [0, 0]) | (rows or {}),
                 "storage_catalogue": storage}
    connections = []

    def run(args, **kwargs):
        connections.append((args, kwargs["env"]))
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(catalogue))

    monkeypatch.setattr(subprocess, "run", run)
    if "PGPASSFILE" not in os.environ and "PGPASSWORD" not in os.environ:
        import getpass

        if getpass.getpass.__module__ == "getpass":  # a test that types the password has already replaced it
            monkeypatch.setenv("PGPASSFILE", str(tmp_path / "unused-pgpass"))
    monkeypatch.setattr(sys, "argv", ["restore_schema_evidence", "--project-ref", "source",
                                      "--source-backup-id", "point",
                                      "--recovery-point-time",
                                      point_time or (datetime.now(UTC) - timedelta(hours=9)).isoformat(),
                                      "--row-counts-out", str(tmp_path / "source-rows.json"), *argv])
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
    for earlier in (catalogue, tmp_path / "source-rows.json"):
        earlier.write_text("an earlier private file")
        code, connections = _capture_cli(monkeypatch, tmp_path, argv)
        assert code == 1 and connections == [] and not receipt.exists()
        earlier.unlink()

    code, connections = _capture_cli(monkeypatch, tmp_path, argv)
    assert code == 0 and len(connections) == 1
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["catalogue.json", "source-rows.json", "source-schema.json"]
    assert all((tmp_path / name).stat().st_mode & 0o077 == 0 for name in written)
    pinned = json.loads(receipt.read_text())
    assert pinned["row_evidence_sha256"] == hashlib.sha256((tmp_path / "source-rows.json").read_bytes()).hexdigest()
    assert "row_counts" not in pinned


def test_capture_refuses_a_recovery_point_time_older_than_any_backup_that_is_still_retained(tmp_path, monkeypatch, capsys):
    # Rows stamped after this time are not required of the restore, so a time typed years early
    # (or an example value left in place) would let an empty restore pass.
    argv = ["--out", str(tmp_path / "source-schema.json")]
    code, connections = _capture_cli(monkeypatch, tmp_path, argv,
                                     point_time=(datetime.now(UTC) - timedelta(days=9)).isoformat())
    assert code == 1 and connections == [] and not (tmp_path / "source-schema.json").exists()
    assert "more than 8 days ago" in capsys.readouterr().err
    code, connections = _capture_cli(monkeypatch, tmp_path, [*argv, "--older-backup"],
                                     point_time=(datetime.now(UTC) - timedelta(days=9)).isoformat())
    assert code == 1 and connections == [] and "more than 8 days ago" in capsys.readouterr().err
    code, connections = _capture_cli(monkeypatch, tmp_path, [*argv, "--older-backup"],
                                     point_time=(datetime.now(UTC) - timedelta(days=7, hours=12)).isoformat())
    assert code == 0 and len(connections) == 1


def test_capture_refuses_a_time_before_the_newest_daily_backup_unless_told_the_backup_is_an_older_one(
        tmp_path, monkeypatch, capsys):
    # Step 1 restores the newest daily backup. A time copied from an older row of the backup list, or the
    # example left in place for a week, would exempt days of rows: half a table lost in the restore then passed.
    argv = ["--out", str(tmp_path / "source-schema.json")]
    for early in (timedelta(days=7), timedelta(days=2, hours=1)):
        code, connections = _capture_cli(monkeypatch, tmp_path, argv, point_time=(datetime.now(UTC) - early).isoformat())
        refusal = capsys.readouterr().err
        assert code == 1 and connections == [] and list(tmp_path.iterdir()) == []
        assert f"{early.days} d " in refusal and "--older-backup" in refusal

    # The newest daily backup can be almost a day old when the capture runs.
    code, connections = _capture_cli(monkeypatch, tmp_path, argv,
                                     point_time=(datetime.now(UTC) - timedelta(hours=24, minutes=30)).isoformat())
    assert code == 0 and len(connections) == 1 and "WARNING recovery point" not in capsys.readouterr().out

    # An older backup restored on purpose is said so, and the capture says what that leaves unchecked.
    for name in ("source-schema.json", "source-rows.json"):
        (tmp_path / name).unlink()
    code, connections = _capture_cli(monkeypatch, tmp_path, [*argv, "--older-backup"],
                                     point_time=(datetime.now(UTC) - timedelta(days=7)).isoformat(),
                                     rows={"analytics_events": [1200, 800], "profiles": [41, 10]})
    said = capsys.readouterr().out
    assert code == 0 and len(connections) == 1
    assert "WARNING recovery point" in said and "810 of the 1241 rows" in said and "7 d " in said


def test_the_drill_says_how_many_source_rows_were_not_required_of_the_restore(tmp_path, monkeypatch, capsys):
    counts = dict.fromkeys(drill._REQUIRED_TABLES, 1) | {"analytics_events": 1200}
    code, record, _, _ = _database_only_drill(
        tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], counts=counts, after={"analytics_events": 37},
        scratch=counts | {"analytics_events": 1163})
    assert code == 0 and record["data_validation"] == "PASS"
    printed = capsys.readouterr().out
    assert "\n           37 of the 1222 rows the capture counted are stamped later than" in printed
    assert "1222" not in (tmp_path / "records" / "synthetic.json").read_text()


def test_the_drill_marks_the_rows_it_did_not_require_when_the_recovery_point_is_an_older_backup(tmp_path, monkeypatch, capsys):
    # The capture accepts such a time only with --older-backup. The drill cannot require the rows stamped
    # since, however many they are, so half a table lost in the restore passes here and the line says why.
    counts = dict.fromkeys(drill._REQUIRED_TABLES, 1) | {"analytics_events": 1200}
    code, record, _, _ = _database_only_drill(
        tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], counts=counts, after={"analytics_events": 800},
        scratch=counts | {"analytics_events": 600}, point=(datetime.now(UTC) - timedelta(days=7)).isoformat())
    assert code == 0 and record["data_validation"] == "PASS"
    assert "WARNING, an older backup: 800 of the 1222 rows the capture counted" in capsys.readouterr().out


def test_capture_leaves_no_private_file_behind_when_the_receipt_cannot_be_written(tmp_path, monkeypatch, capsys):
    # Row counts and a catalogue without the receipt that pins them belong to no capture.
    catalogue = tmp_path / "catalogue.json"
    code, connections = _capture_cli(monkeypatch, tmp_path, [
        "--out", str(tmp_path / "no-such-directory" / "source-schema.json"), "--storage-catalogue-out", str(catalogue)])
    assert code == 1 and len(connections) == 1
    assert "Schema observation unavailable" in capsys.readouterr().err
    assert not catalogue.exists() and not (tmp_path / "source-rows.json").exists()


def test_capture_receipt_is_owner_only_whatever_the_umask(tmp_path, monkeypatch):
    previous = os.umask(0o022)
    try:
        code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "source-schema.json")])
    finally:
        os.umask(previous)
    assert code == 0
    assert (tmp_path / "source-schema.json").stat().st_mode & 0o077 == 0


def _row_evidence(tmp_path, counts, at, after=None):
    from scripts import restore_row_evidence

    path = tmp_path / "source-rows.json"
    path.write_bytes(restore_row_evidence.evidence_bytes(
        "source", "point", at, counts, dict.fromkeys(drill._REQUIRED_TABLES, 0) | (after or {})))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _typed_secrets(monkeypatch, typed=None):
    """Answer the hidden prompts; returns the list of prompts shown."""
    import getpass

    typed = typed or {"database password": "database-pw", "service-role key": "service", "anon key": "anon"}
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(value for label, value in typed.items() if label in prompt)

    monkeypatch.setattr(getpass, "getpass", answer)
    return prompts


def _database_only_drill(tmp_path, monkeypatch, *, ledger_matches_checkout=True, extra=(), counts=None, scratch=None,
                         ready_body=None, typed=None, table_error=None, seen=None, anon_rows=None, after=None,
                         fault=None, point=None):
    """Run the drill CLI against a scratch project whose database is a faithful restore."""
    import sys

    from scripts import release_gate

    candidate = release_gate.migration_set_identity()
    at = datetime.now(UTC).isoformat()
    counts = counts or dict.fromkeys(drill._REQUIRED_TABLES, 1)
    scratch = scratch or counts
    anon_key = (typed or {}).get("anon key", "anon")
    rows_path, rows_pin = _row_evidence(tmp_path, counts, point or at, after)
    part = {"method": schema.METHOD, "project_ref": "source", "source_backup_id": "point", "observed_at": at,
            "columns_sha256": "a" * 64, "ddl_sha256": "d" * 64, "ddl_count": 2, "history_sha256": "b" * 64,
            "column_count": 23, "migration_count": candidate["count"], "migration_parity": True,
            "matched_filenames_digest": candidate["digest"],
            "row_evidence_sha256": rows_pin, "recovery_point_time": point or at}
    if not ledger_matches_checkout:
        part.update(migration_count=candidate["count"] - 1, migration_parity=False, matched_filenames_digest="e" * 16)
    source_path = tmp_path / "source-schema.json"
    source_path.write_bytes(schema.manifest_bytes(part))
    storage_requests = []

    def reply(req):
        path = req.url.path
        refused = fault(req) if fault else None
        if refused:
            return refused
        if path.startswith("/storage/"):
            storage_requests.append(path)
            return httpx.Response(500)
        if seen is not None:
            seen.append((req.url.host, req.headers.get("apikey")))
        if path in ("/api/ready", "/auth/v1/health", "/rest/v1/"):
            return httpx.Response(200, json=ready_body or {})
        if table_error and path.endswith("/profiles"):
            return httpx.Response(500, text=table_error.replace("<the key sent>", req.headers["apikey"]))
        table = path.rsplit("/", 1)[1]
        total = (anon_rows or {}).get(table, 0) if req.headers["apikey"] == anon_key else scratch[table]
        return httpx.Response(200, headers={"content-range": f"*/{total}"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    restored = {k: v for k, v in part.items() if k not in ("row_evidence_sha256", "recovery_point_time")}
    observed_with = {}
    monkeypatch.setattr(schema, "observe", lambda project, point, pooler, **kw: observed_with.update(kw) or restored | {
        "project_ref": project, "observed_at": datetime.now(UTC).isoformat()})
    monkeypatch.delenv("PGPASSFILE", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    prompts = _typed_secrets(monkeypatch, typed)
    monkeypatch.setattr(sys, "argv", [
        "restore_drill", "--source-backup-id", "point", "--source-environment", "source",
        "--scratch-environment", "scratch", "--drill-id", "synthetic", "--restore-started-at", at,
        "--source-schema-manifest", str(source_path), "--source-schema-manifest-sha256",
        hashlib.sha256(source_path.read_bytes()).hexdigest(), "--source-row-counts", str(rows_path),
        "--out-dir", str(tmp_path / "records"), "--api-base", "https://app.example", *extra])
    out = tmp_path / "records" / "synthetic.json"
    monkeypatch.setattr(release_gate, "load_latest_drill", lambda: (json.loads(out.read_text()), None))
    try:
        code = drill.main()
    except SystemExit as stop:
        return stop.code, None, None, storage_requests
    if seen is not None:
        seen.append(("prompts", prompts))
        seen.append(("observe", observed_with))
    if not out.exists():
        return code, None, None, storage_requests
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
    (tmp_path / "source-rows.json").unlink()
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
    assert list(tmp_path.iterdir()) == []

    code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(receipt)], storage=storage)
    assert code == 0 and "storage_catalogue_sha256" not in json.loads(receipt.read_text())
    assert "attachments can only be declared out of scope" in capsys.readouterr().out


def test_the_committed_record_holds_no_row_counts_and_the_full_record_stays_private(tmp_path, monkeypatch, capsys):
    counts = dict.fromkeys(drill._REQUIRED_TABLES, 1) | {"profiles": 4177, "orders": 3894, "waitlist": 6151}
    code, record, gate, _ = _database_only_drill(
        tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], counts=counts,
        scratch=counts | {"orders": 1262}, ready_body={"ready": True, "marker": "readiness-body-marker"})
    public = (tmp_path / "records" / "synthetic.json").read_text()
    assert code == 1 and record["data_validation"] == "FAIL"
    for private_value in ("4177", "6151", "3894", "1262", "readiness-body-marker", "row_counts"):
        assert private_value not in public, private_value
    assert record["evidence"]["data"]["different_tables"] == ["orders"]
    assert record["evidence"]["data"]["tables_compared"] == len(drill._REQUIRED_TABLES)
    assert any(issue.startswith("data: orders") for issue in record["issues_found"])
    # The operator still reads the numbers, on the terminal and in the private record.
    assert "restored 1262 rows; the source capture counted 3894" in capsys.readouterr().out
    private = tmp_path / "synthetic.private.json"
    full = json.loads(private.read_text())
    assert private.stat().st_mode & 0o077 == 0
    assert full["source_row_counts"]["profiles"] == 4177 and full["restored_row_counts"]["orders"] == 1262
    assert "readiness-body-marker" in full["api_ready_body"]
    assert gate["status"] == "FAIL"


def test_a_table_an_anonymous_caller_can_read_is_named_in_the_committed_record_and_counted_only_in_the_private_one(
        tmp_path, monkeypatch, capsys):
    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"],
                                              anon_rows={"profiles": 4177}, typed=_TYPED)
    assert code == 1 and record["rls_validation"] == "FAIL"
    assert record["evidence"]["rls"]["anon_readable"] == [{"table": "profiles", "status": 200}]
    assert "4177" not in (tmp_path / "records" / "synthetic.json").read_text()
    assert "profiles: an anonymous caller could read 4177 rows" in capsys.readouterr().out
    assert json.loads((tmp_path / "synthetic.private.json").read_text())["anon_visible_rows"] == {"profiles": 4177}


def test_the_gate_accepts_a_count_free_record_only_when_it_is_bound_to_the_pinned_row_evidence(tmp_path, monkeypatch):
    from scripts import release_gate

    code, record, gate, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"])
    assert code == 0 and gate["reason"] == "attachments_not_covered"
    record["attachment_validation"] = "PASS"  # isolate the data clause, which the gate reads after attachments
    from scripts import restore_attachment_evidence
    monkeypatch.setattr(restore_attachment_evidence, "bound_attachment_verdict", lambda *_: "PASS")

    def verdict(change):
        data = record["evidence"]["data"] | change
        altered = record | {"evidence": record["evidence"] | {"data": data}}
        monkeypatch.setattr(release_gate, "load_latest_drill", lambda: (altered, None))
        got = release_gate.check_restore_drill()
        return got["status"], got.get("reason")

    assert verdict({}) == ("PASS", None)
    assert verdict({"source_rows_sha256": "0" * 64}) == ("UNVERIFIED", "row_count_comparison_incomplete")
    assert verdict({"tables_compared": 1}) == ("UNVERIFIED", "row_count_comparison_incomplete")
    assert verdict({"different_tables": ["favorites"]}) == ("FAIL", "row_count_comparison_incomplete")
    assert verdict({"unreadable_tables": ["favorites"]}) == ("FAIL", "row_count_comparison_incomplete")


def test_a_private_record_is_never_written_inside_the_repository(tmp_path, monkeypatch, capsys):
    inside = Path(drill.__file__).resolve().parents[1] / "data" / "releases" / "drills" / "source-rows.json"
    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=[
        "--attachments-out-of-scope", "--source-row-counts", str(inside)])
    assert code == 1 and record is None
    assert "outside the repository" in capsys.readouterr().out


def test_a_schema_mismatch_names_the_kind_and_schema_that_differ():
    now = datetime.now(UTC).isoformat()
    source = {"method": schema.METHOD, "project_ref": "original", "source_backup_id": "point", "observed_at": now,
              "columns_sha256": "a" * 64, "ddl_sha256": "d" * 64, "ddl_count": 5, "history_sha256": "b" * 64,
              "column_count": 1, "migration_count": 1, "migration_parity": True, "matched_filenames_digest": "c" * 16,
              "ddl_parts": {"policy/public": [3, "1" * 64], "trigger/storage": [2, "2" * 64]}}
    restored = source | {"project_ref": "scratch", "ddl_sha256": "e" * 64, "ddl_count": 6,
                         "ddl_parts": {"policy/public": [3, "1" * 64], "trigger/storage": [3, "3" * 64]}}
    args = SimpleNamespace(drill_id="synthetic", source_backup_id="point", source_environment="original",
                           scratch_environment="scratch", operator="test",
                           source_schema_manifest_sha256=hashlib.sha256(schema.manifest_bytes(source)).hexdigest())
    record = drill.build_record(args, *[{"result": "PASS"} for _ in range(4)], started_at=now,
                                source_schema=source, scratch_schema=restored)
    assert record["final_result"] == "FAIL"
    assert ("schema observations: source_restored_schema_mismatch in trigger/storage (2 on the source, 3 restored)"
            in record["issues_found"])


_TYPED = {"database password": "typed-database-password", "service-role key": "typed-service-role-key",
          "anon key": "typed-anon-key"}


def test_the_drill_takes_its_credentials_from_hidden_prompts_and_from_nowhere_else(tmp_path, monkeypatch):
    # What an operator would otherwise type as `export NAME=value`, which stays in the shell history.
    monkeypatch.setenv("DRILL_SERVICE_ROLE_KEY", "from-the-environment")
    monkeypatch.setenv("DRILL_ANON_KEY", "from-the-environment")
    monkeypatch.setenv("DRILL_SUPABASE_URL", "https://elsewhere.supabase.co")
    seen = []
    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"],
                                              typed=_TYPED, seen=seen)
    assert code == 0 and record["final_result"] == "PASS"
    rest = {pair for pair in seen if isinstance(pair[0], str) and pair[0].endswith(".supabase.co")}
    assert rest == {("scratch.supabase.co", "typed-service-role-key"), ("scratch.supabase.co", "typed-anon-key")}
    assert dict(seen[-2:])["prompts"] == ["Scratch database password (input hidden): ",
                                         "Scratch service-role key (input hidden): ",
                                         "Scratch anon key (input hidden): "]
    assert dict(seen[-2:])["observe"] == {"password": "typed-database-password"}


def test_a_credential_echoed_back_by_the_server_is_not_written_or_printed(tmp_path, monkeypatch, capsys):
    code, record, _, _ = _database_only_drill(
        tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], typed=_TYPED,
        table_error='{"message":"JWT rejected: typed-service-role-key"}')
    assert code == 1 and record["schema_validation"] == "FAIL"
    written = (tmp_path / "records" / "synthetic.json").read_text() + (tmp_path / "synthetic.private.json").read_text()
    printed = capsys.readouterr()
    for secret in _TYPED.values():
        assert secret not in written and secret not in printed.out + printed.err
    assert "JWT rejected: [redacted]" in written


def test_a_credential_cut_short_by_the_length_limit_on_a_server_reply_is_not_written_or_printed(tmp_path, monkeypatch, capsys):
    # Only the first 200 characters of an error reply are kept, and the cut can fall inside the key.
    code, _, _, _ = _database_only_drill(
        tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], typed=_TYPED,
        table_error="x" * 190 + "<the key sent>")
    written = (tmp_path / "records" / "synthetic.json").read_text() + (tmp_path / "synthetic.private.json").read_text()
    printed = capsys.readouterr()
    assert code == 1 and "x" * 190 in written
    for secret in (_TYPED["service-role key"], _TYPED["anon key"]):
        assert secret[:10] not in written + printed.out + printed.err


@pytest.mark.parametrize("label", ["database password", "service-role key", "anon key"])
def test_a_credential_cut_short_by_the_length_limit_on_the_backends_reply_is_not_written(tmp_path, monkeypatch, label):
    # Only the first 400 characters of what /api/ready answered are kept, in the private record.
    def unready(req):
        if req.url.path == "/api/ready":
            return httpx.Response(503, text="x" * 390 + _TYPED[label])

    code, _, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], typed=_TYPED,
                                         fault=unready)
    written = (tmp_path / "records" / "synthetic.json").read_text() + (tmp_path / "synthetic.private.json").read_text()
    assert code == 1 and "x" * 390 in written
    assert _TYPED[label][:10] not in written


def test_without_a_terminal_that_can_hide_input_no_credential_is_read(tmp_path, monkeypatch, capsys):
    import getpass
    import warnings

    def echoing_fallback(prompt):
        warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning, stacklevel=2)
        return "typed-service-role-key"

    seen = []
    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], seen=seen)
    assert code == 0
    monkeypatch.setattr(getpass, "getpass", echoing_fallback)
    del seen[:]
    assert drill.main() == 1
    assert [pair for pair in seen if pair[0] == "scratch.supabase.co"] == []
    assert "interactive terminal" in capsys.readouterr().out


def test_the_capture_asks_for_the_database_password_and_keeps_it_off_the_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PGPASSFILE", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    prompts = _typed_secrets(monkeypatch, _TYPED)
    code, connections = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "source-schema.json")])
    assert code == 0 and prompts == ["Source database password (input hidden): "]
    (argv, env), = connections
    assert env["PGPASSWORD"] == "typed-database-password" and "typed-database-password" not in " ".join(argv)

    # An operator who already keeps a libpq password file is not asked again.
    monkeypatch.setenv("PGPASSFILE", str(tmp_path / "pgpass"))
    for name in ("source-schema.json", "source-rows.json"):
        (tmp_path / name).unlink()
    capsys.readouterr()
    code, connections = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "source-schema.json")])
    assert code == 0 and len(prompts) == 1 and "PGPASSWORD" not in connections[0][1]
    assert "Source database password: not asked for, PGPASSFILE is set" in capsys.readouterr().err

    # A password exported for other work is used too, and wins over the file as in libpq; the capture says which.
    monkeypatch.setenv("PGPASSWORD", "exported-for-another-database")
    for name in ("source-schema.json", "source-rows.json"):
        (tmp_path / name).unlink()
    code, connections = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "source-schema.json")])
    said = capsys.readouterr()
    assert code == 0 and len(prompts) == 1 and connections[0][1]["PGPASSWORD"] == "exported-for-another-database"
    assert "Source database password: not asked for, PGPASSWORD is set" in said.err
    assert "exported-for-another-database" not in said.out + said.err


@pytest.mark.parametrize("place, error", [
    ("/rest/v1/profiles", httpx.LocalProtocolError), ("/rest/v1/", httpx.LocalProtocolError),
    ("/auth/v1/health", httpx.LocalProtocolError), ("/api/ready", httpx.ConnectError),
    ("/rest/v1/orders", RuntimeError), ("/auth/v1/health", RuntimeError)])
def test_a_credential_quoted_in_a_librarys_own_error_is_not_written_or_printed(tmp_path, monkeypatch, capsys, place, error):
    # What reached the record on 2026-11-27: a key pasted, Ctrl-A Ctrl-K pressed, the key pasted again, and
    # h11 quoting the header value it refused. The prompt now refuses such input; here it is let through.
    pasted = {"database password": "invented-database-password", "service-role key": "invented.service-role.key",
              "anon key": "invented.anon.key"}
    typed = {label: f"{value}\x01\x0b{value}" for label, value in pasted.items()}
    for module in (drill, schema):
        monkeypatch.setattr(module, "hidden_prompt", lambda label: next(v for k, v in typed.items() if k in label))

    def fault(req):
        if req.url.path == place:
            raise error("Illegal header value " + " ".join(repr(value.encode()) for value in typed.values()))

    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"], typed=typed,
                                              fault=fault)
    printed = capsys.readouterr()
    written = "".join(path.read_text() for path in (tmp_path / "records" / "synthetic.json", tmp_path / "synthetic.private.json")
                      if path.exists())
    assert code == 1
    for value in pasted.values():
        assert value not in printed.out + printed.err + written
    if error is RuntimeError:  # nothing in the drill expects it, so it ends in a traceback
        assert "RuntimeError: Illegal header value b'[redacted]'" in printed.err and record is None
    else:
        assert "Illegal header value b'[redacted]'" in written and record["final_result"] == "FAIL"


@pytest.mark.parametrize("error", [ValueError, OSError, RuntimeError])
def test_the_capture_never_prints_the_database_password_with_an_error(tmp_path, monkeypatch, capsys, error):
    monkeypatch.delenv("PGPASSFILE", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    _typed_secrets(monkeypatch, _TYPED)

    def observe(*args, password, **kwargs):
        raise error(f"could not start psql with {password!r} in {('PGPASSWORD=' + password).encode()!r}")

    monkeypatch.setattr(schema, "observe", observe)
    code, _ = _capture_cli(monkeypatch, tmp_path, ["--out", str(tmp_path / "source-schema.json")])
    printed = capsys.readouterr()
    assert code == 1 and "could not start psql with '[redacted]'" in printed.err
    assert _TYPED["database password"] not in printed.out + printed.err


def test_the_application_line_gives_the_answer_of_each_of_the_three_services(tmp_path, monkeypatch, capsys):
    # A wrong anon key (another project's, or half a paste): the gateway refuses every request that carries it,
    # and the backend on this machine still answers 200. The line used to give that 200 as the reason.
    def refuse_the_anon_key(req):
        if req.headers.get("apikey") == "anon":
            return httpx.Response(401, json={"message": "Invalid API key"})

    code, record, _, _ = _database_only_drill(tmp_path, monkeypatch, extra=["--attachments-out-of-scope"],
                                              fault=refuse_the_anon_key)
    assert code == 1 and record["application_smoke"] == "FAIL"
    assert "application: FAIL — PostgREST 401, GoTrue 401, /api/ready 200" in record["issues_found"]
