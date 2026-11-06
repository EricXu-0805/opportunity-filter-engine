"""Application windows read on configured programs' own pages (M05)."""

from __future__ import annotations

import copy
from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from backend import data_loader
from backend.lib.opportunity_detail import build_detail_fields
from backend.lib.public_projection import neutralize_lifecycle_title, project_public_opportunity_payload
from src import evidence
from src.collectors import campus_graph as cg
from src.collectors.schools import SCHOOL_CONFIGS
from src.program_windows import WINDOWS, apply_program_window, reviewed_window

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")


def _schools() -> dict[str, dict]:
    configs = SCHOOL_CONFIGS.values() if isinstance(SCHOOL_CONFIGS, dict) else SCHOOL_CONFIGS
    return {school["school_slug"]: school for school in configs}


def _spec(school_slug: str, key: str) -> tuple[dict, dict, dict]:
    school = _schools()[school_slug]
    for source in school["sources"]:
        for spec in source.get("programs", []):
            if spec["key"] == key:
                return school, source, spec
    raise LookupError((school_slug, key))


def _row(school_slug: str, key: str) -> dict:
    school, source, spec = _spec(school_slug, key)
    return cg._normalize_program(school, source, spec)


@pytest.mark.parametrize(("school", "key"), sorted(WINDOWS))
def test_every_window_is_for_the_page_its_program_is_configured_at(school, key):
    _, _, spec = _spec(school, key)
    assert spec["url"] == WINDOWS[(school, key)].url


@pytest.mark.parametrize(("school", "key"), sorted(WINDOWS))
def test_every_window_quotes_its_closing_date(school, key):
    window = WINDOWS[(school, key)]
    closes = window.closes_on
    written = (f"{_MONTHS[closes.month - 1]} {closes.day}", f"{closes.month}/{closes.day}/{closes.year}")
    assert any(text in window.closes_quote for text in written)


@pytest.mark.parametrize(("school", "key"), sorted(k for k, w in WINDOWS.items() if w.opens_on))
def test_every_stated_opening_is_quoted_with_its_campus_zone(school, key):
    window = WINDOWS[(school, key)]
    opens = window.opens_on
    written = (f"{_MONTHS[opens.month - 1]} {opens.day}", f"{opens.month}/{opens.day}/{opens.year}")
    assert any(text in window.opens_quote for text in written)
    local = window.opens_at.astimezone(ZoneInfo(window.zone))
    assert (local.date(), local.time()) == (opens, time.min)


def test_a_harvested_program_carries_its_pages_stated_close_as_its_deadline():
    row = _row("unl", "unl_summer_research_program")

    assert row["deadline"] == "2027-03-01"
    assert row["deadline_is_estimate"] is False
    assert evidence.stated_listing_deadline(row) == date(2027, 3, 1)


def test_a_stored_row_gets_the_deadline_when_the_corpus_loads():
    stored = _row("northwestern", "nu_tgs_srop")
    stored.update(deadline=None, deadline_is_estimate=None)

    loaded = data_loader._sanitize_opportunity(stored)

    assert loaded["deadline"] == "2027-02-10"
    assert loaded["deadline_is_estimate"] is False


def test_the_program_is_offered_until_its_close_and_closed_after(monkeypatch):
    row = _row("caltech", "wave_fellows")

    monkeypatch.setattr(evidence, "_today", lambda: date(2027, 1, 9))
    assert evidence.target_truth(row).actionable is True
    monkeypatch.setattr(evidence, "_today", lambda: date(2027, 1, 10))
    truth = evidence.target_truth(row)
    assert (truth.actionable, truth.reason_code, truth.evidence_key) == (False, "listing_closed", "deadline")


@pytest.mark.parametrize("change", ["moved", "display_link_moved", "discovered", "other_school", "other_key"])
def test_only_the_reviewed_program_at_its_reviewed_page_gets_the_window(change):
    row = _row("jhu", "summer_pura")
    row.update(deadline=None, deadline_is_estimate=None)
    if change == "moved":
        row["url"] = row["source_url"] = "https://hour.jhu.edu/opportunities/summer-pura-2027/"
    elif change == "display_link_moved":
        row["url"] = "https://hour.jhu.edu/opportunities/summer-pura-2027/"
    elif change == "discovered":
        row["metadata"]["discovered"] = True
    elif change == "other_school":
        row["metadata"]["collector_school"] = "jhu_other"
    else:
        row["metadata"]["collector_key"] = "pura"

    apply_program_window(row)

    assert reviewed_window(row) is None
    assert row["deadline"] is None


def test_a_program_without_a_window_keeps_no_deadline():
    row = _row("jhu", "pura")

    assert row["deadline"] is None
    assert row["is_rolling"] is True


