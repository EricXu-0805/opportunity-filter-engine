"""What the refresh workflow checks before it spends a PR/CI cycle, and what it
accepts as "checks passed" before it merges.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import refresh_merge_gate as gate

_REPO = Path(__file__).resolve().parents[1]
_TOMBSTONE_INVARIANT = (
    "tests/test_contact_gating.py::TestTheCorpusStaysReachable::"
    "test_no_record_holds_an_address_and_a_tombstone"
)


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


def test_workflow_pins_the_generated_data_commit_and_base():
    script = _step("merge once required checks pass")["run"]
    assert 'PR=$(gh pr create --base main --head "$BRANCH"' in script
    assert 'python3 scripts/refresh_merge_gate.py "$PR" "$DATA_HEAD" "$(git rev-parse HEAD^)"' in script
    assert 'DATA_HEAD=$(git rev-parse HEAD)' in script
    assert 'git push --force-with-lease="$DATA_REF:$DATA_HEAD" "$REMOTE" ":$DATA_REF"' in script
    assert '[ "$RESULT" -eq 2 ] || exit "$RESULT"' in script
    assert 'gh pr close "$BRANCH"' not in script


def make_checks(*buckets):
    return [{"name": name, "bucket": bucket} for name, bucket in zip(sorted(gate.REQUIRED), buckets, strict=False)]


class GitHub:
    def __init__(self, monkeypatch, *, check_reads=None, merge_ok=True):
        self.state = {"state": "OPEN", "headRefOid": "original", "baseRefName": "main", "baseRefOid": "base",
                      "mergeStateStatus": "CLEAN", "mergeCommit": None}
        self.check_reads = check_reads or [make_checks("pass", "pass", "pass")]
        self.merge_ok = merge_ok
        self.elapsed = 0
        self.after_sleep = lambda: None
        self.at_merge = lambda: None
        self.after_checks = lambda: None
        self.merges = []
        self.comparisons = []
        self.compare_status = "ahead"
        self.sleeps = []
        self.transient = 0
        monkeypatch.setattr(gate, "gh", self.gh)

    def sleep(self, seconds):
        self.elapsed += seconds
        self.sleeps.append(seconds)
        self.after_sleep()

    def merged(self):
        self.state.update(state="MERGED", mergeCommit={"oid": "squash"})

    def gh(self, *args):
        code = 0
        if self.transient:
            self.transient -= 1
            raise subprocess.TimeoutExpired("gh", 45)
        if args[:2] == ("pr", "view"):
            assert args[2] == "1464"
            obj = dict(self.state)
        elif args[:2] == ("pr", "checks"):
            assert args[2:4] == ("1464", "--required")
            obj = self.check_reads.pop(0) if len(self.check_reads) > 1 else self.check_reads[0]
            self.after_checks()
        elif args[:2] == ("pr", "merge"):
            self.at_merge()
            assert args[2:] == ("1464", "--squash", "--match-head-commit", "original")
            self.merges.append((args[-1], self.state["headRefOid"]))
            code = int(not self.merge_ok or args[-1] != self.state["headRefOid"])
            if not code:
                self.merged()
            obj = None
        elif args[0] == "api":
            assert "/compare/squash...main?" in args[1]
            self.comparisons.append(args[1]); obj = {"status": self.compare_status}
        else:
            pytest.fail(f"Unexpected GitHub operation {args}")
        return subprocess.CompletedProcess(args, code, json.dumps(obj) if obj is not None else "", "")

    def watch(self):
        return gate.wait_for_merge("1464", "original", "base", clock=lambda: self.elapsed, sleep=self.sleep)


@pytest.mark.parametrize("missing", [0, 1, 2])
def test_initial_check_registration_requires_all_three_names(monkeypatch, missing):
    checks = [make_checks(*(["pass"] * missing)), make_checks("pass", "pass", "pass")]
    gh = GitHub(monkeypatch, check_reads=checks)
    assert gh.watch() == gate.MERGED
    assert gh.sleeps[0] == 15 and gh.merges == [("original", "original")]
    assert len(gh.comparisons) == 1


def test_missing_required_check_times_out_without_a_merge(monkeypatch):
    gh = GitHub(monkeypatch, check_reads=[make_checks("pass", "pass") + [{"name": "other", "bucket": "pass"}]])
    assert gh.watch() == gate.FAILED
    assert gh.elapsed == 600 and gh.merges == []


@pytest.mark.parametrize("bad", ["fail", "cancel", "skipping"])
def test_unsuccessful_required_check_stops_before_merge(monkeypatch, bad):
    gh = GitHub(monkeypatch, check_reads=[make_checks("pass", bad, "pass")])
    assert gh.watch() == gate.FAILED and gh.merges == []


def test_repaired_head_without_registered_checks_can_later_reach_main(monkeypatch):
    gh = GitHub(monkeypatch, check_reads=[make_checks("pending", "pending", "pending"), [], make_checks("pass", "pass", "pass")])
    def revise():
        gh.state["headRefOid"] = "repair"
        if gh.elapsed >= 75:
            gh.merged()
    gh.after_sleep = revise
    assert gh.watch() == gate.MERGED and gh.merges == [] and gh.comparisons


def test_changed_head_never_inherits_the_previous_check_results(monkeypatch):
    gh = GitHub(monkeypatch, check_reads=[make_checks("fail", "pass", "pass"), make_checks("pass", "pass", "pass")])
    gh.after_checks = lambda: gh.state.update(headRefOid="repair")
    gh.after_sleep = lambda: gh.merged() if gh.elapsed > 30 else None
    assert gh.watch() == gate.MERGED and gh.merges == []


def test_update_between_green_read_and_merge_is_protected_by_expected_head(monkeypatch):
    gh = GitHub(monkeypatch)
    gh.at_merge = lambda: gh.state.update(headRefOid="repair")
    gh.after_sleep = lambda: gh.merged() if gh.elapsed >= 40 else None
    assert gh.watch() == gate.MERGED and gh.merges == [("original", "repair")]


@pytest.mark.parametrize("closed,base", [("CLOSED", "main"), ("OPEN", "other")])
def test_closed_or_retargeted_repair_cannot_signal_publication(monkeypatch, closed, base):
    gh = GitHub(monkeypatch)
    gh.state.update(headRefOid="repair", state=closed, baseRefName=base)
    assert gh.watch() == gate.FAILED and gh.merges == []


def test_replay_keeps_old_pr_and_only_occurs_after_main_moves(monkeypatch):
    gh = GitHub(monkeypatch, merge_ok=False)
    gh.state.update(baseRefOid="new-main", mergeStateStatus="BEHIND")
    assert gh.watch() == gate.REPLAY and gh.merges == [("original", "original")] * 6
    gh = GitHub(monkeypatch, merge_ok=False)
    assert gh.watch() == gate.FAILED and gh.merges == [("original", "original")] * 6


def test_repaired_head_is_never_closed_or_replayed_after_merge_refusals(monkeypatch):
    gh = GitHub(monkeypatch, merge_ok=False)
    gh.state.update(baseRefOid="new-main", mergeStateStatus="BEHIND")
    def edit():
        if len(gh.merges) == 6:
            gh.state.update(headRefOid="repair", state="CLOSED")
    gh.after_sleep = edit
    assert gh.watch() == gate.FAILED and len(gh.merges) == 6


def test_real_merge_must_be_on_main_even_if_squashed_or_github_is_temporarily_unavailable(monkeypatch):
    gh = GitHub(monkeypatch); gh.merged(); gh.transient = 1
    assert gh.watch() == gate.MERGED and gh.comparisons and gh.merges == []
    gh = GitHub(monkeypatch); gh.merged(); gh.compare_status = "diverged"
    assert gh.watch() == gate.FAILED and gh.comparisons and gh.merges == []
