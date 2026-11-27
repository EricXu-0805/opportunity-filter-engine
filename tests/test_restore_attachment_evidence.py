"""Restore evidence uses synthetic private Storage inventories and downloads."""
import getpass
import hashlib
import json
from copy import deepcopy

import httpx
import pytest

from scripts import restore_attachment_evidence as attachments

RECORD = {"source_environment": "source", "source_backup_id": "point-1", "scratch_environment": "scratch"}
BASE = "https://scratch.supabase.co"
TOKEN = "scratch-unit-test-token"
TRACKER, MATERIALS = attachments.BUCKETS
PRIVATE = "person-1/position/private #résumé?.pdf"
FILES = {TRACKER: {PRIVATE: b"synthetic confidential bytes", "root.txt": b"abc"},
         MATERIALS: {"pdf/demo.pdf": b"another fake PDF"}}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest(files):
    return {"version": 2, "source_environment": "source", "source_backup_id": "point-1",
            "buckets": {attachments.VERSION_BUCKET: None} | {b: [{"key": k, "size": len(v), "sha256": sha(v)} for k, v in rows.items()]
                        for b, rows in files.items()}}


def write_manifest(tmp_path, doc):
    path = tmp_path / "private-manifest.json"
    raw = json.dumps(doc).encode()
    path.write_bytes(raw)
    return path, sha(raw)


class Storage:
    def __init__(self, files):
        self.files = deepcopy(files)
        self.calls = []
        self.downloads = []
        self.unreadable_bucket = None
        self.download_response = None
        self.list_override = None

    def request(self, req):
        self.calls.append(req)
        assert req.url.host == "scratch.supabase.co"
        assert req.headers["apikey"] == TOKEN
        path = req.url.path.removeprefix("/storage/v1/").split("/", 2)
        if path[0] == "bucket":
            assert req.method == "GET"
            if len(path) == 1:
                start = int(req.url.params["offset"])
                return httpx.Response(200, json=[{"id": b} for b in sorted(self.files)[start:start + 1]])
            if path[1] not in self.files:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": path[1], "public": False})
        if req.method == "POST":  # Storage's read-only list endpoint
            assert path[:2] == ["object", "list"]
            bucket = path[2]
            query = json.loads(req.content)
            if self.unreadable_bucket == bucket:
                return httpx.Response(403, text=PRIVATE)
            if self.list_override is not None:
                return httpx.Response(200, json=self.list_override)
            prefix = query["prefix"] + "/" if query["prefix"] else ""
            rows = set()
            for key in self.files[bucket]:
                if key.startswith(prefix):
                    name, separator, _ = key[len(prefix):].partition("/")
                    rows.add((name, bool(separator)))
            ordered = [{"name": name, "id": None if folder else "object-id"} for name, folder in sorted(rows)]
            # Deliberately cap pages below the requested page size.
            offset = query["offset"]
            return httpx.Response(200, json=ordered[offset:offset + 1])
        assert path[0] == "object" and req.method == "GET"
        bucket, key = path[1:]
        assert not req.url.query
        self.downloads.append((bucket, key))
        if key == PRIVATE and self.download_response is not None:
            return self.download_response()
        if key not in self.files.get(bucket, {}):
            return httpx.Response(404, text=PRIVATE)
        return httpx.Response(200, content=self.files[bucket][key])


def bound_record(evidence):
    return {**RECORD, "restore_started_at": "2020-01-01T00:00:00+00:00",
            "performed_at": "2099-01-01T00:00:00+00:00", "attachment_manifest_sha256": evidence["manifest_sha256"]}


def run(store, path, pin, *, base=BASE, record=RECORD):
    with httpx.Client(transport=httpx.MockTransport(store.request), follow_redirects=True) as client:
        return attachments.validate_attachments(client, base, TOKEN, manifest_path=path,
                                               manifest_sha256=pin, **record)


def test_every_manifest_object_downloaded_across_buckets_and_nested_pages(tmp_path):
    store = Storage(FILES)
    result = run(store, *write_manifest(tmp_path, manifest(FILES)))
    assert result["result"] == attachments.attachment_verdict(result, bound_record(result)) == "PASS"
    assert sorted(store.downloads) == sorted((b, k) for b, files in FILES.items() for k in files)
    assert result["buckets"][TRACKER]["verified_bytes"] == sum(map(len, FILES[TRACKER].values()))
    query = [json.loads(req.content) for req in store.calls if req.method == "POST"]
    assert any(q["offset"] > 0 for q in query)
    assert any(q["prefix"] == "person-1/position" for q in query)
    assert "%23" in next(req.url.raw_path.decode() for req in store.calls if PRIVATE in req.url.path)
    public = json.dumps(result)
    for value in (PRIVATE, "person-1", TOKEN, "synthetic confidential bytes", sha(FILES[TRACKER][PRIVATE]),
                  "private-manifest.json"):
        assert value not in public


