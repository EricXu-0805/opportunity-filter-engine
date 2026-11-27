"""Generate a private v2 inventory from a frozen Storage catalogue and its separately backed-up bytes.

With ``--download`` the bytes are first fetched from the source project: one GET per catalogued
object, nothing else, so the source is only ever read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import quote

import httpx

from scripts.restore_attachment_evidence import (
    ALL_BUCKETS,
    BUCKETS,
    VERSION_BUCKET,
    _part,
    _unique_keys,
    hidden_prompt,
)


def _walk_error(error):
    raise error


def _identity(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _files(bucket: Path):
    if bucket.is_symlink() or not bucket.is_dir():
        raise ValueError("missing or unsafe bucket directory")
    for directory, folders, names in os.walk(bucket, onerror=_walk_error):
        directory = Path(directory)
        if any((directory / name).is_symlink() for name in folders):
            raise ValueError("symbolic link in archive")
        for name in names:
            path = directory / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("unsafe archive object")
            yield path.relative_to(bucket).as_posix(), path, _identity(info)


def _scan(bucket: Path, expected: dict) -> tuple[list, dict]:
    records, identities = [], {}
    for key, path, identity in _files(bucket):
        if key not in expected or key in identities:
            raise ValueError("unexpected archive object")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as reader:
            before = os.fstat(reader.fileno())
            if _identity(before) != identity or before.st_size != expected[key]:
                raise ValueError("archived object changed or size differs from source")
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                size += len(chunk)
                if size > expected[key]:
                    raise ValueError("archive changed during capture")
                digest.update(chunk)
            if size != expected[key] or _identity(os.fstat(reader.fileno())) != identity:
                raise ValueError("archive changed during capture")
        identities[key] = identity
        records.append({"key": key, "size": size, "sha256": digest.hexdigest()})
    if identities.keys() != expected.keys():
        raise ValueError("archive lacks one or more catalogued objects")
    return sorted(records, key=lambda row: row["key"]), identities


def download(catalogue_path: Path, archive: Path, source: str, catalogue_sha256: str, service_key: str) -> None:
    """Fetch every catalogued object from the source project into a new archive tree."""
    raw = catalogue_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != catalogue_sha256:
        raise ValueError("source catalogue differs from separately retained receipt")
    buckets = json.loads(raw, object_pairs_hook=_unique_keys).get("buckets")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source) or not isinstance(buckets, dict) or not service_key:
        raise ValueError("a source project ref, its bucket catalogue and its service-role key are required")
    archive.mkdir(mode=0o700)
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "Accept-Encoding": "identity"}
    with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False) as client:
        for bucket, info in buckets.items():
            if bucket not in ALL_BUCKETS or not isinstance(info, dict) or not isinstance(info.get("objects"), dict):
                raise ValueError("incomplete source bucket catalogue")
            (archive / bucket).mkdir(mode=0o700)
            for key in info["objects"]:
                if not all(_part(part) for part in key.split("/")):
                    raise ValueError(f"an object key in {bucket} cannot be stored as a file path")
                target = archive / bucket / key
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                url = f"https://{source}.supabase.co/storage/v1/object/{bucket}/{quote(key, safe='/')}"
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        raise ValueError(f"source Storage answered {response.status_code} for an object in {bucket}")
                    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as dest:
                        for chunk in response.iter_bytes():
                            dest.write(chunk)


def capture(catalogue_path: Path, archive: Path, source: str, backup: str, catalogue_sha256: str) -> dict:
    raw = catalogue_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != catalogue_sha256:
        raise ValueError("source catalogue differs from separately retained receipt")
    catalogue = json.loads(raw, object_pairs_hook=_unique_keys)
    if (not source.strip() or not backup.strip() or not isinstance(catalogue, dict)
            or catalogue.get("source_environment") != source or catalogue.get("source_backup_id") != backup):
        raise ValueError("catalogue and recovery point do not match")
    buckets = catalogue.get("buckets")
    if not isinstance(buckets, dict) or set(buckets) not in (set(BUCKETS), set(ALL_BUCKETS)):
        raise ValueError("incomplete source bucket catalogue")
    result, captured = {}, {}
    for name in ALL_BUCKETS:
        folder = archive / name
        if name == VERSION_BUCKET and name not in buckets:
            if folder.exists() or folder.is_symlink():
                raise ValueError("unexpected version bucket in archive")
            result[name] = None
            continue
        info = buckets[name]
        if not isinstance(info, dict) or info.get("public") is not False:
            raise ValueError("source bucket is not confirmed private")
        expected = info.get("objects")
        if not isinstance(expected, dict) or any(
                not all(_part(part) for part in key.split("/")) or type(size) is not int or size < 0
                for key, size in expected.items()):
            raise ValueError("invalid or missing object metadata")
        result[name], captured[name] = _scan(folder, expected)
    for name in ALL_BUCKETS:
        folder = archive / name
        if name not in captured:
            if folder.exists() or folder.is_symlink():
                raise ValueError("version bucket appeared during capture")
        elif {key: ident for key, _, ident in _files(folder)} != captured[name]:
            raise ValueError("archive inventory changed during capture")
    return {"version": 2, "source_environment": source, "source_backup_id": backup, "buckets": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--catalogue-sha256", required=True, help="storage_catalogue_sha256 in pinned source receipt")
    parser.add_argument("--archive", type=Path, required=True, help="read-only bucket/key directory tree")
    parser.add_argument("--download", action="store_true",
                        help="create --archive first by reading every catalogued object from the source project")
    parser.add_argument("--source-environment", required=True)
    parser.add_argument("--source-backup-id", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new private manifest file")
    args = parser.parse_args()
    if args.download:
        if args.archive.exists() or args.archive.is_symlink():
            parser.exit(1, f"Nothing downloaded: {args.archive} already exists. Choose a new archive directory.\n")
        try:
            download(args.catalogue, args.archive, args.source_environment, args.catalogue_sha256,
                     hidden_prompt("Source service-role key"))
        except (OSError, ValueError, httpx.HTTPError, RecursionError) as exc:
            reason = exc if type(exc) is ValueError else type(exc).__name__
            parser.exit(1, f"Download failed: {reason}. Move the partial {args.archive} away before retrying.\n")
    try:
        if args.out.resolve().is_relative_to(args.archive.resolve()):
            raise ValueError("manifest output must be outside the archive tree")
        manifest = capture(args.catalogue, args.archive, args.source_environment, args.source_backup_id, args.catalogue_sha256)
        raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        # Publish only after the private file is complete; never replace an existing receipt.
        with tempfile.NamedTemporaryFile(dir=args.out.parent) as tmp:
            tmp.write(raw)
            tmp.flush()
            os.link(tmp.name, args.out)
    except (OSError, ValueError, RecursionError):
        parser.exit(1, "Capture failed. Check the frozen catalogue, all archive objects and unused output path.\n")
    print(f"manifest_sha256={hashlib.sha256(raw).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
