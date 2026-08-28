"""
Tests for the three-layer matching engine.
Covers: field matching, eligibility/readiness/upside scoring,
        bucket classification, international filtering, sorting, data integrity.

Run with: pytest tests/test_matcher.py -v
"""

import functools
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.config import (
    EXPLORE_MAJOR_MISMATCH_FLOOR,
    HOME_SCHOOL_AFFINITY_MAX,
    TOPIC_MISMATCH_PENALTY,
    TOPIC_UNKNOWN_PENALTY,
)
from src.matcher.ranker import (
    BUCKET_THRESHOLDS,
    MatchResult,
    _assign_buckets,
    _college_affinity,
    _compute_weights,
    _home_school_affinity,
    _is_grad_year,
    _is_undergrad,
    _major_match_score,
    _normalize_type_key,
    _profile_implicit_keywords,
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
    semantic_rerank,
)

_CORPUS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")


@functools.lru_cache(maxsize=1)
def _load_corpus() -> list[dict]:
    # Parsed once per session and shared read-only across every test that runs
    # the ranker over the real corpus. The file is 300 MB+; re-parsing it per
    # test was pure redundant CI cost. rank_all does not mutate its input, and
    # these tests only read — do not mutate the returned records.
    if not os.path.exists(_CORPUS_PATH):
        pytest.skip("No processed data file")
    with open(_CORPUS_PATH) as f:
        data = json.load(f)
    return data["opportunities"] if isinstance(data, dict) and "opportunities" in data else data


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
        "source_type": "uiuc_research",
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
        "source_type": "external_reu",
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

    def test_grad_student_matches_grad_program(self):
        # A PhD student fits grad-level openings however they're phrased.
        assert _year_match_score("PhD", ["PhD"]) == 100.0
        assert _year_match_score("PhD", ["Graduate", "Doctoral"]) == 100.0
        assert _year_match_score("Masters", ["graduate students"]) == 100.0

    def test_grad_student_not_penalized_for_year_math(self):
        # Regression: grad years aren't in the undergrad order — must not crash
        # to 0 for a grad-friendly program, and must hard-miss undergrad-only ones.
        assert _year_match_score("PhD", ["undergraduate", "senior"]) == 0.0
        assert _year_match_score("Masters", ["freshman", "sophomore"]) == 0.0

    def test_undergrad_hard_misses_grad_only_program(self):
        assert _year_match_score("senior", ["PhD"]) == 0.0
        assert _year_match_score("junior", ["graduate"]) == 0.0

    def test_undergraduate_term_is_not_grad(self):
        # "undergraduate" contains "graduate" — the guard must keep it undergrad,
        # and a generic "undergraduates" program accepts any class year.
        assert _is_grad_year("undergraduate") is False
        assert _is_grad_year("undergrad") is False
        assert _year_match_score("senior", ["undergraduate"]) == 100.0
        assert _year_match_score("freshman", ["undergraduate students"]) == 100.0


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


class TestSkillMapMemoization:
    """rank_all parses the profile's skills once and threads the map into
    score_eligibility (#12). Passing the precomputed map must be score-identical
    to parsing it per call — that equality is the safety basis for hoisting it."""

    def test_skill_overlap_score_skill_map_matches_parse(self):
        from src.matcher.ranker import _parse_skills, _skill_overlap_score
        skills = ["Python", "PyTorch", "C++"]
        smap = _parse_skills(skills)
        req = ["Python", "TensorFlow"]
        assert _skill_overlap_score(skills, req) == _skill_overlap_score(skills, req, skill_map=smap)

    def test_score_eligibility_skill_map_matches_parse(self):
        from src.matcher.ranker import _parse_skills, score_eligibility
        profile = {
            "hard_skills": ["Python", "PyTorch", "C++"],
            "year": "freshman", "major": "CS", "seeking_type": ["research"],
        }
        opp = {
            "opportunity_type": "research",
            "eligibility": {
                "preferred_year": ["freshman"], "majors": ["CS"],
                "skills_required": ["Python", "PyTorch"], "international_friendly": "yes",
            },
        }
        smap = _parse_skills(profile["hard_skills"])
        assert score_eligibility(profile, opp) == score_eligibility(profile, opp, skill_map=smap)


class TestSkillLevelMatchingContract:
    """The skill-level annotation work (tailor / cold-email prompt threading)
    must not change matching. These pin the ranker's pre-existing level
    handling so any accidental coupling breaks loudly:
      - plain string skills keep weight 1.0 (levels stay optional)
      - annotated weights follow PROFICIENCY_WEIGHTS exactly as before
      - unknown level strings fall back to the 'experienced' weight
    """

    def test_proficiency_weights_pinned(self):
        from src.matcher.config import PROFICIENCY_WEIGHTS
        assert PROFICIENCY_WEIGHTS == {
            "expert": 1.0,
            "experienced": 0.75,
            "beginner": 0.5,
        }

    def test_parse_skills_level_weights_unchanged(self):
        from src.matcher.ranker import _parse_skills
        smap = _parse_skills([
            {"name": "Python", "level": "expert"},
            {"name": "Java", "level": "experienced"},
            {"name": "R", "level": "beginner"},
            {"name": "Go", "level": "familiar"},
            "MATLAB",
        ])
        assert smap["python"] == 1.0
        assert smap["java"] == 0.75
        assert smap["r"] == 0.5
        assert smap["go"] == 0.75  # unknown label → experienced weight
        assert smap["matlab"] == 1.0  # plain string, no level

    def test_string_and_expert_annotated_skills_score_identically(self):
        from src.matcher.ranker import score_eligibility
        opp = {
            "opportunity_type": "research",
            "eligibility": {
                "preferred_year": ["junior"], "majors": ["CS"],
                "skills_required": ["Python", "Java"],
                "international_friendly": "yes",
            },
        }
        base = {"year": "junior", "major": "CS", "seeking_type": ["research"]}
        plain = score_eligibility({**base, "hard_skills": ["Python", "Java"]}, opp)
        annotated = score_eligibility(
            {
                **base,
                "hard_skills": [
                    {"name": "Python", "level": "expert"},
                    {"name": "Java", "level": "expert"},
                ],
            },
            opp,
        )
        assert plain[0] == annotated[0]


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

    def test_an_unrecognised_field_is_unknown_not_a_conflict(self):
        # The domain lists name 53 majors; this field carries 1,305 distinct
        # strings across the corpus. Reading every unrecognised one as a clash
        # charged the cross-domain penalty for Immunology, Epidemiology, Cell
        # Biology — and told a Bioengineering student they conflict with them.
        for field in ("Immunology", "Cell Biology", "Epidemiology", "Physiology"):
            unknown = _major_match_score(["ECE"], [field])
            clash = _major_match_score(["Spanish"], ["CS"])
            assert unknown > clash, field
            assert unknown == _major_match_score(["Biology"], ["CS"]), field

    def test_a_department_label_costs_nothing_to_miss(self):
        # `label_only` says the list NAMES a department rather than requiring a
        # major. Missing it must score exactly like a posting that states no
        # major at all — there is no requirement to have failed.
        assert _major_match_score(["ECE"], ["Bioengineering"], label_only=True) == \
            _major_match_score(["ECE"], [])

    def test_a_matching_department_label_still_earns_credit(self):
        # Neutral on a miss, not blind: sharing the department is real evidence.
        assert _major_match_score(["ECE"], ["ECE"], label_only=True) == 100.0
        assert _major_match_score(["ECE"], ["CS"], label_only=True) == 70.0


# ── Unit Tests: Scoring Layers ────────────────

class TestFacultyMajorIsALabel:
    """`majors` on a faculty record is the department the professor sits in,
    copied from config — not a requirement any page of theirs states. Grading a
    mismatch against it cost 20.4 eligibility points, 9.2 of final score, on
    80-85% of 128,449 faculty records."""

    @staticmethod
    def _faculty(**over):
        opp = {
            "id": "fac-1",
            "title": "Research with Prof. Example — Bioengineering",
            "source_type": "faculty_research",
            "opportunity_type": "research",
            "on_campus": True,
            "paid": "unknown",
            "is_rolling": True,
            "description_clean": "Medical imaging research.",
            "eligibility": {
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "majors": ["Bioengineering", "Biomedical Engineering"],
                "skills_required": [],
                "skills_preferred": [],
                "international_friendly": "unknown",
                "citizenship_required": False,
            },
            "application": {"contact_method": "email", "application_effort": "low"},
        }
        opp.update(over)
        return opp

    # The production case, stated exactly: an ECE sophomore who named no second
    # field, against a Bioengineering professor. That pair scores 15.0 — the
    # related-majors bridge does not connect them — which is where the 20.4
    # points went.
    PROFILE = {
        "year": "sophomore",
        "major": "Electrical and Computer Engineering",
        "secondary_interests": [],
        "international_student": True,
        "hard_skills": ["Python"],
        "coursework": ["ECE 120"],
        "experience_level": "beginner",
        "resume_ready": True,
        "can_cold_email": True,
        "seeking_type": ["research"],
        "research_interests_text": "deep learning for medical imaging",
    }

    def test_another_department_costs_the_student_nothing(self):
        outside, _, _ = score_eligibility(self.PROFILE, self._faculty())
        unlabelled = self._faculty()
        unlabelled["eligibility"] = {**unlabelled["eligibility"], "majors": []}
        open_posting, _, _ = score_eligibility(self.PROFILE, unlabelled)
        assert outside == open_posting

    def test_the_professor_is_not_given_a_preference_they_never_stated(self):
        _, _, gap = score_eligibility(self.PROFILE, self._faculty())
        assert not any(g.startswith("Prefers ") for g in gap), gap

    def test_a_real_posting_still_states_a_real_requirement(self):
        # The discriminator is source_type, and it has to stay narrow: a
        # Handshake listing that names majors named them on purpose.
        posting = self._faculty(source_type="handshake")
        scored, _, gap = score_eligibility(self.PROFILE, posting)
        neutral = self._faculty(source_type="handshake")
        neutral["eligibility"] = {**neutral["eligibility"], "majors": []}
        open_scored, _, _ = score_eligibility(self.PROFILE, neutral)
        assert scored < open_scored
        assert any(g.startswith("Prefers ") for g in gap), gap

    def test_sharing_the_department_still_earns_credit(self):
        same = self._faculty()
        same["eligibility"] = {**same["eligibility"], "majors": ["ECE"]}
        matched, fit, _ = score_eligibility(self.PROFILE, same)
        outside, _, _ = score_eligibility(self.PROFILE, self._faculty())
        assert matched > outside
        assert any("department aligns" in f for f in fit), fit

    def test_department_credit_survives_faculty_claim_neutralization(self):
        from src.evidence import (
            FACULTY_MAJOR_LABELS_MARKER,
            faculty_safe_public_record,
            neutralize_unverified_faculty_claims,
        )

        same = self._faculty()
        same["eligibility"] = {**same["eligibility"], "majors": ["ECE"]}
        neutralize_unverified_faculty_claims(same)
        neutralize_unverified_faculty_claims(same)
        assert same["eligibility"]["majors"] == []
        assert same["metadata"][FACULTY_MAJOR_LABELS_MARKER] == ["ECE"]

        matched, fit, gap = score_eligibility(self.PROFILE, same)
        outside = self._faculty()
        outside["eligibility"] = {**outside["eligibility"], "majors": ["Bioengineering"]}
        neutralize_unverified_faculty_claims(outside)
        outside_score, _, outside_gap = score_eligibility(self.PROFILE, outside)

        assert matched > outside_score
        assert any("department aligns" in f for f in fit), fit
        assert not any("Prefers " in item or "requirements" in item for item in gap)
        assert not any("Prefers " in item or "requirements" in item for item in outside_gap)

        public = faculty_safe_public_record(same)
        assert public["eligibility"]["majors"] == []
        assert FACULTY_MAJOR_LABELS_MARKER not in public["metadata"]


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


