"""Static safety contract for the target-only refresh validation workflow."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "refresh-data.yml"
)


def _workflow() -> tuple[str, dict]:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.load(raw, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return raw, parsed


def _job(parsed: dict) -> dict:
    jobs = parsed["jobs"]
    assert list(jobs) == ["validate-refresh"]
    return jobs["validate-refresh"]


def _run_text(job: dict) -> str:
    return "\n".join(
        step.get("run", "")
        for step in job["steps"]
        if isinstance(step, dict)
    )


def _scalar_strings(value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            scalar
            for key, item in value.items()
            for scalar in [
                *_scalar_strings(key),
                *_scalar_strings(item),
            ]
        ]
    if isinstance(value, list):
        return [
            scalar
            for item in value
            for scalar in _scalar_strings(item)
        ]
    return [value] if isinstance(value, str) else []


def test_workflow_is_manual_read_only_validation_not_automatic_publication():
    raw, parsed = _workflow()
    triggers = parsed["on"]
    assert set(triggers) == {"workflow_dispatch"}
    schools = triggers["workflow_dispatch"]["inputs"]["schools"]
    assert schools["required"] == "true"
    assert "default" not in schools

    job = _job(parsed)
    assert job["permissions"] == {"contents": "read"}
    assert "continue-on-error" not in raw
    assert "schedule:" not in raw
    scalars = _scalar_strings(parsed)
    assert all("${{ secrets." not in value for value in scalars)
    assert all("${{ github.token }}" not in value for value in scalars)


def test_untrusted_manual_input_enters_shell_only_through_environment():
    raw, parsed = _workflow()
    job = _job(parsed)
    runs = [
        step.get("run", "")
        for step in job["steps"]
        if isinstance(step, dict)
    ]
    assert all("${{ inputs.schools }}" not in run for run in runs)

    shard_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Determine bounded refresh shard"
    )
    assert shard_step["env"]["REQUESTED_SCHOOLS"] == "${{ inputs.schools }}"
    assert "--publication-unit" in shard_step["run"]
    assert '--schools "$REQUESTED_SCHOOLS"' in shard_step["run"]
    assert "ARGS=(" in _run_text(job)
    assert "eval " not in raw


def test_external_actions_are_commit_pinned_and_checkout_is_full_history():
    _raw, parsed = _workflow()
    job = _job(parsed)
    action_steps = [step for step in job["steps"] if "uses" in step]
    assert len(action_steps) == 2
    assert all(
        re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"])
        for step in action_steps
    )
    checkout = action_steps[0]
    assert checkout["with"]["fetch-depth"] == "0"
    assert checkout["with"]["persist-credentials"] == "false"


def test_validation_is_main_only_and_dynamic_tools_are_version_pinned():
    _raw, parsed = _workflow()
    job = _job(parsed)
    identity = next(
        step
        for step in job["steps"]
        if step.get("name") == "Capture run-start identity"
    )
    assert identity["env"]["TRIGGER_REF"] == "${{ github.ref }}"
    assert '!= "refs/heads/main"' in identity["run"]
    assert "git merge-base --is-ancestor" in identity["run"]

    run = _run_text(job)
    assert "pip install playwright==1.60.0" in run
    assert "pip install playwright\n" not in run
    assert 'case "$REQUESTED_DEEP" in' in run
    assert 'elif [[ "$SHARD" != "national" ]]; then' in run
    assert "DAY_OF_MONTH=\"$((10#$(date -u +%d)))\"" in run


def test_workflow_builds_validates_and_replays_only_target_artifact():
    raw, parsed = _workflow()
    run = _run_text(_job(parsed))
    assert "--base-sha" in run
    assert "--run-id" in run
    assert "--run-attempt" in run
    assert 'split --only-shards "$TARGETS"' in run
    assert "refresh_artifact.py build" in run
    assert "refresh_artifact.py validate" in run
    assert "refresh_artifact.py\" apply" in run
    assert "git fetch origin main" in run
    assert 'git worktree add --detach "$LATEST_ROOT" FETCH_HEAD' in run
    assert "data/processed/collector_status.json" in run
    assert 'f"data/processed/shards/{slug}.json"' in run
    assert "artifact apply changed unauthorized path" in run
    assert "git add data/processed" not in run
    assert "scripts/shard_corpus.py split\n" not in run

    forbidden = (
        "refresh_pat",
        "github_refresh_pat",
        "gh_token",
        "resend",
        "git push",
        "gh pr",
        "--delete-branch",
        "professor_tracking",
        "collector_status_history",
        "/tmp/refresh-opportunities",
        "enrich_processed --save",
        "deactivate_past --save",
    )
    lowered = raw.lower()
    assert all(term not in lowered for term in forbidden)


def test_workflow_cannot_stage_or_publish_even_when_validation_succeeds():
    raw, parsed = _workflow()
    run = _run_text(_job(parsed))
    assert "git commit" not in run
    assert "git add " not in run
    assert "curl " not in run
    assert "upload-artifact" not in raw
    assert "No commit, push, pull request, merge, branch deletion, or email" in run
