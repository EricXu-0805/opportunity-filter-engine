"""W15: the operational plumbing that was silently broken in production.

Three defects this pins, all found by the W15 audit and all invisible from
the code alone — they only showed up by checking what production actually
had on disk:

  * the freshness/"the cron died" detector keyed off a GITIGNORED work file
    that render.yaml never assembles, so it always returned None and could
    never fire;
  * the 7-day data-quality baseline lives on Render's ephemeral disk and
    resets to the committed file on every deploy, so it could pick a
    months-old snapshot and report +340,000% regressions forever;
  * the reminder/digest crons return HTTP 200 with failure counters in the
    body, and the workflows discarded the body — so W14's counters alerted
    nobody.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from backend.routes.admin import (
    _BASELINE_MAX_AGE_DAYS,
    _find_baseline,
    _opportunities_mtime,
)

_REPO = Path(__file__).resolve().parents[1]

_CHECKER = _REPO / "scripts" / "check_cron_response.py"
_spec = importlib.util.spec_from_file_location("check_cron_response", _CHECKER)
_checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checker)


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


class TestFreshnessSource:
    def test_reads_the_committed_snapshot_timestamp(self, tmp_path, monkeypatch):
        # The real repo ships collector_status.json, so the detector must
        # produce a timestamp even though opportunities.json is gitignored
        # and absent in production.
        assert _opportunities_mtime() is not None

    def test_snapshot_timestamp_is_timezone_aware(self):
        # write_status stores a naive UTC string; the health check subtracts
        # it from an aware now() and would raise on a naive value.
        value = _opportunities_mtime()
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None


class TestBaselineStaleness:
    def test_recent_baseline_is_used(self):
        history = [
            {"t": _iso(8), "empty_keywords": 100},
            {"t": _iso(1), "empty_keywords": 110},
        ]
        assert _find_baseline(history, days_ago=7) == history[0]

    def test_fossil_baseline_is_refused(self):
        # The committed admin_history.jsonl is months old and describes a
        # corpus 50x smaller; comparing against it manufactured permanent
        # false alerts.
        history = [
            {"t": _iso(90), "empty_keywords": 17},
            {"t": _iso(0.1), "empty_keywords": 57867},
        ]
        assert _find_baseline(history, days_ago=7) is None

    def test_boundary_is_the_documented_window(self):
        just_inside = [{"t": _iso(_BASELINE_MAX_AGE_DAYS - 1), "x": 1}, {"t": _iso(0), "x": 2}]
        just_outside = [{"t": _iso(_BASELINE_MAX_AGE_DAYS + 1), "x": 1}, {"t": _iso(0), "x": 2}]
        assert _find_baseline(just_inside, days_ago=7) is not None
        assert _find_baseline(just_outside, days_ago=7) is None

    def test_unparseable_timestamps_never_crash(self):
        assert _find_baseline([{"t": "not-a-date"}, {"t": ""}], days_ago=7) is None


class TestCronResponseChecker:
    def _run(self, payload) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_CHECKER)],
            input=json.dumps(payload), capture_output=True, text=True,
        )

    def test_clean_response_passes(self):
        assert self._run({"status": "ok", "sent": 5, "failed": 0}).returncode == 0

    def test_bookkeeping_failure_fails_the_step(self):
        # This is the duplicate-reminder case: delivered, but remind_at never
        # cleared, so the same reminder re-sends tomorrow.
        r = self._run({"status": "ok", "sent": 5, "bookkeeping_failed": 2})
        assert r.returncode == 1
        assert "bookkeeping_failed=2" in r.stdout

    def test_row_errors_fail_the_step(self):
        assert self._run({"status": "ok", "row_errors": 1}).returncode == 1

    def test_unrecorded_incidents_fail_the_step(self):
        # W15: a failure the cron could not push into the operator queue is
        # invisible everywhere else — that is the silence this guards.
        r = self._run({"status": "ok", "sent": 4, "incident_errors": 2})
        assert r.returncode == 1
        assert "incident_errors=2" in r.stdout

    def test_partial_digest_fails_the_step(self):
        r = self._run({"status": "partial", "sent": 1, "errors": ["sid-9: stamp failed"]})
        assert r.returncode == 1
        assert "status=partial" in r.stdout

    def test_skipped_run_is_not_a_failure(self):
        assert self._run({"status": "skipped", "reason": "push env not configured"}).returncode == 0

    def test_non_json_body_warns_but_passes(self):
        r = subprocess.run(
            [sys.executable, str(_CHECKER)],
            input="<html>502</html>", capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "::warning::" in r.stdout

    def test_check_reports_every_signal(self):
        problems = _checker.check(
            {"failed": 3, "row_errors": 1, "status": "partial", "errors": ["a", "b"]}
        )
        assert any("failed=3" in p for p in problems)
        assert any("row_errors=1" in p for p in problems)
        assert "status=partial" in problems


class TestWorkflowWiring:
    def _workflow(self, name: str) -> dict:
        return yaml.safe_load((_REPO / ".github/workflows" / name).read_text())

    def test_cron_workflows_check_their_response_bodies(self):
        for name in ("daily-reminders.yml", "saved-searches-refresh.yml"):
            text = (_REPO / ".github/workflows" / name).read_text()
            assert "check_cron_response.py" in text, name
            # The checker is a repo file: the job must have a working copy.
            job = next(iter(self._workflow(name)["jobs"].values()))
            assert any("checkout" in str(s.get("uses", "")) for s in job["steps"]), name

    def test_refresh_workflow_persists_the_history_ledger(self):
        text = (_REPO / ".github/workflows/refresh-data.yml").read_text()
        # It must survive the rebase (stash+restore) AND be committed —
        # missing either one is why the committed file froze for weeks.
        assert text.count("refresh-collector_history.jsonl") >= 2
        assert "git add data/processed/collector_status_history.jsonl" in text
