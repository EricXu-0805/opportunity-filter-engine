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


def _scan(bucket: Path, expected: dict) -> list[dict]:
    if bucket.is_symlink() or not bucket.is_dir():
        raise ValueError("missing or unsafe bucket directory")
    remaining = set(expected)
    records = []
    for directory, folders, names in os.walk(bucket, onerror=_walk_error):
        directory = Path(directory)
        if any((directory / name).is_symlink() for name in folders):
            raise ValueError("symbolic link in archive")
        for name in names:
            path = directory / name
            key = path.relative_to(bucket).as_posix()
            if key not in remaining or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("unexpected or unsafe archive object")
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as reader:
                if os.fstat(reader.fileno()).st_size != expected[key]:
                    raise ValueError("archived size differs from source catalogue")
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > expected[key]:
                        raise ValueError("archive changed during capture")
                    digest.update(chunk)
                if size != expected[key]:
                    raise ValueError("archive changed during capture")
            records.append({"key": key, "size": size, "sha256": digest.hexdigest()})
            remaining.remove(key)
    if remaining:
        raise ValueError("archive lacks one or more catalogued objects")
    return sorted(records, key=lambda row: row["key"])


def capture(catalogue_path: Path, archive: Path, source: str, backup: str) -> dict:
    catalogue = json.loads(catalogue_path.read_bytes(), object_pairs_hook=_unique_keys)
    if (not source.strip() or not backup.strip() or not isinstance(catalogue, dict)
            or catalogue.get("source_environment") != source or catalogue.get("source_backup_id") != backup):
        raise ValueError("catalogue and recovery point do not match")
    buckets = catalogue.get("buckets")
    if not isinstance(buckets, dict) or set(buckets) not in (set(BUCKETS), set(ALL_BUCKETS)):
        raise ValueError("incomplete source bucket catalogue")
    result = {}
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
        result[name] = _scan(folder, expected)
    return {"version": 2, "source_environment": source, "source_backup_id": backup, "buckets": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True, help="read-only bucket/key directory tree")
    parser.add_argument("--source-environment", required=True)
    parser.add_argument("--source-backup-id", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new private manifest file")
    args = parser.parse_args()
    try:
        if args.out.resolve().is_relative_to(args.archive.resolve()):
            raise ValueError("manifest output must be outside the archive tree")
        manifest = capture(args.catalogue, args.archive, args.source_environment, args.source_backup_id)
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
