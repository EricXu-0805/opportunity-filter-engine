"""M169: a faculty row that states no research is given no focus area.

A faculty row's description is ours: neutralize_unverified_faculty_claims
writes it from the row's fields ("Faculty research profile for <name> in
<department> at <school>. ..."), and it names research areas only when the row
has research text or keywords that are the source's own topics
(faculty_profile_summary_fields). On a row with neither, the similarity
compared that template, and "Your research interests align with <name>'s
focus area" gave the professor a focus area nothing they wrote states. No line
is written for it now. A row whose keywords carry a stamp keeps "topics we
inferred for <name>" (M155), and a listing, whose description is its own,
keeps the focus area. Scores do not change.
"""
from __future__ import annotations

import pytest

from backend.data_loader import _sanitize_opportunity
from src.evidence import stamp_inferred
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import rank_opportunity, score_upside
from src.matcher.reason_keys import reason_keys

DEPARTMENT = "Ecology and Evolutionary Biology"
PROFILE = {"research_interests_text": "ecology and evolutionary biology", "desired_fields": []}
FOCUS = "Your research interests align with Pat Lee's focus area"
OURS = "Your research interests align with topics we inferred for Pat Lee"
STAMPS = ["derived:openalex_topics", "derived:illinois_experts_concepts", "tag:department_field"]


def _faculty(*, keywords=(), stated=None, stamp=None, labelled=True):
    row = {
        "id": "faculty-m169", "source": "ucla_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "pi_name": "Pat Lee", "department": DEPARTMENT,
        "organization": "University of California, Los Angeles", "keywords": list(keywords),
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    if not labelled:
        del row["pi_name"], row["department"]
    if stated is not None:
        row["metadata"]["research_areas_raw"] = stated
    if stamp:
        stamp_inferred(row["metadata"], "keywords", stamp)
    return _sanitize_opportunity(row)


def _aligned(fit):
    return [line for line in fit if line.startswith("Your research interests align")]


def test_the_description_of_a_row_that_states_no_research_is_our_template():
    row = _faculty()
    assert row["description_raw"].startswith(f"Faculty research profile for Pat Lee in {DEPARTMENT}")
    assert "Research areas" not in row["description_raw"]


@pytest.mark.parametrize("stated", [None, "", "   "], ids=["absent", "empty", "blank"])
def test_a_faculty_row_that_states_no_research_has_no_focus_area(stated):
    _, fit, _ = score_upside(PROFILE, _faculty(stated=stated), precomputed_sim=0.5)
    assert _aligned(fit) == []
    assert not any("focus area" in line for line in fit)


@pytest.mark.parametrize("fields", [{}, {"stated": "Coral reef ecology"}, {"keywords": ["ecology"], "stamp": STAMPS[0]}],
                         ids=["no research", "research text", "stamped keywords"])
def test_a_faculty_row_with_no_name_lab_or_department_has_no_focus_area(fields):
    """No one to name the line after, so none is written, whatever the row
    states."""
    row = _faculty(labelled=False, **fields)
    assert not any(row.get(key) for key in ("pi_name", "lab_or_program", "department"))
    _, fit, _ = score_upside(PROFILE, row, precomputed_sim=0.5)
    assert _aligned(fit) == []


def test_the_served_reasons_name_no_focus_area_on_the_real_similarity():
    """No precomputed similarity: the department's name in our template is
    what the student's text matched."""
    result = rank_opportunity(PROFILE, _faculty())
    assert _aligned(result.reasons_fit) == []
    keys = [key and key["key"] for key in reason_keys(result.reasons_fit, "fit", record=_faculty())]
    assert "interests_lab_focus" not in keys


def test_the_real_similarity_still_counts_toward_the_score():
    """The line goes; the similarity it described still lifts the row."""
    near, _, _ = score_upside(PROFILE, _faculty())
    far, _, _ = score_upside({"research_interests_text": "medieval poetry", "desired_fields": []}, _faculty())
    assert near > far


def test_a_faculty_row_with_research_text_keeps_the_focus_area():
    _, fit, _ = score_upside(PROFILE, _faculty(stated="Coral reef ecology"), precomputed_sim=0.5)
    assert _aligned(fit) == [FOCUS]


@pytest.mark.parametrize("keywords", [["machine learning"], ["research", "computer science"]],
                         ids=["broad topic", "generic words"])
def test_a_faculty_row_whose_own_keywords_name_no_specific_topic_keeps_the_focus_area(keywords):
    """Unstamped faculty keywords are the profile's own (the detail page shows
    them as the source's); our description names them as research areas."""
    row = _faculty(keywords=keywords)
    assert "Research areas: " in row["description_raw"]
    _, fit, _ = score_upside(PROFILE, row, precomputed_sim=0.5)
    assert _aligned(fit) == [FOCUS]


@pytest.mark.parametrize("stamp", STAMPS)
def test_a_faculty_row_with_stamped_keywords_keeps_the_line_that_says_they_are_ours(stamp):
    _, fit, _ = score_upside(PROFILE, _faculty(keywords=["ecology"], stamp=stamp), precomputed_sim=0.5)
    assert _aligned(fit) == [OURS]


@pytest.mark.parametrize("keywords", [[], ["research"]], ids=["none", "generic"])
def test_a_listing_keeps_the_focus_area_its_own_description_carries(keywords):
    row = {
        "id": "m169-nsf", "source": "nsf_reu", "source_type": "summer_program",
        "opportunity_type": "summer_program", "title": "Summer Research Site", "pi_name": "Pat Lee",
        "keywords": keywords, "description_raw": "Students study ecology and evolutionary biology in the field.",
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    _, fit, _ = score_upside(PROFILE, row, precomputed_sim=0.5)
    assert _aligned(fit) == ["Your research interests align with Prof. Pat Lee's focus area"]


@pytest.mark.parametrize("sim", [0.0, 0.5])
def test_only_the_sentence_changes(sim):
    """A row with research text scores as one without when the similarity is
    the same: the line is the only difference."""
    bare, fit, gap = score_upside(PROFILE, _faculty(), precomputed_sim=sim)
    stated, stated_fit, stated_gap = score_upside(PROFILE, _faculty(stated="Coral reef ecology"),
                                                  precomputed_sim=sim)
    assert bare == stated and gap == stated_gap
    assert [line for line in stated_fit if line != FOCUS] == fit


def test_the_matcher_version_moved_for_the_removed_sentence():
    assert int(MATCHER_VERSION.split(".")[0]) >= 35
