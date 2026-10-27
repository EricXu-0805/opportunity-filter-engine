"""M155: a match reason says so when the topics it rests on are ours.

"Matches your interests" matched the student's chips against keywords the
detail page shows as ours (a department's field, OpenAlex topics, a listing's
tags) and said nothing of it. A chip the row's own words name (its title, the
research text the detail page shows as the source's) still is the page's.
"Your research interests align with Prof. X's focus area" is the line a row
gets when its keywords are inferred and so are not named; it gave the row a
focus area no page states. Scores do not change.
"""
from __future__ import annotations

import pytest

from backend.data_loader import _sanitize_opportunity
from src.evidence import stamp_inferred
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import _OUR_TOPICS, rank_opportunity, score_upside
from src.matcher.reason_keys import reason_key

STAMPS = ["derived:openalex_topics", "derived:illinois_experts_concepts", "tag:department_field"]


def _faculty(keywords, *, stamp=None, stated=""):
    opp = {
        "id": "faculty-physics-m155", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "pi_name": "Pat Lee", "department": "Department of Physics",
        "keywords": list(keywords), "description_raw": "Faculty research profile for Pat Lee.",
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    if stated:
        opp["metadata"]["research_areas_raw"] = stated
    if stamp:
        stamp_inferred(opp["metadata"], "keywords", stamp)
    return opp


def _listing(source, source_type, *, title="Summer Research Program", keywords=("machine learning",)):
    return {
        "id": f"m155-{source}", "source": source, "source_type": source_type, "opportunity_type": "research",
        "title": title, "keywords": list(keywords), "pi_name": "Pat Lee",
        "description_raw": "Students join a ten-week summer cohort.", "eligibility": {}, "application": {},
        "metadata": {"is_active": True},
    }


def _keyed(fit, prefix):
    """The ranker's line starting with ``prefix`` and its served key."""
    line = next(reason for reason in fit if reason.startswith(prefix))
    return line, reason_key(line, "fit")["key"]


PHYSICS = {"research_interests_text": "nuclear physics", "desired_fields": ["nuclear physics"]}


@pytest.mark.parametrize("stamp", STAMPS)
def test_interests_matched_against_inferred_topics_say_so(stamp):
    _, fit, _ = score_upside(PHYSICS, _faculty(["physics"], stamp=stamp), precomputed_sim=0.0)
    assert _keyed(fit, "Matches your interests") == (
        f"Matches your interests: nuclear physics{_OUR_TOPICS}", "interests_match_ours")
    assert "Matches your interests: nuclear physics" not in fit


def test_a_profiles_own_keywords_keep_the_plain_line():
    _, fit, _ = score_upside(PHYSICS, _faculty(["physics"]), precomputed_sim=0.0)
    assert _keyed(fit, "Matches your interests") == ("Matches your interests: nuclear physics", "interests_match")
    assert not any(_OUR_TOPICS in reason for reason in fit)


@pytest.mark.parametrize(("source", "source_type", "ours"), [
    ("simplify_internships", "internship", True),
    ("nsf_reu", "summer_program", True),
    ("illinois_research_programs", "campus_program", True),
    ("uiuc_sro", "summer_program", False),
])
def test_a_listings_tags_are_ours_and_the_sros_research_area_is_its_own(source, source_type, ours):
    profile = {"research_interests_text": "", "desired_fields": ["machine learning"]}
    _, fit, _ = score_upside(profile, _listing(source, source_type), precomputed_sim=0.0)
    line = "Matches your interests: machine learning"
    assert (f"{line}{_OUR_TOPICS}" if ours else line) in fit


@pytest.mark.parametrize("stamp", STAMPS)
def test_a_chip_the_stated_research_names_is_the_pages_own(stamp):
    """Review round 1: "algebraic geometry" was hedged on a profile whose own
    research areas read "Algebra, Algebraic Geometry"."""
    profile = {"research_interests_text": "", "desired_fields": ["algebraic geometry"]}
    row = _faculty(["algebraic geometry", "galois extension"], stamp=stamp, stated="Algebra, Algebraic Geometry")
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert "Matches your interests: algebraic geometry" in fit
    assert not any(_OUR_TOPICS in reason for reason in fit)


def test_a_chip_the_listings_title_names_is_its_own_and_the_rest_stay_ours():
    """Review round 1: "data science, machine learning" were both hedged on
    "Machine Learning Software Engineer Intern"."""
    profile = {"research_interests_text": "", "desired_fields": ["data science", "machine learning"]}
    row = _listing("simplify_internships", "internship", title="Machine Learning Software Engineer Intern",
                   keywords=("data science", "machine learning"))
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert [reason for reason in fit if reason.startswith("Matches your interests")] == [
        "Matches your interests: machine learning",
        f"Matches your interests: data science{_OUR_TOPICS}",
    ]


@pytest.mark.parametrize("stamp", STAMPS)
def test_inferred_keywords_give_the_row_no_focus_area(stamp):
    _, fit, _ = score_upside(PHYSICS, _faculty(["physics"], stamp=stamp), precomputed_sim=0.5)
    assert _keyed(fit, "Your research interests") == (
        "Your research interests align with topics we inferred for Pat Lee", "interests_lab_ours")
    assert not any("focus area" in reason for reason in fit)


@pytest.mark.parametrize("chip", ["cs", "topics"])
def test_a_chip_inside_the_lines_wording_keeps_its_own_line(chip):
    """The bare line is dropped only as a repeat of topics the similarity line
    names; "topics we inferred for ..." names none, though "cs" is in "topics"."""
    profile = {"research_interests_text": f"{chip} research", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _faculty([chip], stamp="tag:department_field"), precomputed_sim=0.5)
    assert f"Matches your interests: {chip}{_OUR_TOPICS}" in fit


def test_a_chip_inside_the_focus_area_line_keeps_its_own_line():
    """"research" is inside "Your research interests align with ...'s focus area",
    which names no topic."""
    profile = {"research_interests_text": "research", "desired_fields": ["research"]}
    row = _listing("illinois_research_programs", "campus_program", keywords=("research",))
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.5)
    assert "Matches your interests: research" in fit
    assert "Your research interests align with Prof. Pat Lee's focus area" in fit


