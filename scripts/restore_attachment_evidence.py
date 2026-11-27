"""Verify the private attachment buckets in a restored Supabase project.

The manifest and its SHA-256 must come from the selected source backup. Keep
the private manifest outside the repository and obtain the expected digest
from an independent, trusted backup record. Only aggregate evidence is public.
"""
from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import re
import signal
import sys
import termios
import traceback
import warnings
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

BUCKETS = ("tracker-attachments", "application-materials")
VERSION_BUCKET = "tracker-attachment-versions"
ALL_BUCKETS = (*BUCKETS, VERSION_BUCKET)
METHOD = "supabase-storage-list-download-sha256-v2"
_PAGE_SIZE = 100
_COUNTS = ("expected", "expected_bytes", "listed", "missing", "unexpected",
           "verified", "verified_bytes", "mismatched", "unreadable")
_SHA256 = re.compile(r"[a-f0-9]{64}")


@contextlib.contextmanager
def _terminal_acting_on_no_key():
    """Have the terminal hand every key to the reader as a character, and put its settings back afterwards.

    Left alone it acts on some keys itself: Ctrl-\\, Ctrl-Z and (macOS) Ctrl-Y kill or suspend the command before it
    reads them, and the shell then reads the rest of a pasted key as a command line, shows it and keeps it in its
    history; Ctrl-S, Ctrl-Q, Ctrl-V and the line-editing keys are taken out of the input unseen.
    """
    try:
        terminal = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:  # no controlling terminal, so no key can signal this process; getpass decides whether to read
        yield
        return
    try:
        if os.tcgetpgrp(terminal) != os.getpgrp():  # in the background no key arrives, and changing the terminal would stop us
            yield
            return
        saved = termios.tcgetattr(terminal)
        quiet = [*saved[:6], list(saved[6])]
        quiet[0] &= ~termios.IXON
        quiet[3] &= ~(termios.ISIG | termios.IEXTEN | termios.ICANON | termios.ECHO)
        quiet[6][termios.VMIN], quiet[6][termios.VTIME] = 1, 0
        # zsh gives the next command the settings a killed one left, so a plain `kill` has to pass through here too.
        unhandled = signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        if unhandled:
            signal.signal(signal.SIGTERM, _terminated)
        termios.tcsetattr(terminal, termios.TCSAFLUSH, quiet)
        try:
            yield
        finally:
            termios.tcsetattr(terminal, termios.TCSAFLUSH, saved)  # and drop what was typed and not read
            if unhandled:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
    finally:
        os.close(terminal)


def _terminated(signum, frame):
    raise SystemExit(128 + signum)


def hidden_prompt(label: str) -> str:
    """Read a credential from the terminal with echo off, or not at all.

    The drill scripts take keys and passwords only here: not from arguments or exported
    variables, which a shell history or a process listing would keep.
    """
    with warnings.catch_warnings(), _terminal_acting_on_no_key():
        # Without a terminal getpass falls back to reading standard input with echo on.
        warnings.simplefilter("error", getpass.GetPassWarning)
        while True:
            try:
                value = getpass.getpass(f"{label} (input hidden): ").strip()
            except (getpass.GetPassWarning, EOFError):
                raise ValueError("no terminal that can hide input; run this from an interactive terminal") from None
            if "\x03" in value:  # Ctrl-C is not a signal here; it still ends the command, once Enter hands it over
                raise KeyboardInterrupt
            if value.isprintable():
                break
            # Nothing shows at this prompt, so an arrow key or Ctrl-K pressed there goes unseen. An HTTP library
            # refuses such a header value and quotes all of it in its error.
            print(f"{label}: the input held a character that does not print (an arrow key, Backspace or a Ctrl key "
                  "leaves one). It was not used. Enter it once more.", file=sys.stderr)
    if not value:
        raise ValueError(f"nothing was entered for: {label}")
    return value


