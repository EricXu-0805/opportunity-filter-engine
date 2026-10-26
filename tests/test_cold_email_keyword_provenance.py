"""M31: a record's keywords reach the cold email as the source's words only
when the detail page shows them as the source's own topics.

The detail page and the public ``keywords_attribution`` decide this with
``keywords_basis``: a listing's keywords are ours on every collector but the
SRO, stamped or not. The email paths read only the inference stamp, so a
Simplify category-map tag, a campus program's config tag or a keyword-bank hit
reached the AI brief under "Source-stated keywords" and the template opener
as "your work on ...".
"""
from __future__ import annotations

import json

import pytest

from backend.lib.opportunity_detail import keywords_basis
from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes import cold_email as ce
from src.evidence import keywords_are_source_topics, stamp_inferred
from src.recommender.cold_email import (
    _common_parts,
    _stated_keywords,
    generate_cold_email,
    has_source_backed_target_evidence,
)

KEYWORDS = ["zebrafish fin regeneration", "cryo-electron tomography"]
PROFILE = {"name": "Eric", "year": "sophomore", "major": "Biology", "school": "UIUC",
           "hard_skills": ["Python"], "research_interests_text": "developmental biology"}

# (source, source_type) of listings whose unstamped keywords we wrote.
OUR_TAGS = {
    "simplify": ("simplify_internships", "internship"),
    "campus_program_spec": ("illinois_research_programs", "campus_program"),
    "manual": ("manual", "manual"),
    "nsf_reu": ("nsf_reu", "summer_program"),
    "normalizer": ("uiuc_our_rss", "rss"),
}


def _record(source, source_type, *, description="", **metadata):
    return {
        "id": f"m31-{source}", "source": source, "source_type": source_type,
        "opportunity_type": "research", "title": "Summer Research Program",
        "organization": "Test University", "pi_name": "Pat Lee", "keywords": list(KEYWORDS),
        "description_raw": description, "eligibility": {}, "application": {},
        "metadata": {"is_active": True, **metadata},
    }


def _faculty(*, stamped=False):
    opp = _record("faculty_graph", "faculty_research")
    if stamped:
        stamp_inferred(opp["metadata"], "keywords", "derived:openalex_topics")
    return opp


def _brief_keywords(public):
    brief = ce._render_professor_brief(_common_parts(PROFILE, public), public)
    line = next(line for line in brief.splitlines() if line.startswith("- Source-stated keywords: "))
    return json.loads(line.split(": ", 1)[1])


def _email_surfaces(opp):
    """Everything the email paths build from one record, as one lower-cased text."""
    public = project_public_detail(opp)
    parts = _common_parts(PROFILE, public)
    return " ".join([
        generate_cold_email(PROFILE, public),
        ce._render_professor_brief(parts, public),
        " ".join(ce._professor_anchors(parts, public)),
        ce._build_email_corpus(parts, public),
    ]).lower()


@pytest.mark.parametrize("kind", sorted(OUR_TAGS))
def test_our_listing_tags_are_not_offered_as_the_sources_words(kind):
    opp = _record(*OUR_TAGS[kind], description="Students join a ten-week summer cohort on campus.")
    public = project_public_detail(opp)
    # The detail page shows these keywords as ours; the email must agree.
    assert keywords_basis(opp) is not None and public.get("keywords_attribution") == "inferred"
    assert _stated_keywords(public) == []
    assert _brief_keywords(public) == []
    surfaces = _email_surfaces(opp)
    for keyword in KEYWORDS:
        assert keyword not in surfaces, (kind, keyword)


@pytest.mark.parametrize("kind", sorted(OUR_TAGS))
def test_our_listing_tags_alone_do_not_open_the_personalization_gate(kind):
    public = project_public_detail(_record(*OUR_TAGS[kind]))
    assert has_source_backed_target_evidence(public, _common_parts(PROFILE, public)) is False


@pytest.mark.parametrize("opp", [
    _record("uiuc_sro", "summer_program"),
    _faculty(),
], ids=["sro_research_area", "unstamped_faculty"])
def test_the_sources_own_topics_still_reach_the_email(opp):
    public = project_public_detail(opp)
    assert keywords_basis(opp) is None and "keywords_attribution" not in public
    assert _brief_keywords(public) == KEYWORDS
    assert "your work on zebrafish fin regeneration and cryo-electron tomography" in generate_cold_email(PROFILE, public)
    assert has_source_backed_target_evidence(public, _common_parts(PROFILE, public)) is True


def test_a_stamped_faculty_row_stays_excluded():
    opp = _faculty(stamped=True)
    public = project_public_detail(opp)
    assert keywords_basis(opp) is not None
    assert _brief_keywords(public) == []
    surfaces = _email_surfaces(opp)
    assert all(keyword not in surfaces for keyword in KEYWORDS)


def test_a_department_field_the_loader_tags_is_not_their_work_in_the_email():
    """A UIUC profile that states no research keeps its department's field as
    keywords; the loader stamps it ours (M154), so the email no longer says it
    is what the professor works on."""
    from copy import deepcopy

    from backend.data_loader import _sanitize_opportunity

    row = {"id": "faculty-law-m154", "source": "uiuc_faculty", "source_type": "faculty_research",
           "opportunity_type": "research", "organization": "Test University", "department": "College of Law",
           "pi_name": "Pat Lee", "keywords": ["law and society"], "eligibility": {}, "application": {},
           "metadata": {"is_active": True}}
    stated = deepcopy(row)
    row["keywords"] = ["law"]
    served = _sanitize_opportunity(row)
    assert keywords_basis(served) is not None
    assert _stated_keywords(served) == []
    assert _brief_keywords(project_public_detail(served)) == []
    assert "your work on law" not in _email_surfaces(served)
    # The same row with a topic the page stated still names it.
    assert "your work on law and society" in _email_surfaces(_sanitize_opportunity(stated))


@pytest.mark.parametrize("opp", [
    *(_record(*value) for value in OUR_TAGS.values()),
    _record("illinois_research_programs", "campus_program", discovered=True),
    _record("uiuc_sro", "summer_program"),
    _record("handshake", "internship"),
    {**_record("uiuc_sro", "summer_program"), "source_type": None},
    _faculty(), _faculty(stamped=True),
])
def test_one_rule_for_the_detail_page_and_the_email(opp):
    """The canonical record and its public projection get the same answer, and
    it is the detail page's."""
    public = project_public_detail(opp)
    assert keywords_are_source_topics(opp) is keywords_are_source_topics(public) is (keywords_basis(opp) is None)
