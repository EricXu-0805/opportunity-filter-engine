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


def test_illinois_experts_concepts_are_not_their_work_in_the_email():
    """M161: Elsevier's concepts from a person's papers were the opener's
    "your work on ..." for 284 UIUC rows; stamped, the email no longer says so."""
    from backend.data_loader import _sanitize_opportunity
    from src.collectors.uiuc_experts import CONCEPTS_METHOD

    row = {"id": "faculty-ansc-m161", "source": "uiuc_faculty", "source_type": "faculty_research",
           "opportunity_type": "research", "organization": "Test University",
           "department": "Department of Animal Sciences", "pi_name": "Pat Lee",
           "keywords": ["Porcine Sperm", "Oviduct"], "eligibility": {}, "application": {},
           "metadata": {"is_active": True, "inferred_fields": {"keywords": CONCEPTS_METHOD}}}
    served = _sanitize_opportunity(row)
    assert _stated_keywords(served) == []
    assert _brief_keywords(project_public_detail(served)) == []
    assert "porcine sperm" not in _email_surfaces(served)


def test_directory_keywords_are_not_their_work_in_the_email(monkeypatch):
    """M166: the UIUC WIGG directory's keyword list was the opener's "your work
    on ..." for 223 rows, as the stated research text and as stated keywords;
    the email no longer says it is what the professor works on."""
    import src.collectors.uiuc_json_faculty as wigg
    from backend.data_loader import _sanitize_opportunity

    person = {"fullName": "Avery Example", "email": "person1@example.edu", "primaryTitle": "Professor",
              "profileUrl": "https://ahs.example.edu/directory/profile/person1",
              "primaryOffice": "Speech and Hearing Science", "keywords": ["Vocal Fatigue", "Room Acoustics"],
              "jobProfiles": [{"jobType": "Faculty"}]}
    monkeypatch.setattr(wigg, "_fetch_json", lambda url: {"people": [person]})
    [row] = wigg.fetch_ahs()
    served = _sanitize_opportunity(row)
    assert _stated_keywords(served) == []
    assert _brief_keywords(project_public_detail(served)) == []
    surfaces = _email_surfaces(served)
    assert "vocal fatigue" not in surfaces and "room acoustics" not in surfaces


def _faculty_row(keywords, title, *, source="uf_faculty", department="Electrical & Computer Engineering"):
    return {"id": "faculty-ece-pubheading", "source": source, "source_type": "faculty_research",
            "opportunity_type": "research", "organization": "Test University", "department": department,
            "pi_name": "Pat Lee", "title": title, "keywords": keywords, "eligibility": {}, "application": {},
            "metadata": {"is_active": True}}


@pytest.mark.parametrize(("keywords", "served_keywords"), [
    (["neural interfaces", "Selected Publications", "device modeling"], ["neural interfaces", "device modeling"]),
    (["Selected Publications"], []),
])
def test_a_publication_heading_is_not_their_work_in_the_email(keywords, served_keywords):
    """A faculty row stored with its profile's publication heading as a keyword
    is served without it, as the next refresh's hygiene will store it: the
    template email said "your work on Selected Publications" (M163 follow-up)."""
    from copy import deepcopy

    from backend.data_loader import _sanitize_opportunity
    from src.collectors.faculty_graph import clean_corpus_faculty_keywords

    row = _faculty_row(keywords, f"Prof. Pat Lee — ECE ({', '.join(keywords)})")
    refreshed = deepcopy(row)
    clean_corpus_faculty_keywords([refreshed])
    served = _sanitize_opportunity(row)
    assert served["keywords"] == refreshed["keywords"] == served_keywords
    assert "selected publications" not in _email_surfaces(served)


def test_what_is_left_after_a_publication_heading_is_stamped_as_stored_without_it():
    """With the heading gone a department's field stands alone, and the loader
    stamps it ours, as it does on a row stored without the heading."""
    from backend.data_loader import _sanitize_opportunity

    row = _faculty_row(["law", "Publications"], "Pat Lee — LAW", source="uiuc_faculty", department="College of Law")
    served = _sanitize_opportunity(row)
    assert served["keywords"] == ["law"]
    assert keywords_basis(served) is not None
    assert "your work on law" not in _email_surfaces(served)


def test_a_program_keeps_its_publications_tag():
    """Only faculty rows: on a program the tag is ours, about what students do."""
    from backend.data_loader import _sanitize_opportunity

    row = _record("illinois_research_programs", "campus_program")
    row["keywords"] = ["summer research", "publications"]
    assert _sanitize_opportunity(row)["keywords"] == ["summer research", "publications"]


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
