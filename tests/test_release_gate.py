"""The release gate must be impossible to talk into a GO it hasn't earned.

Every test here is really the same test from a different angle: absence of
evidence is never a pass. The gate's default is NO-GO, and each gate can only
flip to PASS by presenting evidence bound to the frozen release SHA.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_gate", _REPO / "scripts" / "release_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

SHA_A = "a" * 40
SHA_B = "b" * 40


def _find(ledger: dict, name: str) -> dict:
    return next(g for g in ledger["gates"] if g["gate"] == name)


def _all_external_pass(sha: str) -> dict:
    """Evidence that satisfies every out-of-repo gate for the given sha."""
    ok = {"status": "PASS", "release_sha": sha, "detail": "verified"}
    names = (*gate._EXTERNAL_GATES, "api_ready", "promotion", "rollback", "scheduler")
    ev = {name: dict(ok) for name in names}
    ev["ci"] = {
        "head_sha": sha,
        "checks": [{"name": n, "conclusion": "SUCCESS"} for n in (
            "Backend (lint + pytest)", "Frontend (typecheck + build)",
            "Migrations (Flow B merge + CLI replay)", "E2E (Playwright)")],
    }
    ev["open_incidents"] = {"rollup": {"open_total": 0, "truncated": False}}
    return ev


# ---------------------------------------------------------------------------
# Default posture
# ---------------------------------------------------------------------------

class TestDefaultNoGo:
    def test_bare_invocation_is_no_go(self):
        ledger = gate.build_ledger(None, {}, min_records=1)
        assert ledger["final_decision"] == "NO-GO"
        assert ledger["blocking_reasons"]

    def test_every_external_gate_starts_unverified_not_passing(self):
        ledger = gate.build_ledger(SHA_A, {}, min_records=1)
        for name in gate._EXTERNAL_GATES:
            assert _find(ledger, name)["status"] == gate.UNVERIFIED, name

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
        got = gate.check_open_incidents({"rollup": {"open_total": 3, "truncated": False}})
        assert got["status"] == gate.FAIL

    def test_truncated_rollup_cannot_prove_zero(self):
        got = gate.check_open_incidents({"rollup": {"open_total": 0, "truncated": True}})
        assert got["status"] == gate.UNVERIFIED

    def test_zero_open_passes(self):
        got = gate.check_open_incidents({"rollup": {"open_total": 0, "truncated": False}})
        assert got["status"] == gate.PASS

    def test_absent_rollup_is_unverified(self):
        assert gate.check_open_incidents(None)["status"] == gate.UNVERIFIED


class TestFlagParity:
    def test_current_repo_state_is_evaluated(self):
        # Frontend-only flags mean a surface with no server-side gate.
        got = gate.check_flag_parity()
        assert got["status"] in (gate.PASS, gate.FAIL, gate.UNVERIFIED)
        if got["status"] == gate.FAIL:
            assert "frontend-only" in got["detail"]


# ---------------------------------------------------------------------------
# The only path to GO
# ---------------------------------------------------------------------------

class TestGoRequiresEverything:
    def test_full_evidence_at_one_sha_can_reach_go(self, monkeypatch, tmp_path):
        import subprocess
        monkeypatch.setattr(gate, "check_release_sha",
                            lambda sha: gate._gate("release_sha", gate.PASS, "stub"))
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=("" if "status" in cmd else SHA_A) + "\n", stderr=""))
        monkeypatch.setattr(gate, "check_tracking_release_ready",
                            lambda: gate._gate("tracking_release_ready", gate.PASS, "stub"))
        monkeypatch.setattr(gate, "check_truthfulness",
                            lambda: gate._gate("truthfulness", gate.PASS, "stub"))
        monkeypatch.setattr(gate, "check_flag_parity",
                            lambda: gate._gate("flag_parity", gate.PASS, "stub"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["final_decision"] == "GO", ledger["blocking_reasons"]

    def test_removing_any_single_evidence_returns_to_no_go(self, monkeypatch):
        import subprocess
        monkeypatch.setattr(gate, "check_release_sha",
                            lambda sha: gate._gate("release_sha", gate.PASS, "stub"))
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=("" if "status" in cmd else SHA_A) + "\n", stderr=""))
        monkeypatch.setattr(gate, "check_tracking_release_ready",
                            lambda: gate._gate("tracking_release_ready", gate.PASS, "stub"))
        monkeypatch.setattr(gate, "check_truthfulness",
                            lambda: gate._gate("truthfulness", gate.PASS, "stub"))
        monkeypatch.setattr(gate, "check_flag_parity",
                            lambda: gate._gate("flag_parity", gate.PASS, "stub"))
        full = _all_external_pass(SHA_A)
        for dropped in list(full):
            partial = {k: v for k, v in full.items() if k != dropped}
            ledger = gate.build_ledger(SHA_A, partial, min_records=1)
            assert ledger["final_decision"] == "NO-GO", f"dropping {dropped} still GO"
