import hashlib
import json
import os
import sys

import pytest

from scripts import restore_storage_manifest as capture
from scripts.restore_attachment_evidence import BUCKETS, VERSION_BUCKET, _manifest


def archive(tmp_path):
    root = tmp_path / "archive"
    key = "user/note #1?.pdf"
    sizes = {BUCKETS[0]: {key: 3}, BUCKETS[1]: {}}
    for bucket, files in sizes.items():
        folder = root / bucket
        folder.mkdir(parents=True)
        for name in files:
            path = folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"abc")
    doc = {"source_environment": "source", "source_backup_id": "snapshot",
           "buckets": {b: {"public": False, "objects": s} for b, s in sizes.items()}}
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(doc))
    return root, catalogue, doc, key


@pytest.mark.parametrize("version", ["absent", "empty", "populated"])
def test_capture_emits_a_private_manifest_readable_by_the_existing_drill(tmp_path, monkeypatch, capsys, version):
    root, catalogue, doc, key = archive(tmp_path)
    if version != "absent":
        (root / VERSION_BUCKET).mkdir()
        objects = {}
        if version == "populated":
            (root / VERSION_BUCKET / "replacement").write_bytes(b"b")
            objects["replacement"] = 1
        doc["buckets"][VERSION_BUCKET] = {"public": False, "objects": objects}
        catalogue.write_text(json.dumps(doc))
    out = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", ["capture", "--catalogue", str(catalogue), "--archive", str(root),
                                      "--catalogue-sha256", hashlib.sha256(catalogue.read_bytes()).hexdigest(),
                                      "--source-environment", "source", "--source-backup-id", "snapshot", "--out", str(out)])
    assert capture.main() == 0
    pin = capsys.readouterr().out.strip().split("=")[1]
    assert hashlib.sha256(out.read_bytes()).hexdigest() == pin and out.stat().st_mode & 0o077 == 0
    parsed = _manifest(out, pin, "source", "snapshot")
    assert parsed[BUCKETS[0]][key] == (3, hashlib.sha256(b"abc").hexdigest())
    assert parsed[VERSION_BUCKET] == {"absent": None, "empty": {}, "populated": {
        "replacement": (1, hashlib.sha256(b"b").hexdigest())}}[version]
    with pytest.raises(SystemExit):
        capture.main()
    assert hashlib.sha256(out.read_bytes()).hexdigest() == pin


@pytest.mark.parametrize("fault", ["missing", "extra", "short", "symlink", "directory-link",
                                  "missing-bucket", "unexpected-version", "public", "bad-size", "other-point"])
def test_incomplete_or_unsafe_archive_cannot_be_captured(tmp_path, fault):
    root, catalogue, doc, key = archive(tmp_path)
    folder = root / BUCKETS[0]
    target = folder / key
    if fault == "missing":
        target.unlink()
    elif fault == "extra":
        (folder / "extra").touch()
    elif fault == "short":
        target.write_bytes(b"x")
    elif fault == "symlink":
        target.unlink()
        target.symlink_to(catalogue)
    elif fault == "directory-link":
        os.symlink(root / BUCKETS[1], folder / "not-archived")
    elif fault == "missing-bucket":
        (root / BUCKETS[1]).rmdir()
    elif fault == "unexpected-version":
        (root / VERSION_BUCKET).mkdir()
    elif fault == "public":
        doc["buckets"][BUCKETS[0]]["public"] = True
    elif fault == "bad-size":
        doc["buckets"][BUCKETS[0]]["objects"][key] = False
    else:
        doc["source_backup_id"] = "other"
    catalogue.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        capture.capture(catalogue, root, "source", "snapshot", hashlib.sha256(catalogue.read_bytes()).hexdigest())

def test_manifest_output_cannot_alter_the_archive(tmp_path, monkeypatch):
    root, catalogue, _, _ = archive(tmp_path)
    out = root / BUCKETS[0] / "manifest.json"
    monkeypatch.setattr(sys, "argv", ["capture", "--catalogue", str(catalogue), "--archive", str(root),
                                      "--catalogue-sha256", hashlib.sha256(catalogue.read_bytes()).hexdigest(),
                                      "--source-environment", "source", "--source-backup-id", "snapshot", "--out", str(out)])
    with pytest.raises(SystemExit):
        capture.main()
    assert not out.exists()

