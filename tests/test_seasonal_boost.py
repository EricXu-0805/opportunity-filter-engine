"""Tests for the seasonal boost (summer-research lift, Feb-Jul)."""

from __future__ import annotations

from datetime import date

from src.matcher.config import SEASONAL_BOOST_FACTOR
from src.matcher.ranker import _seasonal_multiplier, rank_opportunity

_IN_SEASON = date(2026, 4, 15)     # April — in window
_OFF_SEASON = date(2026, 11, 15)   # November — out of window


def _summer_opp():
    return {
        "id": "s1",
        "opportunity_type": "summer_program",
        "title": "Summer REU",
        "keywords": ["summer research", "machine learning"],
        "eligibility": {"preferred_year": ["sophomore", "junior"], "international_friendly": "yes"},
        "application": {"application_effort": "medium"},
        "description_raw": "Mentored summer research.",
    }


def _profile():
    return {"year": "junior", "seeking_type": ["summer_program"], "resume_ready": True}


class TestSeasonalMultiplier:
    def test_boost_in_season_for_summer_program(self):
        assert _seasonal_multiplier(_summer_opp(), today=_IN_SEASON) == SEASONAL_BOOST_FACTOR

    def test_no_boost_off_season(self):
        assert _seasonal_multiplier(_summer_opp(), today=_OFF_SEASON) == 1.0

    def test_no_boost_for_non_summer_type(self):
        opp = _summer_opp()
        opp["opportunity_type"] = "research"
        assert _seasonal_multiplier(opp, today=_IN_SEASON) == 1.0


class TestSeasonalBoostInRanking:
    def test_in_season_scores_at_least_off_season(self):
        p = _profile()
        opp = _summer_opp()
        hi = rank_opportunity(p, opp, today=_IN_SEASON).final_score
        lo = rank_opportunity(p, opp, today=_OFF_SEASON).final_score
        assert hi >= lo

    def test_boost_capped_at_100(self):
        for r in (rank_opportunity(_profile(), _summer_opp(), today=_IN_SEASON),):
            assert r.final_score <= 100.0

    def test_in_season_adds_reason(self):
        r = rank_opportunity(_profile(), _summer_opp(), today=_IN_SEASON)
        assert any("in season" in reason.lower() for reason in r.reasons_fit)

    def test_non_summer_research_unaffected_by_today(self):
        """A research posting must score identically regardless of date — the
        boost must never perturb non-seasonal records (protects the matcher's
        existing score-stability tests)."""
        p = _profile()
        research = dict(_summer_opp(), opportunity_type="research")
        a = rank_opportunity(p, research, today=_IN_SEASON).final_score
        b = rank_opportunity(p, research, today=_OFF_SEASON).final_score
        assert a == b
