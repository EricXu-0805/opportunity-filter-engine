"""M31 step 3: the opener quotes a listing's title without the words our
collectors added to it.

Step 2 quotes the title ('I would like to learn more about “<title>”.'), and
the quote marks present it as the posting's own name. Our collectors add to
some titles: a status suffix ("(applications open)", campus_graph.py and the
UIUC program collectors), a configured program's school tag and hub label
("— Hub (UW)", typed in src/collectors/schools/*.py) and the "REU: " prefix
nsf_reu.py writes in place of the award's "REU Site:". A title the source
wrote itself is quoted as written, however much it looks like one of these.
"""
from __future__ import annotations

import pytest

from backend.lib.public_opportunity_detail import project_public_detail
from src.recommender.cold_email import generate_cold_email

PROFILE = {"name": "Eric", "year": "sophomore", "major": "Biology", "school": "UIUC",
           "hard_skills": ["Python"], "research_interests_text": "developmental biology"}


def _row(source, source_type, title, *, organization="Test University", school=None,
         lab="", metadata=None):
    return project_public_detail({
        "id": f"m31s3-{abs(hash(title))}", "source": source, "source_type": source_type,
        "opportunity_type": "summer_program", "title": title, "lab_or_program": lab,
        "organization": organization, "school": school, "keywords": [],
        "description_raw": "Students work with a faculty mentor for eight weeks.",
        "eligibility": {}, "application": {},
        "metadata": {"is_active": True, **(metadata or {})},
    })


def _configured(title, *, organization, school, status="unknown", source="duke_research_programs"):
    return _row(source, "campus_program", title, organization=organization, school=school,
                metadata={"collector_key": "test_key", "status": status})


def _quoted(public):
    text = generate_cold_email(PROFILE, public)
    body = text.split("\n\n", 1)[1]
    return body.split("I would like to learn more about “", 1)[1].split("”.", 1)[0] \
        if "I would like to learn more about “" in body else None


OURS = {
    # campus_graph.py appends the status the program page showed; the
    # projection keeps it on an actionable listing.
    "lifecycle_suffix": (
        _configured("Bass Connections — Interdisciplinary Research Teams (Duke) (applications open)",
                    organization="Duke University", school="duke", status="open"),
        "Bass Connections — Interdisciplinary Research Teams"),
    "lifecycle_suffix_uiuc_collector": (
        _row("uiuc_drp", "campus_program",
             "CS DRP — Directed Reading Program (Computer Science, Winter Break) (applications open)",
             organization="University of Illinois Urbana-Champaign"),
        "CS DRP — Directed Reading Program (Computer Science, Winter Break)"),
    # nsf_reu.py drops the award's "REU Site:" and prepends "REU: ".
    "prefix": (_row("nsf_reu", "summer_program", "REU: Physics at Kansas State University",
                    organization="Kansas State University"),
               "Physics at Kansas State University"),
    # schools/uw.py: "Office of Undergraduate Research (URP) — Hub (UW)".
    "configured_hub_and_school_tag": (
        _configured("Office of Undergraduate Research (URP) — Hub (UW)",
                    organization="University of Washington", school="uw", source="uw_research_programs"),
        "Office of Undergraduate Research (URP)"),
    "configured_dash_school_tag": (
        _configured("Center for Secure Microelectronics Ecosystem (CSME) — Purdue University",
                    organization="Purdue University", school="purdue", source="purdue_labs"),
        "Center for Secure Microelectronics Ecosystem (CSME)"),
    # A national row has no school; its organization names the university.
    "configured_school_tag_national_row": (
        _configured("Institute for Protein Design — Undergraduate Research Program (UW) (applications open)",
                    organization="Institute for Protein Design, University of Washington", school=None,
                    status="open", source="uw_external_research"),
        "Institute for Protein Design — Undergraduate Research Program"),
    "configured_school_tag_national_row_by_source": (
        _configured("Off-Campus SURF — Caltech", organization="California Institute of Technology",
                    school=None, source="caltech_external_research"),
        "Off-Campus SURF"),
    "configured_school_tag_with_comma": (
        _configured("Summer Research Scholars (University of Tennessee, Knoxville)",
                    organization="University of Tennessee, Knoxville", school="utk",
                    source="utk_research_programs"),
        "Summer Research Scholars"),
}


@pytest.mark.parametrize("case", sorted(OURS))
def test_the_quote_leaves_out_the_words_we_added(case):
    public, expected = OURS[case]
    assert _quoted(public) == expected


SOURCES = {
    # uiuc_our_rss.py takes the blog post's own title.
    "rss_status_prefix": _row("uiuc_our_rss", "rss",
                              "RESEARCH OPPORTUNITY: IHSI Community-Academic Scholars Program"),
    "rss_status_suffix": _row("uiuc_our_rss", "rss",
                              "Maleiha Carino Foundation Scholarship for Cancer Research Advancement "
                              "- APPLICATIONS DUE SOON"),
    # A posting's own "(Applications Open)" is not a suffix we appended.
    "sro_own_parenthetical": _row("uiuc_sro", "summer_program",
                                  "Summer Research in Neuroscience (Applications Open)"),
    # A crawl-discovered campus row is titled by the page's own link text.
    "discovered_school_tag": _row("uw_research_programs", "campus_announcement",
                                  "Undergraduate Research Collective (UW)",
                                  organization="University of Washington", school="uw",
                                  metadata={"discovered": True}),
    # A configured program's acronym and subtitle are not a school tag.
    "configured_acronym": _configured("MISTI — MIT International Science and Technology Initiatives",
                                      organization="Massachusetts Institute of Technology", school="mit",
                                      source="mit_research_programs"),
    "configured_unit_tag": _configured("Petit Undergraduate Research Scholars Program (IBB)",
                                       organization="Georgia Institute of Technology", school="gatech",
                                       source="gatech_research_programs"),
}


@pytest.mark.parametrize("case", sorted(SOURCES))
def test_a_title_the_source_wrote_is_quoted_as_written(case):
    public = SOURCES[case]
    assert _quoted(public) == public["title"]


def test_a_title_that_is_only_our_words_falls_back_to_the_lab_line():
    public = _configured("(applications open)", organization="Duke University", school="duke",
                         status="open")
    public["lab_or_program"] = "Bass Connections"
    text = generate_cold_email(PROFILE, public)
    assert "“" not in text.split("\n\n", 1)[1]
    assert "I would like to learn more about the work in the Bass Connections." in text
