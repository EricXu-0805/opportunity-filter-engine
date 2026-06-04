"""Cold-email template quality guards (CE-1/CE-2/CE-3).

The deterministic template is the email EVERY user without a working LLM gets,
so its prose must be grammatical and must never make an unsupported claim. These
pin the three defects found in review:
  CE-1 — a bare broad department field must not be claimed to "align closely"
         with the student's specific interest.
  CE-2 — the lab reference must read "in Prof. X's Research Group", never the
         ungrammatical "in the Prof. X's Research Group".
  CE-3 — a sparse profile (missing year/major/school) must not produce double
         spaces or dangling words.
"""

from __future__ import annotations

from src.recommender.cold_email import (
    _common_parts,
    _infer_research_area,
    _p1_research_hook,
    _short_interest,
    _student_self,
    generate_cold_email,
)

_LAB = "Prof. Jane Doe's Research Group"


def _hook(research_area="", research_topic="", lab="", interests=""):
    return _p1_research_hook({
        "research_topic": research_topic,
        "research_area": research_area,
        "lab": lab,
        "research_interests": interests,
    })


class TestP1ResearchHookCE1:
    def test_broad_field_area_makes_no_false_alignment_claim(self):
        h = _hook(research_area="physics", lab=_LAB, interests="machine learning")
        assert "aligns closely with my interest" not in h
        assert "your work in physics" not in h
        assert _LAB in h  # falls back to the honest lab-only hook

    def test_broad_field_topic_with_space_makes_no_false_alignment(self):
        h = _hook(research_topic="molecular biology", lab=_LAB, interests="machine learning")
        assert "resonates with my interest" not in h
        assert "your work on molecular biology" not in h

    def test_specific_area_keeps_the_alignment_hook(self):
        h = _hook(research_area="computer vision", lab=_LAB, interests="deep learning")
        assert "aligns closely with my interest" in h
        assert "computer vision" in h


class TestP1ResearchHookCE2:
    def test_possessive_lab_drops_the_article(self):
        h = _hook(research_topic="internet of things", lab=_LAB, interests="robotics")
        assert "in the Prof" not in h
        assert f"in {_LAB}" in h

    def test_plain_lab_keeps_the_article(self):
        h = _hook(research_area="optics", lab="Photonics Lab", interests="lasers")
        assert "the Photonics Lab" in h


class TestStudentSelfCE3:
    def test_full_profile_all_connectors(self):
        p = {"year": "sophomore", "major": "Computer Science", "school": "UIUC"}
        assert _student_self(p, "studying") == "a sophomore studying Computer Science at UIUC"
        assert _student_self(p, "major") == "a sophomore Computer Science major at UIUC"
        assert _student_self(p, "student") == "a sophomore Computer Science student at UIUC"

    def test_missing_major_degrades_cleanly(self):
        p = {"year": "sophomore", "major": "", "school": "UIUC"}
        assert _student_self(p, "studying") == "a sophomore student at UIUC"
        for connector in ("studying", "major", "student"):
            assert "  " not in _student_self(p, connector)

    def test_all_fields_empty(self):
        p = {"year": "", "major": "", "school": ""}
        for connector in ("studying", "major", "student"):
            out = _student_self(p, connector)
            assert out == "a student"


class TestGenerateColdEmailEndToEnd:
    _OPP = {
        "opportunity_type": "research",
        "pi_name": "Jane Doe",
        "lab_or_program": "Prof. Jane Doe's Research Group",
        "department": "Department of Physics",
        "keywords": ["physics"],
        "eligibility": {},
    }

    def test_broad_field_email_has_no_false_alignment(self):
        profile = {
            "name": "Eric", "year": "sophomore", "major": "Computer Science",
            "school": "UIUC", "research_interests_text": "machine learning",
        }
        email = generate_cold_email(profile, self._OPP)
        assert "your work in physics" not in email
        assert "aligns closely with my interest" not in email

    def test_sparse_profile_has_no_double_space(self):
        # The API always sends present-but-empty fields (Pydantic model_dump).
        profile = {"name": "Eric", "year": "", "major": "", "school": "", "research_interests_text": ""}
        email = generate_cold_email(profile, self._OPP)
        assert "  " not in email
        assert "a undergraduate" not in email


class TestRecipientJunkNameCE6:
    def test_na_pi_name_does_not_leak_into_recipient(self):
        # CE-6: "N/A" (in the matcher's _BAD_PI_NAMES) must not render as a name.
        for junk in ("N/A", "n/a", "Unknown", ""):
            p = _common_parts({}, {"pi_name": junk, "opportunity_type": "research"})
            assert p["recipient"] == "Professor"
            if junk.strip():
                assert junk.strip() not in p["recipient"]

    def test_real_pi_name_still_used(self):
        p = _common_parts({}, {"pi_name": "Jane Doe", "opportunity_type": "research"})
        assert p["recipient"] == "Professor Jane Doe"


class TestShortInterestCE_C1:
    """The interest hook must use clean phrase boundaries, never a mid-word
    character slice (regression for `interests[:80]` → '...models, dee')."""

    _LONG = (
        "AI systems and machine learning, computer vision and vision-language "
        "models, deep learning, superconductor materials science"
    )

    def test_no_midword_truncation(self):
        s = _short_interest(self._LONG)
        assert not s.endswith("dee")
        # ends on a whole phrase, not a mid-word character slice
        assert s == "AI systems and machine learning, computer vision and vision-language models"

    def test_single_phrase_passthrough(self):
        assert _short_interest("robotics") == "robotics"

    def test_empty(self):
        assert _short_interest("") == ""

    def test_hook_with_long_interests_is_not_truncated(self):
        h = _hook(lab=_LAB, interests=self._LONG)
        assert "dee." not in h and "dee " not in h
        assert _LAB in h


class TestInferResearchAreaNoDeptFallback_CE_C2:
    """A department name is not a research area — it must not become a
    'your work in <department>' false-alignment claim (CE-C2)."""

    def test_broad_keyword_only_does_not_fall_back_to_department(self):
        area = _infer_research_area({
            "keywords": ["computer science"],
            "department": "Siebel School of Computing and Data Science",
            "title": "Research with Prof. Sasa Misailovic — CS",
        })
        assert "School" not in area and "Department" not in area
        assert area == ""

    def test_specific_keyword_still_returned(self):
        area = _infer_research_area({
            "keywords": ["computer vision", "robotics"],
            "department": "Electrical and Computer Engineering",
        })
        assert area == "computer vision"

    def test_no_dept_false_alignment_in_hook(self):
        # broad-field-only prof: research_area resolves to "" -> lab-only hook
        h = _hook(research_area="", lab=_LAB, interests="machine learning")
        assert "your work in" not in h.lower()
        assert _LAB in h
