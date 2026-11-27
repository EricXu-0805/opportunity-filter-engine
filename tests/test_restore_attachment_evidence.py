"""Restore evidence uses synthetic private Storage inventories and downloads."""
import getpass
import hashlib
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

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


@pytest.mark.parametrize("stray", ["\u00e9", "\u5bc6", "\uff21"])
def test_an_api_key_typed_with_a_letter_no_key_holds_is_refused_and_asked_for_again(monkeypatch, capsys, stray):
    # A Supabase key is ASCII. httpx cannot send anything else in a header: the drill ended in a traceback, the
    # download told the operator to move a partial archive away.
    answers = iter([f"invented-key{stray}invented-key", "invented-key"])
    prompts = []
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompts.append(prompt) or next(answers))
    assert attachments.hidden_prompt("Scratch anon key") == "invented-key"
    assert prompts == ["Scratch anon key (input hidden): "] * 2
    shown = capsys.readouterr()
    assert "Scratch anon key" in shown.err and "invented-key" not in shown.out + shown.err


def test_ctrl_c_in_what_was_typed_abandons_the_prompt_and_uses_nothing(monkeypatch, capsys):
    # The terminal hands Ctrl-C over as a character while a hidden prompt reads; see the pseudo-terminal tests below.
    answers = iter(["invented-\x03key", "invented-key"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    with pytest.raises(KeyboardInterrupt):
        attachments.hidden_prompt("Scratch service-role key")
    shown = capsys.readouterr()
    assert next(answers) == "invented-key" and "invented" not in shown.out + shown.err


_KEY = b"invented-key-first-half-0123456789" + b"invented-key-other-half-abcdefghij"
_HALF = len(_KEY) // 2
_ASK = ("from scripts.restore_attachment_evidence import hidden_prompt; "
        "print('GOT', len(hidden_prompt('Scratch service-role key')))")
_ROOT = Path(__file__).resolve().parents[1]


def _on_a_terminal(argv, env):
    """Start ``argv`` as the session leader of a new pseudo-terminal; returns the process and both ends of the terminal."""
    pty = pytest.importorskip("pty")
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip("no pseudo-terminal is available here")

    def at_the_terminal():
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # a test run in the background starts with it ignored
        os.login_tty(slave)

    process = subprocess.Popen(argv, cwd=_ROOT, preexec_fn=at_the_terminal,
                               env={"PATH": os.environ["PATH"], "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "TERM": "dumb"} | env)
    return process, master, slave


def _read_until(master, shown, *endings, since=0, after=b""):
    deadline = time.monotonic() + 15
    while not (bytes(shown[since:]).endswith(endings) and after in shown[since:]):
        wait = deadline - time.monotonic()
        assert wait > 0 and select.select([master], [], [], wait)[0], f"{endings} did not come after {bytes(shown[-400:])!r}"
        shown += os.read(master, 65536)
    return len(shown)


def _exit_status(process, master, shown):
    # macOS lets a process go only when what it wrote to its terminal has been read.
    deadline = time.monotonic() + 15
    while process.poll() is None:
        assert time.monotonic() < deadline, f"still running after {bytes(shown[-400:])!r}"
        if select.select([master], [], [], 0.05)[0]:
            shown += os.read(master, 65536)
    return process.returncode


def _typed_at_a_prompt_in_a_shell(tmp_path, typed):
    """What an interactive Bash shows and remembers when ``typed`` arrives in one write, as a paste does, at a hidden
    prompt, and the clean key each time the prompt asks again. Returns (shown after the prompt, history file, times asked again)."""
    bash = shutil.which("bash") or pytest.skip("no bash")
    shell, master, slave = _on_a_terminal([bash, "--noprofile", "--norc", "--noediting", "-i"],
                                          {"HOME": str(tmp_path), "HISTFILE": str(tmp_path / "history"), "PS1": "READY> "})
    shown, again = bytearray(), 0
    try:
        _read_until(master, shown, b"READY> ")
        os.write(master, f'{sys.executable} -c "{_ASK}"\n'.encode())
        start = at = _read_until(master, shown, b"(input hidden): ")
        os.write(master, typed + b"\n")
        while True:
            at = _read_until(master, shown, b"(input hidden): ", b"READY> ", since=at)
            if shown.endswith(b"READY> "):
                break
            again += 1
            os.write(master, _KEY + b"\n")
        os.write(master, b'echo "status=$?"; jobs; kill -9 %1; echo fin""ished\n')
        _read_until(master, shown, b"READY> ", since=at, after=b"finished\r\n")
        os.write(master, b"exit\n")
        _exit_status(shell, master, shown)
    finally:
        shell.kill()
        os.close(master)
        os.close(slave)
        shell.wait()
    history = tmp_path / "history"
    return bytes(shown[start:]), history.read_bytes() if history.exists() else b"", again


def _parts_of_the_key_in(data):
    return sorted({_KEY[i:i + 10] for i in range(len(_KEY) - 9) if _KEY[i:i + 10] in data})


@pytest.mark.parametrize("typed", [
    b"\x19" + _KEY, _KEY[:_HALF] + b"\x19" + _KEY[_HALF:],  # Ctrl-Y: delayed suspend on macOS, the rest goes to the shell
    _KEY[:_HALF] + b"\x1c" + _KEY[_HALF:],  # Ctrl-\: quit
    _KEY[:_HALF] + b"\x1a" + _KEY[_HALF:],  # Ctrl-Z: suspend
    _KEY[:_HALF] + b"\x13" + _KEY[_HALF:], _KEY[:_HALF] + b"\x11" + _KEY[_HALF:],  # Ctrl-S, Ctrl-Q: swallowed as flow control
    _KEY[:_HALF] + b"\x16" + _KEY[_HALF:], _KEY + b"\x16",  # Ctrl-V: swallowed, and takes the Enter after it as a letter
], ids=["Ctrl-Y first", "Ctrl-Y", "Ctrl-Backslash", "Ctrl-Z", "Ctrl-S", "Ctrl-Q", "Ctrl-V", "Ctrl-V last"])
def test_no_key_typed_at_a_hidden_prompt_stops_the_command_or_reaches_the_shell(tmp_path, typed):
    shown, history, asked_again = _typed_at_a_prompt_in_a_shell(tmp_path, typed)
    assert _parts_of_the_key_in(shown) == [] and _parts_of_the_key_in(history) == []
    assert asked_again == 1 and shown.count(b"It was not used. Enter it once more.") == 1
    assert b"GOT %d\r\n" % len(_KEY) in shown and b"status=0\r\n" in shown
    assert b"Stopped" not in shown and b"no such job" in shown


def test_ctrl_c_inside_a_pasted_key_ends_the_command_and_leaves_nothing_of_the_key(tmp_path):
    shown, history, asked_again = _typed_at_a_prompt_in_a_shell(tmp_path, _KEY[:_HALF] + b"\x03" + _KEY[_HALF:])
    assert _parts_of_the_key_in(shown) == [] and _parts_of_the_key_in(history) == []
    assert asked_again == 0 and b"GOT" not in shown.replace(_ASK.encode(), b"")
    assert b"KeyboardInterrupt" in shown and b"status=130\r\n" in shown and b"no such job" in shown


@pytest.mark.parametrize("typed, result", [
    (_KEY, b"GOT %d" % len(_KEY)), (b"\x03", b"ENDED KeyboardInterrupt"), (b"\xff", b"ENDED UnicodeDecodeError"),
    (signal.SIGINT, b"ENDED KeyboardInterrupt"), (signal.SIGTERM, b"ENDED SystemExit"),
], ids=["a clean value", "Ctrl-C and Enter", "an error while reading", "an interrupt from outside", "a kill from outside"])
def test_the_terminal_acts_on_no_key_while_a_hidden_prompt_reads_and_has_its_settings_back_afterwards(typed, result):
    termios = pytest.importorskip("termios")
    # The command stays after the prompt: a terminal forgets its settings when the session that owns it ends.
    stays = _ASK.replace("print(", "\ntry: print(") + "\nexcept BaseException as error: print('ENDED', type(error).__name__)\nimport time; time.sleep(60)"
    asking, master, slave = _on_a_terminal([sys.executable, "-c", stays], {})
    try:
        before = termios.tcgetattr(slave)
        shown = bytearray()
        at = _read_until(master, shown, b"(input hidden): ")
        during = termios.tcgetattr(slave)
        assert before[3] & termios.ISIG and before[3] & termios.ECHO and before[0] & termios.IXON
        assert not during[3] & (termios.ISIG | termios.IEXTEN | termios.ICANON | termios.ECHO) and not during[0] & termios.IXON
        if isinstance(typed, signal.Signals):
            asking.send_signal(typed)
        else:
            os.write(master, typed + b"\n")
        _read_until(master, shown, result + b"\r\n", since=at)
        assert termios.tcgetattr(slave) == before
    finally:
        asking.kill()
        os.close(master)
        os.close(slave)
        asking.wait()


@pytest.mark.parametrize("typed", ["invented-key\x01\x0binvented-key", "it's an \"invented\" key", "invented\\key", "clé-inventée"])
def test_a_credential_is_removed_however_an_error_message_quotes_it(typed):
    # h11 quotes a header value it refuses as bytes; other libraries quote with %r. The record is scrubbed as JSON.
    for quoted in (typed, repr(typed), repr(typed.encode())):
        for text in (f"Illegal header value {quoted}", json.dumps({"note": f"Illegal header value {quoted}"})):
            left = attachments.scrub(text, ["another-secret", typed])
            assert "[redacted]" in left and "invent" not in left, text


@pytest.mark.parametrize("typed", ["it's an \"invented\" key", "invented\\key", "clé-inventée", "invented\x0bkey", "invented🔑key"])
def test_a_credential_is_removed_however_many_times_it_was_quoted(typed):
    # KeyError and OSError quote an argument that is a quoted text already, and the record writes the result as JSON.
    for once in (typed, repr(typed), repr(typed.encode()), ascii(typed), json.dumps(typed), json.dumps(typed, ensure_ascii=False)):
        for again in (repr(once), json.dumps(once), str(KeyError(once)), str(OSError(2, "No such file", once)),
                      json.dumps(repr(json.dumps(repr(once))))):
            left = attachments.scrub(f"Illegal header value {again}", ["another-secret", typed])
            assert "[redacted]" in left and "invent" not in left and "key" not in left, again
