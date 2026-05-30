"""Unit tests for the pure text-extraction helpers in backend.routes.resume.

Network- and file-free: these target the three deterministic parsers that
turn already-extracted resume text into structured profile hints —
_extract_skills, _extract_coursework, and _infer_experience_level. The PDF
byte path and the FastAPI upload route are out of scope here.

Note: KNOWN_SKILLS includes the single letters "C" and "R", and
_extract_skills does a naive case-insensitive substring scan, so any text
containing a 'c' or 'r' matches them. Tests therefore use membership
assertions (not whole-list equality) and explicitly characterize that
substring behaviour rather than asserting it away.
"""

from __future__ import annotations

from backend.routes.resume import (
    _extract_coursework,
    _extract_skills,
    _infer_experience_level,
)


class TestExtractSkills:
    def test_detects_multichar_skills(self):
        skills = _extract_skills("Experienced with Python, PyTorch and Docker.")
        assert "Python" in skills
        assert "PyTorch" in skills
        assert "Docker" in skills

    def test_is_case_insensitive(self):
        skills = _extract_skills("python TENSORFLOW kubernetes")
        assert "Python" in skills
        assert "TensorFlow" in skills
        assert "Kubernetes" in skills

    def test_detects_cpp_and_csharp_tokens(self):
        skills = _extract_skills("Languages: C++ and C#")
        assert "C++" in skills
        assert "C#" in skills

    def test_detects_multiword_skills(self):
        skills = _extract_skills("Focus on machine learning and deep learning research")
        assert "machine learning" in skills
        assert "deep learning" in skills

    def test_single_letter_skills_C_and_R_match_via_substring(self):
        skills = _extract_skills("abcdefr")
        assert "C" in skills
        assert "R" in skills

    def test_preserves_canonical_casing_of_the_skill_label(self):
        skills = _extract_skills("i deploy to aws and gcp")
        assert "AWS" in skills
        assert "GCP" in skills

    def test_returns_a_list(self):
        assert isinstance(_extract_skills(""), list)


class TestExtractCoursework:
    def test_extracts_uppercase_course_codes(self):
        assert _extract_coursework("Took CS 124 and ECE 220 last year") == [
            "CS 124",
            "ECE 220",
        ]

    def test_dedupes_and_sorts(self):
        assert _extract_coursework("MATH 241, CS 173, MATH 241") == [
            "CS 173",
            "MATH 241",
        ]

    def test_ignores_lowercase_department(self):
        assert _extract_coursework("cs 124") == []

    def test_accepts_three_and_four_digit_numbers(self):
        assert _extract_coursework("CS 100 and CS 4999") == ["CS 100", "CS 4999"]

    def test_rejects_two_digit_numbers(self):
        assert _extract_coursework("CS 12") == []

    def test_returns_empty_for_no_courses(self):
        assert _extract_coursework("no course identifiers here") == []


class TestInferExperienceLevel:
    def test_strong_when_two_strong_keywords(self):
        assert _infer_experience_level("I led and managed the lab project") == "strong"

    def test_some_when_two_some_keywords(self):
        assert (
            _infer_experience_level("I developed and implemented the feature") == "some"
        )

    def test_beginner_when_below_threshold(self):
        assert _infer_experience_level("Completed relevant coursework") == "beginner"

    def test_single_strong_keyword_is_not_enough(self):
        assert _infer_experience_level("I led one small task") == "beginner"

    def test_strong_takes_precedence_over_some(self):
        text = "I led and managed work I developed and implemented"
        assert _infer_experience_level(text) == "strong"

    def test_is_case_insensitive(self):
        assert _infer_experience_level("LED and MANAGED a team") == "strong"

    def test_empty_text_is_beginner(self):
        assert _infer_experience_level("") == "beginner"
