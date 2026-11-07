"""M174: a keyword a collector writes on every row it emits is no interest match.

The campus collectors append each row's source type ("program", "department",
"lab", "announcement"), and a page their crawl discovered carries only that and
"undergraduate research": 1,629 rows on the 2026-11-07 corpus. The UIUC Siebel,
OUR-program, URAP, DRP and URSA collectors write one fixed list on every row
("research", "computer_science", "siebel", "mentor"; "research",
"program_overview"; "research", "mentorship", "undergraduate"; "research",
"reading", "mentor", "directed_reading"; "research", "engineering", "freshman",
"sophomore", "mentor"): 26 rows. None of it is the page's words, yet the
interest match read it: a student who wrote "undergraduate research" matched
every discovered campus row, and "research" on a Siebel or DRP row sat inside
chips such as "hiv research" and "ux research". The card then said "Matches
your interests: undergraduate research — based on topics we inferred", and the
score counted it.

The interest match (the student's chips against the row's keywords), with the
score it adds, its line and the field-relevance count, skips these keywords
now. The interest-text bonus and the topic-alignment check read them as before.
The detail page shows what it showed: it already leaves the campus collectors'
constants out of a row's research content.
"""
from __future__ import annotations

import copy

import pytest

from backend.lib.opportunity_detail import build_detail_fields
from backend.routes.opportunities import _redact
from src.evidence import collector_constant_keywords
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import rank_opportunity, score_upside


def _campus(*, keywords, discovered=False, source="duke_research_programs", source_type="announcement"):
    row = {
        "id": "m174-campus", "source": source, "source_type": f"campus_{source_type}",
        "campus_source_type": source_type, "opportunity_type": "research",
        "title": "Summer Research Opportunities", "keywords": list(keywords),
        "description_raw": "Students join a lab for the summer.", "eligibility": {}, "application": {},
        "metadata": {"is_active": True},
    }
    if discovered:
        row["metadata"]["discovered"] = True
    return row


def _berkeley_discovered():
    """ucb_campus._normalize_discovered's row (ucb-b0c3175dfa7a3a's shape)."""
    return {
        "id": "m174-ucb", "source": "ucb_research_programs", "source_type": "ucb_department",
        "ucb_source_type": "department", "opportunity_type": "research",
        "title": "Student Research Opportunities", "keywords": ["department", "undergraduate research"],
        "description_raw": "Student Research Opportunities", "eligibility": {}, "application": {},
        "metadata": {"is_active": True, "discovered": True},
    }


def _uiuc(source, keywords):
    return {
        "id": f"m174-{source}", "source": source, "opportunity_type": "research",
        "title": "Research Mentoring Program", "keywords": list(keywords),
        "description_raw": "A mentoring program for undergraduates.", "eligibility": {}, "application": {},
        "metadata": {"is_active": True},
    }


SIEBEL = ["research", "computer_science", "siebel", "mentor"]
URAP = ["research", "mentorship", "undergraduate"]
OUR_PROGRAM = ["research", "program_overview", "grainger_isur"]
DRP = ["research", "reading", "mentor", "directed_reading", "drp-math"]
URSA = ["research", "engineering", "freshman", "sophomore", "mentor"]


def _profile(*chips):
    return {"research_interests_text": ", ".join(chips), "desired_fields": list(chips),
            "seeking_type": ["research"]}


def _interest_lines(fit):
    return [line for line in fit if line.startswith("Matches your interests")]


@pytest.mark.parametrize(("row", "chips"), [
    (_berkeley_discovered(), ("undergraduate research",)),
    (_campus(keywords=["announcement", "undergraduate research"], discovered=True), ("undergraduate research",)),
    (_campus(keywords=["lab"], source="ucb_labs", source_type="lab"), ("lab",)),
    (_uiuc("uiuc_siebel", SIEBEL), ("hiv research", "ux research", "mentor")),
    (_uiuc("uiuc_other", OUR_PROGRAM), ("research internship",)),
    (_uiuc("ucb_urap", URAP), ("mentorship", "undergraduate research")),
    (_uiuc("uiuc_urap", URAP), ("mentorship",)),
    (_uiuc("uiuc_drp", DRP), ("hiv research", "mentor", "reading")),
    (_uiuc("uiuc_ursa", URSA), ("hiv research", "mentor", "engineering")),
], ids=["berkeley discovered", "campus discovered", "lab type", "siebel", "our program", "ucb urap", "uiuc urap",
        "drp", "ursa"])
