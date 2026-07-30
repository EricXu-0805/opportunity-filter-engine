#!/usr/bin/env python3
"""Build, validate, and atomically apply a target-only refresh artifact.

The artifact is the replay boundary between a long scrape and publication on a
newer default branch. It contains only the shards explicitly authorized by the
canonical request, plus the structured collector status. Non-target corpus
files can therefore never be replayed from the run-start checkout. The global
Professor Updates ledger is intentionally not included until a target-safe
merge model exists; its feature remains hidden independently.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from refresh_rotation import normalize_requested_shard, target_shards  # noqa: E402

from src.collectors.refresh_contract import evaluate_refresh_summary  # noqa: E402

SCHEMA_VERSION = 2
MANIFEST_NAME = "refresh_manifest.json"
STATUS_RELATIVE = "data/processed/collector_status.json"
SHARD_PREFIX = "data/processed/shards"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RUN_ID_RE = re.compile(r"[1-9][0-9]*")
_SHARD_FILE_RE = re.compile(r"data/processed/shards/([a-z0-9-]{1,64})\.json")
MAX_SHARD_BYTES = 64 * 1024 * 1024
MAX_STATUS_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 384 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> object:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"artifact input is not a regular file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"artifact input is invalid JSON: {path}") from exc


def _record_shard(record: dict) -> str:
    if "school" not in record:
        raise ValueError("record school field is required")
    school = record["school"]
    if school is None:
        return "national"
    if school == "national":
        raise ValueError(
            "record school must be null for national records; "
            "national is a reserved shard name"
        )
    if (
        isinstance(school, str)
        and school == school.strip()
        and re.fullmatch(r"[a-z0-9-]{1,64}", school)
    ):
        return school
    raise ValueError("record school must be null or a canonical school slug")


def _entry_from_bytes(
    content: bytes,
    *,
    label: str,
    expect_list: bool,
    expected_shard: str | None = None,
) -> dict:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"artifact input is invalid JSON: {label}") from exc
    if expect_list:
        if not isinstance(payload, list) or any(
            not isinstance(record, dict) for record in payload
        ):
            raise ValueError(f"shard must be an array of objects: {label}")
        if not payload:
            raise ValueError(f"target shard must not be empty: {label}")
        if expected_shard is None:
            raise ValueError("expected shard is required for a shard artifact")
        misplaced = [
            index
            for index, record in enumerate(payload)
            if _record_shard(record) != expected_shard
        ]
        if misplaced:
            raise ValueError(
                f"shard contains record(s) for another school: "
                f"{label} indexes={misplaced[:10]}"
            )
        count = len(payload)
    else:
        if not isinstance(payload, dict):
            raise ValueError(f"collector status must be an object: {label}")
        count = None
    size = len(content)
    maximum = MAX_SHARD_BYTES if expect_list else MAX_STATUS_BYTES
    if size <= 0 or size > maximum:
        raise ValueError(f"artifact input size is out of bounds: {label} ({size})")
    entry = {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": size,
    }
    if count is not None:
        entry["count"] = count
    return entry


def _file_entry(
    path: Path,
    *,
    expect_list: bool,
    expected_shard: str | None = None,
) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"artifact input is not a regular file: {path}")
    return _entry_from_bytes(
        path.read_bytes(),
        label=str(path),
        expect_list=expect_list,
        expected_shard=expected_shard,
    )


def _git_preimage(
    repository_root: Path,
    *,
    base_sha: str,
    relative: str,
    expect_list: bool,
    expected_shard: str | None = None,
) -> dict:
    spec = f"{base_sha}:{relative}"
    exists = subprocess.run(
        ["git", "-C", str(repository_root), "cat-file", "-e", spec],
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        return {"absent": True}
    blob = subprocess.run(
        ["git", "-C", str(repository_root), "show", "--no-textconv", spec],
        check=False,
        capture_output=True,
    )
    if blob.returncode != 0:
        raise ValueError(f"could not read base Git blob: {relative}")
    return _entry_from_bytes(
        blob.stdout,
        label=spec,
        expect_list=expect_list,
        expected_shard=expected_shard,
    )


def _validate_base_commit(repository_root: Path, base_sha: str) -> Path:
    if not repository_root.is_dir() or repository_root.is_symlink():
        raise ValueError("base repository must be a real directory")
    resolved = repository_root.resolve(strict=True)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(resolved),
            "rev-parse",
            "--verify",
            f"{base_sha}^{{commit}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != base_sha:
        raise ValueError("base SHA is not the exact commit in base repository")
    return resolved


def _git_text(repository_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("repository root must be a real Git worktree")
    return result.stdout.strip()


def _validate_apply_repository(
    repository_root: Path,
    base_sha: str,
) -> tuple[Path, Path]:
    if not repository_root.is_dir() or repository_root.is_symlink():
        raise ValueError("repository root must be a real Git worktree")
    repository_root = repository_root.resolve(strict=True)
    if _git_text(repository_root, "rev-parse", "--is-inside-work-tree") != "true":
        raise ValueError("repository root must be a real Git worktree")
    worktree_root = Path(
        _git_text(repository_root, "rev-parse", "--show-toplevel")
    ).resolve(strict=True)
    if worktree_root != repository_root:
        raise ValueError("repository root must be the Git worktree root")
    repository_root = _validate_base_commit(repository_root, base_sha)

    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            base_sha,
            "HEAD",
        ],
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise ValueError(
            "expected base SHA must be an ancestor of the worktree HEAD"
        )

    common_text = _git_text(repository_root, "rev-parse", "--git-common-dir")
    common_dir = Path(common_text)
    if not common_dir.is_absolute():
        common_dir = repository_root / common_dir
    try:
        common_dir = common_dir.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Git common directory does not exist") from exc
    if not common_dir.is_dir() or common_dir.is_symlink():
        raise ValueError("Git common directory must be a real directory")
    return repository_root, common_dir


@contextmanager
def _publication_lock(git_common_dir: Path) -> Iterator[None]:
    lock_path = git_common_dir / "ofe-refresh-artifact.lock"
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ValueError("could not open refresh artifact publication lock") from exc
    try:
        try:
            fcntl.flock(
                descriptor,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            raise ValueError(
                "another refresh artifact publication is in progress"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _validate_workspace_inputs(
    repository_root: Path,
    *,
    source_shards: Path,
    collector_status: Path,
) -> tuple[Path, Path]:
    expected_shards = repository_root / SHARD_PREFIX
    expected_status = repository_root / STATUS_RELATIVE
    try:
        resolved_shards = source_shards.resolve(strict=True)
        resolved_status = collector_status.resolve(strict=True)
    except OSError as exc:
        raise ValueError("refresh artifact workspace inputs do not exist") from exc
    if (
        not resolved_shards.is_dir()
        or source_shards.is_symlink()
        or resolved_shards != expected_shards
    ):
        raise ValueError(
            "source shards must be the base repository worktree shard directory"
        )
    if (
        not resolved_status.is_file()
        or collector_status.is_symlink()
        or resolved_status != expected_status
    ):
        raise ValueError(
            "collector status must be the base repository worktree status file"
        )
    return resolved_shards, resolved_status


def _request_from_shard(
    normalized_shard: str,
    *,
    deep: bool,
) -> tuple[set[str] | None, bool, dict]:
    if normalized_shard == "":
        schools: set[str] | None = None
        national = False
    elif normalized_shard == "national":
        schools = None
        national = True
    else:
        schools = set(normalized_shard.split(","))
        national = False
    return schools, national, {
        "schools": sorted(schools) if schools is not None else None,
        "national": national,
        "deep": deep,
    }


def _validate_collector_status(
    status: object,
    normalized_shard: str,
    *,
    expected_deep: bool,
    expected_base_sha: str,
    expected_run_id: str,
    expected_run_attempt: str,
) -> dict:
    if not isinstance(status, dict):
        raise ValueError("collector status must be an object")
    request = status.get("request")
    if not isinstance(request, dict) or type(request.get("deep")) is not bool:
        raise ValueError("collector status request/deep binding is missing")
    if request["deep"] is not expected_deep:
        raise ValueError(
            "collector status deep mode does not match the trusted invocation"
        )
    schools, national, expected_request = _request_from_shard(
        normalized_shard,
        deep=expected_deep,
    )
    if request != expected_request:
        raise ValueError(
            "collector status request does not match the artifact shard"
        )
    expected_shard = None if normalized_shard == "" else {
        "schools": sorted(schools or ()),
        "national": national,
    }
    if status.get("shard") != expected_shard:
        raise ValueError(
            "collector status shard does not match the artifact shard"
        )
    expected_provenance = {
        "base_sha": expected_base_sha,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
    }
    if status.get("provenance") != expected_provenance:
        raise ValueError(
            "collector status provenance does not match the trusted invocation"
        )

    computed = evaluate_refresh_summary(
        status,
        schools=schools,
        national=national,
        deep=expected_deep,
        require_tracking=False,
    )
    if computed.get("ready") is not True:
        raise ValueError(
            f"collector status release contract is blocked: "
            f"{computed.get('reasons')}"
        )
    if status.get("release") != computed:
        raise ValueError(
            "stored collector release verdict does not match recomputation"
        )
    return status


def build_artifact(
    *,
    shard: str,
    base_sha: str,
    repository_root: Path,
    source_shards: Path,
    collector_status: Path,
    output: Path,
    expected_deep: bool,
    run_id: str,
    run_attempt: str,
) -> dict:
    normalized = normalize_requested_shard(shard, allow_full=False)
    targets = target_shards(normalized)
    if _SHA_RE.fullmatch(base_sha) is None:
        raise ValueError("base SHA must be a lowercase 40-character Git SHA")
    repository_root = _validate_base_commit(repository_root, base_sha)
    source_shards, collector_status = _validate_workspace_inputs(
        repository_root,
        source_shards=source_shards,
        collector_status=collector_status,
    )
    if output.exists():
        raise ValueError(f"artifact output already exists: {output}")
    if type(expected_deep) is not bool:
        raise ValueError("expected deep mode must be a boolean")
    for label, value in (("run id", run_id), ("run attempt", run_attempt)):
        if _RUN_ID_RE.fullmatch(str(value)) is None:
            raise ValueError(f"{label} must be a positive integer")
    run_id = str(run_id)
    run_attempt = str(run_attempt)

    status = _load_json(collector_status)
    _validate_collector_status(
        status,
        normalized,
        expected_deep=expected_deep,
        expected_base_sha=base_sha,
        expected_run_id=run_id,
        expected_run_attempt=run_attempt,
    )

    # Preflight every new target and its run-start preimage before creating the
    # output. The preimage map is the compare-and-swap guard used when applying
    # this artifact on a newer main revision.
    files: dict[str, dict] = {}
    preimages: dict[str, dict] = {}
    for slug in targets:
        source = source_shards / f"{slug}.json"
        relative = f"{SHARD_PREFIX}/{slug}.json"
        entry = _file_entry(
            source,
            expect_list=True,
            expected_shard=slug,
        )
        files[relative] = entry
        preimages[relative] = _git_preimage(
            repository_root,
            base_sha=base_sha,
            relative=relative,
            expect_list=True,
            expected_shard=slug,
        )

    status_entry = _file_entry(collector_status, expect_list=False)
    files[STATUS_RELATIVE] = status_entry
    preimages[STATUS_RELATIVE] = _git_preimage(
        repository_root,
        base_sha=base_sha,
        relative=STATUS_RELATIVE,
        expect_list=False,
    )

    total_size = sum(entry["size"] for entry in files.values())
    if total_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"refresh artifact exceeds {MAX_ARTIFACT_BYTES} bytes")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "base_sha": base_sha,
        "shard": normalized,
        "deep": expected_deep,
        "targets": list(targets),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "files": dict(sorted(files.items())),
        "destination_preimages": dict(sorted(preimages.items())),
        "total_size": total_size,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
        )
    )
    installed = False
    try:
        for slug in targets:
            relative = Path(SHARD_PREFIX) / f"{slug}.json"
            destination = temporary_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_shards / f"{slug}.json", destination)
        status_destination = temporary_root / STATUS_RELATIVE
        status_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(collector_status, status_destination)
        (temporary_root / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validate_artifact(
            temporary_root,
            expected_shard=normalized,
            expected_base_sha=base_sha,
            expected_deep=expected_deep,
            expected_run_id=run_id,
            expected_run_attempt=run_attempt,
        )
        os.replace(temporary_root, output)
        installed = True
    finally:
        if not installed:
            shutil.rmtree(temporary_root, ignore_errors=True)
    return manifest


def validate_artifact(
    root: Path,
    *,
    expected_shard: str | None = None,
    expected_base_sha: str | None = None,
    expected_deep: bool | None = None,
    expected_run_id: str | None = None,
    expected_run_attempt: str | None = None,
) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"artifact root is not a regular directory: {root}")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("refresh artifact must not contain symbolic links")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in paths
        if path.is_file()
    }

    manifest_path = root / MANIFEST_NAME
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get(
        "schema_version"
    ) != SCHEMA_VERSION:
        raise ValueError("refresh manifest schema is unsupported")
    expected_manifest_keys = {
        "schema_version",
        "base_sha",
        "shard",
        "deep",
        "targets",
        "run_id",
        "run_attempt",
        "files",
        "destination_preimages",
        "total_size",
    }
    if set(manifest) != expected_manifest_keys:
        raise ValueError("refresh manifest fields are not canonical")
    base_sha = manifest.get("base_sha")
    if not isinstance(base_sha, str) or _SHA_RE.fullmatch(base_sha) is None:
        raise ValueError("refresh manifest base SHA is invalid")
    if expected_base_sha is not None and base_sha != expected_base_sha:
        raise ValueError("refresh manifest base SHA does not match the request")
    deep = manifest.get("deep")
    if type(deep) is not bool:
        raise ValueError("refresh manifest deep mode is invalid")
    if expected_deep is not None and deep is not expected_deep:
        raise ValueError("refresh manifest deep mode does not match the request")
    for label, expected in (
        ("run_id", expected_run_id),
        ("run_attempt", expected_run_attempt),
    ):
        value = manifest.get(label)
        if (
            not isinstance(value, str)
            or _RUN_ID_RE.fullmatch(value) is None
        ):
            raise ValueError(f"refresh manifest {label} is invalid")
        if expected is not None and value != str(expected):
            raise ValueError(
                f"refresh manifest {label} does not match the request"
            )

    shard = manifest.get("shard")
    if not isinstance(shard, str):
        raise ValueError("refresh manifest shard is invalid")
    normalized = normalize_requested_shard(shard, allow_full=False)
    if expected_shard is not None and normalized != normalize_requested_shard(
        expected_shard,
        allow_full=False,
    ):
        raise ValueError("refresh artifact shard does not match the request")

    targets = manifest.get("targets")
    if targets != list(target_shards(normalized)):
        raise ValueError("refresh manifest target set is not canonical")

    entries = manifest.get("files")
    if not isinstance(entries, dict):
        raise ValueError("refresh manifest file map is invalid")
    preimages = manifest.get("destination_preimages")
    if not isinstance(preimages, dict):
        raise ValueError("refresh manifest destination preimages are invalid")
    expected_target_paths = {
        f"{SHARD_PREFIX}/{slug}.json"
        for slug in targets
    }
    if set(preimages) != expected_target_paths | {STATUS_RELATIVE}:
        raise ValueError(
            "refresh manifest destination preimage set is not canonical"
        )
    for relative, preimage in preimages.items():
        if not isinstance(preimage, dict):
            raise ValueError(f"target preimage is invalid: {relative}")
        if preimage == {"absent": True}:
            continue
        expect_count = relative != STATUS_RELATIVE
        expected_keys = {"sha256", "size", "count"} if expect_count else {
            "sha256",
            "size",
        }
        if (
            set(preimage) != expected_keys
            or not isinstance(preimage.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", preimage["sha256"]) is None
            or not isinstance(preimage.get("size"), int)
            or isinstance(preimage.get("size"), bool)
            or not 0 < preimage["size"] <= (
                MAX_SHARD_BYTES if expect_count else MAX_STATUS_BYTES
            )
            or (
                expect_count
                and (
                    not isinstance(preimage.get("count"), int)
                    or isinstance(preimage.get("count"), bool)
                    or preimage["count"] <= 0
                )
            )
        ):
            raise ValueError(
                f"destination preimage metadata is invalid: {relative}"
            )
    expected_paths = {
        *expected_target_paths,
        STATUS_RELATIVE,
        MANIFEST_NAME,
    }
    if actual_files != expected_paths or set(entries) != expected_paths - {
        MANIFEST_NAME
    }:
        raise ValueError("refresh artifact contains missing or unexpected files")

    total_size = 0
    for relative, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValueError(f"refresh manifest entry is invalid: {relative}")
        path = root / relative
        match = _SHARD_FILE_RE.fullmatch(relative)
        expect_list = match is not None
        if not expect_list and relative != STATUS_RELATIVE:
            raise ValueError(f"refresh artifact path is not allowed: {relative}")
        actual = _file_entry(
            path,
            expect_list=expect_list,
            expected_shard=match.group(1) if match is not None else None,
        )
        if actual != entry:
            raise ValueError(f"refresh artifact digest/count mismatch: {relative}")
        total_size += actual["size"]

    if total_size != manifest.get("total_size") or total_size > MAX_ARTIFACT_BYTES:
        raise ValueError("refresh artifact total size does not match its manifest")

    status = _load_json(root / STATUS_RELATIVE)
    _validate_collector_status(
        status,
        normalized,
        expected_deep=deep,
        expected_base_sha=base_sha,
        expected_run_id=manifest["run_id"],
        expected_run_attempt=manifest["run_attempt"],
    )
    return manifest


def _stage_copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, 0o644)
        staged = temporary_path
        temporary_path = None
        return staged
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _backup_destination(destination: Path) -> Path | None:
    if not destination.exists():
        return None
    if not destination.is_file() or destination.is_symlink():
        raise ValueError(f"artifact destination is not a regular file: {destination}")
    descriptor, name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".backup",
    )
    os.close(descriptor)
    backup = Path(name)
    backup.unlink()
    try:
        os.link(destination, backup)
    except OSError:
        shutil.copy2(destination, backup)
    return backup


def _safe_destination(repository_root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"artifact destination path is unsafe: {relative}")
    destination = repository_root / relative
    for candidate in (destination, *destination.parents):
        if candidate == repository_root.parent:
            break
        if candidate.is_symlink():
            raise ValueError(
                f"artifact destination traverses a symbolic link: {candidate}"
            )
        if candidate == repository_root:
            break
    try:
        destination.parent.resolve(strict=False).relative_to(repository_root)
    except ValueError as exc:
        raise ValueError(
            f"artifact destination escapes repository root: {relative}"
        ) from exc
    return destination


def _verify_destination_preimages(
    manifest: dict,
    repository_root: Path,
) -> None:
    paths = [
        (
            Path(SHARD_PREFIX) / f"{slug}.json",
            True,
            slug,
        )
        for slug in manifest["targets"]
    ]
    paths.append((Path(STATUS_RELATIVE), False, None))
    for relative, expect_list, expected_shard in paths:
        destination = _safe_destination(repository_root, relative)
        expected = manifest["destination_preimages"][relative.as_posix()]
        if expected == {"absent": True}:
            if destination.exists() or destination.is_symlink():
                raise ValueError(
                    f"artifact destination appeared after refresh start: {relative}"
                )
            continue
        if not destination.exists():
            raise ValueError(
                f"artifact destination disappeared after refresh start: {relative}"
            )
        actual = _file_entry(
            destination,
            expect_list=expect_list,
            expected_shard=expected_shard,
        )
        if actual != expected:
            raise ValueError(
                f"artifact destination changed after refresh start: {relative}"
            )


def _verify_manifest_preimages_against_git(
    manifest: dict,
    repository_root: Path,
) -> None:
    expected: dict[str, dict] = {}
    for slug in manifest["targets"]:
        relative = f"{SHARD_PREFIX}/{slug}.json"
        expected[relative] = _git_preimage(
            repository_root,
            base_sha=manifest["base_sha"],
            relative=relative,
            expect_list=True,
            expected_shard=slug,
        )
    expected[STATUS_RELATIVE] = _git_preimage(
        repository_root,
        base_sha=manifest["base_sha"],
        relative=STATUS_RELATIVE,
        expect_list=False,
    )
    if dict(sorted(expected.items())) != manifest["destination_preimages"]:
        raise ValueError(
            "refresh manifest destination preimages do not match "
            "the base Git commit"
        )


def _install_with_rollback(
    copies: list[tuple[Path, Path]],
    *,
    install_guard: AbstractContextManager | None = None,
    preflight: Callable[[list[dict[str, object]]], None] | None = None,
) -> None:
    operations: list[dict[str, object]] = []
    try:
        for source, destination in copies:
            staged = _stage_copy(source, destination)
            operations.append(
                {
                    "destination": destination,
                    "staged": staged,
                    "backup": None,
                    "backup_ready": False,
                    "installed": False,
                }
            )
        with install_guard or nullcontext():
            if preflight is not None:
                preflight(operations)
            for operation in operations:
                destination = operation["destination"]
                if not isinstance(destination, Path):
                    raise TypeError("artifact destination must be a path")
                operation["backup"] = _backup_destination(destination)
                operation["backup_ready"] = True
            for operation in operations:
                os.replace(operation["staged"], operation["destination"])
                operation["installed"] = True
    except BaseException as install_error:
        rollback_errors: list[str] = []
        for operation in reversed(operations):
            destination = operation["destination"]
            backup = operation["backup"]
            # Restore every destination whose pre-install state was captured,
            # not only those whose Python-side "installed" flag was reached.
            # A cancellation can arrive after os.replace completed but before
            # the next bytecode marks the operation installed.
            if operation["backup_ready"]:
                try:
                    if isinstance(backup, Path):
                        os.replace(backup, destination)
                        operation["backup"] = None
                    else:
                        destination.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(
                        f"{destination}: {rollback_error}"
                    )
        if rollback_errors:
            raise RuntimeError(
                "refresh artifact install failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from install_error
        raise
    finally:
        for operation in operations:
            staged = operation.get("staged")
            backup = operation.get("backup")
            if isinstance(staged, Path):
                staged.unlink(missing_ok=True)
            if isinstance(backup, Path):
                backup.unlink(missing_ok=True)


def _validate_apply_identity(
    *,
    expected_shard: object,
    expected_base_sha: object,
    expected_deep: object,
    expected_run_id: object,
    expected_run_attempt: object,
) -> str:
    if not isinstance(expected_shard, str) or not expected_shard:
        raise ValueError("expected shard must be a nonempty canonical string")
    normalized_shard = normalize_requested_shard(
        expected_shard,
        allow_full=False,
    )
    if (
        not isinstance(expected_base_sha, str)
        or _SHA_RE.fullmatch(expected_base_sha) is None
    ):
        raise ValueError(
            "expected base SHA must be a lowercase 40-character Git SHA"
        )
    if type(expected_deep) is not bool:
        raise ValueError("expected deep mode must be a boolean")
    for label, value in (
        ("run_id", expected_run_id),
        ("run_attempt", expected_run_attempt),
    ):
        if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
            raise ValueError(f"expected {label} must be a positive integer string")
    return normalized_shard


def apply_artifact(
    root: Path,
    *,
    repository_root: Path,
    expected_shard: str,
    expected_base_sha: str,
    expected_deep: bool,
    expected_run_id: str,
    expected_run_attempt: str,
) -> dict:
    normalized_shard = _validate_apply_identity(
        expected_shard=expected_shard,
        expected_base_sha=expected_base_sha,
        expected_deep=expected_deep,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )
    repository_root, git_common_dir = _validate_apply_repository(
        repository_root,
        expected_base_sha,
    )
    manifest = validate_artifact(
        root,
        expected_shard=normalized_shard,
        expected_base_sha=expected_base_sha,
        expected_deep=expected_deep,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )
    _verify_manifest_preimages_against_git(manifest, repository_root)
    copies: list[tuple[Path, Path]] = []
    for slug in manifest["targets"]:
        relative = Path(SHARD_PREFIX) / f"{slug}.json"
        copies.append(
            (
                root / relative,
                _safe_destination(repository_root, relative),
            )
        )
    status_relative = Path(STATUS_RELATIVE)
    copies.append(
        (
            root / status_relative,
            _safe_destination(repository_root, status_relative),
        )
    )

    def preflight(operations: list[dict[str, object]]) -> None:
        current_root, current_common_dir = _validate_apply_repository(
            repository_root,
            expected_base_sha,
        )
        if (
            current_root != repository_root
            or current_common_dir != git_common_dir
        ):
            raise ValueError("Git worktree identity changed during artifact apply")
        _verify_manifest_preimages_against_git(manifest, repository_root)
        _verify_destination_preimages(manifest, repository_root)
        # validate_artifact() ran before staging. Re-bind the exact private
        # staged bytes to the in-memory manifest so swapping an artifact source
        # between validation and copy cannot install unreviewed content.
        for operation in operations:
            destination = operation.get("destination")
            staged = operation.get("staged")
            if not isinstance(destination, Path) or not isinstance(staged, Path):
                raise ValueError("staged artifact operation is invalid")
            try:
                relative = destination.relative_to(repository_root).as_posix()
            except ValueError as exc:
                raise ValueError("staged artifact destination escaped root") from exc
            match = _SHARD_FILE_RE.fullmatch(relative)
            actual = _file_entry(
                staged,
                expect_list=match is not None,
                expected_shard=match.group(1) if match is not None else None,
            )
            if actual != manifest["files"].get(relative):
                raise ValueError(
                    f"staged artifact digest/count mismatch: {relative}"
                )

    _install_with_rollback(
        copies,
        install_guard=_publication_lock(git_common_dir),
        preflight=preflight,
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--shard", required=True)
    build.add_argument("--base-sha", required=True)
    build.add_argument("--repository-root", type=Path, required=True)
    build.add_argument("--source-shards", type=Path, required=True)
    build.add_argument("--collector-status", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--mode", choices=("deep", "quick"), required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--run-attempt", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--artifact", type=Path, required=True)
    validate.add_argument("--expected-shard")
    validate.add_argument("--expected-base-sha")
    validate.add_argument("--expected-mode", choices=("deep", "quick"))
    validate.add_argument("--expected-run-id")
    validate.add_argument("--expected-run-attempt")

    apply = subparsers.add_parser("apply")
    apply.add_argument("--artifact", type=Path, required=True)
    apply.add_argument("--repository-root", type=Path, required=True)
    apply.add_argument("--expected-shard", required=True)
    apply.add_argument("--expected-base-sha", required=True)
    apply.add_argument("--expected-mode", choices=("deep", "quick"), required=True)
    apply.add_argument("--expected-run-id", required=True)
    apply.add_argument("--expected-run-attempt", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_artifact(
                shard=args.shard,
                base_sha=args.base_sha,
                repository_root=args.repository_root,
                source_shards=args.source_shards,
                collector_status=args.collector_status,
                output=args.output,
                expected_deep=args.mode == "deep",
                run_id=args.run_id,
                run_attempt=args.run_attempt,
            )
        elif args.command == "validate":
            manifest = validate_artifact(
                args.artifact,
                expected_shard=args.expected_shard,
                expected_base_sha=args.expected_base_sha,
                expected_deep=(
                    None
                    if args.expected_mode is None
                    else args.expected_mode == "deep"
                ),
                expected_run_id=args.expected_run_id,
                expected_run_attempt=args.expected_run_attempt,
            )
        else:
            manifest = apply_artifact(
                args.artifact,
                repository_root=args.repository_root,
                expected_shard=args.expected_shard,
                expected_base_sha=args.expected_base_sha,
                expected_deep=args.expected_mode == "deep",
                expected_run_id=args.expected_run_id,
                expected_run_attempt=args.expected_run_attempt,
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"refresh artifact {args.command}: "
        f"{len(manifest['targets'])} target shard(s), "
        f"base {manifest['base_sha'][:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
