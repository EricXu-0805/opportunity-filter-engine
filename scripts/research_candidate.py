"""Build and explicitly promote bounded, research-only local candidate artifacts.

A run envelope is a local journal export, not a signed attestation of OpenAlex
responses. Its corpus digest identifies the original input order; candidate
validation instead proves every selected preimage against committed shards.
No collector status, workflow, Git commit, or network operation is performed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from scripts import refresh_artifact as artifacts
from scripts.refresh_rotation import normalize_requested_shard
from src.collectors import openalex_enrich as oa
from src.collectors.research_queue import canonical_sha256, research_binding_key

MANIFEST = "research_manifest.json"
RUN_FILE = "run.json"
MAX_RUN_BYTES = 2 * 1024 * 1024
_OUTCOMES = frozenset({"success_nonempty", "success_empty", "failed", "incomplete", "deferred",
                       "identity_revoked", "conflict", "needs_review"})
_RUN_KEYS = {"version", "run_id", "base_sha", "corpus_sha256", "settings", "started_at", "finished_at",
             "status", "request_count", "unknown_request_count", "credits_observed", "credit_accounting_complete", "cooldown_until",
             "counts", "targets"}
_TARGET_KEYS = {"record_id", "school", "binding_key", "before_sha256", "outcome", "reason", "attempted", "patch"}
_RESEARCH_FIELDS = frozenset({"research_snapshot", "research_refresh", "recent_works", "publication_attribution_status"})
_HASH = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_STAMP = re.compile(r"[1-9][0-9]{3}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_SHARD = re.compile(r"data/processed/shards/([a-z0-9-]{1,64})\.json")


def _bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid_candidate_json") from error


def _digest(content: bytes) -> dict:
    return {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _decode(content: bytes) -> object:
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_object,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_json")))
        _bytes(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid_candidate_json") from error


def _read(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("invalid_candidate_file")
    content = path.read_bytes()
    if not 0 < len(content) <= maximum:
        raise ValueError("invalid_candidate_file")
    return content


def _stamp(value: object) -> datetime:
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise ValueError("invalid_candidate_time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid_candidate_time") from error


def _finite(value: object, *, positive: bool = False) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def _check_run(run: object, expected_run_id: str | None = None) -> dict:
    if type(run) is not dict or set(run) != _RUN_KEYS or type(run.get("version")) is not int or run["version"] != 1:
        raise ValueError("invalid_research_run_envelope")
    if type(run["run_id"]) is not str or _RUN_ID.fullmatch(run["run_id"]) is None:
        raise ValueError("invalid_research_run_id")
    if expected_run_id is not None and run["run_id"] != expected_run_id:
        raise ValueError("research_run_mismatch")
    if type(run["base_sha"]) is not str or re.fullmatch(r"[0-9a-f]{40}", run["base_sha"]) is None:
        raise ValueError("invalid_research_base")
    if type(run["corpus_sha256"]) is not str or _HASH.fullmatch(run["corpus_sha256"]) is None:
        raise ValueError("invalid_research_corpus_digest")
    started, finished = _stamp(run["started_at"]), _stamp(run["finished_at"])
    if finished < started or finished > datetime.now(UTC) or run["status"] not in ("completed", "deferred"):
        raise ValueError("research_run_not_finished")
    if run["cooldown_until"] is not None:
        _stamp(run["cooldown_until"])
    settings = run["settings"]
    if type(settings) is not dict or set(settings) != {"schools", "limit", "max_requests", "max_seconds", "min_remaining"}:
        raise ValueError("invalid_research_settings")
    schools = settings["schools"]
    if schools is not None:
        if type(schools) is not list or not schools or any(type(s) is not str for s in schools):
            raise ValueError("invalid_research_schools")
        normalize_requested_shard(",".join(schools), allow_full=False)
        if "national" in schools:
            raise ValueError("invalid_research_schools")
    if (type(settings["limit"]) is not int or not 1 <= settings["limit"] <= 25
            or type(settings["max_requests"]) is not int or not 1 <= settings["max_requests"] <= 10000
            or not _finite(settings["max_seconds"], positive=True) or settings["max_seconds"] > 86400
            or not _finite(settings["min_remaining"])):
        raise ValueError("invalid_research_settings")
    if (type(run["request_count"]) is not int or not 0 <= run["request_count"] <= settings["max_requests"]
            or type(run["unknown_request_count"]) is not int
            or not 0 <= run["unknown_request_count"] <= run["request_count"]
            or not _finite(run["credits_observed"]) or type(run["credit_accounting_complete"]) is not bool
            or (run["unknown_request_count"] > 0 and run["credit_accounting_complete"])):
        raise ValueError("invalid_research_accounting")
    targets, counts = run["targets"], run["counts"]
    if (type(targets) is not list or len(targets) > settings["limit"] or type(counts) is not dict
            or any(key not in _OUTCOMES or type(count) is not int or count < 0 for key, count in counts.items())):
        raise ValueError("invalid_research_targets")
    seen = set()
    for target in targets:
        if type(target) is not dict or set(target) != _TARGET_KEYS:
            raise ValueError("invalid_research_target")
        rid, school = target["record_id"], target["school"]
        if type(rid) is not str or not rid.strip() or "\x00" in rid or len(rid) > 512 or rid in seen:
            raise ValueError("invalid_research_record_id")
        seen.add(rid)
        if type(school) is not str or school not in oa.SCHOOL_INST or (schools is not None and school not in schools):
            raise ValueError("research_target_outside_scope")
        normalize_requested_shard(school, allow_full=False)
        if any(type(target[key]) is not str or _HASH.fullmatch(target[key]) is None for key in ("binding_key", "before_sha256")):
            raise ValueError("invalid_research_target_digest")
        if type(target["outcome"]) is not str or target["outcome"] not in _OUTCOMES or type(target["attempted"]) is not bool:
            raise ValueError("invalid_research_outcome")
        if target["reason"] is not None and (type(target["reason"]) is not str or len(target["reason"]) > 512 or "\x00" in target["reason"]):
            raise ValueError("invalid_research_reason")
        outcome, patch = target["outcome"], target["patch"]
        if outcome in ("deferred", "conflict") and patch is not None:
            raise ValueError("unexpected_research_patch")
        if outcome not in ("deferred", "conflict", "needs_review") and patch is None:
            raise ValueError("missing_research_patch")
        if outcome.startswith("success_") and (target["reason"] is not None or target["attempted"] is not True):
            raise ValueError("invalid_research_success")
    derived = Counter(target["outcome"] for target in targets)
    if run["status"] != ("deferred" if derived["deferred"] else "completed"):
        raise ValueError("research_run_status_mismatch")
    if any(counts.get(key, 0) != derived.get(key, 0) for key in _OUTCOMES):
        raise ValueError("research_counts_mismatch")
    if sum(target["attempted"] for target in targets) > run["request_count"]:
        raise ValueError("invalid_research_accounting")
    if len(_bytes(run)) > MAX_RUN_BYTES:
        raise ValueError("research_run_too_large")
    return deepcopy(run)


def _git(repository: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("research_git_read_failed")
    return result.stdout


def _records(content: bytes, relative: str) -> list[dict]:
    match = _SHARD.fullmatch(relative)
    if match is None:
        raise ValueError("invalid_research_shard_path")
    value = _decode(content)
    if type(value) is not list or not value or any(type(record) is not dict for record in value):
        raise ValueError("invalid_research_shard")
    for record in value:
        if artifacts._record_shard(record) != match[1] or type(record.get("metadata", {})) is not dict:
            raise ValueError("invalid_research_record")
    return value


def _all_shards(repository: Path, *, base: str | None = None) -> tuple[dict[str, bytes], dict[str, list[dict]]]:
    if base is not None:
        paths = _git(repository, "ls-tree", "-r", "--name-only", "-z", base, artifacts.SHARD_PREFIX).decode().split("\0")
        paths = sorted(path for path in paths if path)
    else:
        directory = artifacts._safe_destination(repository, Path(artifacts.SHARD_PREFIX))
        paths = sorted(path.relative_to(repository).as_posix() for path in directory.glob("*.json"))
    if not paths or any(_SHARD.fullmatch(path) is None for path in paths):
        raise ValueError("invalid_research_shard_set")
    content, records = {}, {}
    for path in paths:
        if base is None:
            raw = _read(artifacts._safe_destination(repository, Path(path)), artifacts.MAX_SHARD_BYTES)
        else:
            mode = _git(repository, "ls-tree", base, "--", path).split(b" ", 1)[0]
            if mode != b"100644":
                raise ValueError("invalid_research_git_file")
            raw = _git(repository, "show", "--no-textconv", f"{base}:{path}")
            if not 0 < len(raw) <= artifacts.MAX_SHARD_BYTES:
                raise ValueError("research_shard_too_large")
        content[path], records[path] = raw, _records(raw, path)
    corpus = [record for path in sorted(records) for record in records[path]]
    oa._validate_research_corpus(corpus)
    return content, records


def _patch_record(before: dict, target: dict, run: dict) -> dict:
    if (before.get("id") != target["record_id"] or before.get("school") != target["school"]
            or canonical_sha256(before) != target["before_sha256"] or research_binding_key(before) != target["binding_key"]):
        raise ValueError("research_record_preimage_mismatch")
    patch, outcome = target["patch"], target["outcome"]
    if patch is None:
        return deepcopy(before)
    if not oa.research_targets([before], schools=[target["school"]]):
        raise ValueError("research_target_ineligible")
    if type(patch) is not dict or list(patch) != [oa._person_key(before)]:
        raise ValueError("research_patch_identity_mismatch")
    entry = next(iter(patch.values()))
    success = outcome.startswith("success_")
    expected_keys = {"binding", "research_refresh"} | ({"research_snapshot"} if success else set())
    if type(entry) is not dict or set(entry) != expected_keys or entry["binding"] != oa._research_binding(before):
        raise ValueError("invalid_research_patch")
    refresh = entry["research_refresh"]
    if type(refresh) is not dict or set(refresh) != {"checked_at", "status", "reason"}:
        raise ValueError("invalid_research_patch")
    stamp = _stamp(refresh["checked_at"])
    if not _stamp(run["started_at"]) <= stamp <= _stamp(run["finished_at"]):
        raise ValueError("research_patch_time_outside_run")
    expected_status = "success" if success else "incomplete" if outcome == "incomplete" else "failed"
    if refresh["status"] != expected_status or refresh["reason"] != target["reason"]:
        raise ValueError("research_patch_outcome_mismatch")
    if (outcome == "identity_revoked") != (refresh["reason"] == "identity_revoked"):
        raise ValueError("research_patch_revocation_mismatch")
    candidate = deepcopy(before)
    if oa.apply_research_refresh([candidate], patch, now=_stamp(run["finished_at"])) != 1:
        raise ValueError("research_patch_refused")
    if success:
        works = candidate["metadata"]["research_snapshot"]["works"]
        if bool(works) != (outcome == "success_nonempty"):
            raise ValueError("research_patch_outcome_mismatch")
    stripped_before, stripped_after = deepcopy(before), deepcopy(candidate)
    for value in (stripped_before, stripped_after):
        for field in _RESEARCH_FIELDS:
            value.get("metadata", {}).pop(field, None)
    if stripped_before != stripped_after:
        raise ValueError("research_patch_changed_unrelated_fields")
    old_status = before.get("metadata", {}).get("publication_attribution_status")
    if outcome != "identity_revoked" and candidate.get("metadata", {}).get("publication_attribution_status") != old_status:
        raise ValueError("research_patch_changed_authority")
    return candidate


def _collision_check(records: dict[str, list[dict]], targets: list[dict], base_index: dict[str, dict]) -> None:
    corpus = [record for shard in records.values() for record in shard]
    ambiguous = oa.ambiguous_author_ids([
        record for record in corpus if type(record.get("pi_name")) is str
        and type(record.get("metadata", {}).get("publication_author_id")) is str
    ])
    for target in targets:
        if target["patch"] is None or target["outcome"] == "identity_revoked":
            continue
        aid = base_index[target["record_id"]].get("metadata", {}).get("publication_author_id")
        if aid in ambiguous:
            raise ValueError("research_author_collision")


def _rebuild(run: dict, repository: Path) -> tuple[dict, dict[str, bytes], dict[str, dict]]:
    base_bytes, base_records = _all_shards(repository, base=run["base_sha"])
    index = {record.get("id"): record for records in base_records.values() for record in records if record.get("id") is not None}
    after_records = deepcopy(base_records)
    after_index = {record.get("id"): record for records in after_records.values() for record in records if record.get("id") is not None}
    targets = []
    for target in run["targets"]:
        before = index.get(target["record_id"])
        if before is None:
            raise ValueError("research_record_missing_from_base")
        after = _patch_record(before, target, run)
        after_index[target["record_id"]].clear()
        after_index[target["record_id"]].update(after)
        targets.append({key: target[key] for key in ("record_id", "school", "binding_key", "before_sha256", "outcome")}
                       | {"after_sha256": canonical_sha256(after)})
    _collision_check(base_records, run["targets"], index)
    paths = sorted({f"{artifacts.SHARD_PREFIX}/{target['school']}.json" for target in run["targets"]})
    outputs = {path: (base_bytes[path] if after_records[path] == base_records[path] else _bytes(after_records[path])) for path in paths}
    if not any(outputs[path] != base_bytes[path] for path in paths):
        raise ValueError("research_candidate_no_changes")
    shards = {path: {"before": {**_digest(base_bytes[path]), "count": len(base_records[path])},
                     "after": {**_digest(outputs[path]), "count": len(after_records[path])}} for path in paths}
    run_bytes = _bytes(run)
    total = len(run_bytes) + sum(len(raw) for raw in outputs.values())
    if total > artifacts.MAX_ARTIFACT_BYTES:
        raise ValueError("research_candidate_too_large")
    manifest = {"version": 1, "kind": "research_candidate", "run_id": run["run_id"], "base_sha": run["base_sha"],
                "run": {"path": RUN_FILE, **_digest(run_bytes)}, "shards": shards, "targets": targets, "total_size": total}
    return manifest, {RUN_FILE: run_bytes, **outputs}, index


def _current_state(repository: Path, manifest: dict, run: dict, index: dict[str, dict], *, allow_applied: bool) -> str:
    current_bytes, current_records = _all_shards(repository)
    modes = set()
    for path, entries in manifest["shards"].items():
        raw = current_bytes.get(path)
        if raw is None:
            raise ValueError("research_destination_missing")
        current = {**_digest(raw), "count": len(current_records[path])}
        if current == entries["before"]:
            if entries["before"] != entries["after"]:
                modes.add("before")
        elif allow_applied and current == entries["after"]:
            modes.add("after")
        else:
            raise ValueError("research_destination_changed")
    if len(modes) != 1:
        raise ValueError("research_destination_partial_apply")
    _collision_check(current_records, run["targets"], index)
    return "already_applied" if modes == {"after"} else "pending"


def _load_candidate(root: Path, repository_root: Path, expected_run_id: str) -> tuple[dict, dict, dict, Path, Path]:
    if type(expected_run_id) is not str or _RUN_ID.fullmatch(expected_run_id) is None:
        raise ValueError("invalid_research_run_id")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid_research_artifact_root")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
        raise ValueError("research_artifact_symlink")
    run = _check_run(_decode(_read(root / RUN_FILE, MAX_RUN_BYTES)), expected_run_id)
    repository, common = artifacts._validate_apply_repository(repository_root, run["base_sha"])
    manifest, outputs, index = _rebuild(run, repository)
    stored = _decode(_read(root / MANIFEST, MAX_RUN_BYTES))
    actual_paths = {path.relative_to(root).as_posix() for path in paths if path.is_file()}
    if actual_paths != set(outputs) | {MANIFEST} or stored != manifest:
        raise ValueError("research_candidate_manifest_mismatch")
    for relative, expected in outputs.items():
        maximum = MAX_RUN_BYTES if relative == RUN_FILE else artifacts.MAX_SHARD_BYTES
        if _read(root / relative, maximum) != expected:
            raise ValueError("research_candidate_content_mismatch")
    return manifest, run, index, repository, common


def build_candidate(run: dict, *, repository_root: Path, output: Path) -> dict:
    """Create a fresh candidate; the repository and journal remain unchanged."""
    run = _check_run(run)
    repository, _ = artifacts._validate_apply_repository(repository_root, run["base_sha"])
    manifest, outputs, index = _rebuild(run, repository)
    _current_state(repository, manifest, run, index, allow_applied=False)
    if output.exists() or output.is_symlink():
        raise ValueError("research_artifact_output_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=output.parent, prefix=".research-candidate-"))
    try:
        for relative, content in {**outputs, MANIFEST: _bytes(manifest)}.items():
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        validate_candidate(temporary, repository_root=repository, expected_run_id=run["run_id"])
        # Exclusive directory reservation cannot replace a racing empty dir.
        # The manifest is installed last; a crash leaves an incomplete artifact
        # that validation rejects, never an earlier artifact silently erased.
        output.mkdir(mode=0o700)
        for relative in [*outputs, MANIFEST]:
            destination = artifacts._safe_destination(output, Path(relative))
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write((temporary / relative).read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def validate_candidate(root: Path, *, repository_root: Path, expected_run_id: str) -> dict:
    manifest, run, index, repository, _ = _load_candidate(root, repository_root, expected_run_id)
    _current_state(repository, manifest, run, index, allow_applied=True)
    return manifest


def promote_candidate(root: Path, *, repository_root: Path, expected_run_id: str) -> dict:
    """Explicit local shard promotion; no commits, pushes, or workflow writes."""
    manifest, run, index, repository, common = _load_candidate(root, repository_root, expected_run_id)
    with artifacts._publication_lock(common):
        state = _current_state(repository, manifest, run, index, allow_applied=True)
        if state == "already_applied":
            return {"status": state, "run_id": run["run_id"], "manifest": manifest}
    copies = [(root / path, artifacts._safe_destination(repository, Path(path))) for path in manifest["shards"]
              if manifest["shards"][path]["before"] != manifest["shards"][path]["after"]]

    def preflight(operations: list[dict]) -> None:
        current_root, current_common = artifacts._validate_apply_repository(repository, run["base_sha"])
        if current_root != repository or current_common != common:
            raise ValueError("research_repository_changed")
        if _current_state(repository, manifest, run, index, allow_applied=False) != "pending":
            raise ValueError("research_destination_changed")
        for operation in operations:
            relative = operation["destination"].relative_to(repository).as_posix()
            raw = _read(operation["staged"], artifacts.MAX_SHARD_BYTES)
            if {**_digest(raw), "count": len(_records(raw, relative))} != manifest["shards"][relative]["after"]:
                raise ValueError("research_staged_content_changed")

    artifacts._install_with_rollback(copies, install_guard=artifacts._publication_lock(common), preflight=preflight)
    return {"status": "applied", "run_id": run["run_id"], "manifest": manifest}