class TestInternationalUnknownScoring:
    """F-1 'unknown' internships score higher than other 'unknown' postings —
    most internships allow CPT/OPT, so a flat deterrent over-discourages the
    primary audience."""

    def _unknown_opp(self, opp_type):
        return {
            "id": f"opp-unk-{opp_type}",
            "title": "Some Role",
            "opportunity_type": opp_type,
            "on_campus": False,
            "paid": "yes",
            "eligibility": {
                "preferred_year": ["freshman", "sophomore"],
                "majors": ["ECE", "CS"],
                "skills_required": ["Python"],
                "international_friendly": "unknown",
            },
            "application": {"contact_method": "email", "application_effort": "low"},
        }

    def test_internship_unknown_beats_research_unknown_for_f1(self):
        # seeking both types so the type-preference term is symmetric — the only
        # remaining difference is the international-unknown score split.
        f1 = {
            "year": "sophomore", "major": "ECE", "international_student": True,
            "seeking_type": ["research", "internship"],
            "hard_skills": ["Python"], "coursework": ["CS 124"],
        }
        intern_score, _, _ = score_eligibility(f1, self._unknown_opp("internship"))
        research_score, _, _ = score_eligibility(f1, self._unknown_opp("research"))
        assert intern_score > research_score

    def test_internship_unknown_message_mentions_cpt_opt(self, sample_profile):
        _, _, gap = score_eligibility(sample_profile, self._unknown_opp("internship"))
        assert any("cpt" in g.lower() or "opt" in g.lower() for g in gap)


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

    def _brand_opp(self, organization, school=None):
        return {
            "id": f"brand-{organization}", "organization": organization,
            "school": school, "paid": "unknown", "on_campus": False,
            "eligibility": {}, "application": {}, "description_raw": "",
        }

    def test_smithsonian_gets_no_prestige_reason(self, sample_profile):
        for org in ["Smithsonian Institution", "Smiths Detection Group", "Smith+Nephew"]:
            _, fit, _ = score_upside(sample_profile, self._brand_opp(org))
            assert not any("prestigious" in f.lower() for f in fit), org

    def test_registered_schools_get_equal_brand_score(self, sample_profile):
        uw_total, uw_fit, _ = score_upside(
            sample_profile, self._brand_opp("University of Washington", school="uw"))
        ucb_total, ucb_fit, _ = score_upside(
            sample_profile, self._brand_opp("UC Berkeley", school="ucb"))
        assert uw_total == ucb_total
        for fit in (uw_fit, ucb_fit):
            assert any("major research university" in f.lower() for f in fit)
            assert not any("prestigious" in f.lower() for f in fit)

    def test_external_prestige_org_word_bounded(self, sample_profile):
        _, fit, _ = score_upside(sample_profile, self._brand_opp("MIT Lincoln Laboratory"))
        assert any("prestigious" in f.lower() for f in fit)

    def test_score_range(self, sample_profile, good_match_opportunity):
        score, _, _ = score_upside(sample_profile, good_match_opportunity)
        assert 0 <= score <= 100


class TestResearchAreasRawSignal:
    """research_areas_raw is the only topical signal for faculty whose keywords
    never got past the generic department template. The loader used to strip it
    before any consumer saw it; these lock in that it now flows into the
    similarity corpus and actually moves the score."""

    def _faculty_opp(self, research_areas_raw):
        # A faculty record with NO specific keywords and only a template
        # description — the exact shape where research_areas_raw is the sole
        # topical signal.
        return {
            "id": "prof-x",
            "title": "Research with Prof. X",
            "keywords": [],
            "description_raw": "Research opportunity in the department.",
            "metadata": {"research_areas_raw": research_areas_raw},
        }

    def test_similarity_corpus_includes_research_areas_raw(self):
        from src.matcher.ranker import _similarity_corpus

        corpus = _similarity_corpus(self._faculty_opp("superconducting qubits"))
        assert "superconducting qubits" in corpus

    def test_research_areas_raw_lifts_on_topic_similarity(self):
        from src.matcher.ranker import _similarity_corpus, _token_cosine_similarity

        opp = self._faculty_opp("superconducting qubits and quantum error correction")
        query = "quantum error correction"
        with_field = _token_cosine_similarity(query, _similarity_corpus(opp))
        without_field = _token_cosine_similarity(
            query, _similarity_corpus({**opp, "metadata": {}})
        )
        assert with_field > 0.0
        assert with_field > without_field


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

    def test_grad_penalty_is_softened_and_post_stretch(self, sample_profile, good_match_opportunity):
        # The grad penalty (softened 0.5 -> 0.65) is applied AFTER the stretch
        # transform as a clean multiplier, so a grad reach keeps ~65% of the
        # undergrad final score rather than being near-halved.
        base = rank_opportunity(sample_profile, good_match_opportunity)
        grad_opp = dict(good_match_opportunity)
        grad_opp["title"] = good_match_opportunity["title"] + " (PhD Intern)"
        grad = rank_opportunity(sample_profile, grad_opp)
        assert grad.final_score == pytest.approx(base.final_score * 0.65, rel=0.05)


class TestRankAll:
    def test_filters_citizenship_restricted(self, sample_profile, sample_opportunities):
        results = rank_all(sample_profile, sample_opportunities)
        result_ids = {r.opportunity_id for r in results}
        assert "opp-001" in result_ids
        assert "opp-002" not in result_ids

    def test_equal_scores_tie_break_deterministically(self, sample_profile, sample_opportunities):
        """Scores round to 0.1, so tie bands are common; without a secondary
        key the order followed corpus file order and reshuffled every refresh
        (2026-07 audit: 17-way tie observed reordering)."""
        sample_profile["preferences"]["exclude_citizenship_restricted"] = False
        base = next(o for o in sample_opportunities if o["id"] == "opp-001")
        twin_a = dict(base, id="tie-aaa")
        twin_b = dict(base, id="tie-zzz")
        for ordering in ([twin_a, twin_b], [twin_b, twin_a]):
            results = rank_all(sample_profile, list(sample_opportunities) + ordering)
            tie_ids = [r.opportunity_id for r in results if r.opportunity_id.startswith("tie-")]
            assert tie_ids == ["tie-aaa", "tie-zzz"]

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
        return _load_corpus()

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
        data = _load_corpus()

        assert len(data) > 0, "Processed data is empty"

        for opp in data:
            assert opp.get("id"), f"Missing id: {opp.get('title')}"
            assert opp.get("title"), f"Missing title: {opp.get('id')}"
            assert opp.get("url"), f"Missing url: {opp.get('title')}"
            assert isinstance(opp.get("eligibility"), dict), f"Bad eligibility in: {opp.get('title')}"

    def test_no_duplicate_ids(self):
        data = _load_corpus()

        ids = [opp["id"] for opp in data]
        seen: set[str] = set()
        dupes: set[str] = set()
        for i in ids:
            if i in seen:
                dupes.add(i)
            seen.add(i)
        assert not dupes, f"Duplicate IDs: {dupes}"

    def test_ranker_on_real_data(self, sample_profile):
        """End-to-end test: run ranker on actual processed data."""
        opps = _load_corpus()

        results = rank_all(sample_profile, opps)
        assert len(results) > 0, "Ranker returned no results on real data"

        for r in results:
            assert 0 <= r.final_score <= 100
            assert r.bucket in ("high_priority", "good_match", "reach", "low_fit")


