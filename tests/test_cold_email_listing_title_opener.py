"""M31 step 2: a listing whose source states no topics is named by its own
title in the template opener, never by a sentence cut out of its description.

The opener's fallback took the description's first usable sentence and cut it
at 80 characters, so an email said "I would like to learn more about your work
on SURF is an 8-week on-campus summer program (typically starting in early
June) wh". Faculty rows never reach that fallback and keep their output.
"""
from __future__ import annotations

import pytest

from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes import cold_email as ce
from src.recommender.cold_email import _common_parts, generate_cold_email, generate_variants

PROFILE = {"name": "Eric", "year": "sophomore", "major": "Biology", "school": "UIUC",
           "hard_skills": ["Python"], "research_interests_text": "developmental biology"}
SURF = ("SURF is an 8-week on-campus summer program (typically starting in early June) where "
        "students work with a faculty mentor. Applications open in January.")


def _listing(source, source_type, title, *, keywords=(), lab="", description=SURF):
    return project_public_detail({
        "id": f"m31s2-{source}", "source": source, "source_type": source_type,
        "opportunity_type": "summer_program", "title": title, "lab_or_program": lab,
        "organization": "Test University", "keywords": list(keywords),
        "description_raw": description, "eligibility": {}, "application": {},
        "metadata": {"is_active": True},
    })


LISTINGS = {
    # Simplify's category tags are ours; the description is its collector's template.
    "simplify": _listing("simplify_internships", "internship", "Data Scientist Intern - Shop Product DS",
                         keywords=["data science"], lab="TikTok"),
    "campus_program_spec": _listing("illinois_research_programs", "campus_program",
                                    "Summer Undergraduate Research Fellowship (SURF)",
                                    keywords=["data science"], lab="Office of Undergraduate Research"),
    "nsf_reu": _listing("nsf_reu", "summer_program", "REU: Physics at Kansas State University",
                        lab="Physics at Kansas State University"),
}


@pytest.mark.parametrize("kind", sorted(LISTINGS))
def test_a_listing_without_source_topics_is_named_by_its_title(kind):
    public = LISTINGS[kind]
    # nsf_reu.py writes "REU: " in front of the award's title; it is not quoted (step 3).
    title = public["title"].removeprefix("REU: ")
    for variant in generate_variants(PROFILE, public)[:2]:   # concise has no topic sentence
        text = variant["text"]
        assert f"I would like to learn more about “{title}”." in text, (kind, variant["id"])
        assert "your work on" not in text
        assert "8-week on-campus" not in text


def test_a_listing_with_sro_research_area_keywords_keeps_its_topics():
    public = _listing("uiuc_sro", "summer_program", "Summer Undergraduate Research Fellowship (SURF)",
                      keywords=["zebrafish fin regeneration", "cryo-electron tomography"])
    text = generate_cold_email(PROFILE, public)
    assert "I would like to learn more about your work on zebrafish fin regeneration and cryo-electron tomography." in text
    assert "“Summer Undergraduate Research Fellowship (SURF)”" not in text


def test_an_overlong_title_is_not_cut_and_the_description_is_not_quoted():
    title = ("REU: Training Students to Build and Apply Open Source Machine Learning Models "
             "and Tools for Experimental and Computational Spectroscopy")
    assert len(title) >= 120
    public = _listing("nsf_reu", "summer_program", title, lab="Spectroscopy REU Site")
    text = generate_cold_email(PROFILE, public)
    # Nor a word picked out of it ("your work on machine learning").
    assert "I would like to learn more about the work in the Spectroscopy REU Site." in text
    assert "your work on" not in text
    assert "REU: Experimental" not in text.split("\n\n", 1)[1]   # not in the body
    assert "8-week on-campus" not in text


def test_the_title_is_not_turned_into_a_research_topic():
    """Only the template sentence changes: every other reader of the derived
    topic still gets what it got, and a bare title opens no gate."""
    public = _listing("nsf_reu", "summer_program", "REU: Physics at Kansas State University", description="")
    parts = _common_parts(PROFILE, public)
    assert parts["research_topic"] == ""
    assert ce.has_source_backed_target_evidence(public, parts) is False
    assert not any("kansas" in anchor for anchor in ce._professor_anchors(parts, public))
    with_desc = _common_parts(PROFILE, LISTINGS["nsf_reu"])
    assert with_desc["research_topic"] == SURF[:80]


FACULTY = {
    "id": "m31s2-faculty", "source": "faculty_graph", "source_type": "faculty_research",
    "opportunity_type": "research", "title": "Professor of Chemistry", "pi_name": "Pat Lee",
    "lab_or_program": "Lee Lab", "organization": "Test University", "keywords": [],
    "description_raw": "Pat Lee is a faculty member in Chemistry at Test University.",
    "eligibility": {}, "application": {}, "metadata": {"is_active": True, "faculty_title": "Professor"},
}


def test_a_faculty_row_without_topics_keeps_todays_email_exactly():
    public = project_public_detail(FACULTY)
    assert generate_cold_email(PROFILE, public) == (
        "Subject: Undergraduate Research Interest — Lee Lab\n\n"
        "Dear Professor Pat Lee,\n\n"
        "My name is Eric, and I am a sophomore studying Biology at UIUC. I am interested in "
        "developmental biology. I would like to learn more about the work in the Lee Lab.\n\n"
        "I have foundational exposure to Python.\n\n"
        "Could I ask whether you have any current or upcoming research openings for a student? "
        "If so, what preparation would be useful before a brief conversation?\n\n"
        "Best regards,\nEric"
    )
