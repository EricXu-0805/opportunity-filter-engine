"""M164: a faculty display name is not the topic of a research inquiry."""
from copy import deepcopy

import pytest

from backend.lib.email_contact_context import contact_context_parts
from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes import cold_email as ce
from src.evidence import stamp_inferred
from src.recommender.cold_email import _common_parts, generate_cold_email, generate_variants
from tests.test_cold_email_writing_quality import PROFILE
from tests.test_email_contact_context import FIRST, FOLLOW, REFERRAL, result
from tests.test_email_contact_context import client as shared_client


def faculty(*, area="", lab="", inferred=False):
    record = {
        "id": "m164-faculty", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "title": "Pat Lee — Computing",
        "pi_name": "Pat Lee", "department": "Computer Science", "lab_or_program": lab,
        "organization": "Test University", "keywords": [area] if area else [],
        "description_raw": "Pat Lee is a faculty member in Computer Science.",
        "metadata": {"is_active": True, "faculty_title": "Professor"},
        "eligibility": {}, "application": {},
    }
    if inferred:
        stamp_inferred(record["metadata"], "keywords", "derived:department")
    return record


@pytest.mark.parametrize("context", [FIRST, REFERRAL])
@pytest.mark.parametrize("lab_type", ["dry", "wet", "humanities"])
@pytest.mark.parametrize("inferred", [False, True])
def test_no_source_topic_or_lab_uses_a_neutral_subject(context, lab_type, inferred):
    public = project_public_detail(faculty(area="Computer Science" if inferred else "", inferred=inferred))
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(context), lab_type=lab_type)
    assert parts["research_area"] == parts["lab"] == ""
    for variant in generate_variants(PROFILE, public, parts_cache=parts):
        subject, body = variant["text"].split("\n\n", 1)
        assert subject == "Subject: Research inquiry"
        assert "Dear Professor Pat Lee," in body
        assert "?" in body
        if context["purpose"] == "referral":
            assert "Janet Rowan suggested I contact you." in body


@pytest.mark.parametrize("area,lab,expected", [
    ("sparse neural networks", "Lee Lab", "sparse neural networks"),
    ("", "Lee Lab", "Lee Lab"),
])
def test_stated_research_or_lab_can_identify_the_inquiry(area, lab, expected):
    public = project_public_detail(faculty(area=area, lab=lab))
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(FIRST))
    for variant in generate_variants(PROFILE, public, parts_cache=parts):
        subject = variant["text"].split("\n\n", 1)[0]
        assert subject.endswith(f" — {expected}")
        assert "Pat Lee" not in subject


def test_inferred_lab_does_not_replace_the_neutral_subject():
    record = faculty(lab="Imagined Lab")
    stamp_inferred(record["metadata"], "lab_or_program", "estimate:directory")
    public = project_public_detail(record)
    assert all(v["text"].startswith("Subject: Research inquiry\n\n")
               for v in generate_variants(PROFILE, public))


def test_usable_source_phrase_remains_the_subject():
    record = faculty()
    record["metadata"]["research_areas_raw"] = "Sparse neural networks"
    public = project_public_detail(record)
    assert all(v["text"].split("\n\n", 1)[0].endswith(" — Sparse neural networks")
               for v in generate_variants(PROFILE, public))


def test_long_source_context_remains_capped_at_a_word_boundary():
    public = project_public_detail(faculty(lab=(
        "Center for Applied Research in Complex Networks and Adaptive Learning Systems "
        "Across Multiple Environments")))
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(FIRST))
    for variant in generate_variants(PROFILE, public, parts_cache=parts):
        subject = variant["text"].split("\n\n", 1)[0].removeprefix("Subject: ")
        assert len(subject) <= 72
        assert "Center for Applied Research" in subject
        assert parts["lab"].startswith(subject.split(" — ", 1)[1] + " ")


@pytest.mark.parametrize("source_type", ["campus_program", "summer_program", "internship"])
def test_nonfaculty_listing_keeps_its_title(source_type):
    record = faculty()
    record.update(source_type=source_type, source="test_listing", title="Summer Scholars Program")
    public = project_public_detail(record)
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(FIRST))
    assert all(v["text"].split("\n\n", 1)[0].endswith(" — Summer Scholars Program")
               for v in generate_variants(PROFILE, public, parts_cache=parts))


@pytest.mark.parametrize("area,lab", [
    ("", ""), ("sparse neural networks", ""), ("", "Lee Lab"), ("sparse neural networks", "Lee Lab"),
])
def test_faculty_follow_up_subject_names_no_person_area_or_lab(area, lab):
    public = project_public_detail(faculty(area=area, lab=lab))
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(FOLLOW))
    texts = [v["text"] for v in generate_variants(PROFILE, public, parts_cache=parts)]
    for text in [*texts, generate_cold_email(PROFILE, public, parts_cache=parts)]:
        subject, body = text.split("\n\n", 1)
        assert subject == "Subject: Follow-up — research inquiry"
        assert "I am following up on my previous email sent on 2026-09-10." in body


