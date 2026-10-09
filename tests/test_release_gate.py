"""The release gate must be impossible to talk into a GO it hasn't earned.

Every test here is really the same test from a different angle: absence of
evidence is never a pass. The gate's default is NO-GO, and each gate can only
flip to PASS by presenting evidence bound to the frozen release SHA.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_gate", _REPO / "scripts" / "release_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40

_FLAGS = {"match_ai_refine": False, "cross_school_matching": True}
_DATA_A = {"shard_commit": "d" * 40, "shards_tree": "1" * 40}
_DATA_B = {"shard_commit": "e" * 40, "shards_tree": "2" * 40}


def _find(ledger: dict, name: str) -> dict:
    return next(g for g in ledger["gates"] if g["gate"] == name)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _all_external_pass(sha: str) -> dict:
    """Evidence that satisfies every out-of-repo gate for the given sha.

    ``observed_at`` is not decoration: a live observation that cannot say when
    it was taken is undated evidence, and the gate refuses to read undated
    evidence as fresh.
    """
    ok = {"status": "PASS", "release_sha": sha, "detail": "verified",
          "observed_at": _now_iso()}
    names = (*gate._EXTERNAL_GATES, "api_ready", "promotion", "rollback", "scheduler")
    ev = {name: dict(ok) for name in names}
    ev["ci"] = {
        "head_sha": sha,
        "checks": [{"name": n, "conclusion": "SUCCESS"} for n in (
            "Backend (lint + pytest)", "Frontend (typecheck + build)",
            "Migrations (Flow B merge + CLI replay)", "E2E (Playwright)")],
    }
    ev["deployment"] = {"observed_at": _now_iso(), "backend_sha": sha,
                        "frontend_sha": sha}
    ev["open_incidents"] = {"observed_at": _now_iso(),
                            "rollup": {"open_total": 0, "truncated": False}}
    ev["provider_readiness"] = {
        "observed_at": _now_iso(),
        "providers": {name: {"status": "configured"}
                      for name in gate._PROVIDER_REQUIRED_BY},
    }
    return ev


def _passing_drill(migrations: dict | None = None) -> dict:
    """A drill record that satisfies every clause of check_restore_drill."""
    return {
        "drill_id": "drill-2026-09-04-a",
        "performed_at": _now_iso(),
        "source_backup_id": "backup-1",
        "source_environment": "prod",
        "scratch_environment": "scratch",
        "source_schema_version": migrations or gate.migration_set_identity(),
        "restored_schema_version": migrations or gate.migration_set_identity(),
        "schema_validation": "PASS",
        "data_validation": "PASS",
        "rls_validation": "PASS",
        "application_smoke": "PASS",
        "issues_found": [],
        "final_result": "PASS",
    }


def _stub_repo_gates(monkeypatch, sha: str, *, drill: dict | None = None) -> None:
    """Neutralise the gates that read the real repo, so a test can isolate one.

    Everything stubbed here has its own dedicated tests; leaving them live
    would make every ledger-level assertion depend on today's committed corpus.
    """
    import subprocess
    monkeypatch.setattr(gate, "check_release_sha",
                        lambda s: gate._gate("release_sha", gate.PASS, "stub"))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=("" if "status" in cmd else sha) + "\n", stderr=""))
    monkeypatch.setattr(gate, "check_tracking_release_ready",
                        lambda: gate._gate("tracking_release_ready", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_corpus_freshness",
                        lambda: gate._gate("corpus_freshness", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_tracking_freshness",
                        lambda: gate._gate("tracking_freshness", gate.PASS, "stub"))
    # Reads data/processed/source_health.json, whose contents change with every
    # refresh run; stubbed like its peers so this asserts the GO PATH, not
    # today's corpus freshness, which its own tests cover directly.
    monkeypatch.setattr(gate, "check_no_fully_stale_school",
                        lambda: gate._gate("no_fully_stale_school", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_truthfulness",
                        lambda: gate._gate("truthfulness", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_flag_parity",
                        lambda: gate._gate("flag_parity", gate.PASS, "stub"))
    # The release record reads two files and a data version at each deployed
    # commit; with subprocess stubbed above those reads would see the sha
    # string, so they are answered with one aligned commit's state instead.
    monkeypatch.setattr(gate, "commit_exists", lambda rev: True)
    monkeypatch.setattr(gate, "release_scope_at",
                        lambda rev: {"backend": dict(_FLAGS), "frontend": dict(_FLAGS)})
    monkeypatch.setattr(gate, "data_version_at", lambda rev: dict(_DATA_A))
    monkeypatch.setattr(gate, "check_ledger_currency",
                        lambda s, **kw: gate._gate("ledger_currency", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "load_latest_drill",
                        lambda: (drill if drill is not None else _passing_drill(), None))


# ---------------------------------------------------------------------------
# Default posture
# ---------------------------------------------------------------------------

class TestDefaultNoGo:
    def test_bare_invocation_is_no_go(self):
        ledger = gate.build_ledger(None, {}, min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        assert ledger["blocking_reasons"]

    def test_every_external_gate_starts_blocking_not_passing(self):
        """Absent evidence never reads as PASS, whichever blocking flavour it is."""
        ledger = gate.build_ledger(SHA_A, {}, min_records=1)
        for name in gate._EXTERNAL_GATES:
            got = _find(ledger, name)
            assert got["status"] in gate._BLOCKING, (name, got["status"])
            assert got["status"] != gate.PASS, name

    def test_access_gated_evidence_is_blocked_not_merely_unverified(self):
        """"Go and look" and "somebody must grant access" are different asks."""
        ledger = gate.build_ledger(SHA_A, {}, min_records=1)
        assert _find(ledger, "backup")["status"] == gate.BLOCKED
        assert _find(ledger, "restore")["status"] == gate.BLOCKED
        assert _find(ledger, "render_canary")["status"] == gate.UNVERIFIED

    def test_unverified_is_distinct_from_failed(self):
        # Conflating them would hide which gates need infrastructure access
        # versus which are actually broken.
        ledger = gate.build_ledger(SHA_A, {}, min_records=1)
        assert ledger["summary"]["unverified"] > 0
        assert gate.UNVERIFIED in gate._BLOCKING


# ---------------------------------------------------------------------------
# SHA freeze
# ---------------------------------------------------------------------------

class TestReleaseSha:
    def test_missing_sha_blocks(self):
        assert gate.check_release_sha(None)["status"] == gate.FAIL

    def test_short_sha_is_refused_as_ambiguous(self):
        assert gate.check_release_sha("a1b2c3d")["status"] == gate.FAIL

    def test_tag_like_input_is_refused(self):
        assert gate.check_release_sha("v2.7.0")["status"] == gate.FAIL

    def test_unknown_sha_is_refused(self):
        assert gate.check_release_sha(SHA_A)["status"] == gate.FAIL

    def test_real_head_sha_passes(self, tmp_path):
        import subprocess
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO,
                              capture_output=True, text=True, check=True).stdout.strip()
        assert gate.check_release_sha(head)["status"] == gate.PASS


class TestProvenanceBinding:
    def test_ci_evidence_for_a_different_sha_blocks(self):
        ev = _all_external_pass(SHA_B)
        results = gate.check_ci_evidence(ev["ci"], SHA_A)
        assert all(r["status"] == gate.FAIL for r in results)
        assert "release is" in results[0]["detail"]

    def test_external_evidence_for_a_different_sha_blocks(self):
        got = gate.check_external("render_canary",
                                  {"status": "PASS", "release_sha": SHA_B}, SHA_A)
        assert got["status"] == gate.FAIL

    def test_external_evidence_without_a_sha_cannot_bind(self):
        got = gate.check_external("render_canary", {"status": "PASS"}, SHA_A)
        assert got["status"] == gate.UNVERIFIED

    def test_dirty_worktree_blocks_local_evidence(self, monkeypatch):
        # Evidence gathered from a dirty tree does not describe the release.
        import subprocess

        def fake_run(cmd, **kw):
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=" M x.py\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout=SHA_A + "\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert gate.check_worktree_clean(SHA_A)["status"] == gate.FAIL


# ---------------------------------------------------------------------------
# CI gate: skipped is not green
# ---------------------------------------------------------------------------

class TestCiGate:
    def _ev(self, **overrides):
        checks = [{"name": n, "conclusion": "SUCCESS"} for n in (
            "Backend (lint + pytest)", "Frontend (typecheck + build)",
            "Migrations (Flow B merge + CLI replay)", "E2E (Playwright)")]
        for name, conclusion in overrides.items():
            for c in checks:
                if c["name"].startswith(name):
                    c["conclusion"] = conclusion
        return {"head_sha": SHA_A, "checks": checks}

    def test_all_green_passes(self):
        results = gate.check_ci_evidence(self._ev(), SHA_A)
        assert all(r["status"] == gate.PASS for r in results)

    def test_skipped_required_check_blocks(self):
        results = gate.check_ci_evidence(self._ev(Migrations="SKIPPED"), SHA_A)
        skipped = [r for r in results if r["status"] == gate.SKIPPED]
        assert len(skipped) == 1
        assert "not a pass" in skipped[0]["detail"]

    def test_failed_check_blocks(self):
        results = gate.check_ci_evidence(self._ev(Backend="FAILURE"), SHA_A)
        assert any(r["status"] == gate.FAIL for r in results)

    def test_unregistered_check_is_not_run_not_pass(self):
        ev = self._ev()
        ev["checks"] = [c for c in ev["checks"] if not c["name"].startswith("Migrations")]
        results = gate.check_ci_evidence(ev, SHA_A)
        missing = [r for r in results if r["status"] == gate.NOT_RUN]
        assert len(missing) == 1

    def test_no_evidence_means_unverified_for_every_required_check(self):
        results = gate.check_ci_evidence(None, SHA_A)
        assert len(results) == 4
        assert all(r["status"] == gate.UNVERIFIED for r in results)


# ---------------------------------------------------------------------------
# Corpus floor: present-but-empty is not ready
# ---------------------------------------------------------------------------

class TestCorpusFloor:
    def test_real_corpus_passes_the_floor(self):
        assert gate.check_corpus_floor(1000)["status"] == gate.PASS

    def test_floor_above_reality_blocks(self):
        # Proves the floor is actually evaluated, not decorative.
        got = gate.check_corpus_floor(10_000_000)
        assert got["status"] == gate.FAIL
        assert "vacuously" in got["detail"]


# ---------------------------------------------------------------------------
# Artifact gates
# ---------------------------------------------------------------------------

class TestArtifactGates:
    def test_truthfulness_stale_go_is_refused(self, monkeypatch, tmp_path):
        old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        payload = {"decision": "GO", "truthfulness_approved": True, "generated_at": old}
        path = tmp_path / "data" / "audits"
        path.mkdir(parents=True)
        (path / "truthfulness_report.json").write_text(json.dumps(payload))
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        got = gate.check_truthfulness()
        assert got["status"] == gate.FAIL
        assert "predating the corpus" in got["detail"]

    def test_truthfulness_no_go_blocks(self, monkeypatch, tmp_path):
        payload = {"decision": "NO-GO", "generated_at": datetime.now(UTC).isoformat()}
        path = tmp_path / "data" / "audits"
        path.mkdir(parents=True)
        (path / "truthfulness_report.json").write_text(json.dumps(payload))
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        assert gate.check_truthfulness()["status"] == gate.FAIL

    def test_truthfulness_fresh_go_passes(self, monkeypatch, tmp_path):
        payload = {"decision": "GO", "generated_at": datetime.now(UTC).isoformat()}
        path = tmp_path / "data" / "audits"
        path.mkdir(parents=True)
        (path / "truthfulness_report.json").write_text(json.dumps(payload))
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        assert gate.check_truthfulness()["status"] == gate.PASS

    def test_missing_report_is_unverified(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        assert gate.check_truthfulness()["status"] == gate.UNVERIFIED

    def _write_tracking(self, tmp_path, monkeypatch, release: dict) -> None:
        path = tmp_path / "data" / "processed"
        path.mkdir(parents=True)
        (path / "professor_tracking.json").write_text(json.dumps({
            "schema_version": 2, "profiles": {}, "events": [], "release": release,
        }))
        monkeypatch.setattr(gate, "_REPO", tmp_path)

    def test_tracking_strict_contract_is_reported_not_the_raw_boolean(
        self, monkeypatch, tmp_path,
    ):
        """A stored ``release_ready: true`` must not become the verdict.

        Written against a synthetic artifact rather than the committed one on
        purpose. The original version of this test asserted
        ``stored_release_ready is True`` against whatever
        data/processed/professor_tracking.json happened to contain — which was
        an accident of that artifact predating four of the nine checks. The
        moment a refresh regenerated it under the current contract the stored
        boolean flipped to false, `assert False is True` failed, and every
        subsequent data-refresh PR went red (08-10, and #735). The gate was
        behaving correctly the entire time; the test was pinning a data state.
        """
        self._write_tracking(tmp_path, monkeypatch, {
            "release_ready": True,
            # The pre-coverage check set: a naive gate that trusted the stored
            # boolean would call this ready.
            "checks": {
                "schema_v2": True, "events_valid": True,
                "freshness_min_pct": True, "no_fully_stale_school": True,
                "refresh_ok": True,
            },
        })
        got = gate.check_tracking_release_ready()
        assert got["status"] == gate.FAIL
        assert got["evidence"]["stored_release_ready"] is True

    def test_tracking_gate_does_not_require_a_true_stored_boolean_to_report(
        self, monkeypatch, tmp_path,
    ):
        """The other direction: an honestly-false artifact still reports FAIL.

        This is the state a real refresh produces today (tracking covers 54 of
        117 schools), so the gate has to survive it rather than crash or pass.
        """
        self._write_tracking(tmp_path, monkeypatch, {
            "release_ready": False,
            "checks": {
                "schema_v2": True, "events_valid": True,
                "freshness_min_pct": True, "no_fully_stale_school": True,
                "all_active_schools_tracked": False,
                "active_professor_denominator_present": True,
                "active_professor_coverage_min_pct": False,
                "all_active_professors_identifiable": True,
                "refresh_ok": True,
            },
        })
        got = gate.check_tracking_release_ready()
        assert got["status"] == gate.FAIL
        assert got["evidence"]["stored_release_ready"] is False
        assert set(got["evidence"]["failing"]) == {
            "all_active_schools_tracked", "active_professor_coverage_min_pct",
        }

    def test_tracking_gate_evaluates_the_committed_artifact_without_error(self):
        """Smoke: whatever is committed, the gate returns a verdict."""
        assert gate.check_tracking_release_ready()["status"] in (
            gate.PASS, gate.FAIL, gate.UNVERIFIED,
        )


class TestIncidentGate:
    def test_open_incidents_block(self):
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(),
             "rollup": {"open_total": 3, "truncated": False}})
        assert got["status"] == gate.FAIL

    def test_truncated_rollup_cannot_prove_zero(self):
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(),
             "rollup": {"open_total": 0, "truncated": True}})
        assert got["status"] == gate.UNVERIFIED

    def test_zero_open_passes(self):
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(),
             "rollup": {"open_total": 0, "truncated": False}})
        assert got["status"] == gate.PASS

    def test_absent_rollup_is_blocked_on_admin_access(self):
        got = gate.check_open_incidents(None)
        assert got["status"] == gate.BLOCKED
        assert got["reason"] == "access_required"

    def test_open_snapshot_reminders_do_not_block(self):
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(),
             "rollup": {"open_total": 2, "release_blocking_total": 0, "truncated": False}})
        assert got["status"] == gate.PASS
        assert "2 snapshot reminder(s) open" in got["detail"]

    def test_only_the_release_blocking_count_fails_the_gate(self):
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(),
             "rollup": {"open_total": 3, "release_blocking_total": 1, "truncated": False}})
        assert got["status"] == gate.FAIL
        assert got["detail"].startswith("1 unresolved incident(s)")

    def test_a_rollup_that_does_not_say_what_blocks_counts_every_open_row(self):
        """An older backend's rollup has no release_blocking_total."""
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(), "rollup": {"open_total": 1, "truncated": False}})
        assert got["status"] == gate.FAIL

    def test_an_impossible_release_blocking_count_is_not_believed(self):
        for bogus in (-1, 2, "0", None, True, 0.0):
            got = gate.check_open_incidents(
                {"observed_at": _now_iso(),
                 "rollup": {"open_total": 1, "release_blocking_total": bogus, "truncated": False}})
            assert got["status"] == gate.FAIL, bogus

    def test_a_truncated_rollup_cannot_prove_zero_even_with_reminders_set_apart(self):
        got = gate.check_open_incidents(
            {"observed_at": _now_iso(),
             "rollup": {"open_total": 1, "release_blocking_total": 0, "truncated": True}})
        assert got["status"] == gate.UNVERIFIED


