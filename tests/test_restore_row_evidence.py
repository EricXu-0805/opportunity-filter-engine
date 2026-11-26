import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from scripts import restore_drill as drill
from scripts import restore_row_evidence as rows
from scripts import restore_schema_evidence as schema


@pytest.mark.parametrize("bad", [None, {}, {"profiles": True}, dict.fromkeys(rows.TABLES, -1),
                                 dict.fromkeys(rows.TABLES, 0) | {"profiles": False}])
def test_missing_or_invalid_manifest_cannot_validate_an_apparently_populated_database(bad):
    assert rows.compare(bad, dict.fromkeys(rows.TABLES, 1)) == ("UNVERIFIED", [])


def test_readback_requires_an_exact_total_for_every_table():
    source = dict.fromkeys(rows.TABLES, 0) | {"profiles": 7, "favorites": 50}

    def respond(request):
        table = request.url.path.rsplit("/", 1)[-1]
        assert request.method == "GET" and request.url.params["limit"] == "0"
        return httpx.Response(200, headers={"Content-Range": f"*/{1 if table == 'favorites' else source[table]}"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = drill.validate_data(client, "https://scratch.invalid", "fixture", source)
        no_source = drill.validate_data(client, "https://scratch.invalid", "fixture")
    assert result["result"] == "FAIL"
    assert result["different_tables"] == ["favorites"]
    assert no_source["result"] == "UNVERIFIED"
    assert rows.compare(dict.fromkeys(rows.TABLES, 0), dict.fromkeys(rows.TABLES, 0)) == ("PASS", [])


def test_capture_is_one_statement_and_saved_counts_are_in_the_pinned_manifest(tmp_path, monkeypatch):
    source = dict.fromkeys(rows.TABLES, 0) | {"profiles": 5}
    fake_catalogue = {"columns": [{"table": "example"}], "migrations": [{"version": "1", "name": "test"}],
                      "ddl_sha256": "d" * 64, "ddl_count": 1, "row_counts": source}
    fake_catalogue["bucket_catalog_unfiltered"] = True
    fake_catalogue["storage_catalogue"] = {name: {"public": False, "objects": {}} for name in
                                         ("tracker-attachments", "application-materials")}
    import subprocess

    def run(args, **kwargs):
        query = next(s for s in args if "jsonb_build_object('row_counts'" in s)
        assert all(f"(SELECT count(*) FROM public.{t})" in query for t in rows.TABLES)
        assert schema.QUERY in query
        return subprocess.CompletedProcess(args, 0, json.dumps(fake_catalogue))

    monkeypatch.setattr(subprocess, "run", run)
    private = tmp_path / "private-storage-catalogue.json"
    captured = schema.observe("source", "point", include_row_counts=True, storage_catalogue_out=private)
    assert hashlib.sha256(private.read_bytes()).hexdigest() == captured["storage_catalogue_sha256"]
    assert private.stat().st_mode & 0o077 == 0
    path = tmp_path / "source.json"
    raw = schema.manifest_bytes(captured)
    path.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    assert schema.read_source_manifest(path, pin)["row_counts"] == source
    captured["row_counts"]["favorites"] = 1
    path.write_bytes(schema.manifest_bytes(captured))
    assert schema.read_source_manifest(path, pin) is None
    assert datetime.fromisoformat(captured["observed_at"]) <= datetime.now(UTC)
