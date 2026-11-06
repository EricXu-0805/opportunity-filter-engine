"""M167: a broad source label must not erase a grounded student introduction."""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.data_loader import _sanitize_opportunity
from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes import cold_email as ce
from src.recommender.cold_email import _common_parts, generate_variants, has_source_backed_target_evidence
from tests.experience_fixtures import confirmed_experience

PROFILE = {
    "name": "Alex Example", "school": "UIUC", "year": "sophomore", "major": "Computer Science",
    "hard_skills": [{"name": "Python", "level": "beginner", "confirmed": True}],
    "research_interests_text": "artificial intelligence",
}


def faculty(raw="Artificial Intelligence", *, keywords=None, inferred=True, department="Computer Science",
            rank="Professor"):
    row = {
        "id": "m167-faculty", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "title": "Jordan Example", "pi_name": "Jordan Example",
        "organization": "University of Illinois Urbana-Champaign", "department": department,
        "url": "https://example.edu/people/jordan", "source_url": "https://example.edu/people/jordan",
        "keywords": keywords if keywords is not None else ["computer vision", "image classification"],
        "eligibility": {}, "application": {},
        "metadata": {"is_active": True, "faculty_title": rank, "research_areas_raw": raw},
    }
    if inferred:
        row["metadata"]["inferred_fields"] = {"keywords": "derived:illinois_experts_concepts"}
    return _sanitize_opportunity(row)


def _variant(variants, variant_id):
    return next(v["text"] for v in variants if v["id"] == variant_id)


def _base_drafts(opp):
    """Drafts with no profile sentence, identical to the drafts without the label."""
    parts = _common_parts(PROFILE, opp)
    variants = generate_variants(PROFILE, opp, parts_cache=parts)
    for variant in variants:
        assert "Your profile lists" not in variant["text"]
    assert variants == generate_variants(PROFILE, opp, parts_cache={**parts, "broad_research_label": ""})
    return variants


@pytest.mark.parametrize("area", ["Artificial Intelligence", "Machine Learning", "Computer Science"])
def test_broad_source_label_preserves_student_background_in_every_variant(area):
    opp = project_public_detail(faculty(area))
    parts = _common_parts(PROFILE, opp)
    assert not has_source_backed_target_evidence(opp, parts)
    for variant in generate_variants(PROFILE, opp, parts_cache=parts):
        subject, body = ce._extract_subject_and_body(variant["text"])
        assert f'Your profile lists “{area}” as a research area.' in body
        assert "interested in your research in" not in body and "your work on" not in body
        assert "Alex Example" in body and "Computer Science" in body and "UIUC" in body
        assert "foundational exposure to Python" in body
        assert "computer vision" not in body and "image classification" not in body
        assert ce._email_grounding_findings(subject + "\n" + body, parts, opp, deterministic=True) == ([], [])
        assert ce._guard_email_output(subject, body, parts, opp, deterministic=True) == (subject, body, False)


def test_broad_stated_keywords_with_no_stored_research_text_keep_the_existing_drafts():
    opp = project_public_detail(faculty("", keywords=["Biology", "Chemistry"], inferred=False))
    variants = _base_drafts(opp)
    assert "interested in your research in Biology." in _variant(variants, "concise")


@pytest.mark.parametrize("department,rank,keywords", [
    ("Statistics", "Professor", ["Statistics"]),
    ("Environmental Science", "Dean, College of Natural Resources", ["natural resources"]),
])
def test_a_department_or_title_keyword_is_not_quoted_as_a_profile_area(department, rank, keywords):
    _base_drafts(project_public_detail(faculty("", keywords=keywords, inferred=False,
                                               department=department, rank=rank)))


@pytest.mark.parametrize("raw,keywords", [
    ("Ph.D., Example University, 2012, Political Science, B.A., Example College, 2003, Chemistry",
     ["Chemistry"]),
    ("Studies how the brain gives rise to the psychology of mental states", ["psychology"]),
    ("Molecular Biology", ["Biology"]),
    ("Biology/Chemistry", ["Biology"]),
])
def test_a_label_that_is_not_a_whole_list_item_is_not_quoted(raw, keywords):
    _base_drafts(project_public_detail(faculty(raw, keywords=keywords, inferred=False)))


@pytest.mark.parametrize("raw", [
    "Law and Technology", "Law and Technology.", "Biology, Law and Technology", "Biology, and Law and Technology",
    "Law and Technology; Biology", "Biology | Law and Technology", "Law and Technology\nBiology",
    "Biology / Law and Technology",
])
def test_a_whole_list_item_is_quoted_as_the_page_wrote_it(raw):
    opp = project_public_detail(faculty(raw, keywords=["law and technology"], inferred=False))
    parts = _common_parts(PROFILE, opp)
    for variant in generate_variants(PROFILE, opp, parts_cache=parts):
        subject, body = ce._extract_subject_and_body(variant["text"])
        assert 'Your profile lists “Law and Technology” as a research area.' in body
        assert ce._guard_email_output(subject, body, parts, opp, deterministic=True) == (subject, body, False)


def test_two_broad_stated_keywords_that_are_both_list_items_quote_the_research_area():
    opp = project_public_detail(faculty("Biology, Chemistry", keywords=["Biology", "Chemistry"], inferred=False))
    for variant in generate_variants(PROFILE, opp, parts_cache=_common_parts(PROFILE, opp)):
        assert 'Your profile lists “Biology” as a research area.' in variant["text"]


def test_a_specific_list_item_after_a_broad_one_keeps_the_your_work_on_sentence():
    opp = project_public_detail(faculty("Artificial Intelligence, protein structure prediction"))
    variants = _base_drafts(opp)
    assert "your work on Artificial Intelligence." in _variant(variants, "balanced")


