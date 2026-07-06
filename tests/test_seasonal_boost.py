"""Tests for the seasonal boost (summer-research lift, Feb-Jul).

The lift is gated on a verifiably-open application window: a summer record
with no parseable FUTURE deadline gets a neutral 1.0. 279 dateless summer
records (closed cycles that can never expire) monopolized July top-15s when
the boost applied unconditionally (2026-07 audit).
"""

from __future__ import annotations

from datetime import date

from src.matcher.config import SEASONAL_BOOST_FACTOR
from src.matcher.ranker import _seasonal_multiplier, rank_opportunity

_IN_SEASON = date(2026, 4, 15)     # April — in window
_OFF_SEASON = date(2026, 11, 15)   # November — out of window
# Far future: the seasonal gate compares against the injected `today`, but
# rank_opportunity's deadline-passed penalty reads the wall clock — a
# near-term date would trip that penalty as real time advances.
_OPEN_DEADLINE = "2027-05-31"


def _summer_opp(deadline: str | None = _OPEN_DEADLINE):
    opp = {
        "id": "s1",
        "opportunity_type": "summer_program",
        "title": "Summer REU",
        "keywords": ["summer research", "machine learning"],
        "eligibility": {"preferred_year": ["sophomore", "junior"], "international_friendly": "yes"},
        "application": {"application_effort": "medium"},
        "description_raw": "Mentored summer research.",
    }
    if deadline is not None:
        opp["deadline"] = deadline
    return opp


def _profile():
    return {"year": "junior", "seeking_type": ["summer_program"], "resume_ready": True}


class TestSeasonalMultiplier:
    def test_boost_in_season_with_open_deadline(self):
        assert _seasonal_multiplier(_summer_opp(), today=_IN_SEASON) == SEASONAL_BOOST_FACTOR

    def test_no_boost_off_season(self):
        assert _seasonal_multiplier(_summer_opp("2026-12-31"), today=_OFF_SEASON) == 1.0

    def test_no_boost_for_non_summer_type(self):
        opp = _summer_opp()
        opp["opportunity_type"] = "research"
        assert _seasonal_multiplier(opp, today=_IN_SEASON) == 1.0

    def test_no_boost_without_deadline(self):
        assert _seasonal_multiplier(_summer_opp(deadline=None), today=_IN_SEASON) == 1.0

    def test_no_boost_with_passed_deadline(self):
        assert _seasonal_multiplier(_summer_opp("2026-03-01"), today=_IN_SEASON) == 1.0

    def test_no_boost_with_garbage_deadline(self):
        assert _seasonal_multiplier(_summer_opp("rolling"), today=_IN_SEASON) == 1.0


class TestSeasonalBoostInRanking:
    def test_in_season_scores_at_least_off_season(self):
        p = _profile()
        opp = _summer_opp("2027-01-15")  # open at both compared dates
        hi = rank_opportunity(p, opp, today=_IN_SEASON).final_score
        lo = rank_opportunity(p, opp, today=_OFF_SEASON).final_score
        assert hi >= lo

    def test_dateless_summer_record_not_lifted_over_dated_peer(self):
        p = _profile()
        dated = rank_opportunity(p, _summer_opp(), today=_IN_SEASON).final_score
        dateless = rank_opportunity(p, _summer_opp(deadline=None), today=_IN_SEASON).final_score
        assert dated >= dateless

    def test_boost_capped_at_100(self):
        r = rank_opportunity(_profile(), _summer_opp(), today=_IN_SEASON)
        assert r.final_score <= 100.0

    def test_in_season_adds_reason(self):
        r = rank_opportunity(_profile(), _summer_opp(), today=_IN_SEASON)
        assert any("in season" in reason.lower() for reason in r.reasons_fit)

    def test_dateless_gets_no_in_season_reason(self):
        r = rank_opportunity(_profile(), _summer_opp(deadline=None), today=_IN_SEASON)
        assert not any("in season" in reason.lower() for reason in r.reasons_fit)

    def test_non_summer_research_unaffected_by_today(self):
        """A research posting must score identically regardless of date — the
        boost must never perturb non-seasonal records (protects the matcher's
        existing score-stability tests)."""
        p = _profile()
        research = dict(_summer_opp("2027-01-15"), opportunity_type="research")
        a = rank_opportunity(p, research, today=_IN_SEASON).final_score
        b = rank_opportunity(p, research, today=_OFF_SEASON).final_score
        assert a == b
