"""
End-to-end integration tests for the Opportunity Filter Engine.
Covers: collector→normalizer pipeline, tagger updates, ranker sanity,
        cold email generator, resume advisor, and data integrity.

Run with: pytest tests/test_integration.py -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.ranker import rank_all, rank_opportunity
from src.normalizers.normalizer import normalize
from src.parsers.llm_tagger import _build_full_text, apply_updates, needs_tagging, rule_based_tag
from src.recommender.cold_email import generate_cold_email
from src.recommender.resume_advisor import analyze_gaps

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")


def _load_real_data():
    if not os.path.exists(DATA_PATH):
        pytest.skip("No processed data file")
    with open(DATA_PATH) as f:
        return json.load(f)


@pytest.fixture
def sample_profile():
    return {
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
        "deadline": "2026-05-15",
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
    def test_rank_all_returns_results(self, sample_profile):
        data = _load_real_data()
        results = rank_all(sample_profile, data)
        assert len(results) > 0, "Ranker should return results on real data"

    def test_scores_in_valid_range(self, sample_profile):
        data = _load_real_data()
        results = rank_all(sample_profile, data)
        for r in results:
            assert 0 <= r.final_score <= 100
            assert 0 <= r.eligibility_score <= 100
            assert 0 <= r.readiness_score <= 100
            assert 0 <= r.upside_score <= 100

    def test_results_sorted_descending(self, sample_profile):
        data = _load_real_data()
        results = rank_all(sample_profile, data)
        for i in range(len(results) - 1):
            assert results[i].final_score >= results[i + 1].final_score

    def test_good_match_scores_high(self, sample_profile, sample_opportunity):
        result = rank_opportunity(sample_profile, sample_opportunity)
        assert result.final_score >= 60, "A well-matched opportunity should score >= 60"
        assert result.bucket in ("high_priority", "good_match")

    def test_buckets_are_valid(self, sample_profile):
        data = _load_real_data()
        results = rank_all(sample_profile, data)
        valid_buckets = {"high_priority", "good_match", "reach", "low_fit"}
        for r in results:
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