class TestUpsideSimilarityScale:
    """The base upside layer is corpus-fitted TF-IDF in both the batched
    (rank_all) and per-pair paths, so its keyword_score is provider-independent —
    embeddings only influence the bounded semantic_rerank, never this base score."""

    def _faculty_opp(self):
        return {
            "source": "uiuc_faculty",
            "keywords": ["machine learning"],
            "description_raw": "Machine learning research in the group.",
            "lab_or_program": "Prof. X Lab",
            "eligibility": {},
            "paid": "unknown",
            "organization": "uiuc",
        }

    def test_precomputed_sim_is_provider_independent(self, monkeypatch):
        from src.matcher.ranker import score_upside
        # research_text deliberately shares no token with the opp keywords, so the
        # literal text-overlap bonus stays out and only the sim scaling matters.
        profile = {"research_interests_text": "quantum chromodynamics", "desired_fields": []}
        opp = self._faculty_opp()
        for v in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        total_no_provider, _, _ = score_upside(profile, opp, precomputed_sim=0.25)
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        total_with_provider, _, _ = score_upside(profile, opp, precomputed_sim=0.25)
        assert total_no_provider == total_with_provider

    def test_self_computed_sim_is_provider_independent(self, monkeypatch):
        """The per-pair path (no precomputed_sim) computes a TF-IDF sim too, so a
        configured embedding provider must not change the base upside score."""
        import src.matcher.ranker as rk
        monkeypatch.setattr(rk, "_text_similarity", lambda _a, _b: 0.3)
        profile = {"research_interests_text": "quantum chromodynamics", "desired_fields": []}
        opp = self._faculty_opp()
        for v in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        total_no_provider, _, _ = rk.score_upside(profile, opp)
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        total_with_provider, _, _ = rk.score_upside(profile, opp)
        assert total_no_provider == total_with_provider

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

    def test_plural_interest_matches_adjective_keyword(self):
        """'robotics' must align with 'adaptive robotic manipulation' — the
        2026-07 audit found morphology mismatches demoting the only
        robotics-keyworded ME professor to rank 1218 while keywordless REUs
        escaped, inverting the ranking."""
        prof = self._profile("robotics, mechanical design, thermal systems")
        opp = self._research(
            ["adaptive robotic manipulation", "bioinspiration",
             "computational modeling", "rapid prototyping techniques"])
        assert _topic_alignment_penalty(prof, opp) == 1.0

    def test_morphology_does_not_rescue_true_mismatch(self):
        prof = self._profile("robotics, mechanical design, thermal systems")
        opp = self._research(["medieval manuscripts", "poetry translation"])
        assert _topic_alignment_penalty(prof, opp) == TOPIC_MISMATCH_PENALTY

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

    # RANK-7: a curated keyword that is a SUPERSET phrase of the student's
    # interest (or just worded differently) must align on the shared specific
    # token. The prior checks only fired when the whole keyword phrase appeared
    # verbatim in the interest text, so these real faculty keywords were wrongly
    # penalized — burying 38% of UIUC faculty incl. the best ML/CV topical fits
    # (found 2026-06-15 dogfooding a real F-1 profile).
    def test_superset_phrase_keyword_aligns(self):
        # interest "computer vision" vs Prof. Schwing's real keyword
        opp = self._research(["computer vision and pattern recognition"])
        assert _topic_alignment_penalty(self._profile(), opp) == 1.0

    def test_variant_phrasing_ml_keyword_aligns(self):
        # interest "machine learning" vs a "machine learning and ai" keyword,
        # alongside pollution ("associate editor") that must not block alignment
        opp = self._research(["machine learning and ai", "associate editor"])
        assert _topic_alignment_penalty(self._profile(), opp) == 1.0

    def test_shared_specific_token_aligns(self):
        # "machine vision" shares "vision"/"machine" with the interest
        opp = self._research(["cognitive computing", "machine vision"])
        assert _topic_alignment_penalty(self._profile(), opp) == 1.0

    def test_plural_token_still_does_not_falsely_align(self):
        # guard preserved: the new token-overlap path must keep "computer"
        # (singular interest) from aligning with "computers and education"
        opp = self._research(["computers and education"])
        assert _topic_alignment_penalty(self._profile(), opp) == TOPIC_MISMATCH_PENALTY

    # RANK-9 (2026-06-16 dogfooding a real F-1 ML/NLP profile): the exact area
    # "machine learning"/"artificial intelligence" is in _GENERIC_KEYWORDS and was
    # stripped before alignment, so an ML/NLP/LLM lab whose remaining keyword was
    # "natural language processing" got the mismatch penalty for an ML student and
    # was buried into low_fit. Align over the FULL keyword list so the student's
    # own stated area can match.
    def test_exact_ml_keyword_aligns_when_it_is_the_interest(self):
        opp = self._research(["machine learning", "natural language processing"])
        prof = self._profile(interest="machine learning, computer vision")
        assert _topic_alignment_penalty(prof, opp) == 1.0

    def test_llm_keyword_aligns_with_llm_interest(self):
        opp = self._research(["large language models"])
        prof = self._profile(interest="llm-based retrieval and reinforcement")
        assert _topic_alignment_penalty(prof, opp) == 1.0

    def test_ml_keyword_does_not_align_for_unrelated_student(self):
        # the demotion fix must not become "ML keyword always aligns": a history
        # student gets the mismatch penalty on an ML lab.
        opp = self._research(["machine learning", "robotics"])
        prof = self._profile(interest="medieval history and poetry")
        assert _topic_alignment_penalty(prof, opp) == TOPIC_MISMATCH_PENALTY

    # RANK-9 false-promote: a lone broad token ("science"/"computer"/"data"/
    # "computational") shared between a CompE/ML profile and a humanities/soc-sci
    # lab is corpus noise, not topical alignment — those labs floated into
    # good_match. The overlap now requires a MEANINGFUL shared token.
    def test_lone_broad_token_does_not_falsely_align(self):
        opp = self._research(["computational social science", "sociology of culture"])
        prof = self._profile(interest="data science and machine learning")
        assert _topic_alignment_penalty(prof, opp) == TOPIC_MISMATCH_PENALTY

    def test_data_science_keyword_does_not_bleed_into_ml_profile(self):
        opp = self._research(["data science"])
        prof = self._profile(interest="machine learning and computer vision")
        assert _topic_alignment_penalty(prof, opp) == TOPIC_MISMATCH_PENALTY

    def test_student_who_typed_the_broad_phrase_still_aligns(self):
        # the substring path preserves a genuine match: a student who literally
        # typed "data science" still aligns with a "data science" lab.
        opp = self._research(["data science"])
        prof = self._profile(interest="data science and visualization")
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


class TestCitizenshipRequiredHonored:
    """BUG A (filter-correctness gate, 2026-06-15): the matcher must honor
    eligibility.citizenship_required even when international_friendly was never
    reconciled to 'no' — otherwise a US-only posting shows an F-1 student a clean
    ~60 'verify' match. Latent today (every citizenship_required=True record also
    has friendly='no') but bites as domestic / US-only sources enter the corpus."""

    def _us_only(self):
        return {
            "id": "us-only", "source_type": "external",
            "opportunity_type": "research", "title": "US Only Lab",
            "eligibility": {"citizenship_required": True, "international_friendly": "unknown"},
            "application": {},
        }

    def _restricted(self, gap):
        return any("citizenship" in g.lower() or "permanent residency" in g.lower() for g in gap)

    def test_f1_flagged_when_required_but_friendly_unknown(self):
        _, _fit, gap = score_eligibility({"international_student": True}, self._us_only())
        assert self._restricted(gap)

    def test_domestic_not_penalized_by_citizenship_required(self):
        _, _fit, gap = score_eligibility({"international_student": False}, self._us_only())
        assert not self._restricted(gap)

    def test_f1_hard_filtered_out(self):
        profile = {"international_student": True,
                   "preferences": {"exclude_citizenship_restricted": True}}
        results = rank_all(profile, [self._us_only()])
        assert all(r.opportunity_id != "us-only" for r in results)

    def test_domestic_keeps_it(self):
        results = rank_all({"international_student": False}, [self._us_only()])
        assert any(r.opportunity_id == "us-only" for r in results)


class TestCampusConvenienceNeverClaimsWorkAuthorization:
    """Location may be a convenience signal, never an immigration conclusion.

    Even a verified same-campus posting cannot prove the student's particular
    employment/funding arrangement. The matcher may say where it is, but must
    not tell an F-1 student that work authorization is settled.
    """

    def _on_campus(self, school):
        return {"id": f"oc-{school}", "opportunity_type": "research", "on_campus": True,
                "school": school, "eligibility": {}, "application": {}}

    def _f1(self, home):
        return {"international_student": True, "home_school": home, "research_interests_text": ""}

    def _has_legal_claim(self, fit):
        return any("work authorization" in f.lower() for f in fit)

    def test_own_campus_names_location_without_a_legal_claim(self):
        _, fit, _ = score_upside(self._f1("uiuc"), self._on_campus("uiuc"))
        assert "At your university" in fit
        assert not self._has_legal_claim(fit)

    def test_foreign_campus_does_not_earn_bonus(self):
        _, fit, _ = score_upside(self._f1("uiuc"), self._on_campus("uw"))
        assert "At your university" not in fit
        assert not self._has_legal_claim(fit)

    def test_missing_home_school_cannot_claim_a_home_campus(self):
        _, fit, _ = score_upside({"international_student": True, "research_interests_text": ""},
                                 self._on_campus("uiuc"))
        assert "At your university" not in fit
        assert not self._has_legal_claim(fit)

    def test_national_legacy_row_cannot_claim_a_home_campus(self):
        _, fit, _ = score_upside(self._f1("ucb"), self._on_campus(None))
        assert "At your university" not in fit
        assert not self._has_legal_claim(fit)


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


class TestDesiredFieldOverlap:
    """The desired-field credit path must see the OpenAlex enrichment: a chip
    aligns with a longer enriched keyword by bounded containment, not just exact
    set intersection — while a low-signal bare token can't blanket-match."""

    def test_chip_matches_longer_enriched_keyword(self):
        from src.matcher.ranker import _desired_field_overlap
        assert _desired_field_overlap({"machine learning"}, ["multimodal machine learning"]) == {"machine learning"}
        assert _desired_field_overlap({"network security"}, ["network security and intrusion detection"]) == {"network security"}

    def test_keyword_shorter_than_chip_also_matches(self):
        from src.matcher.ranker import _desired_field_overlap
        assert _desired_field_overlap({"quantum physics"}, ["physics"]) == {"quantum physics"}

    def test_low_signal_bare_token_needs_exact(self):
        from src.matcher.ranker import _desired_field_overlap
        assert _desired_field_overlap({"data"}, ["data visualization"]) == set()
        assert _desired_field_overlap({"systems"}, ["distributed systems"]) == set()
        assert _desired_field_overlap({"science"}, ["computer science"]) == set()

    def test_low_signal_opp_keyword_cannot_blanket_credit_specific_chip(self):
        # Reverse direction: a faculty whose ONLY keyword is a broad dept token
        # must not credit a specific student chip that contains it as a word.
        from src.matcher.ranker import _desired_field_overlap
        assert _desired_field_overlap({"chemical engineering"}, ["engineering"]) == set()
        assert _desired_field_overlap({"computer science"}, ["science"]) == set()
        assert _desired_field_overlap({"distributed systems"}, ["systems"]) == set()
        assert _desired_field_overlap({"data mining"}, ["data"]) == set()
        # ...but a DISTINCTIVE shorter keyword (not low-signal) still credits.
        assert _desired_field_overlap({"quantum physics"}, ["physics"]) == {"quantum physics"}
        assert _desired_field_overlap({"molecular biology"}, ["biology"]) == {"molecular biology"}

    def test_exact_and_word_boundary(self):
        from src.matcher.ranker import _desired_field_overlap
        assert _desired_field_overlap({"robotics"}, ["robotics"]) == {"robotics"}
        # word boundary: "art" must not match inside "smart grid"
        assert _desired_field_overlap({"art"}, ["smart grid security"]) == set()

    def test_enriched_faculty_earns_interest_reason(self):
        """End-to-end: an enriched faculty (long OpenAlex phrases) now earns the
        interest bonus + 'Matches your interests' reason it was denied before."""
        opp = {
            "id": "f", "opportunity_type": "research", "pi_name": "X",
            "source_type": "faculty_research",
            "keywords": ["multimodal machine learning", "advanced image and video retrieval"],
            "eligibility": {},
        }
        prof = {"research_interests_text": "", "desired_fields": ["machine learning"]}
        score, fit, _ = score_upside(prof, opp)
        assert any(r == "Matches your interests: machine learning" for r in fit)


class TestInterestReasonDedup:
    """When the similarity reason already names every overlapped keyword, the
    bare 'Matches your interests: X' reason is pure repetition and must be
    dropped; partial or disjoint coverage keeps both reasons."""

    def _opp(self, keywords):
        return {
            "id": "opp-dedup",
            "title": "Research with Prof. Doe",
            "pi_name": "Jane Doe",
            "lab_or_program": "Prof. Jane Doe's Group",
            "opportunity_type": "research",
            "keywords": keywords,
            "description_raw": "Lab working across several areas.",
            "eligibility": {},
        }

    def test_same_keyword_not_explained_twice(self):
        profile = {
            "research_interests_text": "computer vision and deep learning",
            "desired_fields": ["computer vision"],
        }
        _, fit, _ = score_upside(
            profile, self._opp(["computer vision", "deep learning"]), precomputed_sim=0.5
        )
        assert not any(r.startswith("Matches your interests") for r in fit)
        assert sum(1 for r in fit if "computer vision" in r) == 1

    def test_disjoint_keywords_keep_both_reasons(self):
        profile = {
            "research_interests_text": "computer vision and deep learning",
            "desired_fields": ["robotics"],
        }
        _, fit, _ = score_upside(
            profile,
            self._opp(["computer vision", "deep learning", "graphics", "robotics"]),
            precomputed_sim=0.5,
        )
        assert "Matches your interests: robotics" in fit
        assert any("closely matches" in r for r in fit)

    def test_partially_covered_overlap_keeps_bare_reason(self):
        profile = {
            "research_interests_text": "computer vision and deep learning",
            "desired_fields": ["computer vision", "neural interfaces"],
        }
        _, fit, _ = score_upside(
            profile,
            self._opp(["computer vision", "deep learning", "graphics", "neural interfaces"]),
            precomputed_sim=0.5,
        )
        sim_reasons = [r for r in fit if "closely matches" in r]
        assert sim_reasons and "neural interfaces" not in sim_reasons[0]
        bare = [r for r in fit if r.startswith("Matches your interests")]
        assert bare and "neural interfaces" in bare[0]


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


