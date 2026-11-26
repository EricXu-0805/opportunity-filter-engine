"""Generate a private v2 inventory from a frozen Storage catalogue and its separately backed-up bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

from scripts.restore_attachment_evidence import ALL_BUCKETS, BUCKETS, VERSION_BUCKET, _part, _unique_keys


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
    parser.add_argument("--source-environment", required=True)
    parser.add_argument("--source-backup-id", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new private manifest file")
    args = parser.parse_args()
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
