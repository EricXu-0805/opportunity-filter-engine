import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scripts import restore_drill as drill
from scripts import restore_row_evidence as rows
from scripts import restore_schema_evidence as schema

EMPTY = dict.fromkeys(rows.TABLES, 0)
POINT = datetime(2026, 11, 27, 7, 31, 2, tzinfo=UTC)


@pytest.mark.parametrize("bad", [None, {}, {"profiles": True}, dict.fromkeys(rows.TABLES, -1),
                                 EMPTY | {"profiles": False}])
def test_missing_or_invalid_manifest_cannot_validate_an_apparently_populated_database(bad):
    assert rows.compare(bad, dict.fromkeys(rows.TABLES, 1), EMPTY) == ("UNVERIFIED", [])
    assert rows.compare(dict.fromkeys(rows.TABLES, 1), dict.fromkeys(rows.TABLES, 1), bad) == ("UNVERIFIED", [])


def test_more_rows_stamped_after_the_recovery_point_than_the_table_holds_is_not_evidence():
    assert rows.compare(EMPTY | {"favorites": 2}, EMPTY, EMPTY | {"favorites": 3}) == ("UNVERIFIED", [])


def _scratch(counts):
    def respond(request):
        assert request.method == "GET" and request.url.params["limit"] == "0"
        return httpx.Response(200, headers={"Content-Range": f"*/{counts[request.url.path.rsplit('/', 1)[-1]]}"})
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_rows_written_between_the_backup_and_the_capture_do_not_fail_the_data_step():
    # The capture is taken hours after the nightly backup: one page view and one new favourite
    # are in the live counts and cannot be in the restored backup.
    source = EMPTY | {"profiles": 41, "favorites": 8, "analytics_events": 1200}
    after = EMPTY | {"favorites": 1, "analytics_events": 1}
    with _scratch(source | {"favorites": 7, "analytics_events": 1199}) as client:
        result = drill.validate_data(client, "https://scratch.invalid", "fixture", source, after)
    assert result["result"] == "PASS" and result["different_tables"] == []
    # A favourite removed on the live site since the backup is still in the backup.
    assert rows.compare(source, source | {"favorites": 9, "analytics_events": 1199}, after) == ("PASS", [])
    assert rows.compare(EMPTY, EMPTY, EMPTY) == ("PASS", [])


@pytest.mark.parametrize("restored, table", [({"analytics_events": 600}, "analytics_events"),
                                             ({"analytics_events": 1198}, "analytics_events"),
                                             ({"favorites": 6}, "favorites"), ({"profiles": 0}, "profiles")])
def test_rows_that_existed_at_the_recovery_point_and_are_not_restored_fail(restored, table):
    source = EMPTY | {"profiles": 41, "favorites": 8, "analytics_events": 1200}
    after = EMPTY | {"favorites": 1, "analytics_events": 1}
    with _scratch(source | {"favorites": 7, "analytics_events": 1199} | restored) as client:
        result = drill.validate_data(client, "https://scratch.invalid", "fixture", source, after)
        no_source = drill.validate_data(client, "https://scratch.invalid", "fixture")
    assert result["result"] == "FAIL" and result["different_tables"] == [table]
    assert no_source["result"] == "UNVERIFIED"


def test_an_empty_restore_fails_on_every_table_that_held_rows_at_the_recovery_point():
    source = EMPTY | {"profiles": 41, "favorites": 8, "analytics_events": 1200, "orders": 1}
    status, findings = rows.compare(source, EMPTY, EMPTY | {"favorites": 1, "analytics_events": 1, "orders": 1})
    assert status == "FAIL"
    assert [f["table"] for f in findings] == ["profiles", "favorites", "analytics_events"]


def test_only_a_table_the_application_never_deletes_from_fails_for_holding_extra_rows():
    source = EMPTY | {"usage_events": 10, "saved_searches": 10}
    status, findings = rows.compare(source, source | {"usage_events": 12, "saved_searches": 12}, EMPTY)
    assert status == "FAIL" and [f["table"] for f in findings] == ["usage_events"]
    assert rows.describe(findings[0]) == ("usage_events: restored 12 rows, but the later source capture counted 10 "
                                          "and the application never deletes from this table")