class TestBucketRecompute:
    """semantic_rerank changes final_score; buckets must follow (not stay stale)."""

    def _mr(self, oid, score):
        return MatchResult(
            opportunity_id=oid, eligibility_score=0.0, readiness_score=0.0,
            upside_score=0.0, final_score=score, bucket="low_fit",
            reasons_fit=[], reasons_gap=[], next_steps=[],
        )

    def test_assign_buckets_small_set_uses_flat_floors(self):
        rs = [self._mr("a", 75.0), self._mr("b", 65.0), self._mr("c", 50.0), self._mr("d", 10.0)]
        _assign_buckets(rs)
        assert [r.bucket for r in rs] == ["high_priority", "good_match", "reach", "low_fit"]

    def test_semantic_rerank_recomputes_buckets(self, monkeypatch):
        import src.matcher.embeddings as emb
        results = [self._mr(f"o{i}", float(95 - i * 6)) for i in range(12)]
        opps_by_id = {
            f"o{i}": {"title": "t", "keywords": ["x"], "description_raw": "d", "lab_or_program": ""}
            for i in range(12)
        }
        # The lowest-rule-score candidate is maximally similar → should jump up.
        monkeypatch.setattr(
            emb, "semantic_similarity_batch",
            lambda q, texts: [0.0] * (len(texts) - 1) + [1.0],
        )
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        out = semantic_rerank(
            {"research_interests_text": "machine learning"}, results, opps_by_id,
            semantic_weight=0.5,
        )
        order = {"high_priority": 3, "good_match": 2, "reach": 1, "low_fit": 0}
        ranks = [order[r.bucket] for r in out]
        # Buckets are monotonic non-increasing with the re-sorted scores (the bug
        # left a re-blended high score carrying its stale low_fit label).
        assert ranks == sorted(ranks, reverse=True)
        boosted = next(r for r in out if r.opportunity_id == "o11")
        assert boosted.final_score > 50 and boosted.bucket != "low_fit"


class TestBatchedSimilarity:
    """The batched upside similarity (rank_all) must equal the per-pair path
    (score_upside) when the TF-IDF vectorizer is fitted — that equality is the
    whole safety basis for batching (#10)."""

    def _opps(self):
        return [
            {"id": f"o{i}", "opportunity_type": "research",
             "title": f"Lab {i}", "lab_or_program": f"Prof. P{i}'s Group",
             "keywords": kw, "description_raw": desc,
             "eligibility": {"preferred_year": ["freshman"], "international_friendly": "yes"},
             "application": {}}
            for i, (kw, desc) in enumerate([
                (["machine learning", "computer vision"], "Computer vision and ML research."),
                (["robotics", "control"], "Robotics and control systems."),
                (["nlp", "large language models"], "NLP and large language models."),
                (["physics"], "Condensed matter physics."),
                (["computer vision"], "Image understanding."),
            ])
        ]

    def test_similarity_corpus_matches_inline_build(self):
        from src.matcher.ranker import _GENERIC_KEYWORDS, _similarity_corpus
        opp = self._opps()[0]
        opp_kw = [k.lower() for k in opp["keywords"]]
        specific = list(dict.fromkeys(k for k in opp_kw if k not in _GENERIC_KEYWORDS))
        desc = (opp.get("description_raw") or "").lower()
        expected = " ".join(filter(None, [opp["title"], opp["lab_or_program"], " ".join(specific), desc]))
        assert _similarity_corpus(opp) == expected

    def test_batched_equals_per_pair_when_fitted(self):
        import src.matcher.embeddings as emb
        from src.matcher.embeddings import fit_tfidf_corpus
        from src.matcher.ranker import _compute_weights, _similarity_corpus

        prev_v, prev_f = emb._tfidf_vectorizer, emb._tfidf_fitted
        opps = self._opps()
        try:
            fit_tfidf_corpus([_similarity_corpus(o) for o in opps])
            if not emb._tfidf_fitted:
                pytest.skip("sklearn unavailable")
            prof = {"year": "freshman", "seeking_type": ["research"],
                    "research_interests_text": "machine learning and computer vision"}
            batched = {r.opportunity_id: round(r.final_score, 6) for r in rank_all(prof, opps)}
            weights = _compute_weights(50)
            for o in opps:
                if o["id"] in batched:
                    r = rank_opportunity(prof, o, weights, precomputed_sim=None)
                    assert batched[o["id"]] == round(r.final_score, 6)
        finally:
            emb._tfidf_vectorizer, emb._tfidf_fitted = prev_v, prev_f


class TestFacultyUpsideReweight:
    """Faculty descriptions are template-generated, so the mentor/pathway keyword
    scan is a flat constant — its weight is redirected to keyword_score (C4).
    The branch keys on source_type='faculty_research', which is carried by
    exactly the faculty collectors (uiuc_faculty, ucb_eecs_faculty,
    ucb_stat_faculty)."""

    def _prof(self):
        return {"research_interests_text": "x",
                "desired_fields": ["machine learning", "computer vision"]}

    def _opp(self, source, desc, source_type=None, keywords=None):
        return {
            "source": source, "opportunity_type": "research",
            "source_type": source_type or (
                "faculty_research" if source.endswith("_faculty") else "internship"),
            "keywords": keywords or ["machine learning", "computer vision"],
            "description_raw": desc,
            "eligibility": {"skills_required": ["Python"]},
        }

    def test_faculty_upside_unmoved_by_mentor_pathway_text(self):
        # keyword_score is pinned at 100 by the desired_fields overlap, so the
        # only thing the extra desc words could move is mentor/pathway — which
        # carry zero weight for faculty. Upside must be identical.
        prof = self._prof()
        plain = score_upside(prof, self._opp("uiuc_faculty", "Research opportunity."))[0]
        rich = score_upside(prof, self._opp(
            "uiuc_faculty", "mentor training guided publication co-author conference thesis."))[0]
        assert plain == rich

    def test_ucb_faculty_upside_unmoved_by_mentor_pathway_text(self):
        prof = self._prof()
        plain = score_upside(prof, self._opp("ucb_eecs_faculty", "Research opportunity."))[0]
        rich = score_upside(prof, self._opp(
            "ucb_eecs_faculty", "mentor training guided publication co-author conference thesis."))[0]
        assert plain == rich

    def test_ucb_faculty_keyword_gap_wider_than_non_faculty_formula(self):
        # Faculty weighting puts 0.50 on keyword_score (vs 0.20 in the
        # skill-signal non-faculty formula), so the same keyword-fit difference
        # must separate two UCB faculty records by strictly more than it would
        # separate two otherwise-identical non-faculty records.
        prof = self._prof()
        desc = "Research opportunity."
        similar_kw = ["machine learning", "computer vision"]
        dissimilar_kw = ["quantum chemistry"]

        fac_hi = score_upside(prof, self._opp("ucb_eecs_faculty", desc, keywords=similar_kw))[0]
        fac_lo = score_upside(prof, self._opp("ucb_eecs_faculty", desc, keywords=dissimilar_kw))[0]
        non_hi = score_upside(prof, self._opp("handshake", desc, keywords=similar_kw))[0]
        non_lo = score_upside(prof, self._opp("handshake", desc, keywords=dissimilar_kw))[0]

        assert fac_hi > fac_lo
        assert (fac_hi - fac_lo) > (non_hi - non_lo)

    def test_non_faculty_upside_still_responds_to_mentor_pathway(self):
        prof = self._prof()
        plain = score_upside(prof, self._opp("handshake", "Research opportunity."))[0]
        rich = score_upside(prof, self._opp(
            "handshake", "mentor training guided publication co-author conference thesis."))[0]
        assert rich > plain


# ── School / audience discovery scope (PR #187 Phase 1) ──────────────────────

class TestSchoolScopeFilter:
    """rank_all excludes another school's campus-only records before scoring;
    'open' and 'unknown' audiences pass for profiles without a home_school
    (cross-school hiding is undefined without a home — see
    TestCrossSchoolToggle for the opt-in behavior when one is set)."""

    @staticmethod
    def _opp(ident, school, audience, source_type="campus_program"):
        return {
            "id": ident,
            "source_type": source_type,
            "title": f"Research position {ident}",
            "opportunity_type": "research",
            "school": school,
            "audience": audience,
            "eligibility": {},
            "metadata": {"is_active": True},
        }

    @staticmethod
    def _profile(home_school=None):
        prof = {
            "year": "freshman",
            "major": "CS",
            "preferences": {"min_match_threshold": 0},
        }
        if home_school is not None:
            prof["home_school"] = home_school
        return prof

    @pytest.fixture
    def corpus(self):
        return [
            self._opp("uiuc-campus", "uiuc", "campus"),
            self._opp("ucb-campus", "ucb", "campus"),
            self._opp("ucb-unknown", "ucb", "unknown"),
            self._opp("national-open", None, "open", source_type="external"),
        ]

    def _ids(self, profile, corpus):
        return {r.opportunity_id for r in rank_all(profile, corpus)}

    def test_default_home_school_is_uiuc_when_absent(self, corpus):
        # No home_school in the profile → 'uiuc': UIUC campus stays, the other
        # school's campus-only record is excluded.
        ids = self._ids(self._profile(), corpus)
        assert "uiuc-campus" in ids
        assert "ucb-campus" not in ids

    def test_home_ucb_shows_ucb_campus_and_hides_uiuc_campus(self, corpus):
        ids = self._ids(self._profile(home_school="ucb"), corpus)
        assert "ucb-campus" in ids
        assert "uiuc-campus" not in ids

    def test_open_and_unknown_visible_from_both_homes(self, corpus):
        for home in (None, "ucb"):
            ids = self._ids(self._profile(home_school=home), corpus)
            assert {"national-open", "ucb-unknown"} <= ids, f"home={home}"

    def test_ucb_faculty_unknown_stays_visible_without_home_school(self):
        # A profile with no home_school keeps the pre-toggle behavior: the
        # UCB faculty cold-email targets (school='ucb', audience='unknown')
        # stay visible even though include_cross_school defaults to off.
        ucb_faculty = self._opp("ucb-fac", "ucb", "unknown")
        ucb_faculty["source"] = "ucb_eecs_faculty"
        ucb_faculty["source_type"] = "faculty_research"
        ids = self._ids(self._profile(), [ucb_faculty])
        assert ids == {"ucb-fac"}

    def test_untagged_and_national_records_always_pass(self):
        # Records without school/audience (pre-migration shape) and national
        # records (school=None) are never scope-filtered.
        corpus = [
            self._opp("national-open", None, "open", source_type="external"),
            {
                "id": "legacy-untagged",
                "source_type": "manual",
                "title": "Legacy record",
                "opportunity_type": "research",
                "eligibility": {},
                "metadata": {"is_active": True},
            },
        ]
        ids = self._ids(self._profile(home_school="ucb"), corpus)
        assert ids == {"national-open", "legacy-untagged"}


