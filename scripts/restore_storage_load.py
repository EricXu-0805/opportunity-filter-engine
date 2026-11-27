"""Upload a verified attachment archive into the scratch project of a restore drill.

A restored project has the Storage metadata rows of its source and none of the object bytes.
This is the only drill script that writes anything outside the operator's machine. It writes
Storage objects, and only to a project other than the one the inventory was taken from.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from scripts.restore_attachment_evidence import _manifest


def verified_objects(manifest: Path, manifest_sha256: str, archive: Path, source: str, backup: str,
                     scratch: str) -> list[tuple[str, str, bytes]]:
    """Every inventoried object, read from the archive and checked, before anything is sent."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", scratch) or scratch == source:
        raise ValueError("the scratch project must be named and must not be the source project")
    try:
        expected = _manifest(manifest, manifest_sha256, source, backup)
    except ValueError:
        raise ValueError("the inventory does not match its digest, this source project or this recovery point") from None
    bodies = []
    for bucket, objects in expected.items():
        for key, (size, digest) in (objects or {}).items():
            body = (archive / bucket / key).read_bytes()
            if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
                raise ValueError(f"an archived object in {bucket} differs from the inventory")
            bodies.append((bucket, key, body))
    return bodies


def upload(scratch: str, service_key: str, bodies: list[tuple[str, str, bytes]]) -> None:
    # x-upsert: the restored database already holds a metadata row for every key.
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "x-upsert": "true",
               "Content-Type": "application/octet-stream"}
    with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False) as client:
        for bucket, key, body in bodies:
            response = client.post(f"https://{scratch}.supabase.co/storage/v1/object/{bucket}/{quote(key, safe='/')}",
                                   headers=headers, content=body)
            if response.status_code != 200:
                raise ValueError(f"scratch Storage answered {response.status_code} for an upload to {bucket}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attachment-manifest", type=Path, required=True)
    parser.add_argument("--attachment-manifest-sha256", required=True)
    parser.add_argument("--archive", type=Path, required=True, help="bucket/key directory tree the inventory was built from")
    parser.add_argument("--source-environment", required=True, help="project ref the inventory was taken from")
    parser.add_argument("--source-backup-id", required=True)
    parser.add_argument("--scratch-environment", required=True, help="project ref to upload INTO (never the source)")
    args = parser.parse_args()
    try:
        bodies = verified_objects(args.attachment_manifest, args.attachment_manifest_sha256, args.archive,
                                  args.source_environment, args.source_backup_id, args.scratch_environment)
        upload(args.scratch_environment, getpass.getpass("Scratch service-role key (input hidden): "), bodies)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"Upload stopped: {exc if type(exc) is ValueError else type(exc).__name__}.\n")
    print(f"uploaded {len(bodies)} object{'' if len(bodies) == 1 else 's'} to {args.scratch_environment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
