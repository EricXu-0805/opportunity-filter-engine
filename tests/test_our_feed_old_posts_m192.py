"""M192: an OUR blog post more than 180 days old is no longer shown as open.

The collector kept every post the feed still listed, and on 2026-11-20 the
feed listed posts back to 2024-11-18, so a position advertised two years
earlier was offered as open.
A post published more than ``POST_LISTED_DAYS`` days before the run is now
delisted, its row and id kept, unless the row's deadline is a date after the
run date. A delisted post the feed still lists stays delisted with the date it
was delisted on.
"""
from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime, time, timedelta
from email.utils import format_datetime

import pytest

from src.collectors import refresh_all, uiuc_our_rss
from tests.test_refresh_all import _stub_with_processed_file

TODAY = date(2026, 11, 20)
RETIREMENT = ("is_active", "deactivated_at", "deactivation_reason")


def _feed(*posts):
    items = "".join(
        f"<item><title>RESEARCH OPPORTUNITY: Sensor Lab {number}</title>"
        f"<link>https://blogs.illinois.edu/view/6204/{number:06d}</link>"
        f"<description>{description}</description>"
        f"<pubDate>{format_datetime(datetime.combine(published, time(12), tzinfo=UTC))}</pubDate></item>"
        for number, (published, description) in enumerate(posts, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>OUR</title>'
        "<link>https://blogs.illinois.edu/</link><description>feed</description>"
        f"{items}</channel></rss>"
    ).encode()


@pytest.fixture
def collect(monkeypatch):
    """The rows the collector makes of a feed of ``(published, description)`` posts."""
    def rows(*posts):
        body = _feed(*posts)
        monkeypatch.setattr(uiuc_our_rss.UIUCOURRSSCollector, "_fetch_feed_bytes", lambda self: body)
        return uiuc_our_rss.fetch_and_normalize()
    return rows


def _post(days_old, deadline=None, *, today=TODAY):
    description = "The lab is hiring undergraduates to build sensors."
    if deadline is not None:
        description += f" Deadline: {deadline:%B} {deadline.day}, {deadline.year}"
    return today - timedelta(days=days_old), description


def _retirement(row):
    return {key: row["metadata"].get(key) for key in RETIREMENT}


def test_a_post_181_days_old_is_delisted_and_keeps_its_row(collect):
    (row,) = rows = collect(_post(181))
    listed = copy.deepcopy(row)
    assert uiuc_our_rss.delist_old_posts(rows, TODAY) == 1
    assert _retirement(row) == {
        "is_active": False, "deactivated_at": "2026-11-20", "deactivation_reason": "old_post"}
    listed["metadata"].update(_retirement(row))
    assert rows == [listed]


def test_a_post_180_days_old_stays_listed(collect):
    (row,) = rows = collect(_post(180))
    listed = copy.deepcopy(row)
    assert uiuc_our_rss.delist_old_posts(rows, TODAY) == 0
    assert row == listed
    assert row["metadata"]["is_active"] is True


def test_a_deadline_after_the_run_date_keeps_an_old_post_listed(collect):
    (row,) = rows = collect(_post(400, TODAY + timedelta(days=1)))
    assert row["deadline"] == "November 21, 2026"
    assert uiuc_our_rss.delist_old_posts(rows, TODAY) == 0
    assert row["metadata"]["is_active"] is True
    assert "deactivation_reason" not in row["metadata"]


@pytest.mark.parametrize("deadline", [TODAY - timedelta(days=1), TODAY, None],
                         ids=["deadline passed", "deadline today", "no deadline"])
def test_any_other_deadline_does_not(collect, deadline):
    (row,) = rows = collect(_post(400, deadline))
    assert uiuc_our_rss.delist_old_posts(rows, TODAY) == 1
    assert _retirement(row) == {
        "is_active": False, "deactivated_at": "2026-11-20", "deactivation_reason": "old_post"}


@pytest.mark.parametrize("posted", [None, ""])
def test_a_row_with_no_posted_date_is_left_as_it_is(collect, posted):
    (row,) = rows = collect(_post(400))
    row["posted_date"] = posted
    stored = copy.deepcopy(row)
    assert uiuc_our_rss.delist_old_posts(rows, TODAY) == 0
    assert row == stored


def test_a_row_already_inactive_and_another_sources_row_are_left_as_they_are(collect):
    flagged, other = rows = collect(_post(400), _post(400))
    flagged["metadata"]["is_active"] = False
    other["source"] = "uiuc_sro"
    stored = copy.deepcopy(rows)
    assert uiuc_our_rss.delist_old_posts(rows, TODAY) == 0
    assert rows == stored


def test_a_delisted_post_the_feed_still_lists_stays_delisted_from_the_first_date(collect, tmp_path):
    stored = collect(_post(181))
    uiuc_our_rss.delist_old_posts(stored, TODAY)
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps(stored))

    next_week = TODAY + timedelta(days=7)
    assert uiuc_our_rss.merge_into_processed(
        collect(_post(181)), filepath=str(path), today=next_week) == (0, 1)
    merged = json.loads(path.read_text())
    assert [_retirement(row) for row in merged] == [_retirement(row) for row in stored]
    assert uiuc_our_rss.delist_old_posts(merged, next_week) == 0
    assert [_retirement(row) for row in merged] == [_retirement(row) for row in stored]


def test_a_delisted_post_that_now_states_a_later_deadline_is_listed_again(collect, tmp_path):
    stored = collect(_post(181))
    uiuc_our_rss.delist_old_posts(stored, TODAY)
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps(stored))

    edited = collect(_post(181, TODAY + timedelta(days=30)))
    uiuc_our_rss.merge_into_processed(edited, filepath=str(path), today=TODAY)
    (merged,) = json.loads(path.read_text())
    assert uiuc_our_rss.delist_old_posts([merged], TODAY) == 0
    assert merged["id"] == stored[0]["id"]
    assert _retirement(merged) == {"is_active": True, "deactivated_at": None, "deactivation_reason": None}


def test_a_uiuc_refresh_delists_the_old_post_once_and_collects_the_new_one(monkeypatch, tmp_path):
    path = _stub_with_processed_file(monkeypatch, tmp_path, [])
    today = datetime.now(UTC).date()
    body = _feed(_post(200, today=today), _post(3, today=today))
    monkeypatch.setattr(uiuc_our_rss.UIUCOURRSSCollector, "_fetch_feed_bytes", lambda self: body)
    monkeypatch.setattr(refresh_all, "fetch_rss", uiuc_our_rss.fetch_and_normalize)
    monkeypatch.setattr(refresh_all, "merge_rss",
                        lambda rows: uiuc_our_rss.merge_into_processed(rows, str(path)))

    def run():
        summary = refresh_all.refresh_all(deep=False, schools={"uiuc"})
        old, new = json.loads(path.read_text())
        return summary["sources"]["uiuc_our_rss"], old, new

    info, old, new = run()
    assert old["metadata"]["is_active"] is False
    assert old["metadata"]["deactivation_reason"] == "old_post"
    assert new["metadata"]["is_active"] is True
    assert (info["fetched"], info["new"], info["delisted_old_posts"]) == (2, 2, 1)

    old["metadata"]["deactivated_at"] = "2026-11-20"
    path.write_text(json.dumps([old, new]))
    info, again, new = run()
    assert again["id"] == old["id"]
    assert _retirement(again) == _retirement(old)
    assert new["metadata"]["is_active"] is True
    assert (info["fetched"], info["updated"], info["delisted_old_posts"]) == (2, 2, 0)
