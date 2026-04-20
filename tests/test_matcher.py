"""
Tests for the three-layer matching engine.
Covers: field matching, eligibility/readiness/upside scoring,
        bucket classification, international filtering, sorting, data integrity.

Run with: pytest tests/test_matcher.py -v
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.ranker import (
    rank_opportunity,
    rank_all,
    score_eligibility,
    score_readiness,
    score_upside,
    MatchResult,
    _year_match_score,
    _skill_overlap_score,
    _major_match_score,
    BUCKET_THRESHOLDS,
)


# ── Fixtures ──────────────────────────────────

@pytest.fixture
def sample_profile():
    return {
        "year": "freshman",
        "major": "ECE",
        "secondary_interests": ["CS", "Data Science"],
        "international_student": True,
        "hard_skills": ["Python", "Java", "C++", "pandas"],
        "coursework": ["CS 124", "STAT 107", "ECE 120"],
        "experience_level": "beginner",
        "resume_ready": True,
        "can_cold_email": True,
        "preferences": {
            "min_match_threshold": 0,
            "exclude_citizenship_restricted": True,
        },
    }


@pytest.fixture
def good_match_opportunity():
    return {
        "id": "opp-001",
        "title": "Undergraduate Research Assistant — CV Lab",
        "organization": "University of Illinois",
        "on_campus": True,
        "opportunity_type": "research",
        "paid": "yes",
        "deadline": "2026-04-30",
        "description_raw": "Seeking undergraduate research assistant for computer vision with mentorship and training. Python required.",
        "description_clean": "Seeking undergraduate research assistant for computer vision.",
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior"],
            "majors": ["ECE", "CS"],
            "skills_required": ["Python"],
            "skills_preferred": ["PyTorch"],
            "international_friendly": "yes",
        },
        "application": {
            "contact_method": "email",
            "requires_resume": "yes",
            "requires_cover_letter": "no",
            "application_effort": "low",
        },
    }


@pytest.fixture
def citizenship_restricted_opportunity():
    return {
        "id": "opp-002",
        "title": "NSF REU — National Lab",
        "organization": "National Science Foundation",
        "on_campus": False,
        "paid": "yes",
        "description_raw": "US citizens and permanent residents only.",
        "description_clean": "US citizens and permanent residents only.",
        "eligibility": {
            "preferred_year": ["sophomore", "junior"],
            "majors": ["CS", "Physics"],
            "skills_required": ["Python"],
            "international_friendly": "no",
        },
        "application": {
            "contact_method": "portal",
            "requires_resume": "yes",
            "application_effort": "high",
        },
    }


@pytest.fixture
def sample_opportunities(good_match_opportunity, citizenship_restricted_opportunity):
    return [good_match_opportunity, citizenship_restricted_opportunity]


# ── Unit Tests: Field Matching ────────────────

class TestYearMatching:
    def test_exact_match(self):
        assert _year_match_score("freshman", ["freshman", "sophomore"]) == 100.0

    def test_one_year_off(self):
        assert _year_match_score("freshman", ["sophomore"]) == 50.0

    def test_two_years_off(self):
        assert _year_match_score("freshman", ["junior", "senior"]) == 0.0

    def test_no_requirement(self):
        score = _year_match_score("freshman", [])
        assert score == 40.0  # Unknown = penalized, not neutral

    def test_unknown_requirement(self):
        score = _year_match_score("freshman", ["unknown"])
        assert score == 40.0  # Unknown = penalized, not neutral


class TestSkillOverlap:
    def test_full_match(self):
        assert _skill_overlap_score(["Python", "Java"], ["Python", "Java"]) == 100.0

    def test_partial_match(self):
        score = _skill_overlap_score(["Python"], ["Python", "Java"])
        assert 40 <= score <= 60

    def test_no_match(self):
        assert _skill_overlap_score(["R"], ["Python", "Java"]) == 10.0

    def test_no_requirements(self):
        assert _skill_overlap_score(["Python"], []) == 35.0  # No requirement = penalized

    def test_case_insensitive(self):
        score = _skill_overlap_score(["python", "JAVA"], ["Python", "Java"])
        assert score == 100.0


class TestMajorMatching:
    def test_exact_match(self):
        assert _major_match_score(["ECE"], ["ECE"]) == 100.0

    def test_alias_match(self):
        assert _major_match_score(["Computer Engineering"], ["ECE"]) == 100.0

    def test_related_match(self):
        score = _major_match_score(["ECE"], ["CS"])
        assert 60.0 <= score <= 80.0  # Related

    def test_no_match(self):
        score = _major_match_score(["Biology"], ["CS", "ECE"])
        assert score <= 30.0

    def test_open_requirement(self):
        assert _major_match_score(["ECE"], []) == 30.0  # No requirement = penalized

    def test_cross_domain_mismatch_harder(self):
        # Humanities student ↔ STEM-only opp is worse than same-domain mismatch
        humanities_vs_stem = _major_match_score(["Spanish"], ["CS"])
        same_domain = _major_match_score(["Biology"], ["CS"])
        assert humanities_vs_stem < same_domain
        assert humanities_vs_stem <= 10.0


# ── Unit Tests: Scoring Layers ────────────────

class TestEligibilityScoring:
    def test_good_match(self, sample_profile, good_match_opportunity):
        score, fit, gap = score_eligibility(sample_profile, good_match_opportunity)
        assert score >= 70.0
        assert len(fit) >= 2

    def test_citizenship_blocked(self, sample_profile, citizenship_restricted_opportunity):
        score, fit, gap = score_eligibility(sample_profile, citizenship_restricted_opportunity)
        assert score < 70.0
        assert any("citizenship" in g.lower() or "residency" in g.lower() for g in gap)

    def test_domestic_not_penalized(self, citizenship_restricted_opportunity):
        domestic = {
            "year": "freshman", "major": "CS",
            "secondary_interests": ["ECE"],
            "international_student": False,
            "hard_skills": ["Python"],
            "coursework": ["CS 124"],
        }
        score, _, gap = score_eligibility(domestic, citizenship_restricted_opportunity)
        # Should not have citizenship gap for domestic students
        assert not any("citizenship" in g.lower() for g in gap)

    def test_score_range(self, sample_profile, good_match_opportunity):
        score, _, _ = score_eligibility(sample_profile, good_match_opportunity)
        assert 0 <= score <= 100


class TestReadinessScoring:
    def test_ready_student(self, sample_profile, good_match_opportunity):
        score, fit, gap = score_readiness(sample_profile, good_match_opportunity)
        assert score >= 50.0

    def test_unready_student(self, good_match_opportunity):
        unready = {
            "resume_ready": False,
            "experience_level": "none",
            "coursework": [],
            "can_cold_email": False,
        }
        score, fit, gap = score_readiness(unready, good_match_opportunity)
        assert score < 50.0

    def test_score_range(self, sample_profile, good_match_opportunity):
        score, _, _ = score_readiness(sample_profile, good_match_opportunity)
        assert 0 <= score <= 100


class TestUpsideScoring:
    def test_paid_opportunity(self, sample_profile, good_match_opportunity):
        score, fit, _ = score_upside(sample_profile, good_match_opportunity)
        assert any("paid" in f.lower() for f in fit)

    def test_prestigious_institution(self, sample_profile):
        opp = {
            "id": "caltech-test", "organization": "Caltech",
            "paid": "yes", "on_campus": False,
            "eligibility": {"preferred_year": ["freshman"]},
            "application": {}, "description_raw": "",
        }
        _, fit, _ = score_upside(sample_profile, opp)
        assert any("prestigious" in f.lower() for f in fit)

    def test_score_range(self, sample_profile, good_match_opportunity):
        score, _, _ = score_upside(sample_profile, good_match_opportunity)
        assert 0 <= score <= 100


# ── Integration Tests: Full Ranking ───────────

class TestRankOpportunity:
    def test_returns_match_result(self, sample_profile, good_match_opportunity):
        result = rank_opportunity(sample_profile, good_match_opportunity)
        assert isinstance(result, MatchResult)

    def test_score_is_stretched_weighted_sum(self, sample_profile, good_match_opportunity):
        result = rank_opportunity(sample_profile, good_match_opportunity)
        raw = 0.45 * result.eligibility_score + 0.35 * result.readiness_score + 0.20 * result.upside_score
        assert 0.0 <= result.final_score <= 100.0
        if raw >= 70:
            assert result.final_score >= raw - 0.5
        elif raw <= 45:
            assert result.final_score <= raw + 0.5

    def test_bucket_assigned(self, sample_profile, good_match_opportunity):
        result = rank_opportunity(sample_profile, good_match_opportunity)
        assert result.bucket in ("high_priority", "good_match", "reach", "low_fit")

    def test_has_next_steps(self, sample_profile, good_match_opportunity):
        result = rank_opportunity(sample_profile, good_match_opportunity)
        assert len(result.next_steps) >= 1

    def test_has_explanations(self, sample_profile, good_match_opportunity):
        result = rank_opportunity(sample_profile, good_match_opportunity)
        assert len(result.reasons_fit) > 0


class TestRankAll:
    def test_filters_citizenship_restricted(self, sample_profile, sample_opportunities):
        results = rank_all(sample_profile, sample_opportunities)
        result_ids = {r.opportunity_id for r in results}
        assert "opp-001" in result_ids
        assert "opp-002" not in result_ids

    def test_sorted_descending(self, sample_profile, sample_opportunities):
        sample_profile["preferences"]["exclude_citizenship_restricted"] = False
        results = rank_all(sample_profile, sample_opportunities)
        for i in range(len(results) - 1):
            assert results[i].final_score >= results[i + 1].final_score

    def test_no_filter_for_domestic(self, sample_opportunities):
        domestic = {
            "year": "sophomore", "major": "CS",
            "secondary_interests": [],
            "international_student": False,
            "hard_skills": ["Python"],
            "coursework": [],
            "experience_level": "beginner",
            "resume_ready": True,
            "can_cold_email": False,
            "preferences": {"min_match_threshold": 0, "exclude_citizenship_restricted": True},
        }
        results = rank_all(domestic, sample_opportunities)
        assert len(results) == 2  # Both included for domestic

    def test_min_threshold(self, sample_profile, sample_opportunities):
        sample_profile["preferences"]["min_match_threshold"] = 999
        sample_profile["preferences"]["exclude_citizenship_restricted"] = False
        results = rank_all(sample_profile, sample_opportunities)
        assert len(results) == 0  # Nothing meets 999 threshold


class TestBucketClassification:
    def test_thresholds_descending(self):
        thresholds = [t for t, _ in BUCKET_THRESHOLDS]
        assert thresholds == sorted(thresholds, reverse=True)

    def test_high_priority_for_perfect_match(self, sample_profile, good_match_opportunity):
        result = rank_opportunity(sample_profile, good_match_opportunity)
        assert result.final_score >= 80
        assert result.bucket == "high_priority"


# ── Data Integrity Tests ─────────────────────

class TestDataIntegrity:
    def test_processed_data_schema(self):
        path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")
        if not os.path.exists(path):
            pytest.skip("No processed data file")

        with open(path) as f:
            data = json.load(f)

        assert len(data) > 0, "Processed data is empty"

        for opp in data:
            assert opp.get("id"), f"Missing id: {opp.get('title')}"
            assert opp.get("title"), f"Missing title: {opp.get('id')}"
            assert opp.get("url"), f"Missing url: {opp.get('title')}"
            assert isinstance(opp.get("eligibility"), dict), f"Bad eligibility in: {opp.get('title')}"

    def test_no_duplicate_ids(self):
        path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")
        if not os.path.exists(path):
            pytest.skip("No processed data file")

        with open(path) as f:
            data = json.load(f)

        ids = [opp["id"] for opp in data]
        dupes = [x for x in ids if ids.count(x) > 1]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {set(dupes)}"

    def test_ranker_on_real_data(self, sample_profile):
        """End-to-end test: run ranker on actual processed data."""
        path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")
        if not os.path.exists(path):
            pytest.skip("No processed data file")

        with open(path) as f:
            opps = json.load(f)

        results = rank_all(sample_profile, opps)
        assert len(results) > 0, "Ranker returned no results on real data"

        for r in results:
            assert 0 <= r.final_score <= 100
            assert r.bucket in ("high_priority", "good_match", "reach", "low_fit")