def test_the_detail_page_shows_the_deadline_in_the_pages_words():
    row = _row("caltech", "surf_jpl")

    timing = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]

    assert timing["explicit"]["deadline"] == "2027-02-22"
    assert timing["quotes"]["deadline"] == {
        "text": "SURF@JPL applications are due on February 22.",
        "source_url": "https://sfp.caltech.edu/undergraduate-research/programs/surfjpl/application-information",
        "observed_at": "2026-11-05",
    }


def test_a_deadline_other_than_the_windows_carries_no_quote():
    row = _row("caltech", "surf_jpl")
    payload = {**copy.deepcopy(row), "deadline": "2027-03-01"}

    timing = build_detail_fields(payload, row)["fields"]["timing"]

    assert timing["explicit"]["deadline"] == "2027-03-01"
    assert "deadline" not in timing["quotes"]


def _read_open(school_slug: str, key: str, read_at: str | None) -> dict:
    school, source, spec = _spec(school_slug, key)
    row = cg._normalize_program(school, source, spec, status="open", seed_page_verified=True)
    row["metadata"]["last_verified"] = read_at
    assert row["title"].endswith(" (applications open)")
    return row


@pytest.mark.parametrize(("read_at", "kept"), [
    ("2026-10-23T11:43:39.652921", False),
    # Midnight on November 1 in Chicago, still on daylight time, is 05:00 UTC.
    ("2026-11-01T04:59:59", False),
    ("2026-11-01T05:00:00", True),
    ("2026-11-01T05:00:00+00:00", True),
    ("2026-11-01T00:30:00-05:00", True),
    (None, False),
    ("yesterday", False),
])
def test_an_open_status_read_before_the_stated_opening_does_not_title_the_row(read_at, kept):
    row = _read_open("northwestern", "nu_tgs_srop", read_at)

    assert neutralize_lifecycle_title(row["title"], row).endswith(" (applications open)") is kept


def test_the_card_drops_a_suffix_read_before_the_opening():
    row = _read_open("unl", "unl_summer_research_program", "2026-11-14T12:00:00")

    card = project_public_opportunity_payload({"title": row["title"]}, row)

    assert card["title"] == "Nebraska Summer Research Program (University of Nebraska-Lincoln)"
    assert card["target_truth"]["actionable"] is True


def test_a_window_that_states_no_opening_leaves_the_suffix_alone():
    row = _read_open("caltech", "wave_fellows", "2026-07-18T06:41:25")

    assert neutralize_lifecycle_title(row["title"], row).endswith(" (applications open)")


def test_the_public_payload_carries_the_pages_stated_opening():
    row = _row("unl", "unl_summer_research_program")

    out = project_public_opportunity_payload({"title": row["title"]}, row)

    assert out["application_opens"] == {
        "on": "2026-11-15",
        "at": "2026-11-15T06:00:00+00:00",
        "text": "November 15",
        "quote": "November 15: Online application opens.",
        "source_url": "https://summerprogram.unl.edu/",
    }
    assert out["target_truth"]["actionable"] is True


def test_the_match_card_carries_the_opening():
    from backend.routes.matches import _match_card

    assert _match_card(_row("jhu", "summer_pura"))["application_opens"]["text"] == "11/1/2026"


def test_a_window_that_states_no_opening_serves_none():
    row = _row("caltech", "surf_jpl")

    assert "application_opens" not in project_public_opportunity_payload({"title": row["title"]}, row)


def test_a_payload_cannot_bring_its_own_opening():
    row = _row("jhu", "pura")
    forged = {"on": "2099-01-01", "at": "2099-01-01T05:00:00+00:00", "text": "January 1", "quote": "x",
              "source_url": None}

    assert "application_opens" not in project_public_opportunity_payload(
        {"title": row["title"], "application_opens": forged}, row)


# Read 2026-11-05: the award on each program's overview page, the deadline on
# its application page (the window's sentence).
_CALTECH_PAGE_WORDS = {
    "surf": "$8,354 award for the ten-week period",
    "surf_jpl": "$9,600 award for the ten-week period",
    "wave_fellows": "$8,354 for the ten-week period, plus a on-campus housing supplement of $2,000",
}


@pytest.mark.parametrize("key", sorted(_CALTECH_PAGE_WORDS))
def test_caltechs_summer_programs_give_their_2027_award_and_deadline_in_the_pages_words(key):
    _, _, spec = _spec("caltech", key)

    assert spec["compensation"] == _CALTECH_PAGE_WORDS[key]
    assert spec["deadline_note"] == WINDOWS[("caltech", key)].closes_quote
