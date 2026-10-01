"""The reminder that CMU's project-list snapshot needs a new export.

The list opens only for a CMU login, so nothing in the refresh can notice the
hand-exported snapshot going stale. One definition of "due"
(``cmu_uro_projects.refresh_status``) drives two channels: ops-scan files a
manual_review incident in the operator queue, and the weekly
snapshot-reminder workflow emails the operator — and neither says anything
while the snapshot is current.

Past the end date the rows are retired and nothing on the site is stale, so
the reminder stops asking: the incident is filed once and an operator's
suppression stands, the email goes out once and then at most monthly, and at
no point does the reminder block a release.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.main import app
from scripts import snapshot_reminder
from src.collectors import cmu_uro_projects as uro
from tests.test_ops_incidents import (
    _admin_env,
    _hdr,
    _install_supabase,
    _rpcs,
    _run_scan,
    _scan_env,
    _write_artifacts,
)

REPO = Path(__file__).resolve().parents[1]
URO_PAGE = "https://www.cmu.edu/uro/getting-started-in-research/index.html"
SHEET = "https://docs.google.com/spreadsheets/d/1doUAfTmVYeswzP_yHGnWQM32RKtWp6l8OpRRneghz3k/edit"
END = date(2027, 5, 15)

_spec = importlib.util.spec_from_file_location("release_gate", REPO / "scripts" / "release_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return uro.load_snapshot()


def _snapshot_with(**dates) -> dict:
    data = json.loads(uro.SNAPSHOT_FILE.read_text(encoding="utf-8"))
    data["snapshot"].update({k: v.isoformat() for k, v in dates.items()})
    return data


def _expired(days_ago: int = 3) -> dict:
    """The committed snapshot moved so that its end date was ``days_ago`` days ago."""
    today = datetime.now(UTC).date()
    return _snapshot_with(snapshot_date=today - timedelta(days=240),
                          refresh_due=today - timedelta(days=120),
                          valid_until=today - timedelta(days=days_ago))


def _stored(snap: dict, *, state: str, status: str = "open") -> dict:
    """The reminder incident as ops_incidents holds it after a filing in ``state``."""
    meta = snap["snapshot"]
    return {
        "dedup_key": uro.REMINDER_DEDUP_KEY,
        "status": status,
        "detail": {"state": state, "snapshot_date": meta["snapshot_date"],
                   "refresh_due": meta["refresh_due"], "valid_until": meta["valid_until"]},
    }


class TestRefreshStatus:
    @pytest.mark.parametrize("today, state", [
        (date(2026, 9, 30), "current"),
        (date(2027, 1, 10), "current"),
        (date(2027, 1, 11), "refresh_due"),
        (date(2027, 4, 14), "refresh_due"),
        (date(2027, 4, 15), "expiring"),
        (date(2027, 5, 15), "expiring"),
        (date(2027, 5, 16), "expired"),
    ])
    def test_state_by_date(self, snapshot, today, state):
        status = uro.refresh_status(snapshot, today)
        assert status["state"] == state
        assert status["due"] is (state != "current")

    def test_near_expiry_is_due_even_before_the_refresh_date(self, snapshot):
        early = json.loads(json.dumps(snapshot))
        early["snapshot"].update(refresh_due="2027-05-01", valid_until="2027-05-15")
        assert uro.refresh_status(early, date(2027, 4, 20))["state"] == "expiring"

    def test_the_queue_title_names_the_snapshot_not_its_state(self, snapshot):
        # The incident queue keeps the title an incident was first filed with,
        # so a title naming a state would still say "refresh" after expiry.
        titles = {
            uro.reminder(snapshot, uro.refresh_status(snapshot, day))["title"]
            for day in (date(2027, 1, 11), date(2027, 4, 20), date(2027, 5, 17))
        }
        assert titles == {"CMU research project list snapshot taken 2026-09-14"}

    def test_the_reminder_says_what_where_who_and_how(self, snapshot):
        note = uro.reminder(snapshot, uro.refresh_status(snapshot, date(2027, 1, 11)))
        assert note["priority"] == "normal"
        assert "2026-09-14" in note["subject"] and "2027-01-11" in note["subject"]
        for text in (note["text"], note["summary"]):
            assert "Stephen Huang" in text and "CMU" in text
        assert SHEET in note["text"] and URO_PAGE in note["text"]
        assert "only a CMU Andrew account can open" in note["text"]
        assert "data/snapshots/cmu_uro_projects.json" in note["text"]
        # CSV through the importer, never a PDF typed up by hand.
        steps = note["detail"]["how_to_refresh"]
        assert "as CSV" in steps[1] and "not PDF" in steps[1] and "outside the repository" in steps[1]
        assert "--import-csv" in steps[2]
        expiring = uro.reminder(snapshot, uro.refresh_status(snapshot, date(2027, 5, 1)))
        assert "expires on 2027-05-15" in expiring["subject"]

    @pytest.mark.parametrize("today", [date(2027, 1, 11), date(2027, 5, 1), date(2027, 5, 15),
                                       date(2027, 5, 16), date(2027, 9, 1)])
    def test_the_reminder_is_normal_priority_in_every_state(self, snapshot, today):
        """031's record_ops_incident keeps the priority an incident was first
        filed with, so a reminder first filed high near the end date would
        still be high after it."""
        assert uro.reminder(snapshot, uro.refresh_status(snapshot, today))["priority"] == "normal"

    def test_after_the_end_date_it_says_the_list_expired_and_its_rows_were_retired(self, snapshot):
        note = uro.reminder(snapshot, uro.refresh_status(snapshot, date(2027, 5, 17)))
        assert "expired on 2027-05-15" in note["subject"] and "retired" in note["subject"]
        for text in (note["summary"], note["text"]):
            assert "retired from 2027-05-16 by the daily refresh" in text
        assert "every fifth week" in note["text"]
        assert note["detail"]["state"] == "expired"
        assert note["detail"]["retired_on"] == "2027-05-16"


class TestEmailCadence:
    """When the weekly workflow mails: every week while a refresh is due, once
    after the end date, then never more than once a month."""

    def test_weekly_from_the_refresh_date_to_the_end_date(self, snapshot):
        mondays = [date(2027, 1, 11) + timedelta(weeks=n) for n in range(18)]
        assert mondays[-1] <= END
        assert all(uro.email_due(uro.refresh_status(snapshot, d)) for d in mondays)

    def test_nothing_while_the_snapshot_is_current(self, snapshot):
        assert not uro.email_due(uro.refresh_status(snapshot, date(2027, 1, 4)))

    @pytest.mark.parametrize("offset", range(7))
    def test_after_the_end_date_once_then_at_most_monthly(self, snapshot, offset):
        """Whatever weekday the weekly run falls on relative to the end date."""
        runs = [END + timedelta(days=1 + offset + 7 * n) for n in range(60)]
        sent = [d for d in runs if uro.email_due(uro.refresh_status(snapshot, d))]
        assert sent[0] == runs[0]  # the first run after the end date says so
        gaps = [(later - earlier).days for earlier, later in zip(sent, sent[1:], strict=False)]
        assert gaps, "it never repeats"
        assert min(gaps) >= 31 and max(gaps) <= 35


class TestReminderChecker:
    def test_not_due_writes_due_false_and_no_email(self, tmp_path):
        out, payload = tmp_path / "out", tmp_path / "payload.json"
        code = snapshot_reminder.main(["--today", "2026-12-01", "--github-output", str(out),
                                       "--email-payload", str(payload)])
        assert code == 0
        assert out.read_text() == "due=false\n"
        assert not payload.exists()

    @pytest.mark.parametrize("today", ["2027-01-11", "2027-05-01", "2027-05-17", "2027-06-21"])
    def test_due_writes_the_resend_payload(self, tmp_path, monkeypatch, today):
        monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.org")
        monkeypatch.delenv("RESEND_FROM", raising=False)
        out, payload = tmp_path / "out", tmp_path / "payload.json"
        code = snapshot_reminder.main(["--today", today, "--github-output", str(out),
                                       "--email-payload", str(payload)])
        assert code == 0 and out.read_text() == "due=true\n"
        body = json.loads(payload.read_text())
        assert body["to"] == ["ops@example.org"]
        assert body["from"] == snapshot_reminder.DEFAULT_FROM
        assert "CMU research project list" in body["subject"]
        assert SHEET in body["text"]

    def test_the_first_run_after_the_end_date_says_the_rows_were_retired(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.org")
        payload = tmp_path / "payload.json"
        assert snapshot_reminder.main(["--today", "2027-05-17", "--email-payload", str(payload)]) == 0
        body = json.loads(payload.read_text())
        assert "expired on 2027-05-15" in body["subject"]
        assert "retired from 2027-05-16 by the daily refresh" in body["text"]

    @pytest.mark.parametrize("today", ["2027-05-24", "2027-05-31", "2027-06-07", "2027-06-14"])
    def test_after_the_end_date_the_weeks_between_send_nothing(self, tmp_path, today, capsys):
        out, payload = tmp_path / "out", tmp_path / "payload.json"
        code = snapshot_reminder.main(["--today", today, "--github-output", str(out),
                                       "--email-payload", str(payload)])
        assert code == 0
        assert out.read_text() == "due=false\n"
        assert not payload.exists()
        assert "every fifth week" in capsys.readouterr().out

    def test_an_unreadable_snapshot_fails_the_job(self, tmp_path):
        broken = tmp_path / "snap.json"
        broken.write_text("{not json", encoding="utf-8")
        assert snapshot_reminder.main(["--snapshot", str(broken)]) == 1


class TestOpsScanDetector:
    """The operator queue half of the reminder (manual_review, not an alert)."""

    def _scan(self, monkeypatch, tmp_path, snapshot, stored=(), **stub):
        _scan_env(monkeypatch)
        calls: list = []
        _install_supabase(monkeypatch, open_rows=[], incidents=list(stored), calls=calls, **stub)
        _write_artifacts(monkeypatch, tmp_path, uro_snapshot=snapshot)
        return _run_scan().json(), calls

    @staticmethod
    def _filed(calls) -> list[dict]:
        return [p for p in _rpcs(calls, "record_ops_incident")
                if p["p_dedup_key"] == uro.REMINDER_DEDUP_KEY]

    def test_a_due_snapshot_files_one_manual_review_incident(self, monkeypatch, tmp_path):
        today = datetime.now(UTC).date()
        snap = _snapshot_with(snapshot_date=today - timedelta(days=150),
                              refresh_due=today - timedelta(days=1),
                              valid_until=today + timedelta(days=120))
        body, calls = self._scan(monkeypatch, tmp_path, snap)
        assert body["detectors"]["snapshot_refresh"]["state"] == "refresh_due"
        (incident,) = self._filed(calls)
        assert incident["p_kind"] == "manual_review"
        assert incident["p_priority"] == "normal"
        assert incident["p_scope"] == "cmu_uro_projects"
        assert "CMU research project list" in incident["p_title"]
        assert "Stephen Huang" in incident["p_summary"]
        detail = incident["p_detail"]
        assert detail["contributor"] == "Stephen Huang"
        assert detail["source_sheet_url"] == SHEET
        assert any("Download the Projects List tab" in step for step in detail["how_to_refresh"])

    def test_before_the_end_date_it_is_re_sighted_every_day(self, monkeypatch, tmp_path):
        today = datetime.now(UTC).date()
        snap = _snapshot_with(snapshot_date=today - timedelta(days=150),
                              refresh_due=today - timedelta(days=20),
                              valid_until=today + timedelta(days=100))
        _body, calls = self._scan(monkeypatch, tmp_path, snap,
                                  stored=[_stored(snap, state="refresh_due")])
        assert len(self._filed(calls)) == 1

    def test_nearing_its_end_is_still_normal_priority(self, monkeypatch, tmp_path):
        today = datetime.now(UTC).date()
        snap = _snapshot_with(snapshot_date=today - timedelta(days=200),
                              refresh_due=today - timedelta(days=60),
                              valid_until=today + timedelta(days=10))
        _body, calls = self._scan(monkeypatch, tmp_path, snap)
        (incident,) = self._filed(calls)
        assert incident["p_detail"]["state"] == "expiring"
        assert incident["p_priority"] == "normal"

    def test_past_the_end_date_it_is_filed_once_at_normal_priority(self, monkeypatch, tmp_path):
        snap = _expired()
        body, calls = self._scan(monkeypatch, tmp_path, snap,
                                 stored=[_stored(snap, state="expiring")])
        (incident,) = self._filed(calls)
        assert incident["p_priority"] == "normal"
        assert incident["p_detail"]["state"] == "expired"
        assert "retired" in incident["p_summary"]
        assert body["detectors"]["snapshot_refresh"]["incident"] == "filed"

    @pytest.mark.parametrize("status", ["open", "acknowledged", "investigating", "resolved"])
    def test_past_the_end_date_it_is_not_refiled_daily(self, monkeypatch, tmp_path, status):
        snap = _expired(days_ago=9)
        body, calls = self._scan(monkeypatch, tmp_path, snap,
                                 stored=[_stored(snap, state="expired", status=status)])
        assert self._filed(calls) == []
        assert _rpcs(calls, "record_ops_recovery") == []
        assert body["detectors"]["snapshot_refresh"]["incident"] == "already_filed"

    @pytest.mark.parametrize("state", ["refresh_due", "expiring", "expired"])
    def test_past_the_end_date_a_suppression_stands(self, monkeypatch, tmp_path, state):
        """031's RPC reopens a suppressed incident it is asked to record, so
        the detector must not ask while the snapshot is the same one."""
        snap = _expired()
        body, calls = self._scan(monkeypatch, tmp_path, snap,
                                 stored=[_stored(snap, state=state, status="suppressed")])
        assert self._filed(calls) == []
        assert body["detectors"]["snapshot_refresh"]["incident"] == "suppressed"

    def test_a_different_snapshot_files_again_even_over_a_suppression(self, monkeypatch, tmp_path):
        snap = _expired()
        older = _stored(snap, state="expired", status="suppressed")
        older["detail"]["snapshot_date"] = "2025-09-10"
        _body, calls = self._scan(monkeypatch, tmp_path, snap, stored=[older])
        (incident,) = self._filed(calls)
        assert incident["p_detail"]["snapshot_date"] == snap["snapshot"]["snapshot_date"]

    def test_past_the_end_date_an_unreadable_queue_files_nothing(self, monkeypatch, tmp_path):
        """Without the stored status the detector cannot tell a suppression
        from nothing at all, and filing would reopen a suppression."""
        body, calls = self._scan(monkeypatch, tmp_path, _expired(), lookup_fails=True)
        assert self._filed(calls) == []
        assert body["detectors"]["snapshot_refresh"]["incident"] == "lookup_failed"
        assert any(e.get("dedup_key") == uro.REMINDER_DEDUP_KEY for e in body["errors"])

    def test_a_current_snapshot_files_nothing(self, monkeypatch, tmp_path):
        today = datetime.now(UTC).date()
        snap = _snapshot_with(snapshot_date=today, refresh_due=today + timedelta(days=90),
                              valid_until=today + timedelta(days=200))
        body, calls = self._scan(monkeypatch, tmp_path, snap)
        assert body["detectors"]["snapshot_refresh"]["due"] is False
        assert _rpcs(calls, "record_ops_incident") == []
        assert _rpcs(calls, "record_ops_recovery") == []

    def test_a_refreshed_snapshot_closes_the_open_reminder(self, monkeypatch, tmp_path):
        today = datetime.now(UTC).date()
        snap = _snapshot_with(snapshot_date=today, refresh_due=today + timedelta(days=90),
                              valid_until=today + timedelta(days=200))
        old = _stored(_expired(), state="expired")
        _body, calls = self._scan(monkeypatch, tmp_path, snap, stored=[old])
        (recovery,) = _rpcs(calls, "record_ops_recovery")
        assert recovery["p_dedup_key"] == uro.REMINDER_DEDUP_KEY
        assert recovery["p_auto_resolve"] is True

    def test_a_refreshed_snapshot_leaves_a_suppressed_reminder_alone(self, monkeypatch, tmp_path):
        today = datetime.now(UTC).date()
        snap = _snapshot_with(snapshot_date=today, refresh_due=today + timedelta(days=90),
                              valid_until=today + timedelta(days=200))
        old = _stored(_expired(), state="expired", status="suppressed")
        _body, calls = self._scan(monkeypatch, tmp_path, snap, stored=[old])
        assert _rpcs(calls, "record_ops_recovery") == []
        assert self._filed(calls) == []

    def test_a_missing_snapshot_is_reported_skipped(self, monkeypatch, tmp_path):
        body, calls = self._scan(monkeypatch, tmp_path, None)
        assert {"detector": "snapshot_refresh", "reason": "snapshot not present"} in body["skipped"]


class TestReleaseGate:
    """An open reminder is counted in the queue but never blocks a release."""

    client = TestClient(app)

    def _rollup(self, monkeypatch, open_rows) -> dict:
        _admin_env(monkeypatch)
        _install_supabase(monkeypatch, open_rows=open_rows)
        r = self.client.get("/api/admin/ops/incidents", headers=_hdr(),
                            params={"unresolved_only": "true"})
        assert r.status_code == 200
        return r.json()["rollup"]

    def _gate(self, rollup) -> dict:
        return gate.check_open_incidents({"observed_at": datetime.now(UTC).isoformat(),
                                          "rollup": rollup})

    def test_an_open_reminder_alone_passes_the_gate(self, monkeypatch):
        rollup = self._rollup(monkeypatch, [
            {"kind": "manual_review", "priority": "normal", "dedup_key": uro.REMINDER_DEDUP_KEY},
        ])
        assert rollup["open_total"] == 1 and rollup["open_by_kind"]["manual_review"] == 1
        assert rollup["release_blocking_total"] == 0
        got = self._gate(rollup)
        assert got["status"] == gate.PASS
        assert "1 snapshot reminder" in got["detail"]

    def test_every_other_open_incident_still_blocks(self, monkeypatch):
        rollup = self._rollup(monkeypatch, [
            {"kind": "manual_review", "priority": "normal", "dedup_key": uro.REMINDER_DEDUP_KEY},
            {"kind": "manual_review", "priority": "normal", "dedup_key": "manual_review:publication:x"},
            {"kind": "collector_failure", "priority": "high", "dedup_key": "collector_failure:cmu_faculty"},
        ])
        assert (rollup["open_total"], rollup["release_blocking_total"]) == (3, 2)
        got = self._gate(rollup)
        assert got["status"] == gate.FAIL
        assert got["detail"].startswith("2 unresolved incident(s)")


class TestWorkflow:
    def test_the_weekly_workflow_emails_only_when_due(self):
        doc = yaml.safe_load((REPO / ".github/workflows/snapshot-reminder.yml").read_text(encoding="utf-8"))
        assert "schedule" in (doc.get("on") or doc.get(True))
        steps = doc["jobs"]["check"]["steps"]
        check = next(s for s in steps if "snapshot_reminder.py" in str(s.get("run", "")))
        send = next(s for s in steps if "--data @" in str(s.get("run", "")))
        assert send["if"] == f"steps.{check['id']}.outputs.due == 'true'"
        assert "api.resend.com/emails" in send["run"] and "OPERATOR_EMAIL" in send["run"]
        # Nothing but the failure alert and the due-gated send ever mails.
        mailers = [s for s in steps if "api.resend.com" in str(s.get("run", ""))]
        assert {s.get("if") for s in mailers} == {send["if"], "failure() || cancelled()"}
