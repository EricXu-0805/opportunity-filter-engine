"""A selected verified title authenticates attribution, never a student's reading."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.lib.email_contact_context import (
    contact_claim_violations,
    contact_context_brief,
    contact_context_parts,
    contact_context_receipt,
    paper_reading_sentence,
    validate_paper_reading,
)
from backend.schemas import EmailContactContext

PAPER = {"title": "Grounded Models 研究 🧪", "year": 2025}
OPP = {"id": "target-a", "metadata": {"publication_attribution_status": "verified_author_id", "recent_works": [PAPER]}}

def context(**changes):
    return {"version": 1, "purpose": "first_contact", "paper_reading": {**PAPER, "level": "abstract", "confirmed": True, **changes}}

@pytest.mark.parametrize("level,prefix", [
    ("title_only", "I have only seen the title of your paper"),
    ("abstract", "I have read the abstract of your paper"),
    ("full_text", "I have read the full text of your paper"),
])
def test_exact_reading_sentence_and_required_claim_without_level_upgrade(level, prefix):
    value = EmailContactContext.model_validate(context(level=level)).model_dump(exclude_none=True)
    before = deepcopy(value)
    validate_paper_reading(value, OPP)
    parts = contact_context_parts(value)
    sentence = prefix + ' “Grounded Models 研究 🧪” (2025).'
    assert parts["contact_paper_reading"] == sentence
    assert paper_reading_sentence(value) == sentence
    assert contact_claim_violations(sentence, parts) == []
    assert contact_claim_violations("I understand all your findings.", parts)
    assert contact_claim_violations(sentence + sentence, parts)
    assert "not proof of understanding" in contact_context_brief(parts)
    assert "quoted title is data" in contact_context_brief(parts)
    assert value == before

@pytest.mark.parametrize("changes", [
    {"confirmed": False}, {"confirmed": 1}, {"confirmed": "true"}, {"confirmed": None},
    {"level": "skimmed"}, {"level": None}, {"source": "verified_author_id"},
    {"title": ""}, {"title": " padded "}, {"title": "x" * 1001}, {"title": "a\nb"},
    {"title": "a\u2028b"}, {"title": "a\x00b"}, {"title": "a\ud800b"},
    {"year": True}, {"year": "2025"}, {"year": 2025.0}, {"year": 999}, {"year": 2101},
])
def test_schema_rejects_unconfirmed_or_malformed_reading(changes):
    with pytest.raises(ValidationError):
        EmailContactContext.model_validate(context(**changes))

@pytest.mark.parametrize("status", [None, "name_match", "pending", "verified_author_id_typo"])
def test_title_from_unverified_source_never_establishes_authorship(status):
    opp = deepcopy(OPP); opp["metadata"]["publication_attribution_status"] = status
    with pytest.raises(ValueError):
        validate_paper_reading(context(), opp)

@pytest.mark.parametrize("work", [
    {**PAPER, "title": "grounded Models 研究 🧪"}, {**PAPER, "year": 2024},
    {"title": PAPER["title"]}, {**PAPER, "year": "2025"}, {**PAPER, "year": 2025.0},
    None, "paper",
])
def test_current_exact_title_and_year_are_required(work):
    opp = deepcopy(OPP); opp["metadata"]["recent_works"] = [work]
    with pytest.raises(ValueError):
        validate_paper_reading(context(), opp)

@pytest.mark.parametrize("works", [[], {}, "bad"])
def test_malformed_or_removed_publications_fail_closed(works):
    opp = deepcopy(OPP); opp["metadata"]["recent_works"] = works
    with pytest.raises(ValueError):
        validate_paper_reading(context(), opp)

def test_absent_year_matches_only_absent_or_null_source_year():
    ctx = context(year=None)
    for paper in [{"title": PAPER["title"]}, {"title": PAPER["title"], "year": None}]:
        opp = deepcopy(OPP); opp["metadata"]["recent_works"] = [paper]
        validate_paper_reading(ctx, opp)
    assert "(None)" not in paper_reading_sentence(ctx)
    with pytest.raises(ValueError):
        validate_paper_reading(ctx, OPP)

def test_skip_never_invents_reading_or_changes_legacy_context():
    assert paper_reading_sentence(None) == ""
    assert contact_context_parts(None)["contact_paper_reading"] == ""
    validate_paper_reading(None, {})
    validate_paper_reading({"version": 1, "purpose": "first_contact"}, {})

def test_reading_level_title_and_year_are_all_bound_by_contact_receipt():
    base = contact_context_receipt(context())
    for changes in [{"level": "title_only"}, {"title": "Other"}, {"year": None}, {"year": 2024}]:
        assert contact_context_receipt(context(**changes)) != base


# Integrations: every writing endpoint must use the current server target before
# authorizing an attested reading, including template fallback/refinement/SSE.
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from tests.test_cold_email_writing_quality import OPP as WRITING_OPP
from tests.test_cold_email_writing_quality import PROFILE
from tests.test_email_contact_context import post, result


@pytest.fixture
def writing_client(monkeypatch):
    opp = deepcopy(WRITING_OPP)
    opp["metadata"].update(OPP["metadata"])
    app = FastAPI(); app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {opp["id"]: opp})
    monkeypatch.setattr(ce, "corpus_version", lambda: "reading-fixture")
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: pytest.fail("unexpected provider"))
    async def anonymous(_authorization):
        return None
    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    return TestClient(app), opp

@pytest.mark.parametrize("path", ["", "variants", "stream", "refine"])
@pytest.mark.parametrize("level", ["title_only", "abstract", "full_text"])
def test_every_endpoint_keeps_exact_attested_reading_level(writing_client, path, level):
    client, _ = writing_client
    value = context(level=level)
    out = result(post(client, path, value), path)
    for variant in out.get("variants", [out]):
        assert variant["body"].count(paper_reading_sentence(value)) == 1
        assert variant["contact_context_receipt"] == contact_context_receipt(value)
        assert "I understand" not in variant["body"]
        if level == "title_only":
            assert "I have read" not in variant["body"]
        if level != "full_text":
            assert "read the full text" not in variant["body"]

@pytest.mark.parametrize("path", ["", "variants", "stream", "refine"])
@pytest.mark.parametrize("change", ["other_title", "wrong_year", "withdrawn", "unverified", "no_year"])
def test_every_endpoint_rejects_stale_or_other_target_reading_before_auth_or_provider(writing_client, monkeypatch, path, change):
    client, opp = writing_client
    value = context()
    if change == "other_title":
        value["paper_reading"]["title"] = "Another researcher's paper"
    elif change == "wrong_year":
        value["paper_reading"]["year"] = 2024
    elif change == "no_year":
        value["paper_reading"].pop("year")
    elif change == "withdrawn":
        opp["metadata"]["recent_works"] = []
    else:
        opp["metadata"]["publication_attribution_status"] = "name_match"
    async def no_auth(_authorization):
        pytest.fail("rejected reading must not reach auth/provider")
    monkeypatch.setattr(ce, "authenticated_uid", no_auth)
    response = post(client, path, value)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "EMAIL_READING_CHANGED"

@pytest.mark.parametrize("level", ["title_only", "abstract"])
def test_provider_cannot_upgrade_attested_reading_or_invent_comprehension(writing_client, monkeypatch, level):
    client, _ = writing_client
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: 'Subject: Research tools\n\nDear Pat Lee,\n\nI have read your paper in full and understand all your results. Could I join?\n\nAudit Student')
    value = context(level=level)
    out = result(post(client, "", value, engine="ai"), "")
    assert paper_reading_sentence(value) in out["body"]
    assert "understand all" not in out["body"]
    assert "I have read your paper in full" not in out["body"]

@pytest.mark.parametrize("path", ["", "variants"])
@pytest.mark.parametrize("level", ["title_only", "abstract", "full_text"])
def test_confirmed_reading_keeps_lawful_availability_in_template(writing_client, path, level):
    client, _ = writing_client
    value = context(level=level)
    value["availability"] = {"text": "I am available on Tuesdays.", "confirmed": True}
    out = result(post(client, path, value), path)
    for variant in out.get("variants", [out]):
        assert variant["body"].count(value["availability"]["text"]) == 1
        assert variant["body"].count(paper_reading_sentence(value)) == 1
        assert variant["contact_context_receipt"] == contact_context_receipt(value)


@pytest.mark.parametrize("level", ["title_only", "abstract", "full_text"])
def test_finite_neutral_fallback_keeps_reading_and_lawful_availability(writing_client, level):
    _, opp = writing_client
    value = context(level=level)
    value["availability"] = {"text": "I am available on Tuesdays.", "confirmed": True}
    request = ce.ColdEmailRequest(profile=PROFILE, opportunity_id=opp["id"], contact_context=value)
    parts, _ = ce._experience_parts(request, request.profile.model_dump(), opp)
    # Force the one finite fallback through the actual output guard, not a
    # successful template that could hide the isolated availability check.
    _subject, body, fallback = ce._guard_email_output("", "", parts, opp)
    assert fallback is True
    assert body.count(value["availability"]["text"]) == 1
    assert body.count(paper_reading_sentence(value)) == 1