@pytest.mark.parametrize("keywords", [[], ["undergraduate research"], ["research", "summer"]],
                         ids=["none", "role-only", "generic-only"])
def test_unstamped_keywords_that_name_no_topic_keep_the_focus_area(keywords):
    """display_kw is empty without a stamp: the similarity rests on the
    listing's own description."""
    row = _listing("illinois_research_programs", "campus_program", keywords=keywords)
    _, fit, _ = score_upside({"research_interests_text": "neural decoding"}, row, precomputed_sim=0.6)
    assert _keyed(fit, "Your research interests") == (
        "Your research interests align with Prof. Pat Lee's focus area", "interests_lab_focus")


@pytest.mark.parametrize("stamp", STAMPS)
def test_only_the_sentences_change(stamp):
    for sim in (0.0, 0.5):
        stamped, fit, gap = score_upside(PHYSICS, _faculty(["physics"], stamp=stamp), precomputed_sim=sim)
        plain, plain_fit, plain_gap = score_upside(PHYSICS, _faculty(["physics"]), precomputed_sim=sim)
        assert stamped == plain and len(fit) == len(plain_fit) and gap == plain_gap


def test_a_department_field_the_loader_tags_is_matched_as_ours():
    """A UIUC profile that states no research keeps its department's field as
    keywords; the loader stamps it ours (M154), and the served reason says so."""
    row = {
        "id": "faculty-law-m155", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "organization": "University of Illinois Urbana-Champaign",
        "school": "uiuc", "department": "College of Law", "pi_name": "Pat Lee", "keywords": ["law"],
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    result = rank_opportunity({"major": "Political Science", "desired_fields": ["law"]}, _sanitize_opportunity(row))
    assert f"Matches your interests: law{_OUR_TOPICS}" in result.reasons_fit


def test_the_new_lines_key_with_the_students_terms_and_the_rows_label():
    assert reason_key(f"Matches your interests: nuclear physics, optics{_OUR_TOPICS}", "fit") == {
        "key": "interests_match_ours", "params": {"terms": "nuclear physics, optics"}}
    assert reason_key("Your research interests align with topics we inferred for Prof. Pat Lee", "fit") == {
        "key": "interests_lab_ours", "params": {"lab": "Prof. Pat Lee"}}


def test_the_matcher_version_moved_for_the_new_sentences():
    assert int(MATCHER_VERSION.split(".")[0]) >= 29
