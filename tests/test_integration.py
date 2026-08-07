"""
End-to-end integration tests for the Opportunity Filter Engine.
Covers: collector→normalizer pipeline, tagger updates, ranker sanity,
        cold email generator, resume advisor, and data integrity.

Run with: pytest tests/test_integration.py -v
"""

import copy
import functools
import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.ranker import rank_all, rank_opportunity
from src.normalizers.normalizer import normalize
from src.parsers.llm_tagger import _build_full_text, apply_updates, needs_tagging, rule_based_tag
from src.recommender.cold_email import (
    _detect_lab_type,
    generate_cold_email,
    generate_variants,
)
from src.recommender.resume_advisor import analyze_gaps

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")


@functools.lru_cache(maxsize=1)
def _load_real_data():
    # Parsed once per session and shared read-only across every test that reads
    # the real corpus. The file is 300 MB+; re-parsing it per test was pure
    # redundant CI cost. Do not mutate the returned records.
    if not os.path.exists(DATA_PATH):
        pytest.skip("No processed data file")
    with open(DATA_PATH) as f:
        return json.load(f)


_SAMPLE_PROFILE = {
    "name": "Test Student",
    "school": "UIUC",
    "year": "sophomore",
    "major": "CS",
    "secondary_interests": ["ECE", "Data Science"],
    "international_student": True,
    "hard_skills": ["Python", "Java", "C++"],
    "coursework": ["CS 124", "STAT 107"],
    "experience_level": "beginner",
    "resume_ready": True,
    "can_cold_email": True,
    "projects": [
        {"name": "ChatBot", "description": "Built a chatbot using Python and Flask"}
    ],
    "preferences": {
        "min_match_threshold": 0,
        "exclude_citizenship_restricted": True,
    },
}


@pytest.fixture
def sample_profile():
    # Deep-copied so a test that mutates its profile can't leak into another.
    return copy.deepcopy(_SAMPLE_PROFILE)


@pytest.fixture(scope="module")
def sanity_ranked_results():
    # The ranker-sanity tests each assert a different invariant over the SAME
    # rank_all(sample_profile, corpus) result. Ranking the full 128k-record
    # corpus is ~25s, so compute it once and share it read-only rather than
    # re-ranking per assertion. rank_all mutates neither its profile nor the
    # corpus, so the shared result is safe.
    return rank_all(copy.deepcopy(_SAMPLE_PROFILE), _load_real_data())


@pytest.fixture
def sample_opportunity():
    return {
        "id": "test-opp-001",
        "title": "ML Research Assistant — Data Science Lab",
        "organization": "University of Illinois",
        "department": "Computer Science",
        "lab_or_program": "Data Science Lab",
        "pi_name": "Prof. Jane Smith",
        "url": "https://example.com/opportunity/machine-learning-reu",
        "on_campus": True,
        "opportunity_type": "research",
        "paid": "yes",
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
        "description_raw": "Looking for undergrads with Python and machine learning experience.",
        "description_clean": "Looking for undergrads with Python and ML experience.",
        "keywords": ["machine learning", "data science"],
        "eligibility": {
            "preferred_year": ["sophomore", "junior"],
            "majors": ["CS", "ECE", "STAT"],
            "skills_required": ["Python"],
            "skills_preferred": ["PyTorch", "pandas"],
            "international_friendly": "yes",
            "citizenship_required": False,
            "eligibility_text_raw": "",
        },
        "application": {
            "contact_method": "email",
            "requires_resume": "yes",
            "requires_cover_letter": "no",
            "requires_recommendation": "no",
            "application_effort": "low",
        },
        "metadata": {"is_active": True},
    }


# ── Test: Collector → Normalizer Pipeline ────────────────


class TestNormalizerPipeline:
    def test_normalize_produces_valid_schema(self):
        raw = {
            "title": "Summer REU in Biology",
            "description_raw": "A 10-week summer program for undergraduate researchers.",
            "url": "https://example.com/reu",
            "source": "test",
        }
        result = normalize(raw)
        assert result["id"], "Normalized entry must have an id"
        assert result["title"] == "Summer REU in Biology"
        assert isinstance(result["eligibility"], dict)
        assert "skills_required" in result["eligibility"]
        assert "preferred_year" in result["eligibility"]
        assert result["source"] == "test"

    def test_normalize_extracts_skills_from_description(self):
        raw = {
            "title": "Research Position",
            "description_raw": "Must know Python and R for data analysis. MATLAB preferred.",
            "url": "https://example.com",
        }
        result = normalize(raw)
        skills = result["eligibility"]["skills_required"] + result["eligibility"]["skills_preferred"]
        assert "Python" in skills or "R" in skills

    def test_normalize_handles_empty_input(self):
        raw = {"title": "Minimal Entry", "url": "https://example.com"}
        result = normalize(raw)
        assert result["title"] == "Minimal Entry"
        assert isinstance(result["eligibility"], dict)