def test_empty_inventory_requires_both_buckets_and_trusted_manifest(tmp_path):
    empty = {TRACKER: {}, MATERIALS: {}}
    store = Storage(empty)
    assert run(store, None, None)["result"] == "UNVERIFIED"
    assert not store.calls
    args = write_manifest(tmp_path, manifest(empty))
    confirmed = run(store, *args)
    assert confirmed["result"] == "PASS"
    assert all(row["inventory_complete"] and row["verified"] == 0 for row in confirmed["buckets"].values())
    store.unreadable_bucket = MATERIALS
    assert run(store, *args)["result"] == "UNVERIFIED"


def test_incomplete_restore_and_unexpected_object_reported_even_if_counts_equal(tmp_path):
    store = Storage(FILES)
    store.files[TRACKER]["other-user.pdf"] = store.files[TRACKER].pop(PRIVATE)
    result = run(store, *write_manifest(tmp_path, manifest(FILES)))
    assert result["result"] == "FAIL"
    assert result["buckets"][TRACKER]["missing"] == result["buckets"][TRACKER]["unexpected"] == 1
    assert result["buckets"][TRACKER]["mismatched"] == 1
    assert result["buckets"][MATERIALS]["verified"] == 1


@pytest.mark.parametrize("replacement", [b"x" * len(FILES[TRACKER][PRIVATE]), b"x", FILES[TRACKER][PRIVATE] + b"x"])
def test_wrong_bytes_detected_including_same_size(tmp_path, replacement):
    store = Storage(FILES)
    store.files[TRACKER][PRIVATE] = replacement
    result = run(store, *write_manifest(tmp_path, manifest(FILES)))
    assert result["result"] == "FAIL"
    assert result["buckets"][TRACKER]["mismatched"] == 1


def test_empty_object_is_verified_by_downloading_it(tmp_path):
    files = {TRACKER: {PRIVATE: b""}, MATERIALS: {}}
    store = Storage(files)
    result = run(store, *write_manifest(tmp_path, manifest(files)))
    assert result["result"] == "PASS"
    assert store.downloads == [(TRACKER, PRIVATE)]
    assert result["buckets"][TRACKER]["verified"] == 1


@pytest.mark.parametrize("response", [
    lambda: httpx.Response(403, text=PRIVATE + TOKEN),
    lambda: httpx.Response(206, content=FILES[TRACKER][PRIVATE]),
    lambda: httpx.Response(200, headers={"Content-Range": "bytes 0-1/100"}, content=FILES[TRACKER][PRIVATE]),
    lambda: httpx.Response(302, headers={"Location": "https://another-domain.example/private"}),
])
def test_refused_partial_or_redirected_download_is_unverified(tmp_path, response):
    store = Storage(FILES)
    store.download_response = response
    result = run(store, *write_manifest(tmp_path, manifest(FILES)))
    assert result["result"] == "UNVERIFIED"
    assert result["buckets"][TRACKER]["unreadable"] == 1
    assert PRIVATE not in json.dumps(result) and TOKEN not in json.dumps(result)


def test_interrupted_byte_stream_never_counts_as_verified(tmp_path):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield FILES[TRACKER][PRIVATE]
            raise httpx.ReadError(PRIVATE + TOKEN)

    store = Storage(FILES)
    store.download_response = lambda: httpx.Response(200, stream=Interrupted())
    result = run(store, *write_manifest(tmp_path, manifest(FILES)))
    assert result["result"] == "UNVERIFIED"
    assert result["buckets"][TRACKER]["unreadable"] == 1


@pytest.mark.parametrize("listing", [{"error": PRIVATE}, [{"name": PRIVATE}], [{"id": "file", "name": "bad/path"}],
                                    [{"id": "one", "name": "repeated.txt"}]])
def test_unreadable_inventories_never_clear_even_with_good_downloads(tmp_path, listing):
    store = Storage(FILES)
    store.list_override = listing
    result = run(store, *write_manifest(tmp_path, manifest(FILES)))
    assert result["result"] == "UNVERIFIED"
    assert result["buckets"][TRACKER]["verified"] == len(FILES[TRACKER])
    assert result["buckets"][TRACKER]["inventory_complete"] is False


@pytest.mark.parametrize("change", [
    lambda d: d.update(source_backup_id="other"),
    lambda d: d.update(source_environment="scratch"),
    lambda d: d["buckets"].pop(MATERIALS),
    lambda d: d["buckets"][TRACKER].append(d["buckets"][TRACKER][0]),
    lambda d: d["buckets"][TRACKER][0].update(key="../escape"),
    lambda d: d["buckets"][TRACKER][0].update(size=True),
    lambda d: d["buckets"][TRACKER][0].update(sha256="broken"),
])
def test_wrong_or_incomplete_source_manifests_never_initiate_a_request(tmp_path, change):
    store = Storage(FILES)
    doc = manifest(FILES)
    change(doc)
    result = run(store, *write_manifest(tmp_path, doc))
    assert result["result"] == "UNVERIFIED" and not store.calls