LONG_TITLE = "Summer Undergraduate Research Fellowship in Complex Networks and Adaptive Learning Systems"


@pytest.mark.parametrize("title", ["Summer Scholars Program", LONG_TITLE])
@pytest.mark.parametrize("source_type", ["campus_program", "summer_program", "internship"])
def test_nonfaculty_follow_up_keeps_its_title(source_type, title):
    record = faculty()
    record.update(source_type=source_type, source="test_listing", title=title)
    public = project_public_detail(record)
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(FOLLOW))
    for variant in generate_variants(PROFILE, public, parts_cache=parts):
        subject = variant["text"].split("\n\n", 1)[0].removeprefix("Subject: Follow-up — ")
        assert len(subject) <= 72 - len("Follow-up — ")
        assert subject == title or title.startswith(subject + " ")


def test_untitled_listing_follow_up_uses_the_neutral_topic():
    record = faculty()
    record.update(source_type="campus_program", source="test_listing", title="")
    public = project_public_detail(record)
    parts = _common_parts(PROFILE, public)
    parts.update(contact_context_parts(FOLLOW))
    assert all(v["text"].startswith("Subject: Follow-up — research inquiry\n\n")
               for v in generate_variants(PROFILE, public, parts_cache=parts))


@pytest.fixture
def client(monkeypatch):
    client = shared_client.__wrapped__(monkeypatch)
    record = faculty(area="Computer Science", inferred=True)
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {record["id"]: deepcopy(record)})
    return client


@pytest.mark.parametrize("engine", ["template", "ai"])
@pytest.mark.parametrize("path", ["", "stream", "variants"])
def test_public_routes_and_no_evidence_fallback_use_the_neutral_subject(client, engine, path):
    response = client.post("/api/cold-email" + (f"/{path}" if path else ""), json={
        "profile": PROFILE, "opportunity_id": "m164-faculty", "contact_context": FIRST, "engine": engine,
    })
    out = result(response, path)
    for variant in out.get("variants", [out]):
        assert variant["subject"] == "Research inquiry"
        assert "Dear Professor Pat Lee," in variant["body"]
        assert variant.get("fallback_reason") != "fabrication"
    if path != "variants":
        assert out["method"] == "template"
        assert out["grounding"] == "no_target_data"
        assert out["fallback_reason"] == ("insufficient_evidence" if engine == "ai" else None)


@pytest.mark.parametrize("path", ["", "stream"])
def test_failed_ai_with_verified_paper_uses_the_same_template_subject(client, monkeypatch, path):
    record = faculty()
    record["metadata"].update(publication_attribution_status="verified_author_id",
                              recent_works=[{"title": "Sparse neural networks", "year": 2025}])
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {record["id"]: deepcopy(record)})
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("simulated provider unavailable")

    monkeypatch.setattr(ce, "_pipeline_generate", unavailable)
    out = result(client.post("/api/cold-email" + (f"/{path}" if path else ""), json={
        "profile": PROFILE, "opportunity_id": record["id"], "engine": "ai",
    }), path)
    assert calls == [True]
    assert out["subject"] == "Research inquiry"
    assert out["method"] == "template"
    assert out["fallback_reason"] == "unavailable"
    assert "My name is Audit Student" in out["body"]


@pytest.mark.parametrize("path", ["", "stream", "variants"])
def test_explicit_source_subject_still_wins_even_when_it_contains_the_name(client, monkeypatch, path):
    required = "Research inquiry for Pat Lee"
    policy = {"version": 1, "status": "known", "email_policy": "allowed", "rules": [{
        "kind": "subject", "quote": f'Use the subject "{required}".', "subject": required,
        "source_url": "https://example.edu/join", "checked_at": "2026-09-25T10:00:00Z",
    }]}
    monkeypatch.setattr("backend.lib.public_opportunity_detail.contact_instructions_for", lambda _record: deepcopy(policy))
    out = result(client.post("/api/cold-email" + (f"/{path}" if path else ""), json={
        "profile": PROFILE, "opportunity_id": "m164-faculty", "contact_context": FIRST,
    }), path)
    assert all(v["subject"] == required for v in out.get("variants", [out]))


@pytest.mark.parametrize("area,lab", [("", ""), ("sparse neural networks", ""), ("", "Lee Lab")])
@pytest.mark.parametrize("path", ["", "stream", "variants"])
def test_faculty_follow_up_template_is_served_with_its_sign_off(client, monkeypatch, area, lab, path):
    record = faculty(area=area, lab=lab)
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {record["id"]: deepcopy(record)})
    out = result(client.post("/api/cold-email" + (f"/{path}" if path else ""), json={
        "profile": PROFILE, "opportunity_id": record["id"], "contact_context": FOLLOW, "engine": "template",
    }), path)
    for variant in out.get("variants", [out]):
        assert variant["subject"] == "Follow-up — research inquiry"
        assert "I am following up on my previous email sent on 2026-09-10." in variant["body"]
        assert variant["body"].endswith("Best regards,\nAudit Student")
    if path != "variants":
        assert out["method"] == "template"
        assert out["fallback_reason"] is None