# ── Test: Tagger Actually Updates Fields ────────────────


class TestTaggerUpdates:
    def test_rule_based_tag_extracts_skills_from_title(self):
        opp = {
            "title": "Python Developer for Data Science Lab",
            "description_raw": "",
            "description_clean": "",
            "url": "",
            "keywords": ["data science"],
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
            "paid": "unknown",
        }
        updates = rule_based_tag(opp)
        assert "skills_required" in updates or "skills_preferred" in updates
        all_skills = updates.get("skills_required", []) + updates.get("skills_preferred", [])
        assert "Python" in all_skills

    def test_rule_based_tag_extracts_from_url_path(self):
        opp = {
            "title": "Summer Program",
            "description_raw": "",
            "description_clean": "",
            "url": "https://example.com/opportunity/chemistry-reu-colorado-state",
            "keywords": [],
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
            "paid": "unknown",
        }
        full_text = _build_full_text(opp)
        assert "chemistry" in full_text.lower()

    def test_rule_based_tag_extracts_from_keywords(self):
        opp = {
            "title": "Research Assistant",
            "description_raw": "",
            "description_clean": "",
            "url": "",
            "keywords": ["machine learning", "computer vision"],
            "lab_or_program": "CV Lab",
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
            "paid": "unknown",
        }
        updates = rule_based_tag(opp)
        all_skills = updates.get("skills_required", []) + updates.get("skills_preferred", [])
        assert len(all_skills) > 0, "Should infer skills from domain keywords"

    def test_apply_updates_modifies_opportunity(self):
        opp = {
            "paid": "unknown",
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
        }
        updates = {
            "paid": "yes",
            "skills_required": ["Python"],
            "international_friendly": "yes",
            "citizenship_required": False,
        }
        changed = apply_updates(opp, updates)
        assert changed is True
        assert opp["paid"] == "yes"
        assert opp["eligibility"]["skills_required"] == ["Python"]
        assert opp["eligibility"]["international_friendly"] == "yes"

    def test_tagger_tags_real_data(self):
        """At least some real opportunities should be taggable."""
        data = _load_real_data()
        tagged_count = 0
        for opp in data[:50]:
            if needs_tagging(opp):
                updates = rule_based_tag(opp)
                if updates:
                    tagged_count += 1
        assert tagged_count > 0, "Tagger should produce updates for at least some real entries"


# ── Test: Ranker Produces Sane Results ────────────────


class TestRankerSanity:
    def test_rank_all_returns_results(self, sanity_ranked_results):
        assert len(sanity_ranked_results) > 0, "Ranker should return results on real data"

    def test_scores_in_valid_range(self, sanity_ranked_results):
        for r in sanity_ranked_results:
            assert 0 <= r.final_score <= 100
            assert 0 <= r.eligibility_score <= 100
            assert 0 <= r.readiness_score <= 100
            assert 0 <= r.upside_score <= 100

    def test_results_sorted_descending(self, sanity_ranked_results):
        for i in range(len(sanity_ranked_results) - 1):
            assert sanity_ranked_results[i].final_score >= sanity_ranked_results[i + 1].final_score

    def test_good_match_scores_high(self, sample_profile, sample_opportunity):
        result = rank_opportunity(sample_profile, sample_opportunity)
        assert result.final_score >= 60, "A well-matched opportunity should score >= 60"
        assert result.bucket in ("high_priority", "good_match")

    def test_buckets_are_valid(self, sanity_ranked_results):
        valid_buckets = {"high_priority", "good_match", "reach", "low_fit"}
        for r in sanity_ranked_results:
            assert r.bucket in valid_buckets


# ── Test: Cold Email Generator ────────────────