def test_duplicate_json_property_wrong_pin_and_wrong_hosts(tmp_path):
    store = Storage(FILES)
    path, pin = write_manifest(tmp_path, manifest(FILES))
    assert run(store, path, "f" * 64)["result"] == "UNVERIFIED"
    for base in ("https://source.supabase.co", BASE + ".outside.example", "http://scratch.supabase.co",
                 BASE + "/some-path"):
        assert run(store, path, pin, base=base)["result"] == "UNVERIFIED"
    assert run(store, path, pin, record={**RECORD, "source_environment": "scratch"})["result"] == "UNVERIFIED"
    raw = path.read_bytes().replace(b'"version": 2', b'"version": 2, "version": 2')
    path.write_bytes(raw)
    assert run(store, path, sha(raw))["result"] == "UNVERIFIED"
    assert not store.calls


def test_gate_recomputes_result_and_rejects_missing_or_inconsistent_counts(tmp_path):
    proof = run(Storage(FILES), *write_manifest(tmp_path, manifest(FILES)))
    record = bound_record(proof)
    assert attachments.attachment_verdict({"result": "PASS"}, record) == "UNVERIFIED"
    for change in ({"source_backup_id": "other"}, {"attachment_manifest_sha256": "e" * 64},
                   {"restore_started_at": "2098-01-01T00:00:00+00:00"}, {"performed_at": "2019-01-01T00:00:00+00:00"}):
        assert attachments.attachment_verdict(proof, {**record, **change}) == "UNVERIFIED"
    for field, value in (("verified", True), ("verified", 0), ("expected", -1), ("listed", 9),
                         ("inventory_complete", False), ("verified_bytes", 0)):
        suspect = deepcopy(proof)
        suspect["buckets"][TRACKER][field] = value
        assert attachments.attachment_verdict(suspect, record) == "UNVERIFIED"
    del proof["buckets"][MATERIALS]
    assert attachments.attachment_verdict(proof, record) == "UNVERIFIED"


def test_versioned_restore_verifies_replacement_bytes_not_only_the_anchor(tmp_path):
    version = attachments.VERSION_BUCKET
    updated = {**FILES, version: {"owner/revision": b"updated"}}
    args = write_manifest(tmp_path, manifest(updated))
    result = run(Storage(updated), *args)
    assert result["result"] == "PASS" and result["buckets"][version]["verified"] == 1
    bad = Storage(updated)
    bad.files[version]["owner/revision"] = b"damaged"
    assert run(bad, *args)["result"] == "FAIL"
    assert run(Storage(FILES), *args)["result"] != "PASS"


def test_legacy_scope_needs_independent_absence_on_both_sides(tmp_path):
    doc = manifest(FILES)
    args = write_manifest(tmp_path, doc)
    assert run(Storage(FILES | {attachments.VERSION_BUCKET: {}}), *args)["result"] == "FAIL"
    doc["buckets"].pop(attachments.VERSION_BUCKET)
    for version in (1, 2):
        doc["version"] = version
        assert run(Storage(FILES), *write_manifest(tmp_path, doc))["result"] == "UNVERIFIED"


@pytest.mark.parametrize("stray", ["\x01\x0b", "\x0c", "\x00", "\x1b[D", "\x7f", "\u200b"])
def test_a_credential_typed_with_a_control_character_is_refused_and_asked_for_again(monkeypatch, capsys, stray):
    # The prompt shows nothing, so Ctrl-A Ctrl-K before a second paste, or a brushed arrow key, goes unnoticed.
    answers = iter([f"invented-key{stray}invented-key", "invented-key"])
    prompts = []
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompts.append(prompt) or next(answers))
    assert attachments.hidden_prompt("Scratch service-role key") == "invented-key"
    assert prompts == ["Scratch service-role key (input hidden): "] * 2
    shown = capsys.readouterr()
    assert "Scratch service-role key" in shown.err and "invented-key" not in shown.out + shown.err


@pytest.mark.parametrize("typed", ["invented-key\x01\x0binvented-key", "it's an \"invented\" key", "invented\\key", "clé-inventée"])
def test_a_credential_is_removed_however_an_error_message_quotes_it(typed):
    # h11 quotes a header value it refuses as bytes; other libraries quote with %r. The record is scrubbed as JSON.
    for quoted in (typed, repr(typed), repr(typed.encode())):
        for text in (f"Illegal header value {quoted}", json.dumps({"note": f"Illegal header value {quoted}"})):
            left = attachments.scrub(text, ["another-secret", typed])
            assert "[redacted]" in left and "invent" not in left, text
