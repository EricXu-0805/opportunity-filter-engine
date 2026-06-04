"""Unit tests for the pure text-extraction helpers in backend.routes.resume.

Network- and file-free: these target the three deterministic parsers that
turn already-extracted resume text into structured profile hints —
_extract_skills, _extract_coursework, and _infer_experience_level. The PDF
byte path and the FastAPI upload route are out of scope here.

Note: KNOWN_SKILLS includes the single letters "C" and "R". _extract_skills
matches each skill as a standalone token (token-boundary aware), so those
short names no longer false-match inside unrelated words like "Research" or
"Algorithms" while "C++"/"C#"/"Node.js" still match.
"""

from __future__ import annotations

from backend.routes.resume import (
    _extract_coursework,
    _extract_research_interests,
    _extract_skills,
    _infer_experience_level,
)


class TestExtractResearchInterests:
    def test_areas_of_interest_label(self):
        text = (
            "TECHNICAL SKILLS\nProgramming: Python, C++\n"
            "Areas of Interest: AI systems, computer vision, "
            "full-stack product development, intelligent tutoring systems\n"
        )
        assert _extract_research_interests(text) == (
            "AI systems, computer vision, full-stack product development, "
            "intelligent tutoring systems"
        )

    def test_research_interests_label(self):
        text = "Research Interests — machine learning and superconductor materials."
        assert _extract_research_interests(text) == (
            "machine learning and superconductor materials"
        )

    def test_one_line_blob_stops_at_next_section(self):
        # PDF extraction flattens the resume to one line — the capture must stop
        # at the next "Label:" instead of swallowing the rest of the document.
        blob = (
            "Tools & Platforms: Git, Linux, LaTeX "
            "Areas of Interest: AI systems, computer vision, full-stack product "
            "development, intelligent tutoring systems "
            "Languages: Mandarin (native), English PATENT Intelligent Acoustic ..."
        )
        assert _extract_research_interests(blob) == (
            "AI systems, computer vision, full-stack product development, "
            "intelligent tutoring systems"
        )

    def test_no_section_returns_empty(self):
        assert _extract_research_interests("EDUCATION\nUIUC\nSkills: Python") == ""

    def test_personal_interests_hobbies_not_captured(self):
        # Only research-style labels seed the matcher; hobby lines are ignored.
        assert _extract_research_interests("Personal Interests: hiking, chess") == ""


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

    def test_single_letter_skills_do_not_match_inside_words(self):
        skills = _extract_skills("abcdefr")
        assert "C" not in skills
        assert "R" not in skills

    def test_short_skills_need_token_boundaries(self):
        # "Go" must not match "Algorithms", "R" must not match "Research",
        # "C" must not match "C++"; the standalone forms still match.
        skills = _extract_skills(
            "Coursework: Algorithms. Research with C++. Languages: Go, R, C"
        )
        assert "Go" in skills
        assert "R" in skills
        assert "C" in skills
        assert "C++" in skills

    def test_java_does_not_match_inside_javascript(self):
        skills = _extract_skills("Proficient in JavaScript")
        assert "JavaScript" in skills
        assert "Java" not in skills

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

    def test_extracts_named_courses_from_labeled_list(self):
        assert _extract_coursework(
            "Coursework: Data Structures, Linear Algebra, Algorithms"
        ) == ["Algorithms", "Data Structures", "Linear Algebra"]

    def test_named_courses_and_codes_combine(self):
        result = _extract_coursework(
            "Relevant Courses: Operating Systems, CS 233, Databases"
        )
        assert "CS 233" in result
        assert "Operating Systems" in result
        assert "Databases" in result

    def test_unlabeled_prose_does_not_yield_named_courses(self):
        assert _extract_coursework("I enjoy data structures and algorithms") == []


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