def test_a_named_institution_among_the_keywords_is_not_a_specific_topic():
    opp = project_public_detail(faculty("Biology", keywords=["Biology", "Example Cancer Center"], inferred=False))
    parts = _common_parts(PROFILE, opp)
    for variant in generate_variants(PROFILE, opp, parts_cache=parts):
        assert 'Your profile lists “Biology” as a research area.' in variant["text"]
        assert "Example Cancer Center" not in variant["text"]


def test_a_specific_stated_keyword_after_a_broad_one_keeps_the_your_work_on_sentence():
    opp = project_public_detail(faculty("Bioengineering", keywords=["Bioengineering", "tissue scaffolds"],
                                        inferred=False))
    parts = _common_parts(PROFILE, opp)
    assert parts["research_area"] == "Bioengineering"
    assert has_source_backed_target_evidence(opp, parts)
    variants = generate_variants(PROFILE, opp, parts_cache=parts)
    for variant in variants:
        assert "Your profile lists" not in variant["text"]
    assert "your work on Bioengineering and tissue scaffolds" in _variant(variants, "balanced")
    assert "interested in your research in Bioengineering." in _variant(variants, "concise")


def test_a_specific_stated_keyword_past_the_three_the_opener_names_keeps_the_your_work_on_sentence():
    opp = project_public_detail(faculty("Physics, Chemistry, Biology",
                                        keywords=["Physics", "Chemistry", "Biology", "plasma diagnostics"],
                                        inferred=False))
    parts = _common_parts(PROFILE, opp)
    assert parts["research_topic"] == "Physics, Chemistry, and Biology"
    variants = generate_variants(PROFILE, opp, parts_cache=parts)
    for variant in variants:
        assert "Your profile lists" not in variant["text"]
    assert "your work on Physics, Chemistry, and Biology" in _variant(variants, "balanced")


@pytest.mark.parametrize("raw", ["", "Department of Computer Science", "Research", "Office: Room 205"])
def test_department_inferred_topics_and_nonresearch_text_do_not_become_a_profile_area(raw):
    opp = project_public_detail(faculty(raw))
    parts = _common_parts(PROFILE, opp)
    for variant in generate_variants(PROFILE, opp, parts_cache=parts):
        assert "Your profile lists" not in variant["text"]
        assert "your work on computer vision" not in variant["text"]


@pytest.mark.parametrize("area", ["visual representation learning", "Data Science"])
def test_specific_source_research_keeps_its_existing_opener_and_gate(area):
    opp = project_public_detail(faculty(area))
    parts = _common_parts(PROFILE, opp)
    assert has_source_backed_target_evidence(opp, parts)
    variants = generate_variants(PROFILE, opp, parts_cache=parts)
    assert f"your work on {area}" in variants[0]["text"]
    assert "Your profile lists" not in variants[0]["text"]


def test_a_listing_with_a_broad_area_from_its_title_gets_no_profile_sentence():
    row = _sanitize_opportunity({
        "id": "m167-program", "source": "example_programs", "source_type": "program",
        "opportunity_type": "summer_program", "title": "Summer Research in Biology",
        "organization": "Example University", "url": "https://example.edu/summer",
        "keywords": [], "eligibility": {}, "application": {},
        "metadata": {"is_active": True, "research_areas_raw": "Biology"},
    })
    opp = project_public_detail(row)
    parts = _common_parts(PROFILE, opp)
    assert not parts["is_faculty"] and parts["research_area"] == "biology"
    for variant in generate_variants(PROFILE, opp, parts_cache=parts):
        assert "Your profile lists" not in variant["text"]


@pytest.mark.parametrize("engine", ["template", "ai", "variants"])
def test_route_keeps_broad_source_background_without_calling_a_provider(monkeypatch, engine):
    opp = faculty()
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {opp["id"]: deepcopy(opp)})
    monkeypatch.setattr(ce, "corpus_version", lambda: "m167-test")
    async def anonymous(_auth):
        return None
    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    def no_provider(*_a, **_k):
        pytest.fail("a broad source label must not authorize model personalization")
    monkeypatch.setattr(ce, "_pipeline_generate", no_provider)
    monkeypatch.setattr(ce, "chat_completion", no_provider)
    experience = "Built an artificial intelligence demo with Python."
    response = TestClient(app).post(
        "/api/cold-email/variants" if engine == "variants" else "/api/cold-email",
        json={"profile": PROFILE, "opportunity_id": opp["id"], "engine": "ai" if engine == "ai" else "template",
              "experience_evidence": confirmed_experience([experience])},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["grounding"] == "no_target_data"
    drafts = result["variants"] if engine == "variants" else [result]
    for draft in drafts:
        assert "Alex Example" in draft["body"] and "foundational exposure to Python" in draft["body"]
        assert 'Your profile lists “Artificial Intelligence” as a research area.' in draft["body"]
        assert experience in draft["body"]
        assert draft["experience_usage"]["selected"]
        assert draft.get("fallback_reason") != "fabrication"
    if engine == "ai":
        assert result["fallback_reason"] == "insufficient_evidence"


def test_broad_label_does_not_relax_existing_fabrication_or_attachment_checks():
    opp = project_public_detail(faculty())
    parts = _common_parts(PROFILE, opp)
    for claim, expected in [
        ("I would like to learn about your work on machine learning.", "ungrounded research claim"),
        ("I have attached my resume.", "unsupported attachment claim"),
    ]:
        fabricated, _borrowed = ce._email_grounding_findings(claim, parts, opp, deterministic=True)
        assert expected in fabricated
    _, body, replaced = ce._guard_email_output("Research inquiry", "I have attached my resume.", parts, opp, deterministic=True)
    assert replaced and "attached" not in body and "Alex Example" not in body