def scrub(text: str, secrets) -> str:
    """Remove credentials from text about to be written or printed, however they got into it."""
    for secret in secrets:
        if secret:
            # As typed, and as an error message quotes a str or a bytes value; each also as it stands inside JSON.
            forms = {secret, repr(secret)[1:-1], repr(secret.encode("utf-8", "surrogatepass"))[2:-1]}
            for form in sorted(forms | {json.dumps(form)[1:-1] for form in forms}, key=len, reverse=True):
                text = text.replace(form, "[redacted]")
    return text


def run_guarded(body) -> int:
    """Run a script that reads credentials; an error it did not expect is still reported, without them.

    ``body`` is given a list and adds every credential it reads to it.
    """
    typed: list[str | None] = []
    try:
        return body(typed)
    except Exception:
        sys.stderr.write(scrub(traceback.format_exc(), typed))
        return 1


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _part(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and value not in (".", "..")
            and not any(ch in "/\\" or ord(ch) < 32 or ord(ch) == 127 for ch in value))


def catalogue_bytes(source, backup, buckets) -> bytes:
    """Canonical source catalogue, also reconstructed from a private backup manifest."""
    doc = {"source_environment": source, "source_backup_id": backup, "buckets": buckets}
    return (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode()


def bound_attachment_verdict(evidence: object, record: dict) -> str:
    result = attachment_verdict(evidence, record)
    if result != "PASS":
        return result
    schema = record.get("source_schema_version")
    source_pin = schema.get("storage_catalogue_sha256") if isinstance(schema, dict) else None
    archived = evidence.get("source_catalogue_sha256")
    if not all(isinstance(pin, str) and _SHA256.fullmatch(pin) for pin in (source_pin, archived)):
        return "UNVERIFIED"
    return "PASS" if source_pin == archived else "FAIL"


def _manifest(path: Path, pin: str, source: str, backup: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError
    doc = json.loads(raw, object_pairs_hook=_unique_keys)
    if (not isinstance(doc, dict) or type(doc.get("version")) is not int or doc["version"] != 2
            or doc.get("source_environment") != source or doc.get("source_backup_id") != backup
            or not isinstance(doc.get("buckets"), dict) or set(doc["buckets"]) != set(ALL_BUCKETS)):
        raise ValueError
    expected = {}
    for bucket, rows in doc["buckets"].items():
        if bucket == VERSION_BUCKET and rows is None:
            expected[bucket] = None
            continue
        if not isinstance(rows, list):
            raise ValueError
        objects = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError
            key, size, digest = row.get("key"), row.get("size"), row.get("sha256")
            if (not isinstance(key, str) or not all(_part(p) for p in key.split("/"))
                    or key in objects or type(size) is not int or size < 0
                    or not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
                raise ValueError
            key.encode("utf-8")  # JSON escapes can represent unpaired surrogates.
            objects[key] = (size, digest)
        expected[bucket] = objects
    return expected


def _version_bucket_absence(client, storage, headers):
    """Prove nonexistence from a complete bucket listing on the isolated restore."""
    seen = set()
    while True:
        response = client.get(f"{storage}/bucket", headers=headers, follow_redirects=False,
                              params={"limit": _PAGE_SIZE, "offset": len(seen), "sortColumn": "id",
                                      "sortOrder": "asc"})
        if response.status_code != 200:
            raise ValueError
        page = response.json()
        if not isinstance(page, list):
            raise ValueError
        if not page:
            return "verified" if set(BUCKETS) <= seen else "unverified"
        for item in page:
            bucket = item.get("id") if isinstance(item, dict) else None
            if not isinstance(bucket, str) or not bucket or bucket in seen:
                raise ValueError
            if bucket == VERSION_BUCKET:
                return "mismatch"
            seen.add(bucket)


def _inventory(client, storage, headers, bucket):
    bucket_info = client.get(f"{storage}/bucket/{bucket}", headers=headers, follow_redirects=False)
    if bucket_info.status_code != 200:
        raise ValueError
    info = bucket_info.json()
    if not isinstance(info, dict) or info.get("id") != bucket:
        raise ValueError

    files = set()
    pending = [""]
    while pending:
        prefix = pending.pop()
        seen = set()
        offset = 0
        while True:
            response = client.post(
                f"{storage}/object/list/{bucket}", headers=headers, follow_redirects=False,
                json={"prefix": prefix, "limit": _PAGE_SIZE, "offset": offset,
                      "sortBy": {"column": "name", "order": "asc"}},
            )
            if response.status_code != 200:
                raise ValueError
            page = response.json()
            if not isinstance(page, list):
                raise ValueError
            if not page:
                break
            for entry in page:
                if not isinstance(entry, dict) or not _part(entry.get("name")) or "id" not in entry:
                    raise ValueError
                name, oid = entry["name"], entry["id"]
                folder = oid is None
                if (not folder and (not isinstance(oid, str) or not oid)) or (name, folder) in seen:
                    raise ValueError
                seen.add((name, folder))
                key = f"{prefix}/{name}" if prefix else name
                if folder:
                    pending.append(key)
                else:
                    files.add(key)
            offset += len(page)
    return files


def _verify_bytes(client, storage, headers, bucket, key, expected_size, expected_digest):
    url = f"{storage}/object/{bucket}/{quote(key, safe='/')}"
    try:
        with client.stream("GET", url, headers=headers, follow_redirects=False) as response:
            if response.status_code in (404, 410):
                return "mismatched"
            if response.status_code != 200 or "content-range" in response.headers:
                return "unreadable"
            digest = hashlib.sha256()
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > expected_size:
                    return "mismatched"
                digest.update(chunk)
            return "verified" if size == expected_size and digest.hexdigest() == expected_digest else "mismatched"
    except httpx.HTTPError:
        return "unreadable"


def attachment_verdict(evidence: object, record: dict) -> str:
    """Recompute the result from record-bound inventories and byte counts."""
    if not isinstance(evidence, dict) or evidence.get("method") != METHOD:
        return "UNVERIFIED"
    for field in ("source_environment", "source_backup_id", "scratch_environment"):
        if not isinstance(record.get(field), str) or not record[field].strip() or evidence.get(field) != record[field]:
            return "UNVERIFIED"
    if record["source_environment"] == record["scratch_environment"]:
        return "UNVERIFIED"
    pin = evidence.get("manifest_sha256")
    buckets = evidence.get("buckets")
    if (not isinstance(pin, str) or not _SHA256.fullmatch(pin) or pin != record.get("attachment_manifest_sha256")
            or not isinstance(buckets, dict)
            or set(buckets) not in (set(BUCKETS), set(ALL_BUCKETS))):
        return "UNVERIFIED"

    if VERSION_BUCKET not in buckets:
        absence = evidence.get("version_bucket_absence")
        if absence == "mismatch":
            return "FAIL"
        if absence != "verified":
            return "UNVERIFIED"
    elif "version_bucket_absence" in evidence:
        return "UNVERIFIED"

    try:
        times = [datetime.fromisoformat(value) for value in (record.get("restore_started_at"),
                 evidence.get("observed_at"), record.get("performed_at"))]
        if any(t.utcoffset() is None for t in times) or times != sorted(times):
            return "UNVERIFIED"
    except (ValueError, TypeError):
        return "UNVERIFIED"

    verified = True
    failed = False
    for row in buckets.values():
        if (not isinstance(row, dict) or type(row.get("inventory_complete")) is not bool
                or any(type(row.get(k)) is not int or row[k] < 0 for k in _COUNTS)):
            return "UNVERIFIED"
        if (row["verified"] + row["mismatched"] + row["unreadable"] != row["expected"]
                or row["verified_bytes"] > row["expected_bytes"]
                or (row["verified"] == 0 and row["verified_bytes"] != 0)
                or (row["expected"] == 0 and row["expected_bytes"] != 0)
                or row["missing"] > row["expected"] or row["unexpected"] > row["listed"]):
            return "UNVERIFIED"
        if row["inventory_complete"]:
            if row["listed"] != row["expected"] - row["missing"] + row["unexpected"]:
                return "UNVERIFIED"
            failed |= bool(row["missing"] or row["unexpected"])
        verified &= row["inventory_complete"] and not row["unreadable"]
        failed |= bool(row["mismatched"])
        if row["verified"] == row["expected"] and row["verified_bytes"] != row["expected_bytes"]:
            return "UNVERIFIED"
    if failed:
        return "FAIL"
    return "PASS" if verified else "UNVERIFIED"


def validate_attachments(client: httpx.Client, base: str, service_key: str, *,
                         manifest_path: Path | None, manifest_sha256: str | None,
                         source_environment: str, source_backup_id: str, scratch_environment: str) -> dict:
    """Compare the complete source inventory with storage reads from the scratch project."""
    record = {"source_environment": source_environment, "source_backup_id": source_backup_id,
              "scratch_environment": scratch_environment}
    evidence = {**record, "method": METHOD, "result": "UNVERIFIED"}
    started_at = datetime.now(UTC).isoformat()
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]*", scratch_environment)
            or base.rstrip("/") != f"https://{scratch_environment}.supabase.co"
            or not source_environment or source_environment == scratch_environment
            or not source_backup_id.strip() or not service_key):
        return {**evidence, "reason": "scratch_target_unverified"}
    if manifest_path is None or not isinstance(manifest_sha256, str) or not _SHA256.fullmatch(manifest_sha256):
        return {**evidence, "reason": "trusted_manifest_missing"}
    try:
        expected = _manifest(manifest_path, manifest_sha256, source_environment, source_backup_id)
    except (ValueError, OSError, RecursionError):
        return {**evidence, "reason": "trusted_manifest_unverified"}

    buckets = {bucket: {"public": False, "objects": {key: size for key, (size, _) in objects.items()}}
               for bucket, objects in expected.items() if objects is not None}
    evidence["source_catalogue_sha256"] = hashlib.sha256(
        catalogue_bytes(source_environment, source_backup_id, buckets)).hexdigest()
    storage = f"{base.rstrip('/')}/storage/v1"
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "Accept-Encoding": "identity"}
    evidence.update(manifest_sha256=manifest_sha256, buckets={})
    for bucket, objects in expected.items():
        if bucket == VERSION_BUCKET and objects is None:
            try:
                evidence["version_bucket_absence"] = _version_bucket_absence(client, storage, headers)
            except (ValueError, httpx.HTTPError, RecursionError):
                evidence["version_bucket_absence"] = "unverified"
            continue
        row = dict.fromkeys(_COUNTS, 0)
        row.update(inventory_complete=False, expected=len(objects), expected_bytes=sum(s for s, _ in objects.values()))
        try:
            listed = _inventory(client, storage, headers, bucket)
        except (ValueError, httpx.HTTPError, RecursionError):
            pass
        else:
            row.update(inventory_complete=True, listed=len(listed),
                       missing=len(objects.keys() - listed), unexpected=len(listed - objects.keys()))
        for key, (size, digest) in objects.items():
            outcome = _verify_bytes(client, storage, headers, bucket, key, size, digest)
            row[outcome] += 1
            if outcome == "verified":
                row["verified_bytes"] += size
        evidence["buckets"][bucket] = row
    evidence["observed_at"] = datetime.now(UTC).isoformat()
    evidence["result"] = attachment_verdict(evidence, {**record, "restore_started_at": started_at,
        "performed_at": evidence["observed_at"], "attachment_manifest_sha256": manifest_sha256})
    return evidence