def test_a_collector_constant_is_no_interest_match(row, chips):
    profile = _profile(*chips)
    bare = {**row, "keywords": []}
    score, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert _interest_lines(fit) == []
    assert score == score_upside(profile, bare, precomputed_sim=0.0)[0]
    result = rank_opportunity(profile, row, precomputed_sim=0.0)
    assert _interest_lines(result.reasons_fit) == []
    assert result.field_relevant is False


def test_the_rows_own_keywords_still_match_beside_a_constant():
    # A UCSB URCA project: the bank's keywords off its title, then the constant.
    row = _campus(keywords=["machine learning", "undergraduate research"], discovered=True,
                  source="ucsb_urca_projects", source_type="program")
    _, fit, _ = score_upside(_profile("undergraduate research", "machine learning"), row, precomputed_sim=0.0)
    lines = _interest_lines(fit)
    assert len(lines) == 1
    assert lines[0].startswith("Matches your interests: machine learning")
    assert "undergraduate research" not in lines[0]


def test_a_keyword_that_contains_a_constant_still_matches():
    # "program" is this row's constant; "summer program" is its own keyword.
    row = _campus(keywords=["summer program", "program"], source_type="program")
    _, fit, _ = score_upside(_profile("summer program"), row, precomputed_sim=0.0)
    lines = _interest_lines(fit)
    assert len(lines) == 1 and lines[0].startswith("Matches your interests: summer program")
    assert rank_opportunity(_profile("summer program"), row, precomputed_sim=0.0).field_relevant


@pytest.mark.parametrize("row", [
    # A program spec someone typed "undergraduate research" into, on a row the
    # crawl did not discover: a tag of this program, ours but about it.
    _campus(keywords=["undergraduate research", "program"], source="ucb_research_programs",
            source_type="program"),
    # A source type's word on a row that has no source type.
    _uiuc("nsf_reu", ["announcement", "undergraduate research"]),
], ids=["configured tag", "no source type"])
def test_the_same_words_elsewhere_are_still_a_match(row):
    _, fit, _ = score_upside(_profile("undergraduate research"), row, precomputed_sim=0.0)
    lines = _interest_lines(fit)
    assert len(lines) == 1 and "undergraduate research" in lines[0]
    assert rank_opportunity(_profile("undergraduate research"), row, precomputed_sim=0.0).field_relevant


@pytest.mark.parametrize(("row", "constants"), [
    (_berkeley_discovered(), {"department", "undergraduate research"}),
    (_campus(keywords=["robotics", "program"], source_type="program"), {"program"}),
    (_uiuc("uiuc_siebel", SIEBEL), set(SIEBEL)),
    (_uiuc("uiuc_other", OUR_PROGRAM), {"research", "program_overview"}),
    (_uiuc("uiuc_drp", DRP), {"research", "reading", "mentor", "directed_reading"}),
    (_uiuc("uiuc_ursa", URSA), set(URSA)),
    (_uiuc("nsf_reu", ["robotics"]), set()),
    ({**_uiuc("nsf_reu", ["undergraduate research"]), "metadata": {"discovered": True}}, set()),
], ids=["berkeley discovered", "campus program", "siebel", "our program", "drp", "ursa", "nsf",
        "discovered, no type"])
def test_the_constants_by_collector(row, constants):
    assert collector_constant_keywords(row) == constants


def _research_content(row):
    return build_detail_fields(_redact(copy.deepcopy(row)), row)["fields"]["research_content"]


def test_the_detail_page_keeps_what_it_showed():
    """Its research content leaves out the campus constants, as before, and
    still shows a Siebel or DRP row's list as topics we inferred."""
    campus = _research_content(_berkeley_discovered())
    assert "research_areas" not in campus["explicit"] and "research_areas" not in campus["inferred"]
    for source, keywords in (("uiuc_siebel", SIEBEL), ("uiuc_drp", DRP)):
        research = _research_content(_uiuc(source, keywords))
        assert research["inferred"]["research_areas"]["value"] == keywords


def test_the_matcher_version_moved_for_the_match():
    assert int(MATCHER_VERSION.split(".")[0]) >= 36