class TestCrossSchoolToggle:
    """Cross-school resources are opt-in (include_cross_school, default off,
    Eric 2026-07: 正常肯定还是会优先本学校的科研): another school's non-campus
    records are hidden unless the toggle is on — except national records
    (school=None) and summer programs, which recruit everywhere. When on, the
    home school wins ties via the HOME_SCHOOL_AFFINITY_MAX additive bonus."""

    @staticmethod
    def _opp(
        ident,
        school,
        audience,
        opportunity_type="research",
        source_type="faculty_research",
    ):
        return {
            "id": ident,
            "source_type": source_type,
            "title": f"Research position {ident}",
            "opportunity_type": opportunity_type,
            "school": school,
            "audience": audience,
            "eligibility": {},
            "metadata": {"is_active": True},
        }

    @staticmethod
    def _profile(include_cross_school=False, home_school="uiuc"):
        return {
            "year": "freshman",
            "major": "CS",
            "home_school": home_school,
            "include_cross_school": include_cross_school,
            "preferences": {"min_match_threshold": 0},
        }

    @pytest.fixture
    def corpus(self):
        return [
            self._opp("home-fac", "uiuc", "unknown"),
            self._opp("ucb-fac", "ucb", "unknown"),
            self._opp("stanford-summer", "stanford", "open",
                      opportunity_type="summer_program",
                      source_type="summer_program"),
            self._opp("national-open", None, "open", source_type="external"),
        ]

    def _ids(self, profile, corpus):
        return {r.opportunity_id for r in rank_all(profile, corpus)}

    def test_off_hides_other_school_faculty(self, corpus):
        ids = self._ids(self._profile(), corpus)
        assert "home-fac" in ids
        assert "ucb-fac" not in ids

    def test_off_keeps_national_and_summer_programs(self, corpus):
        ids = self._ids(self._profile(), corpus)
        assert {"national-open", "stanford-summer"} <= ids

    def test_on_shows_other_school_records(self, corpus):
        ids = self._ids(self._profile(include_cross_school=True), corpus)
        assert {"home-fac", "ucb-fac", "stanford-summer", "national-open"} <= ids

    def test_no_home_school_keeps_pre_toggle_behavior(self, corpus):
        prof = self._profile()
        del prof["home_school"]
        assert "ucb-fac" in self._ids(prof, corpus)

    def test_uiuc_faculty_symmetric_cross_school(self):
        # Symmetry regression: uiuc_faculty is (uiuc, unknown) like every
        # other school's directory, so a UCB student sees it exactly when the
        # toggle is on.
        fac = self._opp("uiuc-fac", "uiuc", "unknown")
        on = self._profile(include_cross_school=True, home_school="ucb")
        off = self._profile(home_school="ucb")
        assert self._ids(on, [fac]) == {"uiuc-fac"}
        assert self._ids(off, [fac]) == set()

    def test_home_school_bonus_orders_home_first_on_ties(self):
        corpus = [
            self._opp("ucb-fac", "ucb", "unknown"),
            self._opp("home-fac", "uiuc", "unknown"),
        ]
        results = rank_all(self._profile(include_cross_school=True), corpus)
        assert [r.opportunity_id for r in results] == ["home-fac", "ucb-fac"]
        assert results[0].final_score > results[1].final_score

    def test_home_school_bonus_never_outranks_better_topical_match(self):
        prof = self._profile(include_cross_school=True)
        prof["research_interests_text"] = "machine learning"
        prof["desired_fields"] = ["machine learning"]
        strong = self._opp("ucb-ml", "ucb", "unknown")
        strong["keywords"] = ["machine learning"]
        weak = self._opp("home-other", "uiuc", "unknown")
        weak["keywords"] = ["medieval history"]
        results = rank_all(prof, [strong, weak])
        assert results[0].opportunity_id == "ucb-ml"

    def test_bonus_inert_when_toggle_off(self):
        prof = self._profile()
        home = self._opp("home-fac", "uiuc", "unknown")
        assert _home_school_affinity(prof, home) == 0.0
        prof_on = self._profile(include_cross_school=True)
        assert _home_school_affinity(prof_on, home) == HOME_SCHOOL_AFFINITY_MAX


class TestExploreMajorFloor:
    """exploring=True lifts both major-mismatch tiers to a single floor so an
    undecided student's other-domain options aren't buried as 'wrong major'."""

    def test_cross_domain_mismatch_lifted(self):
        normal = _major_match_score(["Spanish"], ["CS"])
        explore = _major_match_score(["Spanish"], ["CS"], exploring=True)
        assert normal <= 10.0
        assert explore > normal
        assert explore == EXPLORE_MAJOR_MISMATCH_FLOOR

    def test_same_domain_mismatch_lifted(self):
        normal = _major_match_score(["Biology"], ["CS"])
        explore = _major_match_score(["Biology"], ["CS"], exploring=True)
        assert explore >= normal
        assert explore == EXPLORE_MAJOR_MISMATCH_FLOOR

    def test_exact_and_related_unchanged(self):
        # exploring must not change a real match — only lift the mismatch floor.
        assert _major_match_score(["ECE"], ["ECE"], exploring=True) == 100.0
        assert _major_match_score(["ECE"], ["CS"], exploring=True) == 70.0


class TestExploreTopicPenalty:
    """An explorer is never topic-penalized — a 'mismatch' is the breadth they
    want, not a poor fit."""

    def _research(self, keywords):
        return {"opportunity_type": "research", "keywords": keywords}

    def test_confirmed_mismatch_not_penalized_when_exploring(self):
        opp = self._research(["computers and education", "computer science"])
        interest = "machine learning, computer vision, deep learning"
        # Normally this is a confirmed mismatch …
        assert _topic_alignment_penalty({"research_interests_text": interest}, opp) == TOPIC_MISMATCH_PENALTY
        # … but an explorer with the same stated interests sees no penalty.
        assert _topic_alignment_penalty(
            {"research_interests_text": interest, "exploring": True}, opp
        ) == 1.0


class TestExploreWeights:
    def test_exploring_de_emphasizes_readiness(self):
        base = _compute_weights(50, exploring=False)
        expl = _compute_weights(50, exploring=True)
        assert expl["readiness"] < base["readiness"]
        assert expl["eligibility"] >= base["eligibility"]
        assert expl["upside"] >= base["upside"]
        # weights still sum to 1 and stay valid
        assert abs(sum(expl.values()) - 1.0) < 1e-9
        assert expl["readiness"] >= 0.05

    def test_default_path_weights_unchanged(self):
        # the guardrail: exploring=False must leave the blend untouched.
        assert _compute_weights(50, exploring=False) == _compute_weights(50)


class TestExploreDiversity:
    """exploring=True diversity-samples the top buckets so the visible order
    spans research areas / opportunity types instead of one cluster — WITHOUT
    changing which bucket anything lands in (the quality floor is untouched)."""

    def _opps(self):
        # 18 research postings across 3 areas, all near-identical score so the
        # default order would clump them area-by-area (insertion order).
        opps = []
        areas = [("nlp", "ml-lab"), ("robotics", "robo-lab"), ("genomics", "bio-lab")]
        for area, dept in areas:
            for i in range(6):
                opps.append({
                    "id": f"{area}-{i}",
                    "source_type": "campus_program",
                    "title": f"{area} lab {i}",
                    "opportunity_type": "research",
                    "is_rolling": True,
                    "department": dept,
                    "keywords": [area],
                    "eligibility": {
                        "preferred_year": ["freshman", "sophomore", "junior"],
                        "majors": [],
                        "international_friendly": "yes",
                    },
                    "metadata": {"is_active": True},
                })
        return opps

    def _profile(self, exploring):
        # No major: this fixture tests diversity reordering in isolation, so the
        # opps must stay equal-scored. A major would (correctly) let the implicit
        # major→keyword bridge lift its field's area (e.g. ECE→robotics) above the
        # others — real behavior, but orthogonal to what these tests assert.
        return {
            "year": "freshman", "major": "", "secondary_interests": [],
            "international_student": False, "hard_skills": [],
            "seeking_type": ["research"], "research_interests_text": "",
            "search_weight": 50, "exploring": exploring,
            "preferences": {"min_match_threshold": 0},
        }

    def _areas_of(self, results, opps):
        by_id = {o["id"]: o for o in opps}
        return [by_id[r.opportunity_id]["keywords"][0] for r in results]

    def test_default_order_has_no_diversity_reorder(self):
        opps = self._opps()
        a = [r.opportunity_id for r in rank_all(self._profile(False), opps)]
        # default = no diversity reorder; equal scores order by id (the
        # deterministic tie-break), independent of corpus file order
        assert a == sorted(a)
        b = [r.opportunity_id for r in rank_all(self._profile(False), list(reversed(opps)))]
        assert b == a

    def test_exploring_interleaves_areas_at_the_top(self):
        opps = self._opps()
        res = rank_all(self._profile(True), opps)
        head = self._areas_of(res, opps)[:6]
        # the first 6 rows should NOT be a single clustered area; with 3 areas a
        # round-robin yields each area at least once in the first 3 slots.
        assert len(set(head[:3])) == 3
        assert len(set(head)) == 3

    def test_buckets_unchanged_by_diversify(self):
        opps = self._opps()
        plain = rank_all(self._profile(False), opps)
        expl = rank_all(self._profile(True), opps)
        # same multiset of (id -> bucket): diversify only reorders within a band.
        assert {r.opportunity_id: r.bucket for r in plain} == {
            r.opportunity_id: r.bucket for r in expl
        }


class TestMajorTopicBridge:
    """Major→topical-keyword bridge: a student with no explicit interests still
    gets a field steer from their major, but it never outranks a stated interest."""

    def test_cs_major_yields_cs_keywords(self):
        kw = _profile_implicit_keywords({"major": "Computer Science"})
        assert {"machine learning", "artificial intelligence"} <= kw

    def test_vet_major_yields_bio_keywords(self):
        kw = _profile_implicit_keywords({"major": "Veterinary Medicine"})
        assert "animal sciences" in kw and "integrative biology" in kw

    def test_secondary_interests_contribute(self):
        kw = _profile_implicit_keywords({"major": "", "secondary_interests": ["Statistics"]})
        assert "statistics" in kw

    def test_unmapped_major_never_raises(self):
        # A major with no group and no related edge returns a set, never errors.
        assert isinstance(_profile_implicit_keywords({"major": "Underwater Basket Weaving"}), set)

    def _opp(self, keywords):
        return {"id": "x", "keywords": keywords, "paid": "unknown", "eligibility": {},
                "source_type": "", "lab_or_program": "", "pi_name": ""}

    def test_implicit_lifts_a_baseline_opportunity(self):
        prof = {"desired_fields": [], "research_interests_text": ""}
        opp = self._opp(["robotics"])
        without = score_upside(prof, opp)[0]
        with_impl = score_upside(prof, opp, implicit_keywords={"robotics"})[0]
        assert with_impl > without

    def test_implicit_never_outranks_an_explicit_match(self):
        # max()-fold precedence: an opp the student EXPLICITLY matches scores the
        # same with or without the implicit major signal — explicit always leads.
        prof = {"desired_fields": ["machine learning"], "research_interests_text": ""}
        opp = self._opp(["machine learning"])
        explicit_only = score_upside(prof, opp)[0]
        with_impl = score_upside(prof, opp, implicit_keywords={"machine learning"})[0]
        assert with_impl == explicit_only


