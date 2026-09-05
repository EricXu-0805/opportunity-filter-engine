"""Target-only refresh artifact provenance, CAS, and replay tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import refresh_artifact as refresh_artifact_module  # noqa: E402
from refresh_artifact import (  # noqa: E402
    STATUS_RELATIVE,
    apply_artifact,
    build_artifact,
    validate_artifact,
)

from src.collectors.refresh_contract import (  # noqa: E402
    evaluate_refresh_summary,
    expected_sources,
)

RUN_ID = "123"
RUN_ATTEMPT = "1"


def _records(
    school: str | None,
    marker: str,
    count: int = 2,
) -> list[dict]:
    prefix = school or "national"
    return [
        {
            "id": f"{prefix}-{marker}-{index}",
            "school": school,
            "title": marker,
        }
        for index in range(count)
    ]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


def _run_git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_base_repository(
    root: Path,
    shards: dict[str, list[dict]],
) -> tuple[Path, str]:
    repository = root / "base-repository"
    repository.mkdir(parents=True)
    for slug, records in shards.items():
        _write_json(
            repository / f"data/processed/shards/{slug}.json",
            records,
        )
    _write_json(repository / STATUS_RELATIVE, {"old_status": True})
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.name", "Artifact Test")
    _run_git(repository, "config", "user.email", "artifact@example.invalid")
    _run_git(repository, "add", "data")
    _run_git(repository, "commit", "-qm", "base")
    return repository, _run_git(repository, "rev-parse", "HEAD")


def _source_info(key: str, *, deep: bool) -> dict:
    info = {"status": "ok", "fetched": 1}
    if deep and (key == "ucb_campus" or key.startswith("campus_graph:")):
        info.update(
            {
                "deep": True,
                "crawl_sources_expected": 1,
                "crawl_sources_loaded": 1,
                "live_pages_attempted": 1,
                "live_pages_loaded": 1,
                "seed_pages_expected": 1,
                "seed_pages_loaded": 1,
                "seed_pages_failed": 0,
                "seed_records": 1,
                "discovered_records": 0,
                "crawl_errors": [],
                "degraded_page_errors": [],
            }
        )
    if key == "uiuc_faculty":
        info["stale_deactivation_authorized"] = False
    if key == "ucsb_urca_projects":
        info.update(
            {
                "sitemap_complete": True,
                "sitemaps_expected": 2,
                "sitemaps_loaded": 2,
                "unexpected_location_count": 0,
                "empty_confirmed": False,
            }
        )
    return info


def _ready_status(
    path: Path,
    *,
    base_sha: str,
    shard: str = "uw",
    deep: bool = True,
    run_id: str = RUN_ID,
    run_attempt: str = RUN_ATTEMPT,
    ready: bool = True,
) -> None:
    if shard == "":
        schools = None
        national = False
    elif shard == "national":
        schools = None
        national = True
    else:
        schools = set(shard.split(","))
        national = False
    policies = expected_sources(
        schools,
        national=national,
        deep=deep,
    )
    sources = {
        key: _source_info(key, deep=deep)
        for key in policies
    }
    if "uiuc_faculty" in policies:
        sources["deactivate_stale_faculty"] = {
            "status": "ok",
            "skipped_partial_scrape": [],
            "deactivation_not_authorized": ["uiuc_faculty"],
        }
    sources["professor_tracking"] = {
        "status": "ok",
        "release_ready": False,
        "publication_status": "local_only_not_in_refresh_artifact",
    }
    payload = {
        "request": {
            "schools": sorted(schools) if schools is not None else None,
            "national": national,
            "deep": deep,
        },
        "provenance": {
            "base_sha": base_sha,
            "run_id": run_id,
            "run_attempt": run_attempt,
        },
        "sources": sources,
    }
    if shard != "":
        payload["shard"] = {
            "schools": sorted(schools or ()),
            "national": national,
        }
    if not ready:
        # An ERRORED source, not an empty one. A source that emitted nothing
        # now degrades its own entry and its school still publishes (that is
        # the department-level isolation), so a zero no longer produces a
        # blocked verdict and could not exercise this rejection path. An
        # error still blocks: the run cannot vouch for what it collected.
        first = next(iter(policies))
        sources[first] = {"status": "error", "error": "simulated failure"}
    payload["release"] = evaluate_refresh_summary(
        payload,
        schools=schools,
        national=national,
        deep=deep,
        require_tracking=False,
    )
    _write_json(path, payload)


def _setup(
    tmp_path: Path,
    *,
    shard: str = "uw",
    deep: bool = True,
    source_markers: dict[str, str] | None = None,
    base_markers: dict[str, str] | None = None,
) -> dict:
    targets = shard.split(",") if shard not in {"", "national"} else [
        "national" if shard == "national" else "uw"
    ]
    source_markers = source_markers or {
        slug: "fresh"
        for slug in targets
    }
    base_markers = base_markers or {
        slug: "old"
        for slug in targets
    }
    base_payloads = {
        slug: _records(None if slug == "national" else slug, marker)
        for slug, marker in base_markers.items()
    }
    repository, base_sha = _init_base_repository(
        tmp_path,
        base_payloads,
    )
    source = repository / "data/processed/shards"
    for slug, marker in source_markers.items():
        _write_json(
            source / f"{slug}.json",
            _records(None if slug == "national" else slug, marker),
        )
    status = repository / STATUS_RELATIVE
    _ready_status(
        status,
        base_sha=base_sha,
        shard=shard,
        deep=deep,
    )
    return {
        "repository": repository,
        "base_sha": base_sha,
        "source": source,
        "status": status,
        "artifact": tmp_path / "artifact",
        "shard": shard,
        "deep": deep,
    }


def _build(context: dict, **overrides) -> dict:
    arguments = {
        "shard": context["shard"],
        "base_sha": context["base_sha"],
        "repository_root": context["repository"],
        "source_shards": context["source"],
        "collector_status": context["status"],
        "output": context["artifact"],
        "expected_deep": context["deep"],
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
    }
    arguments.update(overrides)
    return build_artifact(**arguments)


def _clone_base_repository(
    context: dict,
    destination: Path,
) -> None:
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-hardlinks",
            str(context["repository"]),
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _run_git(destination, "rev-parse", "HEAD") == context["base_sha"]


def _apply(context: dict, latest: Path, **overrides) -> dict:
    arguments = {
        "repository_root": latest,
        "expected_shard": context["shard"],
        "expected_base_sha": context["base_sha"],
        "expected_deep": context["deep"],
        "expected_run_id": RUN_ID,
        "expected_run_attempt": RUN_ATTEMPT,
    }
    arguments.update(overrides)
    return apply_artifact(context["artifact"], **arguments)


def test_target_artifact_contains_and_applies_only_authorized_shards(tmp_path):
    context = _setup(
        tmp_path,
        source_markers={"uw": "fresh", "wisc": "run-start-stale"},
        base_markers={"uw": "old", "wisc": "base-wisc"},
    )
    manifest = _build(context)

    assert manifest["targets"] == ["uw"]
    assert manifest["deep"] is True
    assert not (
        context["artifact"] / "data/processed/shards/wisc.json"
    ).exists()

    latest = tmp_path / "latest-main"
    _clone_base_repository(context, latest)
    latest_wisc = latest / "data/processed/shards/wisc.json"
    _write_json(latest_wisc, _records("wisc", "new-main"))
    before_wisc = latest_wisc.read_bytes()

    _apply(context, latest)

    saved = json.loads(
        (latest / "data/processed/shards/uw.json").read_text(encoding="utf-8")
    )
    assert saved[0]["title"] == "fresh"
    assert latest_wisc.read_bytes() == before_wisc


def test_apply_succeeds_on_descendant_main_with_unrelated_commit(tmp_path):
    context = _setup(
        tmp_path,
        source_markers={"uw": "fresh"},
        base_markers={"uw": "old", "wisc": "base-wisc"},
    )
    _build(context)

    latest = tmp_path / "latest-main"
    _clone_base_repository(context, latest)
    latest_wisc = latest / "data/processed/shards/wisc.json"
    _write_json(latest_wisc, _records("wisc", "new-main"))
    _run_git(latest, "config", "user.name", "Latest Main Test")
    _run_git(latest, "config", "user.email", "latest@example.invalid")
    _run_git(latest, "add", "data/processed/shards/wisc.json")
    _run_git(latest, "commit", "-qm", "unrelated main data change")
    assert _run_git(latest, "rev-parse", "HEAD") != context["base_sha"]
    before_wisc = latest_wisc.read_bytes()

    _apply(context, latest)

    assert latest_wisc.read_bytes() == before_wisc
    saved = json.loads(
        (latest / "data/processed/shards/uw.json").read_text(encoding="utf-8")
    )
    assert saved[0]["title"] == "fresh"


def test_digest_tamper_and_unexpected_files_fail_closed(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    _write_json(
        context["artifact"] / "data/processed/shards/uw.json",
        _records("uw", "tampered"),
    )
    with pytest.raises(ValueError, match="mismatch"):
        validate_artifact(context["artifact"])

    clean = _setup(tmp_path / "second")
    _build(clean)
    (clean["artifact"] / "extra.txt").write_text(
        "unexpected",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unexpected"):
        validate_artifact(clean["artifact"])


def test_non_ready_status_and_untrusted_base_are_rejected(tmp_path):
    context = _setup(tmp_path)
    _ready_status(
        context["status"],
        base_sha=context["base_sha"],
        ready=False,
    )
    with pytest.raises(ValueError, match="release contract is blocked"):
        _build(context)

    _ready_status(context["status"], base_sha=context["base_sha"])
    with pytest.raises(ValueError, match="base SHA"):
        _build(
            context,
            base_sha="a" * 40,
            output=tmp_path / "bad-base",
        )


def test_ucd_quick_artifact_is_rejected_even_when_graph_is_green(tmp_path):
    context = _setup(tmp_path, shard="ucd", deep=False)
    with pytest.raises(
        ValueError,
        match="release contract is blocked",
    ):
        _build(context)
    assert not context["artifact"].exists()


def test_full_refresh_artifact_is_explicitly_disallowed(tmp_path):
    context = _setup(tmp_path)
    with pytest.raises(ValueError, match="explicit school shard"):
        _build(context, shard="")
    assert not context["artifact"].exists()


def test_artifact_rejects_symlinks(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    (context["artifact"] / "link").symlink_to(
        context["artifact"] / "refresh_manifest.json"
    )
    with pytest.raises(ValueError, match="symbolic"):
        validate_artifact(context["artifact"])


def test_cross_school_empty_and_ambiguous_national_records_are_rejected(
    tmp_path,
):
    context = _setup(tmp_path)
    _write_json(context["source"] / "uw.json", _records("wisc", "wrong"))
    with pytest.raises(ValueError, match="another school"):
        _build(context)
    assert not context["artifact"].exists()

    _write_json(context["source"] / "uw.json", [])
    with pytest.raises(ValueError, match="must not be empty"):
        _build(context)
    assert not context["artifact"].exists()

    national = _setup(tmp_path / "national", shard="national")
    rows = _records(None, "fresh")
    rows[0]["school"] = "   "
    _write_json(national["source"] / "national.json", rows)
    with pytest.raises(ValueError, match="canonical school slug"):
        _build(national)

    rows = _records(None, "fresh")
    rows[0].pop("school")
    _write_json(national["source"] / "national.json", rows)
    with pytest.raises(ValueError, match="school field is required"):
        _build(national)

    rows[0]["school"] = "national"
    _write_json(national["source"] / "national.json", rows)
    with pytest.raises(ValueError, match="reserved shard name"):
        _build(national)


def test_status_request_mode_run_and_base_provenance_are_trusted_inputs(
    tmp_path,
):
    context = _setup(tmp_path)
    payload = json.loads(context["status"].read_text(encoding="utf-8"))
    payload["request"]["schools"] = ["wisc"]
    _write_json(context["status"], payload)
    with pytest.raises(ValueError, match="request does not match"):
        _build(context)

    _ready_status(
        context["status"],
        base_sha=context["base_sha"],
        deep=False,
    )
    with pytest.raises(ValueError, match="deep mode"):
        _build(context)

    _ready_status(
        context["status"],
        base_sha=context["base_sha"],
        run_id="999",
    )
    with pytest.raises(ValueError, match="provenance"):
        _build(context)


@pytest.mark.parametrize("changed", ["shard", "status"])
def test_destination_preimage_change_blocks_stale_replay(tmp_path, changed):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    if changed == "shard":
        _write_json(
            latest / "data/processed/shards/uw.json",
            _records("uw", "newer-main"),
        )
    else:
        _write_json(latest / STATUS_RELATIVE, {"newer_status": True})

    with pytest.raises(ValueError, match="changed after refresh start"):
        _apply(context, latest)


def test_apply_requires_real_git_worktree(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    plain_directory = tmp_path / "not-a-worktree"
    plain_directory.mkdir()

    with pytest.raises(ValueError, match="real Git worktree"):
        _apply(context, plain_directory)


def test_apply_requires_base_to_be_head_ancestor(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)

    with pytest.raises(ValueError, match="exact commit"):
        _apply(context, latest, expected_base_sha="a" * 40)

    _run_git(latest, "config", "user.name", "Artifact Test")
    _run_git(latest, "config", "user.email", "artifact@example.invalid")
    tree = _run_git(latest, "rev-parse", "HEAD^{tree}")
    unrelated = _run_git(latest, "commit-tree", tree, "-m", "unrelated")
    _run_git(latest, "checkout", "-q", "--detach", unrelated)

    with pytest.raises(ValueError, match="ancestor"):
        _apply(context, latest)


def test_manifest_preimages_must_match_base_git_commit(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    destination = latest / "data/processed/shards/uw.json"
    _write_json(destination, _records("uw", "newer-main"))

    manifest_path = context["artifact"] / "refresh_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["destination_preimages"][
        "data/processed/shards/uw.json"
    ] = refresh_artifact_module._file_entry(
        destination,
        expect_list=True,
        expected_shard="uw",
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="base Git commit"):
        _apply(context, latest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_shard", None, "expected shard"),
        ("expected_base_sha", None, "expected base SHA"),
        ("expected_deep", None, "expected deep mode"),
        ("expected_run_id", None, "expected run_id"),
        ("expected_run_attempt", None, "expected run_attempt"),
        ("expected_shard", "", "expected shard"),
        ("expected_base_sha", "abc", "expected base SHA"),
        ("expected_deep", 1, "expected deep mode"),
        ("expected_run_id", 123, "expected run_id"),
        ("expected_run_attempt", "0", "expected run_attempt"),
    ],
)
def test_apply_identity_is_strict_runtime_input(
    tmp_path,
    field,
    value,
    message,
):
    arguments = {
        "repository_root": tmp_path / "unused-repository",
        "expected_shard": "uw",
        "expected_base_sha": "a" * 40,
        "expected_deep": True,
        "expected_run_id": RUN_ID,
        "expected_run_attempt": RUN_ATTEMPT,
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=message):
        apply_artifact(tmp_path / "unused-artifact", **arguments)


def test_apply_rejects_wrong_run_identity_and_mode(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)

    with pytest.raises(ValueError, match="run_id"):
        _apply(context, latest, expected_run_id="999")
    with pytest.raises(ValueError, match="deep mode"):
        _apply(context, latest, expected_deep=False)


def test_multi_target_install_failure_rolls_back_every_destination(
    monkeypatch,
    tmp_path,
):
    context = _setup(tmp_path, shard="uw,wisc")
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    paths = (
        latest / "data/processed/shards/uw.json",
        latest / "data/processed/shards/wisc.json",
        latest / STATUS_RELATIVE,
    )
    before = {path: path.read_bytes() for path in paths}

    real_replace = refresh_artifact_module.os.replace
    calls = {"count": 0, "failed": False}

    def fail_second_install(source_path, destination_path):
        calls["count"] += 1
        if calls["count"] == 2 and not calls["failed"]:
            calls["failed"] = True
            raise OSError("injected second install failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(
        refresh_artifact_module.os,
        "replace",
        fail_second_install,
    )

    with pytest.raises(OSError, match="injected"):
        _apply(context, latest)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_keyboard_interrupt_rolls_back_every_destination(
    monkeypatch,
    tmp_path,
):
    context = _setup(tmp_path, shard="uw,wisc")
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    paths = (
        latest / "data/processed/shards/uw.json",
        latest / "data/processed/shards/wisc.json",
        latest / STATUS_RELATIVE,
    )
    before = {path: path.read_bytes() for path in paths}

    real_replace = refresh_artifact_module.os.replace
    calls = {"count": 0, "failed": False}

    def interrupt_second_install(source_path, destination_path):
        calls["count"] += 1
        if calls["count"] == 2 and not calls["failed"]:
            calls["failed"] = True
            raise KeyboardInterrupt
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(
        refresh_artifact_module.os,
        "replace",
        interrupt_second_install,
    )

    with pytest.raises(KeyboardInterrupt):
        _apply(context, latest)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_interrupt_after_replace_still_restores_every_destination(
    monkeypatch,
    tmp_path,
):
    context = _setup(tmp_path, shard="uw,wisc")
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    paths = (
        latest / "data/processed/shards/uw.json",
        latest / "data/processed/shards/wisc.json",
        latest / STATUS_RELATIVE,
    )
    before = {path: path.read_bytes() for path in paths}

    real_replace = refresh_artifact_module.os.replace
    calls = {"count": 0, "failed": False}

    def interrupt_after_second_install(source_path, destination_path):
        calls["count"] += 1
        result = real_replace(source_path, destination_path)
        if calls["count"] == 2 and not calls["failed"]:
            calls["failed"] = True
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(
        refresh_artifact_module.os,
        "replace",
        interrupt_after_second_install,
    )

    with pytest.raises(KeyboardInterrupt):
        _apply(context, latest)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_destination_change_during_staging_fails_final_cas(
    monkeypatch,
    tmp_path,
):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    shard_path = latest / "data/processed/shards/uw.json"
    status_path = latest / STATUS_RELATIVE
    shard_before = shard_path.read_bytes()

    real_stage_copy = refresh_artifact_module._stage_copy
    calls = {"count": 0}

    def mutate_destination_after_stage(source_path, destination_path):
        staged = real_stage_copy(source_path, destination_path)
        calls["count"] += 1
        if calls["count"] == 1:
            _write_json(status_path, {"concurrent_status": True})
        return staged

    monkeypatch.setattr(
        refresh_artifact_module,
        "_stage_copy",
        mutate_destination_after_stage,
    )

    with pytest.raises(ValueError, match="changed after refresh start"):
        _apply(context, latest)
    assert shard_path.read_bytes() == shard_before
    assert json.loads(status_path.read_text(encoding="utf-8")) == {
        "concurrent_status": True
    }


def test_artifact_source_swap_during_staging_is_not_installed(
    monkeypatch,
    tmp_path,
):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    shard_path = latest / "data/processed/shards/uw.json"
    status_path = latest / STATUS_RELATIVE
    before = {
        shard_path: shard_path.read_bytes(),
        status_path: status_path.read_bytes(),
    }

    real_stage_copy = refresh_artifact_module._stage_copy
    swapped = {"done": False}

    def swap_sources_before_copy(source_path, destination_path):
        if not swapped["done"]:
            swapped["done"] = True
            _write_json(
                context["artifact"] / "data/processed/shards/uw.json",
                _records("uw", "post-validation-swap"),
            )
            _write_json(
                context["artifact"] / STATUS_RELATIVE,
                {"unvalidated": True},
            )
        return real_stage_copy(source_path, destination_path)

    monkeypatch.setattr(
        refresh_artifact_module,
        "_stage_copy",
        swap_sources_before_copy,
    )

    with pytest.raises(ValueError, match="staged artifact digest/count mismatch"):
        _apply(context, latest)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_apply_rejects_symlink_destination(tmp_path):
    context = _setup(tmp_path)
    _build(context)
    latest = tmp_path / "latest"
    _clone_base_repository(context, latest)
    target = latest / "data/processed/shards/uw.json"
    target.unlink()
    outside = tmp_path / "outside.json"
    _write_json(outside, _records("uw", "old"))
    target.symlink_to(outside)

    with pytest.raises(ValueError, match="symbolic link"):
        _apply(context, latest)


def test_cli_build_validate_apply_round_trip(tmp_path):
    context = _setup(tmp_path)
    script = Path(refresh_artifact_module.__file__).resolve()
    build = subprocess.run(
        [
            sys.executable,
            str(script),
            "build",
            "--shard",
            context["shard"],
            "--base-sha",
            context["base_sha"],
            "--repository-root",
            str(context["repository"]),
            "--source-shards",
            str(context["source"]),
            "--collector-status",
            str(context["status"]),
            "--output",
            str(context["artifact"]),
            "--mode",
            "deep",
            "--run-id",
            RUN_ID,
            "--run-attempt",
            RUN_ATTEMPT,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr

    validate = subprocess.run(
        [
            sys.executable,
            str(script),
            "validate",
            "--artifact",
            str(context["artifact"]),
            "--expected-shard",
            context["shard"],
            "--expected-base-sha",
            context["base_sha"],
            "--expected-mode",
            "deep",
            "--expected-run-id",
            RUN_ID,
            "--expected-run-attempt",
            RUN_ATTEMPT,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert validate.returncode == 0, validate.stderr

    latest = tmp_path / "latest-cli"
    _clone_base_repository(context, latest)
    apply = subprocess.run(
        [
            sys.executable,
            str(script),
            "apply",
            "--artifact",
            str(context["artifact"]),
            "--repository-root",
            str(latest),
            "--expected-shard",
            context["shard"],
            "--expected-base-sha",
            context["base_sha"],
            "--expected-mode",
            "deep",
            "--expected-run-id",
            RUN_ID,
            "--expected-run-attempt",
            RUN_ATTEMPT,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert apply.returncode == 0, apply.stderr
    saved = json.loads(
        (latest / "data/processed/shards/uw.json").read_text(encoding="utf-8")
    )
    assert saved[0]["title"] == "fresh"
