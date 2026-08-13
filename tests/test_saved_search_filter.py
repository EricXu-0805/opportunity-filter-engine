"""Tests for src.saved_searches.filter — the cron-side filter port.

These tests are the *only* defence against silent drift between the
frontend filter logic (frontend/src/app/results/page.tsx) and the
cron-side Python port. If the frontend gains a new filter dimension and
the port doesn't, saved searches start producing stale match-sets and
the user gets either missing or spurious "new match" notifications —
neither is caught by any other test.

Each filter dimension gets its own class; helper rows are intentionally
small so the asserts read like a truth table.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.saved_searches.filter import (
    days_until,
    filter_opportunities,
    match_filter,
    matching_ids,
)

EMPTY_FILTERS: dict = {
    "paid": "",
    "intl": "",
    "source": "",
    "onCampus": "",
    "deadline": "",
    "minScore": 0,
}


def _opp(**overrides) -> dict:
    base = {
        "id": "opp-1",
        "title": "Software Engineering Intern",
        "organization": "Acme Robotics",
        "department": "ECE",
        "description_clean": "Build computer vision pipelines for autonomous systems.",
        "paid": "yes",
        "on_campus": True,
        "deadline": (date.today() + timedelta(days=5)).isoformat(),
        "source": "uiuc_faculty",
        "keywords": ["machine learning", "robotics"],
        "eligibility": {"international_friendly": "yes"},
    }
    base.update(overrides)
    return base


class TestDaysUntil:
    def test_future_date(self):
        future = (date.today() + timedelta(days=10)).isoformat()
        assert days_until(future) == 10

    def test_today_is_zero(self):
        assert days_until(date.today().isoformat()) == 0

    def test_past_is_negative(self):
        past = (date.today() - timedelta(days=3)).isoformat()
        assert days_until(past) == -3

    def test_none_returns_none(self):
        assert days_until(None) is None
        assert days_until("") is None

    def test_malformed_returns_none(self):
        assert days_until("not-a-date") is None
        assert days_until("2026-13-99") is None

    def test_accepts_extended_iso_date_time(self):
        future = (date.today() + timedelta(days=2)).isoformat()
        assert days_until(f"{future}T12:00:00Z") == 2


class TestMatchFilterPaid:
    def test_empty_passes_everything(self):
        assert match_filter(_opp(paid="yes"), EMPTY_FILTERS) is True
        assert match_filter(_opp(paid="no"), EMPTY_FILTERS) is True
        assert match_filter(_opp(paid="unknown"), EMPTY_FILTERS) is True

    def test_paid_yes_includes_stipend(self):
        f = {**EMPTY_FILTERS, "paid": "yes"}
        assert match_filter(_opp(paid="yes"), f) is True
        assert match_filter(_opp(paid="stipend"), f) is True
        assert match_filter(_opp(paid="no"), f) is False
        assert match_filter(_opp(paid="unknown"), f) is False

    def test_paid_no_includes_unknown_and_missing(self):
        f = {**EMPTY_FILTERS, "paid": "no"}
        assert match_filter(_opp(paid="no"), f) is True
        assert match_filter(_opp(paid="unknown"), f) is True
        assert match_filter(_opp(paid=None), f) is True
        assert match_filter(_opp(paid="yes"), f) is False


class TestMatchFilterIntl:
    def test_intl_yes_requires_friendly(self):
        f = {**EMPTY_FILTERS, "intl": "yes"}
        assert match_filter(_opp(eligibility={"international_friendly": "yes"}), f) is True
        assert match_filter(_opp(eligibility={"international_friendly": "no"}), f) is False
        assert match_filter(_opp(eligibility={}), f) is False

    def test_intl_empty_includes_everyone(self):
        assert match_filter(_opp(eligibility={"international_friendly": "no"}), EMPTY_FILTERS) is True


class TestMatchFilterSource:
    def test_source_exact_match(self):
        f = {**EMPTY_FILTERS, "source": "uiuc_faculty"}
        assert match_filter(_opp(source="uiuc_faculty"), f) is True
        assert match_filter(_opp(source="nsf_reu"), f) is False

    def test_empty_passes_everything(self):
        assert match_filter(_opp(source="nsf_reu"), EMPTY_FILTERS) is True
        assert match_filter(_opp(source=None), EMPTY_FILTERS) is True


class TestMatchFilterOnCampus:
    def test_on_campus_yes(self):
        f = {**EMPTY_FILTERS, "onCampus": "yes"}
        assert match_filter(_opp(on_campus=True), f) is True
        assert match_filter(_opp(on_campus=False), f) is False
        assert match_filter(_opp(on_campus=None), f) is False

    def test_on_campus_no(self):
        f = {**EMPTY_FILTERS, "onCampus": "no"}
        assert match_filter(_opp(on_campus=False), f) is True
        assert match_filter(_opp(on_campus=None), f) is True
        assert match_filter(_opp(on_campus=True), f) is False


class TestMatchFilterDeadline:
    def test_deadline_passed(self):
        f = {**EMPTY_FILTERS, "deadline": "passed"}
        past = (date.today() - timedelta(days=1)).isoformat()
        future = (date.today() + timedelta(days=5)).isoformat()
        assert match_filter(_opp(deadline=past), f) is True
        assert match_filter(_opp(deadline=future), f) is False
        assert match_filter(_opp(deadline=None), f) is False

    def test_deadline_within_7(self):
        f = {**EMPTY_FILTERS, "deadline": "7"}
        soon = (date.today() + timedelta(days=3)).isoformat()
        later = (date.today() + timedelta(days=10)).isoformat()
        past = (date.today() - timedelta(days=1)).isoformat()
        assert match_filter(_opp(deadline=soon), f) is True
        assert match_filter(_opp(deadline=later), f) is False
        assert match_filter(_opp(deadline=past), f) is False
        assert match_filter(_opp(deadline=None), f) is False

    def test_today_counted_as_within_window(self):
        f = {**EMPTY_FILTERS, "deadline": "7"}
        today = date.today().isoformat()
        assert match_filter(_opp(deadline=today), f) is True

    def test_rolling_selects_rolling_records_only(self):
        """The value the digest cron would otherwise wave through.

        'rolling' reads is_rolling, not deadline, so the int(want) fallthrough
        below it raised ValueError and returned True — a saved search for
        "open now" silently matched every record in the corpus, and the digest
        emailed the user the whole database as "new matches".
        """
        f = {**EMPTY_FILTERS, "deadline": "rolling"}
        assert match_filter(_opp(is_rolling=True), f) is True
        assert match_filter(_opp(is_rolling=False), f) is False
        assert match_filter(_opp(), f) is False  # field absent entirely

    def test_rolling_ignores_the_deadline_field(self):
        f = {**EMPTY_FILTERS, "deadline": "rolling"}
        past = (date.today() - timedelta(days=30)).isoformat()
        assert match_filter(_opp(is_rolling=True, deadline=past), f) is True
        assert match_filter(_opp(is_rolling=True, deadline=None), f) is True


class TestMatchFilterCombinations:
    def test_all_filters_must_pass_aand_logic(self):
        f = {**EMPTY_FILTERS, "paid": "yes", "onCampus": "yes", "source": "uiuc_faculty"}
        assert match_filter(_opp(paid="yes", on_campus=True, source="uiuc_faculty"), f) is True
        assert match_filter(_opp(paid="no", on_campus=True, source="uiuc_faculty"), f) is False
        assert match_filter(_opp(paid="yes", on_campus=False, source="uiuc_faculty"), f) is False
        assert match_filter(_opp(paid="yes", on_campus=True, source="nsf_reu"), f) is False

    def test_min_score_is_ignored_even_when_set(self):
        f = {**EMPTY_FILTERS, "minScore": 99}
        assert match_filter(_opp(), f) is True


class TestQuerySearch:
    def test_query_against_title(self):
        results = filter_opportunities([_opp(title="Computer Vision Internship")], EMPTY_FILTERS, "computer vision")
        assert len(results) == 1

    def test_query_against_organization(self):
        results = filter_opportunities([_opp(organization="Acme Robotics")], EMPTY_FILTERS, "robotics")
        assert len(results) == 1

    def test_query_against_keywords(self):
        results = filter_opportunities([_opp(keywords=["machine learning", "nlp"])], EMPTY_FILTERS, "nlp")
        assert len(results) == 1

    def test_query_against_description(self):
        results = filter_opportunities(
            [_opp(description_clean="Build autonomous robotics systems.", description_raw=None)],
            EMPTY_FILTERS,
            "autonomous",
        )
        assert len(results) == 1

    def test_query_falls_back_to_description_raw(self):
        opp = _opp()
        opp["description_clean"] = None
        opp["description_raw"] = "Working with quantum systems."
        assert len(filter_opportunities([opp], EMPTY_FILTERS, "quantum")) == 1

    def test_query_no_match_excludes(self):
        results = filter_opportunities([_opp(title="Software Engineering")], EMPTY_FILTERS, "xenobiology")
        assert results == []

    def test_query_case_insensitive(self):
        results = filter_opportunities([_opp(title="Machine Learning Researcher")], EMPTY_FILTERS, "MACHINE")
        assert len(results) == 1

    def test_empty_query_matches_everything(self):
        results = filter_opportunities([_opp(title="Anything")], EMPTY_FILTERS, "")
        assert len(results) == 1

    def test_query_combines_with_filters(self):
        f = {**EMPTY_FILTERS, "paid": "yes"}
        opps = [
            _opp(id="a", title="ML role", paid="yes"),
            _opp(id="b", title="ML role", paid="no"),
            _opp(id="c", title="Bio role", paid="yes"),
        ]
        ids = matching_ids(opps, f, "ML")
        assert ids == ["a"]


class TestMatchFilterDefensive:
    def test_missing_eligibility_does_not_crash(self):
        opp = _opp()
        del opp["eligibility"]
        assert match_filter(opp, {**EMPTY_FILTERS, "intl": "yes"}) is False

    def test_non_dict_eligibility_does_not_crash(self):
        opp = _opp(eligibility="not a dict")
        assert match_filter(opp, {**EMPTY_FILTERS, "intl": "yes"}) is False

    def test_malformed_deadline_filter_value_passes_safely(self):
        f = {**EMPTY_FILTERS, "deadline": "garbage"}
        assert match_filter(_opp(), f) is True


class TestFilterOpportunities:
    def test_preserves_input_order(self):
        opps = [
            _opp(id="a", paid="yes"),
            _opp(id="b", paid="yes"),
            _opp(id="c", paid="yes"),
        ]
        out = filter_opportunities(opps, {**EMPTY_FILTERS, "paid": "yes"})
        assert [o["id"] for o in out] == ["a", "b", "c"]

    def test_empty_input_returns_empty(self):
        assert filter_opportunities([], EMPTY_FILTERS) == []

    def test_no_filter_matches_passes_through(self):
        opps = [_opp(id="a"), _opp(id="b")]
        out = filter_opportunities(opps, EMPTY_FILTERS)
        assert len(out) == 2


class TestMatchingIds:
    def test_returns_ids_only(self):
        opps = [_opp(id="opp-1"), _opp(id="opp-2")]
        assert matching_ids(opps, EMPTY_FILTERS) == ["opp-1", "opp-2"]

    def test_skips_opps_without_id(self):
        opps = [_opp(id="a"), {**_opp(), "id": None}, _opp(id="c")]
        assert matching_ids(opps, EMPTY_FILTERS) == ["a", "c"]

    def test_coerces_int_ids_to_string(self):
        opps = [_opp(id=42)]
        assert matching_ids(opps, EMPTY_FILTERS) == ["42"]