@pytest.mark.parametrize("mutation", ["extra", "same_size", "remove", "version"])
def test_final_inventory_rejects_archive_drift_after_hashing(tmp_path, monkeypatch, mutation):
    root, catalogue, _, key = archive(tmp_path)
    original = capture._scan

    def drift(bucket, expected):
        result = original(bucket, expected)
        if bucket.name == BUCKETS[1]:
            path = root / BUCKETS[0] / key
            if mutation == "extra":
                (root / BUCKETS[0] / "another").touch()
            elif mutation == "same_size":
                path.write_bytes(b"xyz")
                os.utime(path, (1000000000, 1000000000))
            elif mutation == "remove":
                path.unlink()
            else:
                (root / VERSION_BUCKET).mkdir()
        return result

    monkeypatch.setattr(capture, "_scan", drift)
    with pytest.raises(ValueError):
        capture.capture(catalogue, root, "source", "snapshot", hashlib.sha256(catalogue.read_bytes()).hexdigest())


def test_independent_catalogue_digest_is_checked_before_reading_archive(tmp_path):
    root, catalogue, _, _ = archive(tmp_path)
    with pytest.raises(ValueError, match="separately retained"):
        capture.capture(catalogue, root, "source", "snapshot", "0" * 64)


def _source_storage(monkeypatch, stored, requests):
    import getpass

    import httpx

    def reply(request):
        requests.append((request.method, request.url.host, request.url.path, request.headers.get("apikey")))
        bucket, _, name = request.url.path.removeprefix("/storage/v1/object/").partition("/")
        if name in stored.get(bucket, {}):
            return httpx.Response(200, content=stored[bucket][name])
        return httpx.Response(404, json={"error": "not found"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "typed-at-the-prompt")


def test_download_builds_the_archive_and_inventory_from_the_source_project_with_reads_only(tmp_path, monkeypatch, capsys):
    key = "user/note #1?.pdf"
    doc = {"source_environment": "source", "source_backup_id": "snapshot", "buckets": {
        BUCKETS[0]: {"public": False, "objects": {key: 3}}, BUCKETS[1]: {"public": False, "objects": {}}}}
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(doc))
    requests = []
    _source_storage(monkeypatch, {BUCKETS[0]: {"user/note%20%231%3F.pdf": b"abc", key: b"abc"}}, requests)
    out, root = tmp_path / "inventory.json", tmp_path / "archive"
    argv = ["capture", "--catalogue", str(catalogue), "--archive", str(root), "--download",
            "--catalogue-sha256", hashlib.sha256(catalogue.read_bytes()).hexdigest(),
            "--source-environment", "source", "--source-backup-id", "snapshot", "--out", str(out)]
    monkeypatch.setattr(sys, "argv", argv)
    assert capture.main() == 0
    printed = capsys.readouterr()
    pin = printed.out.strip().split("=")[1]
    assert _manifest(out, pin, "source", "snapshot")[BUCKETS[0]][key] == (3, hashlib.sha256(b"abc").hexdigest())
    assert (root / BUCKETS[0] / key).read_bytes() == b"abc" and (root / BUCKETS[1]).is_dir()
    assert (root / BUCKETS[0] / key).stat().st_mode & 0o077 == 0
    assert requests == [("GET", "source.supabase.co", f"/storage/v1/object/{BUCKETS[0]}/{key}", "typed-at-the-prompt")]
    assert "typed-at-the-prompt" not in printed.out + printed.err

    # An archive is never downloaded over: the second run stops before any request.
    monkeypatch.setattr(sys, "argv", [*argv[:-1], str(tmp_path / "second.json")])
    with pytest.raises(SystemExit):
        capture.main()
    assert len(requests) == 1 and not (tmp_path / "second.json").exists()


def test_download_stops_when_the_source_no_longer_serves_a_catalogued_object(tmp_path, monkeypatch, capsys):
    doc = {"source_environment": "source", "source_backup_id": "snapshot", "buckets": {
        BUCKETS[0]: {"public": False, "objects": {"owner/private-name.pdf": 3}}, BUCKETS[1]: {"public": False, "objects": {}}}}
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(doc))
    _source_storage(monkeypatch, {}, [])
    monkeypatch.setattr(sys, "argv", ["capture", "--catalogue", str(catalogue), "--archive", str(tmp_path / "archive"),
                                      "--download", "--catalogue-sha256", hashlib.sha256(catalogue.read_bytes()).hexdigest(),
                                      "--source-environment", "source", "--source-backup-id", "snapshot",
                                      "--out", str(tmp_path / "inventory.json")])
    with pytest.raises(SystemExit):
        capture.main()
    error = capsys.readouterr().err
    assert "answered 404" in error and BUCKETS[0] in error and "private-name" not in error
    assert not (tmp_path / "inventory.json").exists()