_BE_SCOPE = '''
from types import MappingProxyType
RELEASE_SCOPE = MappingProxyType(
    {
        # Closed until its acceptance PR: "comment": True,
        "match_ai_refine": False,
        "cross_school_matching": True,
    }
)
_PROVIDER_FEATURES = {"azure": "microsoft_school_auth"}
'''

_FE_SCOPE = '''
export const RELEASE_SCOPE = Object.freeze({
  // Closed until its acceptance PR. notAFlag: true,
  matchAiRefine: false,
  /* block comment: alsoNotAFlag: false */
  crossSchoolMatching: true,
} as const);

export function normalize(profile) {
  return { ...profile, includeCrossSchool: false };
}
'''


def _write_scope(tmp_path, monkeypatch, *, be: str = _BE_SCOPE,
                 fe: str = _FE_SCOPE) -> None:
    (tmp_path / "backend" / "lib").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "lib").mkdir(parents=True)
    (tmp_path / "backend" / "lib" / "release_scope.py").write_text(be)
    (tmp_path / "frontend" / "src" / "lib" / "release-scope.ts").write_text(fe)
    monkeypatch.setattr(gate, "_REPO", tmp_path)


class TestFlagParity:
    """Names AND values. M65 names comparing only flag names as the shortcut
    a release check may not take: a flag open on one side and closed on the
    other is a control with no server-side door, or a door with no control."""

    def test_the_committed_tables_agree(self):
        got = gate.check_flag_parity()
        assert got["status"] == gate.PASS, got["detail"]
        assert got["evidence"]["backend"] == got["evidence"]["frontend"]

    def test_aligned_tables_pass(self, tmp_path, monkeypatch):
        _write_scope(tmp_path, monkeypatch)
        got = gate.check_flag_parity()
        assert got["status"] == gate.PASS, got["detail"]
        assert got["evidence"]["backend"] == _FLAGS

    def test_a_flag_open_on_one_side_only_fails(self, tmp_path, monkeypatch):
        _write_scope(tmp_path, monkeypatch,
                     fe=_FE_SCOPE.replace("matchAiRefine: false", "matchAiRefine: true"))
        got = gate.check_flag_parity()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "flag_drift"
        assert got["evidence"]["value_mismatch"] == {
            "match_ai_refine": {"backend": False, "frontend": True}}
        assert "match_ai_refine" in got["detail"]

    def test_a_flag_declared_on_one_side_only_fails(self, tmp_path, monkeypatch):
        _write_scope(tmp_path, monkeypatch,
                     be=_BE_SCOPE.replace('"cross_school_matching": True,',
                                          '"cross_school_matching": True,\n'
                                          '        "payments": False,'))
        got = gate.check_flag_parity()
        assert got["status"] == gate.FAIL
        assert got["evidence"]["backend_only"] == ["payments"]

    def test_text_outside_the_tables_is_not_read_as_a_flag(self, tmp_path, monkeypatch):
        _write_scope(tmp_path, monkeypatch)
        tables = gate.release_scope_at(None)
        assert tables == {"backend": _FLAGS, "frontend": _FLAGS}

    def test_a_value_that_is_not_a_literal_cannot_be_verified(self, tmp_path, monkeypatch):
        # A computed flag could be either value at runtime; reading it as
        # absent would let a real drift through as "aligned".
        _write_scope(tmp_path, monkeypatch,
                     fe=_FE_SCOPE.replace("crossSchoolMatching: true",
                                          "crossSchoolMatching: ENABLE_CROSS"))
        got = gate.check_flag_parity()
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "evidence_unreadable"

    def test_a_backend_value_that_is_not_a_boolean_cannot_be_verified(
            self, tmp_path, monkeypatch):
        # 1 == True in Python, so an int would compare "equal" to the frontend's
        # true while feature_enabled reads it with its own truthiness.
        _write_scope(tmp_path, monkeypatch,
                     be=_BE_SCOPE.replace('"cross_school_matching": True',
                                          '"cross_school_matching": 1'))
        assert gate.check_flag_parity()["status"] == gate.UNVERIFIED

    def test_a_missing_table_cannot_be_verified(self, tmp_path, monkeypatch):
        _write_scope(tmp_path, monkeypatch)
        (tmp_path / "frontend" / "src" / "lib" / "release-scope.ts").unlink()
        assert gate.check_flag_parity()["status"] == gate.UNVERIFIED


# ---------------------------------------------------------------------------
# One release record: the backend that answers, the frontend that renders, the
# corpus each was built with, and the flags each enforces, against the
# candidate (M65). Before this, nothing compared the deployed frontend's SHA
# with anything (O7: production backend 83940c19 on 10-02, frontend unread).
# ---------------------------------------------------------------------------

def _deployment(backend: str | None = SHA_A, frontend: str | None = SHA_A,
                **extra) -> dict:
    return {"observed_at": _now_iso(), "backend_sha": backend,
            "frontend_sha": frontend, **extra}