class TestStructuralMajorWeight:
    """Major carries more of the eligibility layer than before, but the layer
    still sums to 1.0 and exact match lifts a field-restricted opportunity."""

    def test_eligibility_subweights_sum_to_one(self):
        from src.matcher.config import ELIG_MAJOR_WEIGHT
        rem = 1.0 - ELIG_MAJOR_WEIGHT
        total = ELIG_MAJOR_WEIGHT + rem * (0.375 + 0.25 + 0.1875 + 0.1875)
        assert abs(total - 1.0) < 1e-9

    def _restricted_opp(self):
        return {
            "id": "r", "opportunity_type": "research", "is_rolling": True,
            "keywords": [], "eligibility": {
                "preferred_year": ["freshman", "sophomore", "junior"],
                "majors": ["CS"], "international_friendly": "yes",
            },
        }

    def test_exact_major_lifts_eligibility_over_cross_domain(self):
        opp = self._restricted_opp()
        cs = {"year": "sophomore", "major": "Computer Science", "secondary_interests": [],
              "hard_skills": [], "seeking_type": ["research"]}
        spanish = {"year": "sophomore", "major": "Spanish", "secondary_interests": [],
                   "hard_skills": [], "seeking_type": ["research"]}
        assert score_eligibility(cs, opp)[0] > score_eligibility(spanish, opp)[0]


class TestCollegeAffinity:
    """College → opportunity.department affinity: a small bonus when they match,
    and never a penalty when the department is missing or the college unknown."""

    def test_matching_department_gives_bonus(self):
        from src.matcher.config import COLLEGE_AFFINITY_MAX
        prof = {"college": "Grainger College of Engineering"}
        opp = {"department": "Electrical & Computer Engineering"}
        assert _college_affinity(prof, opp) == COLLEGE_AFFINITY_MAX

    def test_missing_department_no_bonus_no_penalty(self):
        prof = {"college": "Grainger College of Engineering"}
        assert _college_affinity(prof, {"department": ""}) == 0.0
        assert _college_affinity(prof, {}) == 0.0

    def test_unknown_college_no_bonus(self):
        assert _college_affinity({"college": "Hogwarts"}, {"department": "Potions"}) == 0.0

    def test_non_matching_department_no_bonus(self):
        prof = {"college": "Grainger College of Engineering"}
        assert _college_affinity(prof, {"department": "Department of History"}) == 0.0


class TestMajorDriveRealCorpus:
    """On the real corpus: an empty-interest student's results actually change
    with their major, and the field-relevant count is honest (thin for a field
    the corpus barely covers)."""

    def _opps(self):
        return _load_corpus()

    def _profile(self, major):
        return {"year": "sophomore", "major": major, "secondary_interests": [],
                "international_student": False, "hard_skills": [], "coursework": [],
                "seeking_type": ["research", "summer_program"], "research_interests_text": "",
                "desired_fields": [], "search_weight": 50,
                "preferences": {"min_match_threshold": 25}}

    def test_empty_interest_major_changes_results(self):
        opps = self._opps()
        cs = [r.opportunity_id for r in rank_all(self._profile("Computer Science"), opps)[:10]]
        vet = [r.opportunity_id for r in rank_all(self._profile("Veterinary Medicine"), opps)[:10]]
        assert cs != vet  # major now reorders an otherwise-identical (empty-interest) query

    def test_field_relevant_count_is_honest(self):
        opps = self._opps()
        cs = rank_all(self._profile("Computer Science"), opps)
        vet = rank_all(self._profile("Veterinary Medicine"), opps)
        cs_rel = sum(1 for r in cs if r.bucket != "low_fit" and r.field_relevant)
        vet_rel = sum(1 for r in vet if r.bucket != "low_fit" and r.field_relevant)
        # The CS-dominated corpus has far more CS-relevant inventory than vet.
        assert cs_rel > vet_rel


