"""When each scheduled workflow starts, and why it is not on the hour.

GitHub's documentation for the `schedule` event names the start of every hour
as its high-load time: runs queued then are delayed first, and under enough
load some are dropped. Every cron here used to start at :00. Since
2026-10-02 the 23:00 reminders run has started between 01:38 and 02:48 UTC
the next day (backend/routes/push.py, _reminder_day), and #1045 had to make
the reminder day independent of the start time.

Moving the minute must not move anything else: each job keeps its hour, its
days and its place in the order, and the two gaps the comments give a reason
for (the scan five hours behind the refresh, saved searches thirty minutes
behind reminders) stay what they were.

Its own file rather than a class in test_ops_plumbing.py, for the same reason
as test_refresh_alerting.py: other branches edit TestWorkflowWiring.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Hour, day-of-month, month and day-of-week of every scheduled workflow, as
# they were on the hour. Only the minute may differ.
_KEPT = {
    "refresh-data.yml": "6 * * *",
    "ops-scan.yml": "11 * * *",
    "campus-seed-health.yml": "12 * * 0",
    "snapshot-reminder.yml": "13 * * 1",
    "daily-reminders.yml": "23 * * *",
    "saved-searches-refresh.yml": "23 * * *",
}


def _crons() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        # PyYAML resolves the bare key `on` to the boolean True.
        triggers = doc.get("on") or doc.get(True) or {}
        if isinstance(triggers, dict) and "schedule" in triggers:
            found[path.name] = [entry["cron"] for entry in triggers["schedule"]]
    return found


def _only_cron(name: str) -> tuple[int, int]:
    (cron,) = _crons()[name]
    minute, hour = cron.split()[:2]
    return int(hour), int(minute)


def _minutes_after_midnight(name: str) -> int:
    hour, minute = _only_cron(name)
    return hour * 60 + minute


def test_the_inventory_is_every_scheduled_workflow():
    """A new scheduled workflow has to be added here, and so be given a
    minute, rather than slip past the checks below."""
    assert set(_crons()) == set(_KEPT)


@pytest.mark.parametrize("name", sorted(_KEPT))
def test_no_scheduled_workflow_starts_on_the_hour(name):
    for cron in _crons()[name]:
        minute = cron.split()[0]
        assert minute.isdigit(), f"{name}: minute {minute!r} must be one fixed minute"
        assert int(minute) != 0, f"{name}: '{cron}' starts at the top of the hour"


@pytest.mark.parametrize("name", sorted(_KEPT))
def test_each_workflow_keeps_its_hour_and_days(name):
    for cron in _crons()[name]:
        assert cron.split(maxsplit=1)[1] == _KEPT[name], name


def test_no_two_workflows_share_a_minute():
    minutes = [cron.split()[0] for crons in _crons().values() for cron in crons]
    assert len(minutes) == len(set(minutes)), sorted(minutes)


def test_the_scan_still_starts_at_least_five_hours_after_the_refresh():
    """ops-scan reads the artifact the refresh publishes. 11:00 against 06:00
    was the floor measured on 2026-08-14 (ops-scan.yml); a later refresh
    minute must not eat into it."""
    gap = _minutes_after_midnight("ops-scan.yml") - _minutes_after_midnight("refresh-data.yml")
    assert gap >= 5 * 60, gap


def test_saved_searches_stay_thirty_minutes_after_reminders():
    """So a student due both is not notified twice at once."""
    gap = (_minutes_after_midnight("saved-searches-refresh.yml")
           - _minutes_after_midnight("daily-reminders.yml"))
    assert gap == 30, gap


_CRON_LINE = re.compile(r"-\s*cron:\s*'(\d+) (\d+) [^']*'\s*#\s*(.*)")
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\s*UTC\b")


@pytest.mark.parametrize("name", sorted(_KEPT))
def test_the_comment_beside_a_cron_states_its_time(name):
    """Two of these comments carried a UTC time and a US conversion. A moved
    minute must not leave them describing the old one."""
    text = (_WORKFLOWS / name).read_text(encoding="utf-8")
    for minute, hour, comment in _CRON_LINE.findall(text):
        for stated_hour, stated_minute in _CLOCK.findall(comment):
            assert (int(stated_hour), int(stated_minute)) == (int(hour), int(minute)), (
                f"{name}: the comment says {stated_hour}:{stated_minute} UTC, "
                f"the cron runs at {hour}:{int(minute):02d}")
