import getpass
import hashlib
import json
import sys

import httpx
import pytest

from scripts import restore_storage_load as load
from scripts.restore_attachment_evidence import BUCKETS


def _setup(tmp_path, monkeypatch, *, status=200):
    key = "user/note #1?.pdf"
    (tmp_path / "archive" / BUCKETS[0] / "user").mkdir(parents=True)
    (tmp_path / "archive" / BUCKETS[1]).mkdir()
    (tmp_path / "archive" / BUCKETS[0] / key).write_bytes(b"abc")
    manifest = tmp_path / "inventory.json"
    manifest.write_text(json.dumps({"version": 2, "source_environment": "source", "source_backup_id": "snapshot", "buckets": {
        BUCKETS[0]: [{"key": key, "size": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}], BUCKETS[1]: [],
        "tracker-attachment-versions": None}}))
    requests = []

    def reply(request):
        requests.append((request.method, request.url.host, request.url.path, request.headers.get("x-upsert"),
                         request.headers.get("apikey"), request.content))
        return httpx.Response(status, json={})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "typed-at-the-prompt")

    def run(scratch="scratch", source="source"):
        monkeypatch.setattr(sys, "argv", [
            "load", "--attachment-manifest", str(manifest), "--attachment-manifest-sha256",
            hashlib.sha256(manifest.read_bytes()).hexdigest(), "--archive", str(tmp_path / "archive"),
            "--source-environment", source, "--source-backup-id", "snapshot", "--scratch-environment", scratch])
        try:
            return load.main()
        except SystemExit as stop:
            return stop.code
    return run, requests, key


def test_every_inventoried_object_is_uploaded_to_the_scratch_project_only(tmp_path, monkeypatch, capsys):
    run, requests, key = _setup(tmp_path, monkeypatch)
    assert run() == 0
    assert requests == [("POST", "scratch.supabase.co", f"/storage/v1/object/{BUCKETS[0]}/{key}", "true",
                         "typed-at-the-prompt", b"abc")]
    printed = capsys.readouterr()
    assert "1 object" in printed.out and "typed-at-the-prompt" not in printed.out + printed.err


@pytest.mark.parametrize("scratch, source", [("source", "source"), ("scratch", "other-project"), ("Not A Ref", "source")])
def test_nothing_is_sent_unless_the_target_is_a_project_other_than_the_inventory_source(tmp_path, monkeypatch, scratch, source):
    run, requests, _ = _setup(tmp_path, monkeypatch)
    assert run(scratch=scratch, source=source) == 1 and requests == []


def test_an_archive_that_differs_from_the_inventory_is_refused_before_any_upload(tmp_path, monkeypatch):
    run, requests, key = _setup(tmp_path, monkeypatch)
    (tmp_path / "archive" / BUCKETS[0] / key).write_bytes(b"abd")
    assert run() == 1 and requests == []


def test_a_refused_upload_is_reported_with_the_bucket_and_not_the_object_name(tmp_path, monkeypatch, capsys):
    run, requests, _ = _setup(tmp_path, monkeypatch, status=403)
    assert run() == 1 and len(requests) == 1
    error = capsys.readouterr().err
    assert "answered 403" in error and BUCKETS[0] in error and "note" not in error
