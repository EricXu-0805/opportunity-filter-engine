"""What the refresh workflow checks before it spends a PR/CI cycle, and what it
accepts as "checks passed" before it merges.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_TOMBSTONE_INVARIANT = (
    "tests/test_contact_gating.py::TestTheCorpusStaysReachable::"
    "test_no_record_holds_an_address_and_a_tombstone"
)
_WATCH = 'gh pr checks "$BRANCH" --required --watch'


def _step(name_fragment: str) -> dict:
    workflow = yaml.safe_load(
        (_REPO / ".github/workflows/refresh-data.yml").read_text()
    )
    job = next(iter(workflow["jobs"].values()))
    return next(
        step for step in job["steps"] if name_fragment in str(step.get("name", ""))
    )


def test_the_data_quality_gate_runs_the_tombstone_invariant():
    """The data PR's Backend check refused 09-21 and 09-28 refreshes for one
    record holding an address beside ``identity_bound: False``. The gate step
    runs on the refreshed work file before the PR is opened, so the same
    invariant there fails the run without a full CI cycle."""
    command = str(_step("Data-quality gate").get("run", ""))
    assert _TOMBSTONE_INVARIANT in command

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", _TOMBSTONE_INVARIANT],
        cwd=_REPO, capture_output=True, text=True,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr


def _after_watch() -> str:
    """The step's script from the --watch line up to the merge loop."""
    script = str(_step("merge once required checks pass").get("run", ""))
    tail = script.split(_WATCH, 1)[1]
    return textwrap.dedent(tail.split('MERGED=""', 1)[0])


def _run_after_watch(tmp_path: Path, checks_json: str) -> subprocess.CompletedProcess:
    # A stand-in gh that answers `pr checks --json ... --jq EXPR` from a fixed
    # payload through the real jq, as gh's built-in --jq would.
    fake_gh = tmp_path / "gh"
    (tmp_path / "checks.json").write_text(checks_json)
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "expr=''\n"
        'while [ $# -gt 0 ]; do [ "$1" = --jq ] && expr="$2"; shift; done\n'
        f'jq -r "$expr" "{tmp_path}/checks.json"\n'
    )
    fake_gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "BRANCH": "b"}
    return subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _after_watch()],
        env=env, capture_output=True, text=True,
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_a_cancelled_required_check_stops_the_merge(tmp_path):
    """gh 2.93 `pr checks --required --watch` exits 0 when a required check was
    cancelled (PR #996: Backend cancelled at 30m, E2E skipped behind it). The
    script then treated that as green, was refused six merges by branch policy,
    and replayed a full CI run for nothing."""
    result = _run_after_watch(
        tmp_path,
        '[{"bucket":"skipping","name":"E2E (Playwright)","state":"SKIPPED"},'
        '{"bucket":"cancel","name":"Backend (lint + pytest)","state":"CANCELLED"},'
        '{"bucket":"pass","name":"Frontend (typecheck + build)","state":"SUCCESS"}]',
    )
    assert result.returncode != 0
    assert "Backend (lint + pytest)" in result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_all_required_checks_passing_proceeds_to_the_merge(tmp_path):
    result = _run_after_watch(
        tmp_path,
        '[{"bucket":"pass","name":"E2E (Playwright)","state":"SUCCESS"},'
        '{"bucket":"pass","name":"Backend (lint + pytest)","state":"SUCCESS"},'
        '{"bucket":"pass","name":"Frontend (typecheck + build)","state":"SUCCESS"}]',
    )
    assert result.returncode == 0, result.stdout + result.stderr