class TestColdEmailGenerator:
    def test_generates_non_empty_output(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert len(email) > 0
        assert len(email.split()) <= 200  # reasonable length

    def test_includes_student_name(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert sample_profile["name"] in email

    def test_includes_pi_name(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert "Smith" in email or "Professor" in email

    def test_includes_lab_name(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert "Data Science Lab" in email

    def test_includes_skills(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert "Python" in email

    def test_has_subject_line(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert email.startswith("Subject:")

    def test_handles_minimal_profile(self, sample_opportunity):
        minimal = {"name": "", "year": "freshman", "major": "CS", "school": "UIUC"}
        email = generate_cold_email(minimal, sample_opportunity)
        assert len(email) > 0
        assert "Subject:" in email

    def test_handles_minimal_opportunity(self, sample_profile):
        minimal = {"id": "min", "title": "Some Research", "eligibility": {}}
        email = generate_cold_email(sample_profile, minimal)
        assert len(email) > 0

    def test_on_real_data(self, sample_profile):
        data = _load_real_data()
        for opp in data[:5]:
            email = generate_cold_email(sample_profile, opp)
            assert len(email) > 50, f"Email too short for {opp.get('title')}"


class TestLabTypeDetection:
    def test_wet_lab_from_biology_department(self):
        opp = {
            "title": "Undergraduate research in protein folding",
            "department": "Molecular and Cellular Biology",
            "description_clean": "Looking for students to assist with cell culture and Western blot.",
            "keywords": ["protein", "cell biology"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"

    def test_wet_lab_from_techniques_even_without_department(self):
        opp = {
            "title": "Summer fellowship",
            "department": "",
            "description_clean": "PCR, gel electrophoresis, and sterile technique daily.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"

    def test_dry_lab_from_cs_department(self):
        opp = {
            "title": "ML research with deep neural networks",
            "department": "Computer Science",
            "description_clean": "Looking for students with Python and PyTorch experience.",
            "keywords": ["machine learning", "deep learning"],
            "eligibility": {"skills_required": ["Python", "PyTorch"]},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_ece_with_medical_application_keywords_stays_dry(self):
        # Real UIUC shape (observed live 2026-08-07): the department's
        # ampersand form matched neither "electrical engineering" nor "ece",
        # muting the highest-weight dry signal, while "medical" inside an
        # application phrase ("healthcare and medical technologies") scored
        # wet — a chip-architecture group got wet-lab PCR guidance.
        opp = {
            "title": "Research with Prof. Nam Sung Kim — ECE (beyond cmos, ai applications, healthcare and medical technologies)",
            "department": "Electrical & Computer Engineering",
            "description_clean": "Research opportunity with Professor Nam Sung Kim in the Electrical & Computer Engineering at UIUC. Research areas: beyond cmos, ai applications, healthcare and medical technologies, wearable and mobile computing.",
            "keywords": ["beyond cmos", "ai applications", "healthcare and medical technologies", "wearable and mobile computing"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_humanities_lab_from_psychology(self):
        opp = {
            "title": "Research assistant — behavioral psychology",
            "department": "Psychology",
            "description_clean": "Qualitative coding of interviews using NVivo. IRB protocol experience preferred.",
            "keywords": ["psychology", "qualitative"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "humanities"

    def test_defaults_to_dry_on_no_signal(self):
        opp = {
            "title": "Research opportunity",
            "department": "",
            "description_clean": "Contact the professor for details.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_wet_wins_over_dry_buzzword(self):
        """A wet-lab posting that mentions Python for analysis should
        not be misrouted to dry. Wet-lab signals (cell culture, microscopy)
        get 3x weight from the department field plus 2x from title."""
        opp = {
            "title": "Cell biology REU — microscopy and image analysis",
            "department": "Cell and Developmental Biology",
            "description_clean": "Use Python for image analysis after wet-bench microscopy work.",
            "keywords": ["cell biology", "microscopy"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"


class TestLabTypeAwareTemplates:
    def test_wet_lab_subject_says_inquiry(self, sample_profile):
        opp = {
            "id": "wet-1", "title": "Biology research",
            "department": "Molecular Biology", "lab_or_program": "Smith Lab",
            "pi_name": "Prof. Smith",
            "description_clean": "PCR and cell culture daily.",
            "keywords": ["biology"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        first_line = email.split("\n")[0]
        assert "Research Inquiry" in first_line

    def test_dry_lab_subject_says_interest(self, sample_profile):
        opp = {
            "id": "dry-1", "title": "ML research",
            "department": "Computer Science", "lab_or_program": "Smith Lab",
            "pi_name": "Prof. Smith",
            "description_clean": "Python and PyTorch required.",
            "keywords": ["machine learning"],
            "eligibility": {"skills_required": ["Python"]},
        }
        email = generate_cold_email(sample_profile, opp)
        first_line = email.split("\n")[0]
        assert "Undergraduate Research Interest" in first_line

    def test_humanities_subject_says_assistant_interest(self, sample_profile):
        opp = {
            "id": "hum-1", "title": "Sociology RA",
            "department": "Sociology", "lab_or_program": "Smith Lab",
            "pi_name": "Prof. Smith",
            "description_clean": "Qualitative interviews and survey design.",
            "keywords": ["sociology"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        first_line = email.split("\n")[0]
        assert "Research Assistant Interest" in first_line

    def test_wet_lab_ask_mentions_safety_training(self, sample_profile):
        opp = {
            "id": "wet-2", "title": "Bio research",
            "department": "Biology", "description_clean": "PCR work.",
            "keywords": ["biology"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        assert "safety training" in email.lower() or "graduate mentor" in email.lower()

    def test_humanities_ask_mentions_literature_reviews(self, sample_profile):
        opp = {
            "id": "hum-2", "title": "History RA",
            "department": "History", "description_clean": "Archival research.",
            "keywords": ["history"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        assert (
            "literature review" in email.lower()
            or "qualitative coding" in email.lower()
        )

    def test_variants_include_lab_type_field(self, sample_profile):
        opp = {
            "id": "dry-2", "title": "CS research",
            "department": "Computer Science",
            "description_clean": "ML work in Python.",
            "keywords": ["computer science"],
            "eligibility": {"skills_required": ["Python"]},
        }
        variants = generate_variants(sample_profile, opp)
        assert len(variants) == 3
        for v in variants:
            assert v["lab_type"] == "dry"


# ── Test: Resume Advisor ────────────────


class TestResumeAdvisor:
    def test_identifies_missing_skills(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["missing_skills"], list)
        # PyTorch and pandas are preferred but not in profile
        assert "PyTorch" in gaps["missing_skills"] or "pandas" in gaps["missing_skills"]

    def test_suggests_coursework(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["suggested_coursework"], list)
        assert len(gaps["suggested_coursework"]) > 0

    def test_provides_resume_tips(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["resume_tips"], list)
        assert len(gaps["resume_tips"]) > 0

    def test_provides_preparation_timeline(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["preparation_timeline"], list)
        for item in gaps["preparation_timeline"]:
            assert "skill" in item
            assert "estimated_time" in item
            assert "priority" in item
            assert item["priority"] in ("high", "medium")

    def test_no_gaps_for_perfect_match(self):
        profile = {
            "hard_skills": ["Python", "PyTorch", "pandas"],
            "coursework": [],
            "experience_level": "strong",
            "resume_ready": True,
            "projects": [{"name": "Demo", "description": "A project"}],
        }
        opp = {
            "eligibility": {
                "skills_required": ["Python"],
                "skills_preferred": ["PyTorch", "pandas"],
            },
            "opportunity_type": "research",
            "application": {},
        }
        gaps = analyze_gaps(profile, opp)
        assert len(gaps["missing_skills"]) == 0
        assert len(gaps["preparation_timeline"]) == 0

    def test_on_real_data(self, sample_profile):
        data = _load_real_data()
        for opp in data[:5]:
            gaps = analyze_gaps(sample_profile, opp)
            assert isinstance(gaps, dict)
            assert "missing_skills" in gaps
            assert "resume_tips" in gaps


# ── Test: Data Integrity — All Records ────────────────


class TestAllRecordsIntegrity:
    def test_all_records_have_required_fields(self):
        data = _load_real_data()
        required_fields = ["id", "title", "url", "eligibility"]
        for opp in data:
            for field in required_fields:
                assert field in opp and opp[field], \
                    f"Record '{opp.get('title', 'UNKNOWN')}' missing required field '{field}'"

    def test_all_eligibility_dicts_have_structure(self):
        data = _load_real_data()
        for opp in data:
            elig = opp.get("eligibility", {})
            assert isinstance(elig, dict), f"Bad eligibility in: {opp.get('title')}"
            assert "preferred_year" in elig, f"Missing preferred_year: {opp.get('title')}"
            assert isinstance(elig["preferred_year"], list)

    def test_no_duplicate_ids(self):
        data = _load_real_data()
        ids = [o["id"] for o in data]
        assert len(ids) == len(set(ids)), "Duplicate IDs found"

    def test_all_paid_values_valid(self):
        data = _load_real_data()
        valid_paid = {"yes", "no", "stipend", "unknown"}
        for opp in data:
            assert opp.get("paid", "unknown") in valid_paid, \
                f"Invalid paid value in: {opp.get('title')}"

    def test_all_intl_values_valid(self):
        data = _load_real_data()
        valid_intl = {"yes", "no", "unknown"}
        for opp in data:
            intl = opp.get("eligibility", {}).get("international_friendly", "unknown")
            assert intl in valid_intl, f"Invalid international_friendly in: {opp.get('title')}"


def test_extract_years_advanced_undergraduate_excludes_underclassmen():
    """'advanced undergraduate' is an explicit no-freshman signal — the AAAS
    Mass Media Fellowship said exactly this yet displayed 'Accepts freshman
    students' because the phrase fell through to the all-years default."""
    from src.normalizers.normalizer import _extract_years
    years = _extract_years(
        "placing advanced undergraduate, graduate, and post-graduate level "
        "scientists at media organizations"
    )
    assert years == ["junior", "senior"]