class TestCorpusPrecomputeEquivalence:
    """The per-record precompute (register_corpus: statics + TF-IDF row matrix)
    is a pure hoist — ranking a registered corpus must be byte-identical to
    ranking the same records unregistered (the ad-hoc compute path)."""

    def _mini_corpus(self):
        base_deadline = (date.today() + timedelta(days=20)).isoformat()
        passed_deadline = (date.today() - timedelta(days=30)).isoformat()
        corpus = []
        kw_pool = [
            ["machine learning", "computer vision", "robotics"],
            ["computational biology", "genomics"],
            ["quantum", "condensed matter physics", "physics"],
            ["medieval history", "poetry"],
            ["natural language processing", "large language models"],
            ["undergraduate research", "engineering"],
            [],
            ["data science", "statistics", "optimization"],
        ]
        for i in range(32):
            kws = kw_pool[i % len(kw_pool)]
            corpus.append({
                "id": f"pre-{i}",
                "title": f"Research Assistant {i} — {kws[0] if kws else 'General'}",
                "organization": "University of Illinois" if i % 3 else "NASA JPL",
                "opportunity_type": ["research", "internship", "summer_program"][i % 3],
                "school": ["uiuc", "ucb", None][i % 3],
                "on_campus": i % 2 == 0,
                "paid": ["yes", "stipend", "unknown", "no"][i % 4],
                "deadline": [base_deadline, passed_deadline, ""][i % 3],
                "keywords": kws,
                "pi_name": f"Ada Lovelace {i}" if i % 4 == 0 else "",
                "lab_or_program": f"Vision Lab {i}" if i % 5 == 0 else "",
                "department": ["Computer Science", "Electrical & Computer Engineering", ""][i % 3],
                "source_type": "faculty_research" if i % 2 == 0 else "job_board",
                "is_rolling": i % 2 == 0,
                "description_raw": (
                    f"Position {i}: mentorship and training with publication and "
                    "conference opportunities for undergraduate students."
                    + (" PhD students preferred." if i % 7 == 0 else "")
                ),
                "eligibility": {
                    "preferred_year": [["freshman", "sophomore"], ["junior", "senior"], []][i % 3],
                    "majors": [["Computer Science"], ["Physics"], []][i % 3],
                    "international_friendly": ["yes", "unknown", "no"][i % 3],
                    "skills_required": [["python", "pytorch"], [], ["r"]][i % 3],
                },
                "application": {"application_effort": ["low", "medium", "high"][i % 3],
                                "requires_resume": "yes"},
            })
        return corpus

    def _profiles(self):
        explicit = {
            "year": "sophomore", "major": "ECE", "secondary_interests": ["CS"],
            "international_student": True, "home_school": "uiuc",
            "include_cross_school": True,
            "hard_skills": [{"name": "Python", "level": "experienced"},
                            {"name": "PyTorch", "level": "beginner"}],
            "coursework": ["ECE 120", "CS 225"], "experience_level": "some",
            "resume_ready": True, "can_cold_email": True,
            "research_interests_text": "machine learning for computer vision and robotics",
            "desired_fields": ["machine learning", "robotics"],
            "seeking_type": [], "search_weight": 70,
            "college": "Grainger College of Engineering",
            "preferences": {"min_match_threshold": 0},
        }
        implicit_only = {
            **explicit,
            "research_interests_text": "", "desired_fields": [],
            "search_weight": 30, "exploring": True,
        }
        return explicit, implicit_only

    @pytest.fixture
    def _isolated_precompute(self):
        import src.matcher.embeddings as emb
        import src.matcher.ranker as rk
        saved = (emb._tfidf_vectorizer, emb._tfidf_fitted, rk._corpus_ref,
                 rk._corpus_rows, rk._static_cache, rk._sim_matrix)
        yield
        (emb._tfidf_vectorizer, emb._tfidf_fitted, rk._corpus_ref,
         rk._corpus_rows, rk._static_cache, rk._sim_matrix) = saved

    def test_top20_byte_identical_with_and_without_precompute(self, _isolated_precompute):
        from dataclasses import asdict

        import src.matcher.embeddings as emb
        import src.matcher.ranker as rk
        from backend.data_loader import _opportunity_corpus_text

        corpus = self._mini_corpus()
        emb.fit_tfidf_corpus([_opportunity_corpus_text(o) for o in corpus])

        rk.register_corpus([])  # unbind: forces the ad-hoc per-call path
        baselines = [rank_all(p, corpus) for p in self._profiles()]

        rk.register_corpus(corpus)
        assert rk._sim_matrix is not None  # the TF-IDF row matrix engaged
        fasts = [rank_all(p, corpus) for p in self._profiles()]

        for baseline, fast in zip(baselines, fasts, strict=False):
            top_base = json.dumps([asdict(r) for r in baseline[:20]], sort_keys=True)
            top_fast = json.dumps([asdict(r) for r in fast[:20]], sort_keys=True)
            assert top_fast == top_base
            assert [asdict(r) for r in fast] == [asdict(r) for r in baseline]

    def test_register_corpus_invalidates_on_new_list(self, _isolated_precompute):
        import src.matcher.ranker as rk
        corpus = self._mini_corpus()
        rk.register_corpus(corpus)
        st_first = rk._opp_static(corpus[0])
        assert rk._opp_static(corpus[0]) is st_first  # cached for the bound list

        reloaded = [dict(o) for o in corpus]
        rk.register_corpus(reloaded)
        assert rk._corpus_ref is reloaded
        assert rk._opp_static(corpus[0]) is not st_first  # old ids no longer cached

    def test_hot_reload_waits_for_complete_score_generation(
        self,
        _isolated_precompute,
        monkeypatch,
    ):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        import src.matcher.ranker as rk

        corpus = self._mini_corpus()
        reloaded = [dict(opportunity) for opportunity in corpus]
        profile = self._profiles()[0]
        rk.register_corpus(corpus)

        scorer_entered = threading.Event()
        release_scorer = threading.Event()
        reload_finished = threading.Event()
        original_chunk_similarities = rk._chunk_similarities

        def blocked_chunk_similarities(*args, **kwargs):
            scorer_entered.set()
            if not release_scorer.wait(timeout=5):
                raise TimeoutError("test did not release scorer")
            return original_chunk_similarities(*args, **kwargs)

        monkeypatch.setattr(rk, "_chunk_similarities", blocked_chunk_similarities)

        def reload():
            rk.register_corpus(reloaded)
            reload_finished.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            score_future = executor.submit(rk.rank_all, profile, corpus)
            assert scorer_entered.wait(timeout=5)
            reload_future = executor.submit(reload)
            try:
                assert not reload_finished.wait(timeout=0.1), (
                    "reload must not replace the registered matrix mid-score"
                )
            finally:
                release_scorer.set()
            assert score_future.result(timeout=5)
            reload_future.result(timeout=5)

        assert reload_finished.is_set()
        assert rk._corpus_ref is reloaded

    def test_queued_old_generation_is_rejected_after_reload_wins_lock(
        self,
        _isolated_precompute,
        monkeypatch,
    ):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        import backend.routes.matches as match_routes
        import src.matcher.ranker as rk

        corpus = self._mini_corpus()
        reloaded = [dict(opportunity) for opportunity in corpus]
        profile = self._profiles()[0]
        rk.register_corpus(corpus)
        monkeypatch.setattr(
            match_routes,
            "_active_corpus_identity",
            id(corpus),
        )

        reload_holds_lock = threading.Event()
        finish_reload = threading.Event()

        def reload_first():
            with rk.corpus_generation_lock:
                reload_holds_lock.set()
                if not finish_reload.wait(timeout=5):
                    raise TimeoutError("test did not finish reload")
                rk._register_corpus_unlocked(reloaded)
                match_routes._activate_corpus_generation(reloaded)

        with ThreadPoolExecutor(max_workers=1) as executor:
            reload_future = executor.submit(reload_first)
            assert reload_holds_lock.wait(timeout=5)
            stale_future = executor.submit(
                match_routes._compute_rule_snapshot,
                "stale-generation",
                profile,
                id(corpus),
                corpus,
                None,
            )
            finish_reload.set()
            reload_future.result(timeout=5)
            with pytest.raises(match_routes._MatchGenerationChanged):
                stale_future.result(timeout=5)

        assert "stale-generation" not in match_routes._match_snapshots

    def test_registered_subset_reuses_full_corpus_rows_exactly(self, _isolated_precompute):
        import src.matcher.embeddings as emb
        import src.matcher.ranker as rk
        from backend.data_loader import _opportunity_corpus_text

        corpus = self._mini_corpus()
        emb.fit_tfidf_corpus([_opportunity_corpus_text(o) for o in corpus])
        rk.register_corpus(corpus)
        subset = [corpus[i] for i in (1, 4, 7, 19, 23)]
        query = "machine learning computer vision"

        reused = rk._corpus_sims_precomputed(query, subset)
        direct = emb.semantic_similarity_batch(
            query,
            [rk._similarity_corpus(o) for o in subset],
            allow_embeddings=False,
        )
        assert reused == direct

    def test_compact_visible_universe_is_byte_identical(self, _isolated_precompute):
        from dataclasses import asdict

        import src.matcher.embeddings as emb
        import src.matcher.ranker as rk
        from backend.data_loader import _opportunity_corpus_text

        corpus = self._mini_corpus()
        emb.fit_tfidf_corpus([_opportunity_corpus_text(o) for o in corpus])
        rk.register_corpus(corpus)

        profiles = [
            *self._profiles(),
            {
                **self._profiles()[0],
                "preferences": {"min_match_threshold": 75},
            },
        ]
        for profile in profiles:
            baseline = rk.rank_all(profile, corpus)
            compact = rk.rank_visible_universe(profile, corpus)
            expected_visible = [r for r in baseline if r.bucket != "low_fit"]
            expected_buckets = {
                label: sum(1 for r in baseline if r.bucket == label)
                for label in ("high_priority", "good_match", "reach", "low_fit")
            }
            assert [asdict(r) for r in compact.visible] == [
                asdict(r) for r in expected_visible
            ]
            assert compact.buckets == expected_buckets
            assert compact.field_relevant_count == sum(
                1 for r in expected_visible if r.field_relevant
            )

    def test_compact_explore_uses_complete_universe_for_small_set_guard(
        self,
        _isolated_precompute,
        monkeypatch,
    ):
        import src.matcher.ranker as rk

        opportunities = [
            {"id": "a1", "opportunity_type": "research", "keywords": ["alpha"]},
            {"id": "a2", "opportunity_type": "research", "keywords": ["alpha"]},
            {"id": "b1", "opportunity_type": "research", "keywords": ["beta"]},
            {"id": "z-low", "opportunity_type": "research", "keywords": ["gamma"]},
        ]

        def scored_results():
            return [
                rk.MatchResult(
                    opportunity_id=opportunity_id,
                    eligibility_score=80.0,
                    readiness_score=80.0,
                    upside_score=80.0,
                    final_score=score,
                    bucket="low_fit",
                    reasons_fit=[],
                    reasons_gap=[],
                    next_steps=[],
                )
                for opportunity_id, score in (
                    ("a1", 80.0),
                    ("a2", 79.0),
                    ("b1", 78.0),
                    ("z-low", 10.0),
                )
            ]

        monkeypatch.setattr(
            rk,
            "_iter_scored_results",
            lambda *_args, **_kwargs: iter(scored_results()),
        )
        profile = {"exploring": True}

        baseline = [
            result.opportunity_id
            for result in rk.rank_all(profile, opportunities)
            if result.bucket != "low_fit"
        ]
        compact = [
            result.opportunity_id
            for result in rk.rank_visible_universe(profile, opportunities).visible
        ]

        assert baseline == ["a1", "b1", "a2"]
        assert compact == baseline

    def test_hard_exclusion_runs_before_similarity(self, _isolated_precompute, monkeypatch):
        import src.matcher.ranker as rk

        corpus = self._mini_corpus()
        excluded = {
            **corpus[0],
            "id": "excluded-campus",
            "school": "ucb",
            "audience": "campus",
        }
        seen: list[str] = []

        def fake_sims(_query, opportunities):
            seen.extend(o["id"] for o in opportunities)
            return [0.0] * len(opportunities)

        monkeypatch.setattr(rk, "_chunk_similarities", fake_sims)
        profile = {
            **self._profiles()[0],
            "include_cross_school": False,
        }
        rk.rank_all(profile, [excluded, *corpus])
        assert "excluded-campus" not in seen

    def test_min_threshold_only_applies_after_the_complete_score(
        self,
        _isolated_precompute,
        monkeypatch,
    ):
        import src.matcher.ranker as rk

        opportunity = self._mini_corpus()[0]
        profile = {
            **self._profiles()[0],
            "preferences": {"min_match_threshold": 75},
        }
        monkeypatch.setattr(
            rk,
            "score_eligibility",
            lambda *_args, **_kwargs: (0.0, [], []),
        )
        monkeypatch.setattr(
            rk,
            "_chunk_similarities",
            lambda _query, opportunities: [0.0] * len(opportunities),
        )

        def complete_score(*_args, **_kwargs):
            return rk.MatchResult(
                opportunity_id=opportunity["id"],
                eligibility_score=0.0,
                readiness_score=100.0,
                upside_score=100.0,
                final_score=80.0,
                bucket="high_priority",
                reasons_fit=[],
                reasons_gap=[],
                next_steps=[],
            )

        monkeypatch.setattr(rk, "_rank_opportunity_unlocked", complete_score)
        results = list(rk._iter_scored_results(profile, [opportunity]))

        assert [result.opportunity_id for result in results] == [opportunity["id"]]

    def test_static_cache_is_hard_bounded(self, _isolated_precompute, monkeypatch):
        import src.matcher.ranker as rk

        corpus = self._mini_corpus()[:6]
        monkeypatch.setattr(rk, "_STATIC_CACHE_MAX", 3)
        rk.register_corpus(corpus)
        for opportunity in corpus:
            rk._opp_static(opportunity)
        assert len(rk._static_cache) == 3
        newest = rk._opp_static(corpus[-1])
        assert rk._opp_static(corpus[-1]) is newest


class TestInterestBonusNameLeakage:
    """Interest tokens must match research signal, not the professor's name.
    2026-07 audit: a cancer-immunology student's 'gene/genomics' tokens put
    Gene Fridman (ENT) at #1 and Eugene Finkel (political science) in her
    top-8 at JHU — 10/15 of her matches were name-substring luck."""

    def _opp(self, pi, title, kws):
        return {"id": f"t-{pi.replace(' ', '')}", "opportunity_type": "research",
                "pi_name": pi, "title": title, "keywords": kws,
                "eligibility": {}, "application": {}}

    def test_interest_token_ignores_professor_name(self):
        from src.matcher.ranker import _interest_bonus
        opp = self._opp("Gene Y. Fridman", "Research with Prof. Gene Y. Fridman — SOM", [])
        assert _interest_bonus(
            {"research_interests_text": "cancer immunology, genomics, gene editing"}, opp
        ) == 0.0

    def test_interest_token_no_midword_hit(self):
        from src.matcher.ranker import _interest_bonus
        # even with the name cut out, 'gene' must not hit the middle of a word
        opp = self._opp("Eugene Finkel", "Research with Prof. Eugene Finkel — SAIS",
                        ["eugenics history"])
        assert _interest_bonus({"research_interests_text": "gene editing"}, opp) == 0.0

    def test_interest_token_prefix_still_matches(self):
        from src.matcher.ranker import _interest_bonus
        opp = self._opp("A Person", "Research with Prof. A Person — BIO",
                        ["genetics", "genomic medicine"])
        assert _interest_bonus({"research_interests_text": "gene editing, genomics"}, opp) > 0.0

    def test_real_topical_keyword_unaffected(self):
        from src.matcher.ranker import _interest_bonus
        opp = self._opp("Nicole Baumgarth", "Research with Prof. Nicole Baumgarth — SOM",
                        ["cancer immunology", "B cells"])
        assert _interest_bonus({"research_interests_text": "cancer immunology"}, opp) > 0.0


class TestInterestBonusLowSignalTokens:
    """A lone broad token from the interests ('AI systems' → 'systems') must not
    earn the literal-overlap bonus. 2026-07 dogfood: it prefix-hit 'data and
    information systems' / 'type systems' and put topically-unrelated
    data-systems faculty in an ML student's top-10 at 96.9."""

    def _opp(self, kws):
        return {"id": "t-low-signal", "opportunity_type": "research",
                "pi_name": "A Person", "title": "Research with Prof. A Person",
                "keywords": kws, "eligibility": {}, "application": {}}

    def test_lone_systems_token_earns_no_bonus(self):
        from src.matcher.ranker import _interest_bonus
        opp = self._opp(["data and information systems", "type systems"])
        assert _interest_bonus(
            {"research_interests_text": "AI systems, computational neuroscience"}, opp
        ) == 0.0

    def test_distinctive_token_still_earns_the_bonus(self):
        from src.matcher.ranker import _interest_bonus
        opp = self._opp(["computational neuroscience", "neural circuits"])
        assert _interest_bonus(
            {"research_interests_text": "AI systems, computational neuroscience"}, opp
        ) > 0.0

    def test_all_broad_interest_keeps_its_bonus(self):
        # Adversarial-review HIGH: interests made ENTIRELY of low-signal tokens
        # ("data science") are that student's real topic — wiping the bonus
        # dropped every on-topic result out of the top-25 on the real corpus.
        from src.matcher.ranker import _interest_bonus
        opp = self._opp(["data science", "statistical learning"])
        assert _interest_bonus({"research_interests_text": "data science"}, opp) > 0.0
        opp2 = self._opp(["information theory", "coding theory"])
        assert _interest_bonus({"research_interests_text": "information theory"}, opp2) > 0.0