def test_the_failure_text_states_the_observed_numbers():
    source = EMPTY | {"analytics_events": 1200}
    _, findings = rows.compare(source, EMPTY | {"analytics_events": 600}, EMPTY | {"analytics_events": 1})
    assert rows.describe(findings[0]) == (
        "analytics_events: restored 600 rows; the source capture counted 1200, of which 1 may be later than "
        "the backup, so at least 1199 existed at the recovery point and at least 599 are missing")


def test_every_stamp_column_is_a_timestamp_declared_for_its_table():
    migrations = "\n".join(path.read_text() for path in sorted(
        (Path(__file__).resolve().parents[1] / "supabase" / "migrations").glob("*.sql")))
    assert set(rows.STAMPS) == set(rows.TABLES) and rows.GROWING <= set(rows.TABLES)
    for table, column in rows.STAMPS.items():
        body = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?(?:public\.)?{table}\s*\((.*?)\n\);", migrations, re.S)
        assert body and re.search(rf"^\s*{column}\s+timestamptz\b", body.group(1), re.M), table


def test_capture_is_one_statement_and_saved_counts_are_in_the_pinned_manifest(tmp_path, monkeypatch):
    source = EMPTY | {"profiles": 5}
    after = EMPTY | {"profiles": 2}
    fake_catalogue = {"columns": [{"table": "example"}], "migrations": [{"version": "1", "name": "test"}],
                      "ddl_sha256": "d" * 64, "ddl_count": 1,
                      "row_counts": {table: [source[table], after[table]] for table in rows.TABLES}}
    fake_catalogue["bucket_catalog_unfiltered"] = True
    fake_catalogue["storage_catalogue"] = {name: {"public": False, "objects": {}} for name in
                                         ("tracker-attachments", "application-materials")}
    import subprocess

    def run(args, **kwargs):
        query = next(s for s in args if "jsonb_build_object('row_counts'" in s)
        cutoff = (POINT - rows.STAMP_MARGIN).isoformat()
        assert all(f"count(*) FILTER (WHERE {column} IS NULL OR {column} > '{cutoff}'::timestamptz)) "
                   f"FROM public.{table})" in query for table, column in rows.STAMPS.items())
        assert schema.QUERY in query
        return subprocess.CompletedProcess(args, 0, json.dumps(fake_catalogue))

    monkeypatch.setattr(subprocess, "run", run)
    private, private_rows = tmp_path / "private-storage-catalogue.json", tmp_path / "private-rows.json"
    captured = schema.observe("source", "point", include_row_counts=True, storage_catalogue_out=private,
                              recovery_point_time=POINT, row_counts_out=private_rows)
    assert hashlib.sha256(private.read_bytes()).hexdigest() == captured["storage_catalogue_sha256"]
    assert private.stat().st_mode & 0o077 == 0 and private_rows.stat().st_mode & 0o077 == 0
    # The receipt can be copied into a public record: it pins the counts and holds none of them.
    assert hashlib.sha256(private_rows.read_bytes()).hexdigest() == captured["row_evidence_sha256"]
    assert "row_counts" not in captured and "rows_stamped_after" not in captured
    saved = json.loads(private_rows.read_text())
    assert saved["row_counts"] == source and saved["rows_stamped_after"] == after
    assert saved["recovery_point_time"] == POINT.isoformat()
    path = tmp_path / "source.json"
    raw = schema.manifest_bytes(captured)
    path.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    read = schema.read_source_manifest(path, pin)
    assert read["row_evidence_sha256"] == captured["row_evidence_sha256"]
    assert read["recovery_point_time"] == POINT.isoformat()
    private_rows.write_text(private_rows.read_text().replace('"profiles": 5', '"profiles": 6'))
    assert drill._pinned_rows(private_rows, read["row_evidence_sha256"]) == {}
    path.write_bytes(schema.manifest_bytes(captured | {"row_evidence_sha256": "0" * 64}))
    assert schema.read_source_manifest(path, pin) is None
    assert datetime.fromisoformat(captured["observed_at"]) <= datetime.now(UTC)
    with pytest.raises(ValueError, match="recovery point time"):
        schema.observe("source", "point", include_row_counts=True, recovery_point_time=datetime.now(UTC) + timedelta(hours=1))