def _repo_state(monkeypatch, *, data: dict | None = None,
                scopes: dict | None = None, known: set | None = None) -> None:
    """Per-commit answers for the readers the release record uses."""
    data = data or {}
    scopes = scopes or {}
    monkeypatch.setattr(gate, "commit_exists",
                        lambda rev: rev in (known or {SHA_A, SHA_B, SHA_C}))
    monkeypatch.setattr(gate, "data_version_at",
                        lambda rev: dict(data.get(rev, _DATA_A)))
    monkeypatch.setattr(
        gate, "release_scope_at",
        lambda rev: scopes.get(rev, {"backend": dict(_FLAGS), "frontend": dict(_FLAGS)}))


class TestReleaseRecord:
    def test_no_observation_is_unverified_not_pass(self, monkeypatch):
        _repo_state(monkeypatch)
        got = gate.check_release_record(SHA_A, None)
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "evidence_absent"

    def test_everything_at_the_candidate_passes(self, monkeypatch):
        _repo_state(monkeypatch)
        got = gate.check_release_record(SHA_A, _deployment())
        assert got["status"] == gate.PASS, got["detail"]
        record = got["evidence"]
        assert record["backend"]["deployed_sha"] == SHA_A
        assert record["frontend"]["deployed_sha"] == SHA_A
        assert record["candidate"]["data_version"] == _DATA_A
        assert record["candidate"]["release_scope"] == {"backend": _FLAGS,
                                                        "frontend": _FLAGS}
        assert record["disagreements"] == []

    def test_a_backend_on_another_commit_fails(self, monkeypatch):
        _repo_state(monkeypatch)
        got = gate.check_release_record(SHA_A, _deployment(backend=SHA_B))
        assert got["status"] == gate.FAIL
        assert got["reason"] == "sha_mismatch"
        assert any("backend" in d and SHA_B[:8] in d
                   for d in got["evidence"]["disagreements"])

    def test_a_frontend_on_another_commit_fails(self, monkeypatch):
        # Vercel deploys without waiting for checks while Render waits for
        # every one (docs/RELEASE.md §3): this is the drift that happens.
        _repo_state(monkeypatch)
        got = gate.check_release_record(SHA_A, _deployment(frontend=SHA_B))
        assert got["status"] == gate.FAIL
        assert any("frontend" in d for d in got["evidence"]["disagreements"])

    def test_the_data_each_side_was_built_with_is_compared(self, monkeypatch):
        _repo_state(monkeypatch, data={SHA_B: _DATA_B})
        got = gate.check_release_record(SHA_A, _deployment(backend=SHA_B))
        assert got["status"] == gate.FAIL
        data_lines = [d for d in got["evidence"]["disagreements"] if "data" in d]
        assert data_lines and _DATA_B["shard_commit"][:8] in data_lines[0]
        assert got["evidence"]["backend"]["data_version"] == _DATA_B

    def test_same_data_is_not_reported_as_a_data_disagreement(self, monkeypatch):
        # A code-only commit between the two leaves the corpus identical; the
        # record should say the code differs, not invent a data drift.
        _repo_state(monkeypatch)
        got = gate.check_release_record(SHA_A, _deployment(frontend=SHA_B))
        assert not [d for d in got["evidence"]["disagreements"] if "data" in d]

    def test_deployed_flag_tables_that_disagree_fail(self, monkeypatch):
        opened = dict(_FLAGS, match_ai_refine=True)
        _repo_state(monkeypatch, scopes={
            SHA_B: {"backend": dict(_FLAGS), "frontend": opened}})
        got = gate.check_release_record(SHA_A, _deployment(frontend=SHA_B))
        flag_lines = [d for d in got["evidence"]["disagreements"] if "flag" in d]
        assert flag_lines and "match_ai_refine" in flag_lines[0]
        assert got["evidence"]["frontend"]["release_scope"] == opened

    def test_flags_are_compared_even_when_both_shas_match(self, monkeypatch):
        # The candidate's own two tables disagreeing is a release-record
        # failure too, not only a flag_parity one: the record is the one
        # place that says what the deployed pair enforces.
        _repo_state(monkeypatch, scopes={
            SHA_A: {"backend": dict(_FLAGS),
                    "frontend": dict(_FLAGS, cross_school_matching=False)}})
        got = gate.check_release_record(SHA_A, _deployment())
        assert got["status"] == gate.FAIL
        assert got["reason"] == "flag_drift"

    def test_a_deploy_that_does_not_name_its_commit_is_unverified(self, monkeypatch):
        # /api/health reports null when RENDER_GIT_COMMIT is unset, and the
        # page says data-release-sha="unknown": no identity, so no record.
        _repo_state(monkeypatch)
        for backend, frontend in ((None, SHA_A), (SHA_A, "unknown"), (SHA_A[:7], SHA_A)):
            got = gate.check_release_record(SHA_A, _deployment(backend, frontend))
            assert got["status"] == gate.UNVERIFIED, (backend, frontend)
            assert got["reason"] == "evidence_incomplete"

    def test_a_deployed_commit_this_repo_does_not_have_fails(self, monkeypatch):
        _repo_state(monkeypatch, known={SHA_A})
        got = gate.check_release_record(SHA_A, _deployment(backend=SHA_C))
        assert got["status"] == gate.FAIL
        assert got["evidence"]["backend"]["data_version"] is None
        assert any("not in this repository" in d
                   for d in got["evidence"]["disagreements"])

    def test_an_old_observation_is_stale(self, monkeypatch):
        _repo_state(monkeypatch)
        old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        got = gate.check_release_record(SHA_A, _deployment(observed_at=old))
        assert got["status"] == gate.FAIL
        assert got["reason"] == "evidence_stale"

    def test_the_ledger_carries_the_record_and_it_blocks(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        evidence = _all_external_pass(SHA_A)
        evidence["deployment"] = _deployment(frontend=SHA_B)
        ledger = gate.build_ledger(SHA_A, evidence, min_records=1)
        assert ledger["release_record"]["frontend"]["deployed_sha"] == SHA_B
        assert ledger["final_decision"] == "NO-GO"
        assert [b["check"] for b in ledger["blockers"]] == ["release_record"]


class TestObserveDeployment:
    _HTML = ('<!DOCTYPE html><html data-dpl-id="dpl_x" lang="en" '
             f'data-release-sha="{SHA_B}"><head></head></html>')

    def test_reads_health_and_the_page_attribute(self):
        pages = {"https://api.example/api/health": json.dumps({"release_sha": SHA_A}),
                 "https://app.example/": self._HTML}
        got = gate.observe_deployment("https://api.example/", "https://app.example",
                                      fetch=pages.__getitem__)
        assert got["backend_sha"] == SHA_A
        assert got["frontend_sha"] == SHA_B
        assert gate._parse_stamp(got["observed_at"]) is not None

    def test_a_failed_read_is_recorded_not_raised(self):
        def fetch(url):
            raise TimeoutError("timed out")
        got = gate.observe_deployment("https://api.example", "https://app.example",
                                      fetch=fetch)
        assert got["backend_sha"] is None and got["frontend_sha"] is None
        assert got["backend_error"] == "TimeoutError"
        # The error names the failure, never the URL: the ledger is uploaded
        # from a public repository and BACKEND_URL is a workflow secret.
        assert "api.example" not in json.dumps(got)

    def test_a_page_without_the_attribute_reports_no_sha(self):
        pages = {"https://api.example/api/health": "{}",
                 "https://app.example/": "<html></html>"}
        got = gate.observe_deployment("https://api.example", "https://app.example",
                                      fetch=pages.__getitem__)
        assert got["backend_sha"] is None and got["frontend_sha"] is None


# ---------------------------------------------------------------------------
# The only path to GO
# ---------------------------------------------------------------------------

class TestGoRequiresEverything:
    def test_full_evidence_at_one_sha_can_reach_go(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["final_decision"] == "GO", ledger["blocking_reasons"]

    def test_removing_any_single_evidence_returns_to_no_go(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        full = _all_external_pass(SHA_A)
        for dropped in list(full):
            partial = {k: v for k, v in full.items() if k != dropped}
            ledger = gate.build_ledger(SHA_A, partial, min_records=1)
            assert ledger["final_decision"] == "NO-GO", f"dropping {dropped} still GO"


# ---------------------------------------------------------------------------
# Ledger currency: a verdict from another SHA, or from three weeks ago, is not
# evidence about today's candidate. Both states were live on 2026-09-03, when
# CURRENT.json described a SHA 127 commits behind main and still read as the
# project's release posture.
# ---------------------------------------------------------------------------

def _write_ledger(tmp_path, monkeypatch, **fields) -> None:
    path = tmp_path / "data" / "releases"
    path.mkdir(parents=True, exist_ok=True)
    payload = {"release_sha": SHA_A, "generated_at": _now_iso(),
               "final_decision": "GO", **fields}
    (path / "CURRENT.json").write_text(json.dumps(payload))
    monkeypatch.setattr(gate, "_REPO", tmp_path)


class TestLedgerCurrency:
    def test_ledger_for_a_different_sha_is_rejected(self, monkeypatch, tmp_path):
        _write_ledger(tmp_path, monkeypatch, release_sha=SHA_B)
        got = gate.check_ledger_currency(SHA_A)
        assert got["status"] == gate.FAIL
        assert got["reason"] == "sha_mismatch"

    def test_stale_ledger_is_rejected_even_at_the_right_sha(self, monkeypatch, tmp_path):
        old = (datetime.now(UTC)
               - timedelta(days=gate.LEDGER_MAX_AGE_DAYS + 1)).isoformat()
        _write_ledger(tmp_path, monkeypatch, generated_at=old)
        got = gate.check_ledger_currency(SHA_A)
        assert got["status"] == gate.FAIL
        assert got["reason"] == "evidence_stale"

    def test_undated_ledger_cannot_claim_currency(self, monkeypatch, tmp_path):
        _write_ledger(tmp_path, monkeypatch, generated_at=None)
        got = gate.check_ledger_currency(SHA_A)
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "evidence_undated"

    def test_absent_ledger_is_unverified_not_a_pass(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.UNVERIFIED

    def test_current_ledger_at_the_candidate_sha_passes(self, monkeypatch, tmp_path):
        _write_ledger(tmp_path, monkeypatch)
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.PASS

    def test_a_stale_ledger_cannot_produce_go(self, monkeypatch, tmp_path):
        """The whole point, at ledger level rather than gate level."""
        _stub_repo_gates(monkeypatch, SHA_A)
        # Applied after the stub, so this is the ledger_currency the build sees.
        monkeypatch.setattr(
            gate, "check_ledger_currency",
            lambda s, **kw: gate._gate("ledger_currency", gate.FAIL, "stale",
                                       reason="evidence_stale"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        assert any(b["check"] == "ledger_currency" for b in ledger["blockers"])


# ---------------------------------------------------------------------------
# Freshness: the approved floor, and the four ways the number gets improved
# without anything improving.
# ---------------------------------------------------------------------------

def _write_release_block(tmp_path, monkeypatch, block: dict) -> None:
    path = tmp_path / "data" / "processed"
    path.mkdir(parents=True, exist_ok=True)
    (path / "professor_tracking.json").write_text(json.dumps({
        "schema_version": 2, "profiles": {}, "events": [], "release": block,
    }))
    monkeypatch.setattr(gate, "_REPO", tmp_path)
    monkeypatch.setattr(gate, "_tracking_release_block", lambda: (block, None))


def _freshness_block(fresh: int, total: int, **over) -> dict:
    block = {
        "fresh_profiles": fresh,
        "total_profiles": total,
        "expected_profile_count": total,
        "freshness_pct": round(100.0 * fresh / total, 2) if total else None,
        "fully_stale_school_count": 0,
        "fully_stale_schools": [],
        "computed_at": _now_iso(),
    }
    block.update(over)
    return block


class TestFreshnessGate:
    def test_below_the_approved_floor_blocks(self, monkeypatch, tmp_path):
        _write_release_block(tmp_path, monkeypatch, _freshness_block(94, 100))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "below_threshold"
        assert got["evidence"]["freshness_threshold"] == 95.0

    def test_at_the_approved_floor_can_pass(self, monkeypatch, tmp_path):
        _write_release_block(tmp_path, monkeypatch, _freshness_block(95, 100))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.PASS
        assert got["evidence"]["freshness_percent"] == 95.0

    def test_one_fully_stale_school_blocks_a_passing_percentage(
            self, monkeypatch, tmp_path):
        """A school-wide outage averages away against enough fresh siblings."""
        _write_release_block(tmp_path, monkeypatch, _freshness_block(
            99, 100, fully_stale_school_count=1, fully_stale_schools=["caltech"]))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "fully_stale_schools"

    def test_shrinking_the_denominator_is_refused(self, monkeypatch, tmp_path):
        """Counting only the already-tracked subset is not a freshness gain."""
        _write_release_block(tmp_path, monkeypatch, _freshness_block(
            100, 100, expected_profile_count=129060))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "denominator_shrunk"

    def test_a_hand_edited_percentage_is_refused(self, monkeypatch, tmp_path):
        """The percent is recomputed from the counts, never trusted."""
        _write_release_block(tmp_path, monkeypatch,
                             _freshness_block(34, 100, freshness_pct=99.9))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "freshness_inconsistent"

    def test_an_attempted_refresh_does_not_improve_freshness(
            self, monkeypatch, tmp_path):
        """Re-running the producer without verifying anything moves nothing.

        ``fresh_profiles`` only advances on a strictly-newer real profile
        fetch. A refresh that ran, touched nothing, and re-stamped
        ``computed_at`` therefore lands here: current timestamp, same counts,
        same verdict.
        """
        before = _freshness_block(34, 100, computed_at="2026-08-01T00:00:00+00:00")
        _write_release_block(tmp_path, monkeypatch, before)
        assert gate.check_tracking_freshness()["status"] == gate.FAIL

        after = _freshness_block(34, 100)  # computed_at is now
        _write_release_block(tmp_path, monkeypatch, after)
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "below_threshold"
        assert got["evidence"]["freshness_percent"] == 34.0

    def test_an_empty_denominator_is_never_vacuously_fresh(
            self, monkeypatch, tmp_path):
        _write_release_block(tmp_path, monkeypatch, _freshness_block(0, 0))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "denominator_absent"

    def test_a_reading_past_its_ttl_is_stale_not_fresh(self, monkeypatch, tmp_path):
        old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        _write_release_block(tmp_path, monkeypatch,
                             _freshness_block(99, 100, computed_at=old))
        got = gate.check_tracking_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "evidence_stale"


# ---------------------------------------------------------------------------
# Feature-flag applicability
# ---------------------------------------------------------------------------

class TestFeatureFlagApplicability:
    def test_disabled_feature_reports_not_applicable_not_fail(self):
        failing = gate._gate("tracking_release_ready", gate.FAIL, "contract unmet")
        got = gate.apply_applicability(failing, {"professor_signals": False})
        assert got["status"] == gate.NOT_APPLICABLE
        assert got["reason"] == "feature_flag_disabled"
        assert "professor_signals" in got["detail"]

    def test_not_applicable_does_not_block(self):
        assert gate.NOT_APPLICABLE not in gate._BLOCKING

    def test_the_underlying_failure_is_kept_not_erased(self):
        """NOT_APPLICABLE is a statement about the surface, not an all-clear."""
        failing = gate._gate("tracking_freshness", gate.FAIL, "34.14% below 95.0%",
                             {"freshness_percent": 34.14})
        got = gate.apply_applicability(failing, {"professor_signals": False})
        assert got["evidence"]["would_be"]["status"] == gate.FAIL
        assert got["evidence"]["would_be"]["evidence"]["freshness_percent"] == 34.14

    def test_a_disabled_feature_is_never_relabelled_pass(self):
        failing = gate._gate("tracking_freshness", gate.FAIL, "below floor")
        got = gate.apply_applicability(failing, {"professor_signals": False})
        assert got["status"] != gate.PASS

    def test_enabled_feature_keeps_its_gate_blocking(self):
        failing = gate._gate("tracking_release_ready", gate.FAIL, "contract unmet")
        got = gate.apply_applicability(failing, {"professor_signals": True})
        assert got["status"] == gate.FAIL
        assert got["release_blocking"] is True

    def test_unknown_flag_state_fails_safe(self):
        """An unreadable table must not silently excuse every gate it maps."""
        failing = gate._gate("tracking_release_ready", gate.FAIL, "contract unmet")
        assert gate.apply_applicability(failing, None)["status"] == gate.FAIL
        applies, detail = gate.feature_applicability("tracking_release_ready", None)
        assert applies is True
        assert detail["flag_state"] == "unknown"

    def test_an_unrecognised_flag_name_fails_safe(self):
        applies, detail = gate.feature_applicability(
            "tracking_release_ready", {"something_else": True})
        assert applies is True
        assert detail["unknown_features"] == ["professor_signals"]

    def test_a_gate_with_no_feature_mapping_always_applies(self):
        failing = gate._gate("corpus", gate.FAIL, "below floor")
        got = gate.apply_applicability(failing, {"professor_signals": False})
        assert got["status"] == gate.FAIL

    def test_an_operator_cannot_declare_not_applicable_without_a_reason(self):
        """A bare "N/A" is how a real blocker gets retired without being fixed."""
        got = gate.check_external(
            "restore", {"status": "NOT_APPLICABLE", "release_sha": SHA_A}, SHA_A)
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "exemption_unexplained"

    def test_a_reasoned_operator_exemption_is_accepted(self):
        got = gate.check_external(
            "dead_man",
            {"status": "NOT_APPLICABLE", "release_sha": SHA_A,
             "reason": "pg_cron_not_provisioned_on_this_plan"}, SHA_A)
        assert got["status"] == gate.NOT_APPLICABLE
        assert got["reason"] == "pg_cron_not_provisioned_on_this_plan"

    def test_the_committed_flag_table_is_readable(self):
        scope = gate.load_release_scope()
        assert scope is not None
        assert "professor_signals" in scope


class TestProviderApplicability:
    def test_a_provider_shared_with_an_enabled_feature_stays_required(self):
        """ask_ai is off, but resume_renovate is on and shares the LLM key."""
        required, _ = gate.required_providers(
            {"ask_ai": False, "resume_renovate": True})
        assert "llm" in required

    def test_a_core_provider_is_required_regardless_of_flags(self):
        required, not_applicable = gate.required_providers(
            {"ask_ai": False, "resume_renovate": False})
        assert "supabase" in required
        assert "supabase" not in not_applicable

    def test_an_enabled_feature_with_a_missing_provider_blocks(self):
        got = gate.check_providers(
            {"observed_at": _now_iso(),
             "providers": {name: {"status": "configured"}
                           for name in gate._PROVIDER_REQUIRED_BY
                           if name != "supabase"} | {"supabase": {"status": "missing"}}},
            {"ask_ai": False, "resume_renovate": True})
        assert got["status"] == gate.FAIL
        assert got["reason"] == "provider_unconfigured"
        assert "supabase" in got["detail"]

    def test_unknown_flag_state_keeps_every_provider_required(self):
        required, not_applicable = gate.required_providers(None)
        assert not_applicable == []
        assert set(required) == set(gate._PROVIDER_REQUIRED_BY)

    def test_absent_provider_evidence_is_blocked_on_admin_access(self):
        assert gate.check_providers(None, {})["status"] == gate.BLOCKED


# ---------------------------------------------------------------------------
# Evidence staleness
# ---------------------------------------------------------------------------

class TestEvidenceStaleness:
    def test_undated_live_evidence_is_not_treated_as_fresh(self):
        got = gate.check_external(
            "render_canary", {"status": "PASS", "release_sha": SHA_A}, SHA_A)
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "evidence_undated"

    def test_evidence_past_its_maximum_age_is_refused(self):
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        got = gate.check_external(
            "render_canary",
            {"status": "PASS", "release_sha": SHA_A, "observed_at": old}, SHA_A)
        assert got["status"] == gate.FAIL
        assert got["reason"] == "evidence_stale"

    def test_current_evidence_at_the_right_sha_is_accepted(self):
        got = gate.check_external(
            "render_canary",
            {"status": "PASS", "release_sha": SHA_A, "observed_at": _now_iso(),
             "detail": "deployed sha matches"}, SHA_A)
        assert got["status"] == gate.PASS

    def test_ci_evidence_needs_no_age_because_it_is_commit_keyed(self):
        got = gate.check_ci_evidence(
            {"head_sha": SHA_A,
             "checks": [{"name": "Backend (lint + pytest)", "conclusion": "SUCCESS"}]},
            SHA_A)
        backend = next(g for g in got if g["gate"] == "ci:Backend (lint + pytest)")
        assert backend["status"] == gate.PASS


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

class TestRestoreDrillGate:
    def test_a_never_performed_drill_is_blocked_on_scratch_access(
            self, monkeypatch, tmp_path):
        """Not "nobody looked" — nobody CAN, until a project is provisioned."""
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        got = gate.check_restore_drill()
        assert got["status"] == gate.BLOCKED
        assert got["reason"] == "scratch_project_access_required"
        assert got["release_blocking"] is True
        assert got["owner"].startswith("infrastructure owner")
        assert "scratch Supabase project" in got["evidence"]["required_access"]

    def test_a_failed_drill_blocks(self, monkeypatch):
        record = _passing_drill() | {"final_result": "FAIL",
                                     "issues_found": ["RLS policies absent"]}
        monkeypatch.setattr(gate, "load_latest_drill", lambda: (record, None))
        got = gate.check_restore_drill()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "drill_failed"

    def test_a_summary_that_disagrees_with_its_own_steps_blocks(self, monkeypatch):
        record = _passing_drill() | {"rls_validation": "FAIL"}
        monkeypatch.setattr(gate, "load_latest_drill", lambda: (record, None))
        got = gate.check_restore_drill()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "drill_internally_inconsistent"

    def test_a_drill_that_names_no_backup_proves_nothing(self, monkeypatch):
        record = _passing_drill() | {"source_backup_id": None}
        monkeypatch.setattr(gate, "load_latest_drill", lambda: (record, None))
        got = gate.check_restore_drill()
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "backup_unidentified"

    def test_a_drill_for_an_older_schema_state_is_stale_evidence(self, monkeypatch):
        """Migrations are forward-only, so an older drill is not this target."""
        record = _passing_drill() | {
            "restored_schema_version": {"count": 30, "head": "030_x.sql",
                                        "digest": "0" * 16}}
        monkeypatch.setattr(gate, "load_latest_drill", lambda: (record, None))
        got = gate.check_restore_drill(
            {"count": 34, "head": "034_y.sql", "digest": "f" * 16})
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "schema_state_advanced"

    def test_a_drill_past_its_maximum_age_is_refused(self, monkeypatch):
        old = (datetime.now(UTC)
               - timedelta(days=gate.RESTORE_DRILL_MAX_AGE_DAYS + 1)).isoformat()
        record = _passing_drill() | {"performed_at": old}
        monkeypatch.setattr(gate, "load_latest_drill", lambda: (record, None))
        got = gate.check_restore_drill()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "evidence_stale"

    def test_a_successful_current_drill_passes_and_is_traceable(self, monkeypatch):
        record = _passing_drill()
        monkeypatch.setattr(gate, "load_latest_drill", lambda: (record, None))
        got = gate.check_restore_drill()
        assert got["status"] == gate.PASS
        assert got["evidence"]["drill_id"] == "drill-2026-09-04-a"
        assert got["evidence"]["source_backup_id"] == "backup-1"

    def test_the_drill_gate_is_not_excused_by_any_feature_flag(self):
        """Recovery is not a feature; no flag may retire it."""
        assert "restore_drill" not in gate._GATE_REQUIRED_BY

    def test_a_missing_drill_keeps_the_release_no_go(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(gate, "load_latest_drill",
                            lambda: (None, "no restore-drill record"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        assert ledger["restore_drill_status"] == gate.BLOCKED

    def test_the_latest_drill_is_the_one_that_counts(self, monkeypatch, tmp_path):
        drills = tmp_path / "data" / "releases" / "drills"
        drills.mkdir(parents=True)
        older = _passing_drill() | {"drill_id": "older",
                                    "performed_at": "2026-01-01T00:00:00+00:00"}
        newer = _passing_drill() | {"drill_id": "newer"}
        (drills / "a.json").write_text(json.dumps(newer))
        (drills / "b.json").write_text(json.dumps(older))
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        record, err = gate.load_latest_drill()
        assert err is None
        assert record["drill_id"] == "newer"


# ---------------------------------------------------------------------------
# The ledger as an artifact: it has to be reconstructable
# ---------------------------------------------------------------------------

class TestLedgerShape:
    def _ledger(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        return gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)

    def test_ledger_carries_the_release_sha(self, monkeypatch):
        assert self._ledger(monkeypatch)["release_sha"] == SHA_A

    def test_ledger_carries_a_generation_timestamp(self, monkeypatch):
        stamp = gate._parse_stamp(self._ledger(monkeypatch)["generated_at"])
        assert stamp is not None
        assert abs((datetime.now(UTC) - stamp).total_seconds()) < 300

    def test_ledger_binds_the_candidate_artifacts(self, monkeypatch):
        candidate = self._ledger(monkeypatch)["candidate"]
        assert candidate["release_sha"] == SHA_A
        assert "corpus_version" in candidate
        assert "matcher_version" in candidate
        assert candidate["schema_version"]["migrations"]["count"] > 0

    def test_ledger_records_the_feature_flag_states(self, monkeypatch):
        flags = self._ledger(monkeypatch)["feature_flag_states"]
        assert isinstance(flags, dict)
        assert flags["professor_signals"] is False

    def test_ledger_carries_evidence_references_for_each_ci_check(self, monkeypatch):
        ledger = self._ledger(monkeypatch)
        backend = next(g for g in ledger["gates"]
                       if g["gate"] == "ci:Backend (lint + pytest)")
        assert backend["evidence"]["head_sha"] == SHA_A

    def test_every_gate_is_stamped_with_when_it_was_checked(self, monkeypatch):
        for g in self._ledger(monkeypatch)["gates"]:
            assert gate._parse_stamp(g["last_checked_at"]) is not None

    def test_blockers_name_an_owner_and_an_action(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        ledger = gate.build_ledger(SHA_A, {}, min_records=1)
        assert ledger["blockers"]
        for blocker in ledger["blockers"]:
            assert blocker["owner"]
            assert blocker["recommended_action"]
            assert blocker["reason"]
            assert blocker["release_blocking"] is True

    def test_not_applicable_gates_are_listed_with_their_reason(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(
            gate, "check_tracking_freshness",
            lambda: gate._gate("tracking_freshness", gate.FAIL, "34.14% below 95.0%"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        entry = next(e for e in ledger["not_applicable_gates"]
                     if e["gate"] == "tracking_freshness")
        assert entry["reason"] == "feature_flag_disabled"

    def test_tracking_freshness_is_reported_even_when_it_does_not_gate(
            self, monkeypatch):
        """"Not applicable" is about the surface, not a reason to stop measuring."""
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(
            gate, "check_tracking_freshness",
            lambda: gate._gate("tracking_freshness", gate.FAIL, "below floor",
                               {"freshness_percent": 34.8,
                                "freshness_threshold": 95.0,
                                "fully_stale_school_count": 39}))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["tracking_freshness_percent"] == 34.8
        assert ledger["tracking_fully_stale_school_count"] == 39

    def test_the_headline_freshness_is_the_corpus_one(self, monkeypatch):
        """The release requirement is corpus freshness, not tracking coverage.

        Reporting the tracking number under the bare name `freshness` is how a
        34.8% coverage gap and a 91.2% corpus reading were read as one fact.
        """
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(
            gate, "check_corpus_freshness",
            lambda: gate._gate("corpus_freshness", gate.PASS, "fine",
                               {"freshness_percent": 96.5,
                                "freshness_threshold": 95.0,
                                "fully_stale_school_count": 0}))
        monkeypatch.setattr(
            gate, "check_tracking_freshness",
            lambda: gate._gate("tracking_freshness", gate.FAIL, "below floor",
                               {"freshness_percent": 34.8,
                                "freshness_threshold": 95.0,
                                "fully_stale_school_count": 39}))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["freshness_percent"] == 96.5
        assert ledger["fully_stale_school_count"] == 0
        assert ledger["tracking_freshness_percent"] == 34.8

    def test_the_candidate_can_regenerate_the_committed_ledger(
            self, monkeypatch, tmp_path):
        _write_ledger(tmp_path, monkeypatch, release_sha=SHA_B)
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.FAIL
        fresh = {"release_sha": SHA_A, "generated_at": _now_iso(),
                 "final_decision": "NO-GO"}
        (tmp_path / "data" / "releases" / "CURRENT.json").write_text(json.dumps(fresh))
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.PASS


class TestUnknownNeverDefaultsToPass:
    def test_cannot_verify_required_evidence_is_no_go(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        evidence = _all_external_pass(SHA_A)
        evidence["supabase_canary"] = {"release_sha": SHA_A,
                                       "observed_at": _now_iso()}  # no status
        ledger = gate.build_ledger(SHA_A, evidence, min_records=1)
        assert ledger["final_decision"] == "NO-GO"

    def test_every_blocking_status_actually_blocks(self):
        for status in (gate.FAIL, gate.UNVERIFIED, gate.SKIPPED, gate.NOT_RUN):
            assert status in gate._BLOCKING


class TestLedgerRefreshIsNotAnExemption:
    def test_a_refreshing_run_satisfies_ledger_currency(self, monkeypatch, tmp_path):
        """A ledger is written after its candidate, so the copy in that
        candidate's own tree always describes an earlier commit. Without this,
        the gate would be unsatisfiable for a tip candidate no matter what
        anyone did — which is how a check stops being read."""
        _write_ledger(tmp_path, monkeypatch, release_sha=SHA_B)
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.FAIL
        got = gate.check_ledger_currency(SHA_A, refreshing=True)
        assert got["status"] == gate.PASS
        assert got["evidence"]["refreshed"] is True

    def test_refreshing_excuses_only_the_ledger_gate(self, monkeypatch):
        """--update-current must not become a way to publish a GO."""
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(gate, "load_latest_drill",
                            lambda: (None, "no restore-drill record"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A),
                                   min_records=1, refreshing=True)
        assert ledger["final_decision"] == "NO-GO"
        assert [b["check"] for b in ledger["blockers"]] == ["restore_drill"]

    def test_a_non_refreshing_run_still_catches_a_stale_ledger(
            self, monkeypatch, tmp_path):
        old = (datetime.now(UTC)
               - timedelta(days=gate.LEDGER_MAX_AGE_DAYS + 1)).isoformat()
        _write_ledger(tmp_path, monkeypatch, generated_at=old)
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.FAIL
# Per-source freshness: the record floor cannot see a frozen school
# ---------------------------------------------------------------------------

def _health(sources: dict) -> dict:
    return {"schema_version": 1, "sources": sources, "shards": {}}


def _row(school: str, days_ago: int, status: str = "success_nonzero") -> dict:
    when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return {
        "school": school,
        "last_attempt_at": datetime.now(UTC).isoformat(),
        "last_success_at": when,
        "status": status,
        "current_count": 0 if status != "success_nonzero" else 10,
        "last_good_count": 10,
        "consecutive_failures": 0 if status == "success_nonzero" else 3,
    }


class TestFullyStaleSchoolGate:
    """The corpus floor counts RECORDS, which a frozen school passes easily -
    UC Berkeley's 3,106 records sat 44 days stale and counted every one."""

    def _run(self, monkeypatch, tmp_path, ledger):
        path = tmp_path / "source_health.json"
        path.write_text(json.dumps(ledger), encoding="utf-8")
        monkeypatch.setattr(gate, "_SOURCE_HEALTH_PATH", path)
        return gate.check_no_fully_stale_school()

    def test_a_school_with_no_fresh_source_fails_the_gate(
        self, monkeypatch, tmp_path,
    ):
        result = self._run(monkeypatch, tmp_path, _health({
            "ucb_ling_faculty": _row("ucb", 44, "suspicious_zero"),
            "ucb_eecs_faculty": _row("ucb", 44, "suspicious_zero"),
        }))
        assert result["status"] == gate.FAIL
        assert result["evidence"]["fully_stale_school_count"] == 1
        assert result["evidence"]["fully_stale_schools"] == ["ucb"]

    def test_one_stale_department_among_fresh_ones_passes(
        self, monkeypatch, tmp_path,
    ):
        """Deliberately NOT a blocker: partial degradation is what the publish
        path now allows on purpose. Failing the release for it would rebuild
        the veto from the other direction."""
        result = self._run(monkeypatch, tmp_path, _health({
            "ucb_ling_faculty": _row("ucb", 44, "suspicious_zero"),
            "ucb_eecs_faculty": _row("ucb", 2),
            "ucb_math_faculty": _row("ucb", 2),
        }))
        assert result["status"] == gate.PASS
        assert result["evidence"]["fully_stale_school_count"] == 0
        assert result["evidence"]["partially_degraded_school_count"] == 1
        assert result["evidence"]["stale_shard_count"] == 1

    def test_all_fresh_passes_cleanly(self, monkeypatch, tmp_path):
        result = self._run(monkeypatch, tmp_path, _health({
            "yale_faculty": _row("yale", 1),
            "ucb_eecs_faculty": _row("ucb", 3),
        }))
        assert result["status"] == gate.PASS
        assert result["evidence"]["stale_shard_count"] == 0

    def test_an_absent_ledger_cannot_be_verified_and_is_not_a_pass(
        self, monkeypatch, tmp_path,
    ):
        """Default NO-GO: not knowing must never read as knowing it is fine."""
        monkeypatch.setattr(
            gate, "_SOURCE_HEALTH_PATH", tmp_path / "absent.json",
        )
        result = gate.check_no_fully_stale_school()
        assert result["status"] == gate.CANNOT_VERIFY
        assert result["status"] in gate._BLOCKING

    def test_the_gate_is_part_of_the_ledger(self, monkeypatch, tmp_path):
        """A gate nobody evaluates is not a gate."""
        import subprocess
        monkeypatch.setattr(gate, "check_release_sha",
                            lambda sha: gate._gate("release_sha", gate.PASS, "s"))
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=("" if "status" in cmd else SHA_A) + "\n", stderr=""))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        names = {g["gate"] for g in ledger["gates"]}
        assert "no_fully_stale_school" in names


# ---------------------------------------------------------------------------
# Corpus freshness is a release requirement, not a report. These tests exist
# because it spent a release cycle being measured, printed, and not enforced.
# ---------------------------------------------------------------------------

def _write_shard(tmp_path, monkeypatch, schools: dict[str, list[tuple[bool, int]]]):
    """schools -> [(is_active, days_since_last_seen), ...] per record."""
    shard_dir = tmp_path / "data" / "processed" / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    for school, records in schools.items():
        payload = [
            {"id": f"{school}-{i}", "metadata": {
                "is_active": active,
                "last_seen_at": (now - timedelta(days=age)).isoformat(),
            }}
            for i, (active, age) in enumerate(records)
        ]
        (shard_dir / f"{school}.json").write_text(json.dumps(payload))
    monkeypatch.setattr(gate, "_REPO", tmp_path)
    # The policy constants live in the real tree, not the fixture one.
    monkeypatch.setattr(gate, "corpus_freshness_policy", lambda: (95.0, 14.0))


class TestCorpusFreshnessIsEnforced:
    def test_below_the_configured_floor_is_fail_not_unverified(
            self, monkeypatch, tmp_path):
        """The failure this whole round is about."""
        _write_shard(tmp_path, monkeypatch, {
            "a": [(True, 1)] * 91 + [(True, 40)] * 9,
        })
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.FAIL
        assert got["status"] != gate.UNVERIFIED
        assert got["reason"] == "below_threshold"
        assert got["evidence"]["freshness_percent"] == 91.0

    def test_any_fully_stale_school_is_fail(self, monkeypatch, tmp_path):
        """Even at a passing percentage: one dead school is a release blocker."""
        _write_shard(tmp_path, monkeypatch, {
            "big": [(True, 1)] * 990,
            "dead": [(True, 40)] * 10,
        })
        got = gate.check_corpus_freshness()
        assert got["evidence"]["freshness_percent"] == 99.0
        assert got["status"] == gate.FAIL
        assert got["evidence"]["fully_stale_school_count"] == 1
        assert got["evidence"]["fully_stale_schools"] == ["dead"]

    def test_at_or_above_the_floor_with_no_dead_school_passes(
            self, monkeypatch, tmp_path):
        _write_shard(tmp_path, monkeypatch, {
            "a": [(True, 1)] * 95 + [(True, 40)] * 5,
            "b": [(True, 2)] * 10,
        })
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.PASS

    def test_it_blocks_the_release(self, monkeypatch, tmp_path):
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(
            gate, "check_corpus_freshness",
            lambda: gate._gate("corpus_freshness", gate.FAIL, "91.17% < 95.0%",
                               reason="below_threshold"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        assert "corpus_freshness" in [b["check"] for b in ledger["blockers"]]

    def test_no_feature_flag_can_retire_it(self):
        """Every surface reads the corpus; no optional feature owns it."""
        assert "corpus_freshness" not in gate._GATE_REQUIRED_BY
        failing = gate._gate("corpus_freshness", gate.FAIL, "below floor")
        for scope in ({"professor_signals": False}, {}, None):
            assert gate.apply_applicability(failing, scope)["status"] == gate.FAIL

    def test_deactivated_records_are_excluded_from_both_sides(
            self, monkeypatch, tmp_path):
        """Retired records are not stale data being served."""
        _write_shard(tmp_path, monkeypatch, {
            "a": [(True, 1)] * 10 + [(False, 400)] * 90,
        })
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.PASS
        assert got["evidence"]["active_records"] == 10
        assert got["evidence"]["inactive_records"] == 90

    def test_a_rewritten_shard_carrying_old_stamps_is_still_stale(
            self, monkeypatch, tmp_path):
        """Republishing retained records is not a refresh.

        The stamp only moves when a collector really re-observed the record, so
        a run that executed and fetched nothing cannot raise this number.
        """
        _write_shard(tmp_path, monkeypatch, {"a": [(True, 40)] * 100})
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.FAIL
        assert got["evidence"]["fresh_records"] == 0

    def test_an_empty_corpus_is_never_vacuously_fresh(self, monkeypatch, tmp_path):
        _write_shard(tmp_path, monkeypatch, {"a": [(False, 1)] * 5})
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.CANNOT_VERIFY
        assert got["reason"] == "denominator_absent"

    def test_the_threshold_comes_from_the_project_not_this_module(self):
        """Imported, never restated, so the gate cannot drift off the pipeline."""
        import src.normalizers.deactivate_stale_faculty as dsf
        import src.tracking.professor_profiles as pp
        min_pct, stale_days = gate.corpus_freshness_policy()
        assert min_pct == pp.FRESHNESS_MIN_PCT
        assert stale_days == float(dsf.GRACE_DAYS)


class TestBlockingStatusesAreDistinct:
    def test_all_four_non_pass_states_block(self):
        for status in (gate.FAIL, gate.UNVERIFIED, gate.BLOCKED,
                       gate.CANNOT_VERIFY):
            assert status in gate._BLOCKING

    def test_not_applicable_is_the_only_non_blocking_non_pass(self):
        assert gate.NOT_APPLICABLE not in gate._BLOCKING

    def test_a_known_numeric_failure_is_never_reported_as_unverified(
            self, monkeypatch, tmp_path):
        _write_shard(tmp_path, monkeypatch, {"a": [(True, 40)] * 100})
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.FAIL
        assert got["status"] not in (gate.UNVERIFIED, gate.BLOCKED,
                                     gate.CANNOT_VERIFY, gate.NOT_APPLICABLE)

    def test_missing_restore_access_is_blocked_never_pass(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        got = gate.check_restore_drill()
        assert got["status"] == gate.BLOCKED
        assert got["status"] != gate.PASS

    def test_the_summary_separates_every_state(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        ledger = gate.build_ledger(SHA_A, {}, min_records=1)
        s = ledger["summary"]
        for key in ("passed", "failed", "blocked", "cannot_verify", "unverified",
                    "not_applicable", "release_blocking"):
            assert key in s, key
        assert s["release_blocking"] == len(ledger["blockers"])


class TestCandidateProvenance:
    def test_changing_the_candidate_sha_invalidates_old_evidence(self, monkeypatch):
        """Evidence gathered for one build says nothing about another."""
        _stub_repo_gates(monkeypatch, SHA_A)
        old = _all_external_pass(SHA_A)
        ledger = gate.build_ledger(SHA_B, old, min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        mismatched = [g for g in ledger["gates"]
                      if g.get("reason") == "sha_mismatch"]
        assert mismatched, "evidence for another SHA must not be reused"

    def test_a_stale_ledger_cannot_satisfy_a_candidate(self, monkeypatch, tmp_path):
        _write_ledger(tmp_path, monkeypatch, release_sha=SHA_B)
        assert gate.check_ledger_currency(SHA_A)["status"] == gate.FAIL


# ---------------------------------------------------------------------------
# Publishing a school whose departments partly failed must not launder those
# departments' records into looking fresh. The contract now lets that school
# publish; these pin what publishing is allowed to change.
# ---------------------------------------------------------------------------

class TestPartialPublishDoesNotFakeFreshness:
    def test_a_retained_record_keeps_its_own_stale_stamp(
            self, monkeypatch, tmp_path):
        """55 departments re-observed, one not: only 55 move.

        This is the UCB shape. Publishing the school is correct; publishing it
        as though every department had been seen would not be.
        """
        _write_shard(tmp_path, monkeypatch, {
            "ucb": [(True, 1)] * 55 + [(True, 45)] * 45,
        })
        got = gate.check_corpus_freshness()
        assert got["evidence"]["fresh_records"] == 55
        assert got["evidence"]["stale_records"] == 45
        assert got["evidence"]["fully_stale_school_count"] == 0
        assert got["evidence"]["partially_stale_school_count"] == 1

    def test_a_school_leaves_fully_stale_only_when_real_records_are_fresh(
            self, monkeypatch, tmp_path):
        _write_shard(tmp_path, monkeypatch, {"ucb": [(True, 45)] * 100})
        before = gate.check_corpus_freshness()
        assert before["evidence"]["fully_stale_schools"] == ["ucb"]

        # One department genuinely re-observed — the school is no longer dead.
        _write_shard(tmp_path, monkeypatch, {
            "ucb": [(True, 1)] * 16 + [(True, 45)] * 84,
        })
        after = gate.check_corpus_freshness()
        assert after["evidence"]["fully_stale_school_count"] == 0
        # Still failing on the percentage — recovering one department is not
        # recovering the corpus.
        assert after["status"] == gate.FAIL
        assert after["reason"] == "below_threshold"

    def test_freshness_uses_the_active_corpus_denominator(
            self, monkeypatch, tmp_path):
        """Retired records leave both sides; they are not stale data served."""
        _write_shard(tmp_path, monkeypatch, {
            "ucb": [(True, 1)] * 96 + [(True, 45)] * 4 + [(False, 900)] * 500,
        })
        got = gate.check_corpus_freshness()
        assert got["evidence"]["active_records"] == 100
        assert got["evidence"]["inactive_records"] == 500
        assert got["evidence"]["freshness_percent"] == 96.0
        assert got["status"] == gate.PASS

    def test_the_threshold_still_blocks_the_release(self, monkeypatch):
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(
            gate, "check_corpus_freshness",
            lambda: gate._gate("corpus_freshness", gate.FAIL, "94.9% < 95.0%",
                               reason="below_threshold"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        assert ledger["summary"]["failed"] >= 1


# ---------------------------------------------------------------------------
# Migration parity (M66): committed supabase/migrations against an export of
# production's supabase_migrations.schema_migrations. The script never
# connects to anything; running its SQL against production waits on owner Q4.
# Production records the same migration three ways, all seen there: a CLI
# version equal to the file prefix, a hosted timestamp alias for 012-014
# (MIGRATION_REPAIR.md), and an MCP apply_migration timestamp with the name
# passed at apply time (024 onwards) — which is why it reconciles by name.
# ---------------------------------------------------------------------------

_mp_spec = importlib.util.spec_from_file_location(
    "check_migration_parity", _REPO / "scripts" / "check_migration_parity.py")
parity = importlib.util.module_from_spec(_mp_spec)
# dataclasses resolve string annotations through sys.modules.
sys.modules[_mp_spec.name] = parity
_mp_spec.loader.exec_module(parity)

_MIGRATIONS = {
    "001_core_profiles_favorites.sql": "create table profiles ();\n",
    "012_match_feedback.sql": "create table match_feedback ();\n",
    "0181_oauth_merge_secret.sql": "create table oauth_merge ();\n",
    "20260924181610_target_resume_cas.sql": "create function target_resume_cas();\n",
}


def _md5(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()


def _applied_rows() -> list[dict]:
    return [
        {"version": "001", "name": None},
        {"version": "20260611111920", "name": "match_feedback"},
        {"version": "20260814101500", "name": "0181_oauth_merge_secret"},
        {"version": "20260930112700", "name": "target_resume_cas",
         "statements_md5": _md5(_MIGRATIONS["20260924181610_target_resume_cas.sql"])},
    ]


def _migrations_dir(tmp_path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    for name, body in _MIGRATIONS.items():
        (directory / name).write_text(body)
    return directory


class TestMigrationParity:
    def test_every_recording_style_reconciles(self, tmp_path):
        report = parity.compare(parity.committed_migrations(_migrations_dir(tmp_path)),
                                parity.applied_rows(_applied_rows()))
        assert report["in_parity"] is True, report
        assert report["missing"] == [] and report["extra"] == []
        how = {m["file"]: m["matched_by"] for m in report["matched"]}
        assert how["001_core_profiles_favorites.sql"] == "version"
        assert how["012_match_feedback.sql"] == "name"
        assert report["content"]["matching"] == ["20260924181610_target_resume_cas.sql"]

    def test_a_committed_migration_production_never_ran_is_missing(self, tmp_path):
        rows = [r for r in _applied_rows() if r["name"] != "target_resume_cas"]
        report = parity.compare(parity.committed_migrations(_migrations_dir(tmp_path)),
                                parity.applied_rows(rows))
        assert report["in_parity"] is False
        assert report["missing"] == ["20260924181610_target_resume_cas.sql"]

    def test_a_migration_production_ran_that_the_repo_lacks_is_extra(self, tmp_path):
        rows = _applied_rows() + [{"version": "20261001000000", "name": "hotfix_by_hand"}]
        report = parity.compare(parity.committed_migrations(_migrations_dir(tmp_path)),
                                parity.applied_rows(rows))
        assert report["in_parity"] is False
        assert report["extra"] == [{"version": "20261001000000", "name": "hotfix_by_hand"}]

    def test_a_migration_recorded_twice_is_not_parity(self, tmp_path):
        rows = _applied_rows() + [{"version": "012", "name": "match_feedback"}]
        report = parity.compare(parity.committed_migrations(_migrations_dir(tmp_path)),
                                parity.applied_rows(rows))
        assert report["in_parity"] is False
        assert report["duplicates"] == {"012_match_feedback.sql": 2}

    def test_different_bytes_are_reported_but_do_not_fail_by_default(self, tmp_path):
        # 025-032 went in comment-stripped (memory 2026-09-30): same behaviour,
        # different md5. Named, so a real transcription error is visible.
        rows = _applied_rows()
        rows[-1]["statements_md5"] = "0" * 32
        committed = parity.committed_migrations(_migrations_dir(tmp_path))
        report = parity.compare(committed, parity.applied_rows(rows))
        assert report["in_parity"] is True
        assert report["content"]["differs"] == ["20260924181610_target_resume_cas.sql"]
        strict = parity.compare(committed, parity.applied_rows(rows), strict_content=True)
        assert strict["in_parity"] is False

    def test_reads_json_and_csv_exports(self, tmp_path):
        as_json = tmp_path / "rows.json"
        as_json.write_text(json.dumps({"rows": _applied_rows()}))
        as_csv = tmp_path / "rows.csv"
        as_csv.write_text("version,name,statements_md5\n001,,\n"
                          "20260611111920,match_feedback,\n")
        assert len(parity.load_export(as_json)) == 4
        assert parity.load_export(as_csv)[0] == {"version": "001", "name": None,
                                                 "statements_md5": None}

    def test_cli_exit_codes(self, tmp_path):
        import subprocess
        directory = _migrations_dir(tmp_path)
        good = tmp_path / "good.json"
        good.write_text(json.dumps(_applied_rows()))
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(_applied_rows()[:-1]))
        broken = tmp_path / "broken.json"
        broken.write_text("{not json")
        script = str(_REPO / "scripts" / "check_migration_parity.py")

        def run(path):
            return subprocess.run([sys.executable, script, "--applied", str(path),
                                   "--migrations-dir", str(directory)],
                                  capture_output=True, text=True).returncode

        assert (run(good), run(bad), run(broken)) == (0, 1, 2)

    def test_the_query_it_prints_only_reads(self):
        sql = parity.EXPORT_SQL.lower()
        assert "supabase_migrations.schema_migrations" in sql
        assert sql.lstrip().startswith(("--", "select"))
        for verb in ("insert", "update", "delete", "drop", "alter", "truncate", "grant"):
            assert f" {verb} " not in f" {sql} "

    def test_the_committed_set_can_be_reconciled_by_name(self):
        """Name matching is only safe while no two files share a name."""
        committed = parity.committed_migrations(_REPO / "supabase" / "migrations")
        assert len(committed) >= 49
        names = [m.bare_name for m in committed]
        assert len(names) == len(set(names)), "two migrations share a name"
        assert all(m.prefix and m.bare_name for m in committed)


# ---------------------------------------------------------------------------
# Environment variables (M67): docs/RELEASE.md §6 is the inventory. The code
# is scanned so the table cannot drift from it, and every backend variable
# the table calls required is removed in turn to show it fails loudly.
# ---------------------------------------------------------------------------

_RELEASE_DOC = _REPO / "docs" / "RELEASE.md"


def _documented_env() -> dict[str, dict[str, str]]:
    """{section: {name: "required"|"optional"}} from RELEASE.md §6."""
    text = _RELEASE_DOC.read_text(encoding="utf-8")
    section = text.split("## 6. Environment variables", 1)[1].split("\n## ", 1)[0]
    tables: dict[str, dict[str, str]] = {}
    for block in section.split("\n### ")[1:]:
        heading, _, body = block.partition("\n")
        rows: dict[str, str] = {}
        for line in body.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3 or cells[0] in ("Variable", "---"):
                continue
            requirement = cells[1].split()[0]
            assert requirement in ("required", "optional"), line
            for name in re.findall(r"`([A-Z][A-Z0-9_]*\*?)`", cells[0]):
                assert name not in rows, f"{name} listed twice under {heading}"
                rows[name] = requirement
        tables[heading.split(" (")[0].strip()] = rows
    return tables


def _is_environ(node: ast.AST) -> bool:
    return ((isinstance(node, ast.Attribute) and node.attr == "environ")
            or (isinstance(node, ast.Name) and node.id == "environ"))


def _env_name_arg(node: ast.AST) -> ast.AST | None:
    """The name argument of an environment read, or None if this is not one."""
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        return node.slice
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        func = node.func
        if ((func.attr in ("get", "setdefault", "pop") and _is_environ(func.value))
                or func.attr == "getenv") and node.args:
            return node.args[0]
    return None


def _scan_python_env() -> tuple[set[str], set[tuple[str, str]]]:
    """(literal names read, (file, function) sites whose name is not literal).

    A function whose first parameter is read as a variable name (directly, or
    by looping over it) is a helper: `_env_float("OFE_W_ELIG", …)`,
    `_required_env(["SUPABASE_URL", …])`. Literal arguments to helpers count
    as reads; any other non-literal read is an indirect site.
    """
    files = [p for d in ("backend", "src") for p in sorted((_REPO / d).rglob("*.py"))]
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in files}
    helpers: dict[str, tuple[str, int]] = {}
    for tree in trees.values():
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) or not fn.args.args:
                continue
            params = [a.arg for a in fn.args.args]
            loops = {n.target.id: n.iter.id for n in ast.walk(fn)
                     if isinstance(n, ast.For | ast.comprehension)
                     and isinstance(n.iter, ast.Name) and n.iter.id in params
                     and isinstance(n.target, ast.Name)}
            for node in ast.walk(fn):
                arg = _env_name_arg(node)
                if isinstance(arg, ast.Name) and arg.id in params:
                    helpers[fn.name] = ("one", params.index(arg.id))
                elif isinstance(arg, ast.Name) and arg.id in loops:
                    helpers[fn.name] = ("many", params.index(loops[arg.id]))

    names: set[str] = set()
    indirect: set[tuple[str, str]] = set()
    for path, tree in trees.items():
        rel = path.relative_to(_REPO).as_posix()
        owner: dict[ast.AST, str] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                for node in ast.walk(fn):
                    if node is not fn:
                        owner[node] = fn.name  # walk is outer-first: innermost wins
        for node in ast.walk(tree):
            where = owner.get(node, "<module>")
            arg = _env_name_arg(node)
            if arg is None and isinstance(node, ast.Call):
                func = node.func
                called = (func.id if isinstance(func, ast.Name)
                          else func.attr if isinstance(func, ast.Attribute) else None)
                if called in helpers and len(node.args) > helpers[called][1]:
                    mode, index = helpers[called]
                    arg = node.args[index]
                    if mode == "many" and isinstance(arg, ast.Tuple | ast.List):
                        if all(isinstance(e, ast.Constant) for e in arg.elts):
                            names.update(e.value for e in arg.elts)
                            continue
            if arg is None:
                continue
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.add(arg.value)
            elif where not in helpers:
                indirect.add((rel, where))
    return names, indirect


def _indirect_env_names() -> dict[tuple[str, str], list[str]]:
    """Where each non-literal read gets its names. A new indirect read fails
    the inventory until it is added here, so the scan cannot silently stop
    seeing a variable."""
    from backend.lib import build_info, llm, release_scope

    return {
        ("backend/lib/build_info.py", "release_sha"): list(build_info.SHA_ENV_VARS),
        ("backend/lib/llm.py", "_resolve"): [p[1] for p in llm._PROVIDERS],
        ("backend/lib/llm.py", "model_for"): ["OFE_MODEL_*"],
        ("backend/lib/release_scope.py", "feature_enabled"):
            list(release_scope._RUNTIME_KILL_SWITCHES.values()),
        # Not configuration: OS variables handed to a sandboxed subprocess,
        # and two CLI loaders that copy backend/.env into os.environ.
        ("backend/lib/material_archive.py", "validate_pdf"): [],
        ("src/collectors/llm_enrich.py", "_load_dotenv"): [],
        ("src/collectors/openalex_enrich.py", "_load_dotenv"): [],
    }


def _scan_frontend_env() -> set[str]:
    root = _REPO / "frontend"
    paths = [root / "next.config.js", *sorted((root / "scripts").glob("*.mjs"))]
    paths += [p for p in sorted((root / "src").rglob("*"))
              if p.suffix in (".ts", ".tsx", ".js", ".mjs")
              and not re.search(r"\.(test|spec)\.", p.name) and "__fixtures__" not in p.parts]
    found: set[str] = set()
    for path in paths:
        found.update(re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)",
                                path.read_text(encoding="utf-8")))
    return found


def _scan_workflow_env() -> set[str]:
    found: set[str] = set()
    for path in sorted((_REPO / ".github" / "workflows").glob("*.yml")):
        found.update(re.findall(r"\b(?:secrets|vars)\.([A-Z][A-Z0-9_]*)",
                                path.read_text(encoding="utf-8")))
    return found


class TestEnvironmentInventory:
    def test_every_variable_the_python_code_reads_is_listed_and_no_other(self):
        names, indirect = _scan_python_env()
        sources = _indirect_env_names()
        for site in indirect & set(sources):
            names.update(sources[site])
        unexplained = sorted(indirect - set(sources))
        assert not unexplained, (
            f"non-literal environment reads at {unexplained}: add where their "
            "names come from to _indirect_env_names")
        documented = _documented_env()
        listed = {**documented["Backend"], **documented["Data refresh"]}
        assert sorted(names - set(listed)) == [], "read in code, missing from RELEASE.md §6"
        assert sorted(set(listed) - names) == [], "listed in RELEASE.md §6, read nowhere"

    def test_every_indirect_source_still_exists(self):
        _, indirect = _scan_python_env()
        assert sorted(set(_indirect_env_names()) - indirect) == []

    def test_every_variable_the_frontend_reads_is_listed_and_no_other(self):
        listed = set(_documented_env()["Frontend"])
        found = _scan_frontend_env()
        assert sorted(found - listed) == [] and sorted(listed - found) == []

    def test_every_workflow_secret_and_variable_is_listed_and_no_other(self):
        listed = set(_documented_env()["GitHub Actions secrets and variables"])
        found = _scan_workflow_env()
        assert sorted(found - listed) == [] and sorted(listed - found) == []

    def test_the_scan_sees_reads_through_helpers(self):
        # Guards the scanner itself: these four are only ever read through a
        # helper or a table, never as os.environ.get("…") at the call site.
        names, _ = _scan_python_env()
        assert {"OFE_W_ELIG", "OFE_BLOCKING_AI_MAX_WORKERS", "VAPID_SUBJECT",
                "OFE_CORPUS_STALE_HOURS"} <= names


# --- required backend variables fail loudly ---------------------------------

_ccr_spec = importlib.util.spec_from_file_location(
    "check_cron_response_for_release", _REPO / "scripts" / "check_cron_response.py")
cron_checker = importlib.util.module_from_spec(_ccr_spec)
_ccr_spec.loader.exec_module(cron_checker)

_FULL_BACKEND_ENV = {
    "CRON_SECRET": "cron-ok",
    "ADMIN_TOKEN": "admin-ok",
    # Never contacted: every probe below stops before its first request.
    "SUPABASE_URL": "http://127.0.0.1:9",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-placeholder",
    "VAPID_PRIVATE_KEY": "vapid-private-placeholder",
    "VAPID_PUBLIC_KEY": "vapid-public-placeholder",
    "VAPID_SUBJECT": "mailto:ops@example.invalid",
    "RESEND_API_KEY": "resend-placeholder",
    "RESEND_FROM_EMAIL": "JoinALab <alerts@example.invalid>",
    "RESTORE_LINK_SECRET": "unsubscribe-signing-placeholder",
}
_CRON = {"Authorization": "Bearer cron-ok"}
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _env_without(monkeypatch, name: str) -> None:
    for key, value in _FULL_BACKEND_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_VAPID_PUBLIC_KEY", raising=False)


def _client():
    from fastapi.testclient import TestClient

    from backend.main import app
    return app, TestClient(app)


def _workflow_verdict(monkeypatch, body: dict) -> int:
    """What the cron workflow's check_cron_response.py step does with a body."""
    monkeypatch.setattr(cron_checker.sys, "stdin", io.StringIO(json.dumps(body)))
    return cron_checker.main()


def _routes(app, prefix: str) -> list[tuple[str, str]]:
    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(prefix):
            out += [(method, re.sub(r"\{[^}]+\}", _ZERO_UUID, path))
                    for method in sorted(route.methods)]
    return out


def _cron_bodies_name_it(monkeypatch, name: str, paths: list[tuple[str, str]]) -> None:
    _, client = _client()
    for method, path in paths:
        response = client.request(method, path, headers=_CRON)
        assert response.status_code == 200, (path, response.text)
        body = response.json()
        assert body["status"] == "skipped" and name in body.get("missing", []), (path, body)
        assert _workflow_verdict(monkeypatch, body) == 1, (path, body)


def _probe_cron_secret(monkeypatch):
    app, client = _client()
    routes = _routes(app, "/api/cron/")
    assert len(routes) >= 5
    for method, path in routes:
        response = client.request(method, path, json={"name": "release-probe"})
        assert response.status_code == 503, (path, response.status_code)
        assert "CRON_SECRET" in response.json()["detail"], path


def _probe_admin_token(monkeypatch):
    app, client = _client()
    routes = _routes(app, "/api/admin/") + [("GET", "/api/ready")]
    assert len(routes) >= 20
    for method, path in routes:
        response = client.request(method, path, json={},
                                  headers={"X-Admin-Token": "anything"})
        assert response.status_code == 503, (path, response.status_code)
        assert "ADMIN_TOKEN" in response.json()["detail"], path


def _probe_supabase(name: str):
    def probe(monkeypatch):
        _cron_bodies_name_it(monkeypatch, name, [
            ("GET", "/api/cron/reminders"),
            ("GET", "/api/cron/saved-searches/refresh"),
            ("GET", "/api/cron/saved-searches/digest"),
            ("POST", "/api/cron/ops-scan"),
        ])
        _, client = _client()
        heartbeat = client.post("/api/cron/heartbeat", headers=_CRON,
                                json={"name": "release-probe"})
        assert heartbeat.status_code == 503 and name in heartbeat.json()["detail"]
        incidents = client.get("/api/admin/ops/incidents",
                               headers={"X-Admin-Token": "admin-ok"})
        assert incidents.status_code == 503 and name in incidents.json()["detail"]
    return probe


def _probe_vapid(name: str):
    def probe(monkeypatch):
        _cron_bodies_name_it(monkeypatch, name, [("GET", "/api/cron/reminders")])
        if name == "VAPID_PUBLIC_KEY":
            _, client = _client()
            assert client.get("/api/push/vapid-public-key").status_code == 503
    return probe


def _probe_digest(name: str):
    def probe(monkeypatch):
        _cron_bodies_name_it(monkeypatch, name, [("GET", "/api/cron/saved-searches/digest")])
        if name == "RESTORE_LINK_SECRET":
            _, client = _client()
            response = client.get("/api/email/digest-unsubscribe",
                                  params={"sid": _ZERO_UUID, "t": 0, "s": "0" * 32})
            assert response.status_code == 503
    return probe


_FAIL_FAST_PROBES = {
    "CRON_SECRET": _probe_cron_secret,
    "ADMIN_TOKEN": _probe_admin_token,
    "SUPABASE_URL": _probe_supabase("SUPABASE_URL"),
    "SUPABASE_SERVICE_ROLE_KEY": _probe_supabase("SUPABASE_SERVICE_ROLE_KEY"),
    "VAPID_PRIVATE_KEY": _probe_vapid("VAPID_PRIVATE_KEY"),
    "VAPID_PUBLIC_KEY": _probe_vapid("VAPID_PUBLIC_KEY"),
    "VAPID_SUBJECT": _probe_vapid("VAPID_SUBJECT"),
    "RESEND_API_KEY": _probe_digest("RESEND_API_KEY"),
    "RESEND_FROM_EMAIL": _probe_digest("RESEND_FROM_EMAIL"),
    "RESTORE_LINK_SECRET": _probe_digest("RESTORE_LINK_SECRET"),
}


class TestRequiredEnvironmentFailsFast:
    def test_every_required_backend_variable_has_a_probe(self):
        required = {name for name, need in _documented_env()["Backend"].items()
                    if need == "required"}
        assert required == set(_FAIL_FAST_PROBES)

    @pytest.mark.parametrize("name", sorted(_FAIL_FAST_PROBES))
    def test_removing_it_fails_loudly(self, name, monkeypatch):
        _env_without(monkeypatch, name)
        _FAIL_FAST_PROBES[name](monkeypatch)

    def test_a_skip_that_names_missing_configuration_fails_the_workflow(
            self, monkeypatch):
        """A cron that cannot run in production is not a deliberate no-op.

        Every production cron answered "ok" on 10-08 and 10-09, so this changes
        nothing today; it is what makes a variable that later disappears from
        Render fail the next run instead of turning it green every day.
        """
        assert _workflow_verdict(monkeypatch, {
            "status": "skipped", "reason": "push env not configured",
            "missing": ["VAPID_SUBJECT"]}) == 1
        # A skip that names no configuration is still the announced no-op.
        assert _workflow_verdict(monkeypatch, {
            "status": "skipped", "reason": "pywebpush not installed"}) == 0
