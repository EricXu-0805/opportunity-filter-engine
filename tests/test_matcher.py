"""
Tests for the three-layer matching engine.
Covers: field matching, eligibility/readiness/upside scoring,
        bucket classification, international filtering, sorting, data integrity.

Run with: pytest tests/test_matcher.py -v
"""

import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.config import TOPIC_MISMATCH_PENALTY, TOPIC_UNKNOWN_PENALTY
from src.matcher.ranker import (
    BUCKET_THRESHOLDS,
    MatchResult,
    _is_undergrad,
    _major_match_score,
    _normalize_type_key,
    _requires_graduate_standing,
    _skill_overlap_score,
    _summarize_research,
    _topic_alignment_penalty,
    _topical_keywords,
    _type_preference_score,
    _year_match_score,
    rank_all,
    rank_opportunity,
    score_eligibility,
    score_readiness,
    score_upside,
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
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
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


class TestTypePreferenceNormalisation:
    """R69-D: _type_preference_score normalises inputs so case / space /
    hyphen drift from non-form callers (share URLs, admin debug, future
    API integrations) doesn't silently land in the 30.0 fallback and
    produce a false 'not your primary target type' concern downstream."""

    def test_normalize_lowercase(self):
        assert _normalize_type_key("research") == "research"

    def test_normalize_capitalised(self):
        assert _normalize_type_key("Research") == "research"

    def test_normalize_uppercase_with_spaces(self):
        assert _normalize_type_key("Summer Program") == "summer_program"

    def test_normalize_hyphens_become_underscores(self):
        assert _normalize_type_key("summer-program") == "summer_program"

    def test_normalize_strips_surrounding_whitespace(self):
        assert _normalize_type_key("  Internship  ") == "internship"

    def test_empty_seeking_types_returns_neutral_60(self):
        assert _type_preference_score([], "research") == 60.0

    def test_whitespace_only_entries_filtered_out(self):
        # An empty string in the list should not be treated as a real
        # preference; result mirrors the no-preference path.
        assert _type_preference_score([""], "research") == 60.0

    def test_exact_lowercase_match(self):
        assert _type_preference_score(["research"], "research") == 100.0

    def test_capitalised_seeking_matches_canonical_opp(self):
        # Pre-R69-D this returned 30.0 ('Research' != 'research') and
        # triggered the false 'not your primary target type' concern.
        assert _type_preference_score(["Research"], "research") == 100.0

    def test_space_form_matches_underscore_form(self):
        # The frontend home form stores 'summer_program' but other
        # callers may pass 'Summer program' (display label) — both
        # should land on an exact match against an opp typed
        # 'summer_program'.
        assert _type_preference_score(["Summer program"], "summer_program") == 100.0

    def test_affinity_score_survives_normalisation(self):
        # 'Research' user seeking 'summer_program' opp → affinity 70.0
        # via the (research, summer_program) entry; both inputs are
        # case/format normalised before the affinity lookup.
        assert _type_preference_score(["Research"], "Summer Program") == 70.0

    def test_genuinely_unrelated_still_returns_30(self):
        # Normalisation cannot turn an unrelated pair into a match — the
        # 30.0 floor still applies for off-affinity combinations.
        assert _type_preference_score(["fellowship"], "internship") == 30.0

    def test_mixed_list_picks_best_affinity(self):
        # Multiple seeking entries: an exact match anywhere in the list
        # should win over an unrelated entry.
        assert _type_preference_score(["Fellowship", "Research"], "research") == 100.0


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


class TestGraduateLevelGating:
    def test_detects_graduate_level_titles(self):
        for title in [
            "PhD Autonomy Engineer Intern - Deep Learning",
            "Machine Learning PhD Intern",
            "Research Scientist Intern - Ph.D",
            "ML Technology Intern, Graduate Students",
            "Doctoral Research Assistant",
            "Postdoctoral Researcher",
        ]:
            assert _requires_graduate_standing({"title": title}), title

    def test_detects_masters_and_mba_titles(self):
        # DQ-5: master's / MBA roles are grad-level for an undergrad audience.
        for title in [
            "MBA Intern - Product Manager",
            "Software Engineering Masters Intern",
            "Analog IC R&D Intern - Master's Degree",
        ]:
            assert _requires_graduate_standing({"title": title}), title

    def test_does_not_flag_undergraduate_titles(self):
        for title in [
            "Undergraduate Research Assistant",
            "UR2PhD (CS 397)",
            "Computer Vision Intern",
            "Research with Prof. David Forsyth — CS",
            "Summer Undergraduate Research Fellowship",
            "Master Electrician Apprentice",  # "Master" without 's must NOT match
            "New Graduate Software Engineer",  # entry-level scheme, NOT grad-level
        ]:
            assert not _requires_graduate_standing({"title": title}), title

    def test_detects_graduate_requirement_in_description(self):
        opp = {"title": "Research Intern", "description_clean": "Must be a PhD candidate."}
        assert _requires_graduate_standing(opp)

    def test_phd_application_prep_description_is_not_flagged(self):
        opp = {
            "title": "Research Prep Seminar",
            "description_clean": "Prepares undergraduates for PhD applications.",
        }
        assert not _requires_graduate_standing(opp)

    def test_is_undergrad(self):
        assert _is_undergrad({"year": "sophomore"})
        assert _is_undergrad({"year": ""})
        assert not _is_undergrad({"year": "phd"})
        assert not _is_undergrad({"year": "graduate"})

    def test_graduate_role_is_penalized_for_undergrad(self, sample_profile, good_match_opportunity):
        undergrad_result = rank_opportunity(sample_profile, good_match_opportunity)
        grad_opp = dict(good_match_opportunity)
        grad_opp["title"] = good_match_opportunity["title"] + " (PhD Intern)"
        grad_result = rank_opportunity(sample_profile, grad_opp)
        assert grad_result.final_score < undergrad_result.final_score
        assert any("graduate" in g.lower() for g in grad_result.reasons_gap)


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


class TestHighPriorityBucketing:
    """RANK-6: high_priority is a focused, quality-gated shortlist (top-N that
    clear OFE_BUCKET_HIGH), normalized across profiles — not a flat absolute floor
    that yields 5 for one student and 80 for another."""

    def _opps(self):
        path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")
        if not os.path.exists(path):
            pytest.skip("No processed data file")
        with open(path) as f:
            return json.load(f)

    def test_high_priority_quality_gated_and_bounded(self):
        from src.matcher.config import BUCKET_THRESHOLDS
        floor_high = float(BUCKET_THRESHOLDS[0][0])
        opps = self._opps()
        prof = {
            "year": "sophomore", "major": "CS",
            "research_interests_text": "machine learning, computer vision",
            "seeking_type": ["research"],
            "hard_skills": [{"name": "Python", "level": "experienced"}],
            "coursework": ["CS225"], "experience_level": "some",
        }
        results = rank_all(prof, opps)
        hp = [r for r in results if r.bucket == "high_priority"]
        good = [r for r in results if r.bucket == "good_match"]
        # Every high_priority result clears the quality floor.
        assert all(r.final_score >= floor_high for r in hp)
        # It's a focused shortlist (not the bulk of results) and not empty for a
        # strong-interest profile.
        assert 0 < len(hp) <= 100
        assert len(hp) < len(good)

    def test_sparse_profile_high_priority_still_quality_gated(self):
        from src.matcher.config import BUCKET_THRESHOLDS
        floor_high = float(BUCKET_THRESHOLDS[0][0])
        opps = self._opps()
        prof = {"year": "freshman", "major": "ECE", "research_interests_text": "",
                "seeking_type": [], "experience_level": "none"}
        hp = [r for r in rank_all(prof, opps) if r.bucket == "high_priority"]
        # A sparse profile must never get a high_priority below the quality floor
        # (an honest empty top bucket is acceptable).
        assert all(r.final_score >= floor_high for r in hp)


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


class TestSimilarityScaleRANK5:
    """RANK-5: the similarity→keyword_score multiplier is backend-aware so the
    embedding path isn't saturated at sim≈0.21, without changing the TF-IDF path."""

    def test_scale_switches_on_embedding_provider(self, monkeypatch):
        from src.matcher.config import SIMILARITY_SCALE_EMBEDDING, SIMILARITY_SCALE_TFIDF
        from src.matcher.ranker import _similarity_score_scale
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert _similarity_score_scale() == SIMILARITY_SCALE_TFIDF
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert _similarity_score_scale() == SIMILARITY_SCALE_EMBEDDING

    def test_embedding_scale_stays_discriminative(self):
        from src.matcher.config import SIMILARITY_SCALE_EMBEDDING
        # The saturation point (15 + sim*scale == 100) must sit well above the old
        # 0.21, so embedding cosines in the ~0.35-0.75 band aren't flattened to 100.
        assert (100.0 - 15.0) / SIMILARITY_SCALE_EMBEDDING > 0.5

    def test_tfidf_scale_unchanged(self):
        from src.matcher.config import SIMILARITY_SCALE_TFIDF
        assert SIMILARITY_SCALE_TFIDF == 400.0  # offline default path untouched


class TestTopicAlignmentPenalty:
    INTEREST = "machine learning, computer vision, deep learning"

    def _research(self, keywords):
        return {"opportunity_type": "research", "keywords": keywords}

    def _profile(self, interest=INTEREST):
        return {"research_interests_text": interest}

    def test_aligned_keyword_no_penalty(self):
        opp = self._research(["computer vision", "robotics"])
        assert _topic_alignment_penalty(self._profile(), opp) == 1.0

    def test_confirmed_mismatch_penalized(self):
        opp = self._research(["computers and education", "computer science"])
        assert _topic_alignment_penalty(self._profile(), opp) == TOPIC_MISMATCH_PENALTY

    def test_broad_field_only_is_unknown(self):
        opp = self._research(["computer science"])
        assert _topic_alignment_penalty(self._profile(), opp) == TOPIC_UNKNOWN_PENALTY

    def test_unknown_penalty_defaults_to_no_op(self):
        # RANK-1: an unenriched (broad-field-only) lab is a data gap, not a
        # mismatch, so the unknown case must not demote (default 1.0).
        assert TOPIC_UNKNOWN_PENALTY == 1.0
        opp = self._research(["physics"])
        assert _topic_alignment_penalty(self._profile(), opp) == 1.0

    def test_non_research_never_penalized(self):
        opp = {"opportunity_type": "internship", "keywords": ["computers and education"]}
        assert _topic_alignment_penalty(self._profile(), opp) == 1.0

    def test_no_interest_text_is_inert(self):
        opp = self._research(["computers and education"])
        assert _topic_alignment_penalty(self._profile(interest=""), opp) == 1.0

    def test_token_substring_does_not_falsely_align(self):
        # "computer" (from the interest) must NOT match "computers and education"
        opp = self._research(["computers and education"])
        assert _topic_alignment_penalty(self._profile(), opp) == TOPIC_MISMATCH_PENALTY

    # RANK-2: short acronym interests must align with the area the student wants,
    # in both directions (acronym keyword vs acronym/full-phrase interest).
    def test_acronym_keyword_aligns_with_acronym_interest(self):
        opp = self._research(["nlp", "dialogue systems"])
        assert _topic_alignment_penalty(self._profile(interest="nlp and robotics"), opp) == 1.0

    def test_acronym_interest_aligns_with_full_phrase_keyword(self):
        opp = self._research(["natural language processing"])
        assert _topic_alignment_penalty(self._profile(interest="nlp and reinforcement"), opp) == 1.0

    def test_full_phrase_interest_aligns_with_acronym_keyword(self):
        opp = self._research(["cv"])
        prof = self._profile(interest="computer vision and robotics")
        assert _topic_alignment_penalty(prof, opp) == 1.0


class TestTopicAlignmentRankingRegression:
    """Golden regression: the topic penalty must move final_score in the right
    direction — an aligned research posting ranks above a confirmed mismatch,
    while an unenriched (broad-field-only) posting is NOT demoted like a
    mismatch (RANK-1)."""

    INTEREST = "machine learning and computer vision"

    def _profile(self):
        return {
            "year": "sophomore", "major": "CS",
            "research_interests_text": self.INTEREST,
            "seeking_type": ["research"],
        }

    def _opp(self, oid, keywords):
        return {
            "id": oid, "opportunity_type": "research",
            "title": "Undergraduate Research Position",
            "keywords": keywords, "eligibility": {}, "application": {},
        }

    def test_aligned_outranks_confirmed_mismatch(self):
        prof = self._profile()
        aligned = rank_opportunity(prof, self._opp("a", ["computer vision", "robotics"]))
        mismatch = rank_opportunity(prof, self._opp("m", ["medieval history", "poetry"]))
        assert aligned.final_score > mismatch.final_score

    def test_unknown_lab_not_demoted_like_mismatch(self):
        # The unenriched (broad-field) lab must score strictly above a confirmed
        # topic mismatch: a missing keyword is a data gap, not poor fit.
        prof = self._profile()
        unknown = rank_opportunity(prof, self._opp("u", ["physics"]))
        mismatch = rank_opportunity(prof, self._opp("m", ["medieval history", "poetry"]))
        assert unknown.final_score > mismatch.final_score
        assert "Research area looks different from your stated interests" not in unknown.reasons_gap


class TestInternationalUnknownChip:
    """DQ-6: the 'unknown international eligibility' chip is softened for
    internships (most allow CPT/OPT) but kept as a plain verify for research."""

    def _opp(self, otype):
        return {"opportunity_type": otype, "eligibility": {"international_friendly": "unknown"}}

    def test_internship_unknown_mentions_cpt_opt(self):
        _, _fit, gap = score_eligibility({"international_student": True}, self._opp("internship"))
        assert any("CPT/OPT" in g for g in gap)

    def test_research_unknown_keeps_plain_verify(self):
        _, _fit, gap = score_eligibility({"international_student": True}, self._opp("research"))
        assert any("verify before applying" in g for g in gap)
        assert not any("CPT/OPT" in g for g in gap)


class TestMajorFitSingleCount:
    """RANK-3: major fit is weighted once (inside score_eligibility). A
    cross-domain mismatch is still clearly demoted, but the signal is not
    double-counted via a separate raw multiplier."""

    def _cs_only_opp(self):
        return {
            "id": "cs", "opportunity_type": "research", "title": "CS Research",
            "keywords": ["computer vision"],
            "eligibility": {"majors": ["CS"]}, "application": {},
        }

    def test_matching_major_outranks_cross_domain_mismatch(self):
        opp = self._cs_only_opp()
        cs = {"year": "sophomore", "major": "CS",
              "research_interests_text": "computer vision and deep learning"}
        spanish = {"year": "sophomore", "major": "Spanish",
                   "research_interests_text": "second language acquisition"}
        cs_score = rank_opportunity(cs, opp).final_score
        spanish_score = rank_opportunity(spanish, opp).final_score
        assert cs_score > spanish_score
        # The mismatch is still firmly weak — major fit continues to matter.
        assert spanish_score < cs_score - 15


class TestUpsideReasonHook:
    """The interest-match reason must name the matched keywords, not echo a
    mid-word, lowercased slice of the student's free-text interests (regression
    for `research_text[:50]` producing '...computer vision a closely matches')."""

    def _opp(self):
        return {
            "id": "opp-hook",
            "title": "Research with Prof. Schwing — ECE",
            "lab_or_program": "Prof. Alexander Schwing's Research Group",
            "pi_name": "Alexander Schwing",
            "opportunity_type": "research",
            "keywords": ["machine learning", "computer vision", "robotics"],
            "description_raw": "Computer vision and machine learning research group.",
            "eligibility": {"skills_required": ["Python"]},
        }

    def test_reason_does_not_echo_truncated_interest_text(self):
        profile = {
            "research_interests_text": (
                "ai systems and machine learning, computer vision and "
                "vision-language models, deep learning"
            ),
            "desired_fields": ["computer vision", "machine learning"],
        }
        _, reasons_fit, _ = score_upside(profile, self._opp())
        joined = " ".join(reasons_fit)
        # The free-text-only prefix must not leak (old code sliced it in raw).
        assert "ai systems and" not in joined
        # No mid-word truncation artifact.
        assert "vision a closely" not in joined
        # The lab's matched areas are named instead.
        assert "computer vision" in joined and "machine learning" in joined

    def test_reason_keyword_order_is_deterministic(self):
        opp = self._opp()
        profile = {
            "research_interests_text": "computer vision, robotics, machine learning",
            "desired_fields": [],
        }
        runs = {tuple(score_upside(profile, opp)[1]) for _ in range(8)}
        assert len(runs) == 1  # set-ordered keywords used to make this flaky


class TestReasonQualityOptimizations:
    """Role/format tokens must not surface as research topics; type reasons must
    be humanized; the 'This lab focuses on' headline is research-only."""

    def test_topical_keywords_drops_role_tokens(self):
        kws = ["computer vision", "research assistant", "undergraduate research", "deep learning"]
        assert _topical_keywords(kws) == ["computer vision", "deep learning"]

    def test_summary_does_not_show_role_token_as_topic(self):
        opp = {
            "pi_name": "Jane Doe",
            "lab_or_program": "Prof. Jane Doe's Research Group",
            "opportunity_type": "research",
            "keywords": ["computer vision", "research assistant", "deep learning"],
        }
        s = _summarize_research(opp)
        assert "research assistant" not in s
        assert "computer vision" in s and "deep learning" in s

    def test_type_reason_is_humanized(self):
        profile = {"year": "freshman", "seeking_type": ["summer_program"]}
        opp = {
            "opportunity_type": "summer_program",
            "title": "AI/ML REU",
            "keywords": ["machine learning"],
            "eligibility": {"preferred_year": ["freshman"], "international_friendly": "yes"},
            "application": {},
        }
        joined = " ".join(rank_opportunity(profile, opp).reasons_fit)
        assert "summer_program" not in joined
        assert "summer program" in joined

    def test_lab_focus_headline_not_applied_to_internships(self):
        profile = {"year": "freshman", "seeking_type": ["internship"],
                   "research_interests_text": "machine learning and python"}
        opp = {
            "opportunity_type": "internship",
            "title": "Software Engineering Intern",
            "keywords": ["machine learning", "python"],
            "description_raw": "A software internship building ML tooling in Python.",
            "eligibility": {"preferred_year": ["freshman"], "international_friendly": "yes"},
            "application": {},
        }
        assert not any(
            "This lab focuses on" in r for r in rank_opportunity(profile, opp).reasons_fit
        )