class TestReasonOrdering:
    """Specific-first display: the topical-tie reason leads, the lab headline
    follows, and boilerplate every card shares ('Accepts …', 'Your major …')
    sinks to the bottom. 2026-07 dogfood: the old elig+ready+up concatenation
    made every card's visible top-3 identical."""

    def _profile(self):
        return {
            "name": "T", "year": "sophomore", "major": "Computer Science",
            "home_school": "uiuc", "school": "UIUC",
            "hard_skills": [{"name": "Python", "level": "experienced"}],
            "research_interests_text": "machine learning, computer vision",
            "desired_fields": ["machine learning", "computer vision"],
            "seeking_type": ["research"], "coursework": [], "search_weight": 50,
            "preferences": {"min_match_threshold": 25, "show_reach_opportunities": True,
                            "prioritize_paid": True, "exclude_citizenship_restricted": True},
        }

    def _opp(self):
        return {
            "id": "t-order", "opportunity_type": "research",
            "title": "Research with Prof. Vision Person",
            "pi_name": "Vision Person",
            "lab_or_program": "Prof. Vision Person's Research Group",
            "keywords": ["computer vision", "machine learning", "medical imaging"],
            "description_raw": "We research computer vision and machine learning for medical imaging.",
            "school": "uiuc", "on_campus": True,
            "eligibility": {"preferred_year": ["sophomore"], "majors": ["Computer Science"]},
            "application": {},
        }

    def test_topical_tie_leads_and_boilerplate_sinks(self):
        from src.matcher.ranker import rank_opportunity
        result = rank_opportunity(self._profile(), self._opp())
        fit = result.reasons_fit
        assert fit, "expected fit reasons"
        # Lead reason is the student-specific topical tie, not 'Accepts …'.
        assert fit[0].startswith(("Your interest in", "Matches your interests:",
                                  "Your research interests align")), fit[0]
        boiler = [i for i, r in enumerate(fit)
                  if r.startswith(("Accepts ", "Your major ("))]
        specific = [i for i, r in enumerate(fit)
                    if r.startswith(("Your interest in", "Matches your interests:"))]
        assert boiler and specific
        assert max(specific) < min(boiler)  # every specific reason above boilerplate

    def test_priority_tiers_are_stable(self):
        from src.matcher.ranker import _reason_priority
        assert _reason_priority("Your interest in vision closely matches their work") == 0
        assert _reason_priority("Matches your interests: machine learning") == 0
        assert _reason_priority("Strong tech stack fit: Python — 1/1 required") == 2
        assert _reason_priority("Paid opportunity") == 5
        assert _reason_priority("Accepts sophomore students") == 6
        assert _reason_priority("Matches your interest in research") == 6
        # School-constant brand lines are boilerplate, not differentiators.
        assert _reason_priority("Major research university — strong resume builder") == 6
        assert _reason_priority("Prestigious institution — strong resume builder") == 6
        assert _reason_priority("Something novel and unclassified") == 4


class TestActionableTieBreak:
    """Scores round to 0.1 and keyword-thin schools produce 8-way tie walls
    ordered by record id — the audit found #1 matches with no email while
    equal-scored contactable peers sat below. Within a tie, actionable first."""

    def _opp(self, oid, email=None, app_url=None, method="email", email_verified=False):
        # the faculty shape: contact_method='email' and application_url stamped
        # with the PROFILE url — that url must not count as actionability.
        # email_verified=True attaches the complete, fresh identity-bound
        # evidence tuple verified_send_target requires (including url/
        # source_url matching the evidence's source URL, since a
        # bound_profile_* source ties evidence to the record's own profile
        # identity) — a bare `email` alone (the profile_page/legacy shape)
        # is deliberately NOT actionable since it carries no such evidence.
        url = app_url or f"https://x.edu/{oid}"
        metadata = {}
        if email and email_verified:
            metadata = {
                "identity_bound": True,
                "email_source": "bound_profile_container",
                "contact_verified_email": email,
                "contact_source_url": url,
                "contact_verified_at": datetime.now(UTC).isoformat(),
            }
        opp = {"id": oid, "source_type": "faculty_research",
               "opportunity_type": "research", "pi_name": f"P {oid}",
               "title": f"Research with Prof. P {oid}", "keywords": ["robotics"],
               "contact_email": email,
               "eligibility": {},
               "metadata": metadata,
               "application": {"contact_method": method, "application_url": url}}
        if email and email_verified:
            opp["url"] = url
            opp["source_url"] = url
        return opp

    def test_tied_scores_prefer_actionable(self):
        from src.matcher.ranker import rank_all
        profile = {"year": "junior", "major": "Computer Science",
                   "research_interests_text": "robotics"}
        opps = [
            self._opp("a-dead-end"),
            self._opp("b-email", email="p@x.edu", email_verified=True),
            self._opp("c-app-url", app_url="https://x.edu/apply", method="website"),
        ]
        results = rank_all(profile, opps)
        scores = {r.final_score for r in results}
        assert len(scores) == 1  # identical records = a true tie wall
        assert [r.opportunity_id for r in results] == ["b-email", "c-app-url", "a-dead-end"]

    def test_legacy_email_never_outranks_verified_bound_email_in_tie(self):
        # Equal-score counterfactual for the ranker/reveal parity fix: a
        # legacy/unverified email (profile_page shape — real address, no
        # identity-bound evidence) must not win the actionable tie-break
        # over a fully verified-bound one, and must not be treated as
        # actionable itself — it ties with the true dead-end instead.
        from src.matcher.ranker import rank_all
        profile = {"year": "junior", "major": "Computer Science",
                   "research_interests_text": "robotics"}
        opps = [
            self._opp("a-dead-end"),
            self._opp("b-legacy-email", email="p@x.edu"),
            self._opp("c-verified-email", email="q@x.edu", email_verified=True),
        ]
        results = rank_all(profile, opps)
        scores = {r.final_score for r in results}
        assert len(scores) == 1  # true tie wall
        # Evidence ladder (W7a reconciliation): fully-bound beats legacy,
        # legacy beats the dead end — a legacy address IS actionable (the
        # product reveals and sends it), it just never outranks proof.
        assert [r.opportunity_id for r in results] == [
            "c-verified-email", "b-legacy-email", "a-dead-end",
        ]

    def test_score_still_dominates_actionability(self):
        from src.matcher.ranker import rank_all
        profile = {"year": "junior", "major": "Computer Science",
                   "research_interests_text": "robotics"}
        strong = self._opp("z-strong")
        strong["keywords"] = ["robotics", "robot manipulation", "motion planning"]
        weak = self._opp("a-weak", email="p@x.edu", email_verified=True)
        weak["keywords"] = ["ceramics"]
        results = rank_all(profile, [strong, weak])
        assert results[0].opportunity_id == "z-strong"  # actionable weak still loses on score


class TestEmptyInterestMajorBonus:
    """With no stated interests the major is the only topical signal — the
    2026-07 audit found a CogSci freshman's own CogSci faculty at #12-15,
    under a radio-astronomy REU, separated by ~3 points of generic polish."""

    def _fac(self, oid, majors):
        return {"id": oid, "source_type": "faculty_research",
                "opportunity_type": "research", "pi_name": f"P {oid}",
                "title": f"Research with Prof. P {oid}", "keywords": [],
                "eligibility": {"majors": majors}, "application": {}}

    def test_major_direct_leads_when_interests_empty(self):
        from src.matcher.ranker import rank_all
        profile = {"year": "freshman", "major": "Cognitive Science",
                   "research_interests_text": "", "exploring": True}
        results = rank_all(profile, [
            self._fac("a-offfield", ["Astronomy"]),
            self._fac("b-openmajor", []),
            self._fac("c-cogsci", ["Cognitive Science"]),
        ])
        assert results[0].opportunity_id == "c-cogsci"

    def test_no_bonus_once_interests_present(self):
        from src.matcher.ranker import _empty_interest_major_bonus
        opp = self._fac("c-cogsci", ["Cognitive Science"])
        profile = {"major": "Cognitive Science",
                   "research_interests_text": "memory and attention"}
        assert _empty_interest_major_bonus(profile, opp) == 0.0

    def test_no_bonus_for_related_but_not_direct(self):
        from src.matcher.ranker import _empty_interest_major_bonus
        opp = self._fac("d-related", ["Psychology"])
        profile = {"major": "Cognitive Science", "research_interests_text": ""}
        assert _empty_interest_major_bonus(profile, opp) == 0.0


class TestAnsweringNeverCostsYou:
    """Filling in a profile field must never score worse than leaving it blank.

    Coursework had exactly that shape. The no-answer default was 30 and each
    course was worth 12, so a student who typed one course scored 12 and a
    student who typed two scored 24 — both BELOW the 30 handed to a student who
    typed nothing. The form asks for coursework on the first screen; answering
    it honestly cost you up to 18 points of readiness against staying silent.

    The rule this pins is about the semantics of an unknown, not about the
    constants: a blank is a neutral prior, so information may move a student up
    from it or leave them level, and may never move them down.
    """

    @staticmethod
    def _opp_without_course_signals() -> dict:
        # No keywords/skills for a course code to match, so the relevance bonus
        # cannot mask the count component being tested here.
        return {"id": "o1", "title": "Lab position", "description": "",
                "keywords": [], "eligibility": {}, "application": {}}

    def test_one_course_is_never_worth_less_than_no_courses(self):
        from src.matcher.ranker import _coursework_score

        opp = self._opp_without_course_signals()
        blank = _coursework_score(frozenset(), opp)
        for n in range(1, 8):
            courses = frozenset(f"ECE {100 + i}" for i in range(n))
            assert _coursework_score(courses, opp) >= blank, (
                f"{n} course(s) scored below listing none ({blank})"
            )

    def test_more_coursework_never_scores_lower_than_less(self):
        from src.matcher.ranker import _coursework_score

        opp = self._opp_without_course_signals()
        scores = [
            _coursework_score(frozenset(f"ECE {100 + i}" for i in range(n)), opp)
            for n in range(0, 10)
        ]
        assert scores == sorted(scores), f"non-monotone in course count: {scores}"

    def test_a_relevant_course_still_pays_on_top_of_the_floor(self):
        """The floor must not swallow the relevance bonus — otherwise raising it
        would quietly delete the signal that a course matches the target."""
        from src.matcher.ranker import _coursework_score

        relevant = {"id": "o2", "title": "CS lab", "description": "",
                    "keywords": ["cs"], "eligibility": {}, "application": {}}
        one_relevant = _coursework_score(frozenset({"CS 225"}), relevant)
        one_irrelevant = _coursework_score(
            frozenset({"CS 225"}), self._opp_without_course_signals()
        )
        assert one_relevant > one_irrelevant
