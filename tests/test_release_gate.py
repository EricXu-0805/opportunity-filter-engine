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
    monkeypatch.setattr(gate, "check_freshness",
                        lambda: gate._gate("freshness", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_truthfulness",
                        lambda: gate._gate("truthfulness", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_flag_parity",
                        lambda: gate._gate("flag_parity", gate.PASS, "stub"))
    monkeypatch.setattr(gate, "check_ledger_currency",
                        lambda s: gate._gate("ledger_currency", gate.PASS, "stub"))
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
            lambda s: gate._gate("ledger_currency", gate.FAIL, "stale",
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
        got = gate.check_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "below_threshold"
        assert got["evidence"]["freshness_threshold"] == 95.0

    def test_at_the_approved_floor_can_pass(self, monkeypatch, tmp_path):
        _write_release_block(tmp_path, monkeypatch, _freshness_block(95, 100))
        got = gate.check_freshness()
        assert got["status"] == gate.PASS
        assert got["evidence"]["freshness_percent"] == 95.0

    def test_one_fully_stale_school_blocks_a_passing_percentage(
            self, monkeypatch, tmp_path):
        """A school-wide outage averages away against enough fresh siblings."""
        _write_release_block(tmp_path, monkeypatch, _freshness_block(
            99, 100, fully_stale_school_count=1, fully_stale_schools=["caltech"]))
        got = gate.check_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "fully_stale_schools"

    def test_shrinking_the_denominator_is_refused(self, monkeypatch, tmp_path):
        """Counting only the already-tracked subset is not a freshness gain."""
        _write_release_block(tmp_path, monkeypatch, _freshness_block(
            100, 100, expected_profile_count=129060))
        got = gate.check_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "denominator_shrunk"

    def test_a_hand_edited_percentage_is_refused(self, monkeypatch, tmp_path):
        """The percent is recomputed from the counts, never trusted."""
        _write_release_block(tmp_path, monkeypatch,
                             _freshness_block(34, 100, freshness_pct=99.9))
        got = gate.check_freshness()
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
        assert gate.check_freshness()["status"] == gate.FAIL

        after = _freshness_block(34, 100)  # computed_at is now
        _write_release_block(tmp_path, monkeypatch, after)
        got = gate.check_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "below_threshold"
        assert got["evidence"]["freshness_percent"] == 34.0

    def test_an_empty_denominator_is_never_vacuously_fresh(
            self, monkeypatch, tmp_path):
        _write_release_block(tmp_path, monkeypatch, _freshness_block(0, 0))
        got = gate.check_freshness()
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "denominator_absent"

    def test_a_reading_past_its_ttl_is_stale_not_fresh(self, monkeypatch, tmp_path):
        old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        _write_release_block(tmp_path, monkeypatch,
                             _freshness_block(99, 100, computed_at=old))
        got = gate.check_freshness()
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
        failing = gate._gate("freshness", gate.FAIL, "34.14% below 95.0%",
                             {"freshness_percent": 34.14})
        got = gate.apply_applicability(failing, {"professor_signals": False})
        assert got["evidence"]["would_be"]["status"] == gate.FAIL
        assert got["evidence"]["would_be"]["evidence"]["freshness_percent"] == 34.14

    def test_a_disabled_feature_is_never_relabelled_pass(self):
        failing = gate._gate("freshness", gate.FAIL, "below floor")
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

    def test_absent_provider_evidence_is_unverified(self):
        assert gate.check_providers(None, {})["status"] == gate.UNVERIFIED


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
    def test_a_never_performed_drill_blocks(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "_REPO", tmp_path)
        got = gate.check_restore_drill()
        assert got["status"] == gate.UNVERIFIED
        assert got["reason"] == "drill_never_performed"
        assert got["release_blocking"] is True

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
        assert ledger["restore_drill_status"] == gate.UNVERIFIED

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
            gate, "check_freshness",
            lambda: gate._gate("freshness", gate.FAIL, "34.14% below 95.0%"))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        entry = next(e for e in ledger["not_applicable_gates"]
                     if e["gate"] == "freshness")
        assert entry["reason"] == "feature_flag_disabled"

    def test_freshness_is_reported_even_when_it_does_not_gate(self, monkeypatch):
        """"Not applicable" is about the surface, not a reason to stop measuring."""
        _stub_repo_gates(monkeypatch, SHA_A)
        monkeypatch.setattr(
            gate, "check_freshness",
            lambda: gate._gate("freshness", gate.FAIL, "below floor",
                               {"freshness_percent": 34.8,
                                "freshness_threshold": 95.0,
                                "fully_stale_school_count": 39}))
        ledger = gate.build_ledger(SHA_A, _all_external_pass(SHA_A), min_records=1)
        assert ledger["freshness_percent"] == 34.8
        assert ledger["freshness_threshold"] == 95.0
        assert ledger["fully_stale_school_count"] == 39

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
