"""Confirmed, current source facts reach email writers without provider I/O."""
import hashlib
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.lib.experience_evidence import select_experience
from backend.routes import cold_email as ce
from backend.schemas import ColdEmailRequest, ExperienceEvidence
from src.recommender.cold_email import _common_parts
from tests.experience_fixtures import confirmed_experience

PROFILE = {"name": "Audit Student", "school": "UIUC", "year": "sophomore",
           "major": "Computer Science", "hard_skills": [], "coursework": []}
OPP = {"id": "experience-test", "source_type": "campus_program", "opportunity_type": "research",
       "title": "Renaissance research", "pi_name": "Pat Lee", "organization": "Test University",
       "keywords": ["Renaissance", "cultural history"],
       "description_raw": "Research on Renaissance cultural history.",
       "eligibility": {"skills_required": []}, "application": {}, "metadata": {"is_active": True}}
RELEVANT = "Analyzed Renaissance cultural history using archival manuscripts."


def resume_evidence(text=RELEVANT):
    raw = "🧪 Source heading\n" + text + "\nSource end"
    start = raw.index(text)
    payload = confirmed_experience([text])
    payload["resume_text"] = raw
    payload["entries"][0]["source"] = {
        "kind": "resume", "signature": hashlib.sha256(raw.encode()).hexdigest(),
        "quote": text, "start": start, "end": start + len(text),
    }
    return payload


def selected(payload, legacy=()):
    return select_experience(ExperienceEvidence.model_validate(payload), _common_parts(PROFILE, OPP),
                             legacy_bullets=list(legacy))


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(version=True), lambda p: p.update(version=1.0),
    lambda p: p.update(resume_text="文" * 60001),
    lambda p: p.update(resume_text="\ud800"),
    lambda p: p["entries"][0].update(text="\ud800"),
    lambda p: p["entries"].append(deepcopy(p["entries"][0])),
    lambda p: p["entries"][0].update(id="x" * 81),
    lambda p: p["entries"][0].update(revision=True),
    lambda p: p["entries"][0].update(revision=1.5),
    lambda p: p["entries"][0].update(revision=0),
    lambda p: p["entries"][0].update(revision=9007199254740992),
    lambda p: p["entries"][0].update(text="🧪" * 6001),
    lambda p: p["entries"][0].update(text=" "),
    lambda p: p["entries"][0].update(status="true"),
    lambda p: p["entries"][0]["source"].update(signature="A" * 64),
    lambda p: p["entries"][0]["source"].update(start=True),
    lambda p: p["entries"][0]["source"].update(start=-1),
    lambda p: p["entries"][0]["source"].update(end=60001),
    lambda p: p["entries"][0]["source"].update(end=1),
    lambda p: p["entries"][0]["source"].update(quote=""),
    lambda p: p["entries"][0]["source"].update(kind="github"),
])
def test_malformed_collection_is_rejected_without_truncation(mutation):
    payload = resume_evidence()
    mutation(payload)
    with pytest.raises(ValidationError):
        ExperienceEvidence.model_validate(payload)


def test_collection_count_and_aggregate_limits():
    for payload in (confirmed_experience(["a"] * 101), confirmed_experience(["🧪" * 6000] * 11)):
        with pytest.raises(ValidationError):
            ExperienceEvidence.model_validate(payload)
    payload = resume_evidence("q" * 6000)
    payload["entries"] = [dict(deepcopy(payload["entries"][0]), id=f"id-{i}", text="small") for i in range(11)]
    with pytest.raises(ValidationError):
        ExperienceEvidence.model_validate(payload)
    valid = confirmed_experience(["🧪" * 6000] * 10)
    assert len(ExperienceEvidence.model_validate(valid).entries) == 10


def test_unicode_exact_source_and_full_original_are_preserved():
    payload = resume_evidence("🧪 " + RELEVANT)
    before = deepcopy(payload)
    result = selected(payload)
    assert payload == before
    assert result.eligible[0].text == payload["entries"][0]["text"]
    assert result.selected[0]["source"]["start"] == len("🧪 Source heading\n")
    assert "quote" not in result.selected[0]["source"]
    assert "resume_text" not in result.usage()
    assert result.usage()["needs_review"] is False


@pytest.mark.parametrize(("change", "reason"), [
    (lambda p: p["entries"][0].update(status="candidate"), "candidate"),
    (lambda p: p["entries"][0].update(status="rejected"), "rejected"),
    (lambda p: p["entries"][0].update(status="withdrawn"), "withdrawn"),
    (lambda p: p.update(resume_text=p["resume_text"] + " changed"), "source_signature_mismatch"),
    (lambda p: p["entries"][0]["source"].update(quote="x" * len(RELEVANT)), "source_quote_mismatch"),
])
def test_ineligible_entries_have_explicit_receipt_and_never_fall_back_to_raw(change, reason):
    payload = resume_evidence()
    change(payload)
    result = selected(payload, [RELEVANT])
    assert result.eligible == [] and result.selected == []
    assert result.usage()["excluded"] == [{"id": "experience-0", "revision": 1, "reason": reason}]
    assert result.usage()["notices"] == ["legacy_resume_bullets_unconfirmed"]


def test_legacy_strings_and_explicit_empty_do_not_authenticate_experience():
    for envelope in (None, ExperienceEvidence.model_validate(confirmed_experience([]))):
        result = select_experience(envelope, _common_parts(PROFILE, OPP), legacy_bullets=[RELEVANT])
        assert result.usage()["eligible_count"] == 0
        assert result.selected == [] and result.usage()["needs_review"]


def test_rank_full_collection_before_cap_and_reach_relevant_long_entry_tail():
    texts = ["Organized campus community events."] * 12 + ["Unrelated background. " * 90 + RELEVANT]
    result = selected(confirmed_experience(texts))
    assert result.selected[0]["id"] == "experience-12"
    assert RELEVANT in result.selected[0]["excerpt"]
    assert len(result.selected) == 8
    assert len(result.eligible) == 13
    assert all(item["excerpt"] == texts[int(item["id"].split('-')[1])] for item in result.selected)
    assert sum(len(item["excerpt"]) for item in result.selected) <= 4000
    assert result.template is None  # Never extract a favorable sentence from a longer entry.
    assert "experience_prompt_budget_omission" in result.usage()["notices"]
    assert "experience_template_budget_omission" in result.quoted_usage("")["notices"]


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: OPP})
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: pytest.fail("unexpected provider"))
    async def anonymous(_authorization):
        return None
    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    return TestClient(app)


def payload_for(endpoint, evidence):
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": evidence,
               "resume_bullets": [RELEVANT]}
    if endpoint == "refine":
        payload.update(current_body="Dear Pat Lee,\n\nI am interested in research. Thank you.", instruction="more formal")
    return payload


def response_body(response, endpoint):
    assert response.status_code == 200, response.text
    if endpoint == "stream":
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: ") and json.loads(line[6:]).get("stage") == "done")
    return response.json()


@pytest.mark.parametrize("endpoint", ["", "stream", "variants", "refine"])
def test_every_public_route_uses_confirmed_current_evidence_and_returns_receipt(client, endpoint):
    payload = payload_for(endpoint, resume_evidence())
    payload.pop("resume_bullets")
    if endpoint == "refine":
        payload["current_body"] = "Dear Pat Lee,\n\nI have attached my resume."
    out = response_body(client.post('/api/cold-email' + (f'/{endpoint}' if endpoint else ''), json=payload), endpoint)
    assert out["experience_usage"]["eligible_count"] == 1
    assert len(out["experience_usage"]["selected"]) == 1
    assert out["experience_usage"]["selected"][0]["excerpt"] == RELEVANT
    assert out["pipeline_version"] == "w12.5"
    if endpoint == "variants":
        assert all(v["experience_usage"]["selected"] == out["experience_usage"]["selected"] for v in out["variants"])


@pytest.mark.parametrize("endpoint", ["", "stream", "variants", "refine"])
@pytest.mark.parametrize("evidence", [None, confirmed_experience([])])
def test_legacy_requests_are_usable_but_unconfirmed_strings_are_not_evidence(client, endpoint, evidence):
    payload = payload_for(endpoint, evidence)
    if evidence is None:
        payload.pop("experience_evidence")
    out = response_body(client.post('/api/cold-email' + (f'/{endpoint}' if endpoint else ''), json=payload), endpoint)
    assert out["experience_usage"]["selected"] == []
    assert out["experience_usage"]["notices"] == ["legacy_resume_bullets_unconfirmed"]
    assert RELEVANT not in str(out)


@pytest.mark.parametrize("endpoint", ["", "stream", "variants", "refine"])
def test_invalid_collection_is_rejected_at_http_boundary(client, endpoint):
    evidence = confirmed_experience([RELEVANT])
    evidence["entries"].append(deepcopy(evidence["entries"][0]))
    response = client.post('/api/cold-email' + (f'/{endpoint}' if endpoint else ''), json=payload_for(endpoint, evidence))
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["", "stream", "refine"])
def test_actual_provider_prompt_is_bounded_and_sees_thirteenth_experience(client, monkeypatch, endpoint):
    texts = ["Organized campus community events."] * 12 + ["Unrelated background. " * 90 + RELEVANT]
    evidence = confirmed_experience(texts)
    captured = []
    def provider(messages, **_kwargs):
        captured.extend(messages)
        body = f"Dear Pat Lee,\n\n{RELEVANT}\n\nWould you have time for a conversation?\n\nBest regards,\nAudit Student"
        return body if endpoint == "refine" else f"Subject: Research inquiry\n\n{body}"
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", provider)
    payload = payload_for(endpoint, evidence)
    payload.update(engine="ai")
    payload.pop("resume_bullets")
    out = response_body(client.post('/api/cold-email' + (f'/{endpoint}' if endpoint else ''), json=payload), endpoint)
    assert out["method"] == ("llm" if endpoint == "refine" else "ai"), out
    assert len(out["experience_usage"]["selected"]) == 8
    prompt = next(m["content"] for m in captured if m["role"] == "user" and "STUDENT:" in m["content"])
    assert RELEVANT in prompt and texts[-1] in prompt
    assert sum(len(item["excerpt"]) for item in out["experience_usage"]["selected"]) <= 4000
    assert prompt.count("Organized campus community events.") == 7
    assert len(captured) == 2  # no new model extraction/ranking call


def test_full_eligible_originals_stay_in_fact_corpus_without_upgrading_skill_level():
    evidence = confirmed_experience(["Built a Python parser. " + "Details. " * 100])
    profile = dict(PROFILE, hard_skills=[{"name": "Python", "level": "beginner"}])
    request = ColdEmailRequest(profile=profile, opportunity_id=OPP["id"], experience_evidence=evidence)
    parts, _ = ce._experience_parts(request, profile, OPP)
    assert parts["resume_bullets"] == [evidence["entries"][0]["text"]]
    assert parts["skill_levels"]["Python"] == "beginner"
    assert any(ce._email_grounding_findings("I am an expert in Python.", parts, OPP))


@pytest.mark.parametrize("path", ["", "variants", "refine"])
def test_neutral_final_recovery_receipt_does_not_claim_unused_experiences(client, monkeypatch, path):
    monkeypatch.setattr(ce, "generate_cold_email", lambda *_a, **_k: "")
    monkeypatch.setattr(ce, "generate_variants", lambda *_a, **_k: [
        {"id": "balanced", "label": "Balanced", "text": ""},
    ])
    payload = payload_for(path, confirmed_experience([RELEVANT]))
    if path == "refine":
        payload["current_body"] = "Dear Pat Lee, I have attached my resume."
    out = response_body(client.post('/api/cold-email' + (f'/{path}' if path else ''), json=payload), path)
    assert out["experience_usage"]["eligible_count"] == 1
    assert out["experience_usage"]["selected"] == []


@pytest.mark.parametrize("reason", ["not_configured", "unavailable", "fabrication"])
def test_ai_fallback_receipt_describes_final_template_only(client, monkeypatch, reason):
    monkeypatch.setattr(ce, "is_configured", lambda: reason != "not_configured")
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k:
        None if reason == "unavailable" else "Subject: Research inquiry\n\nDear Pat Lee, I have attached my resume.")
    payload = payload_for('', confirmed_experience(["Organized campus events."] * 12 + [RELEVANT]))
    payload["engine"] = "ai"
    out = response_body(client.post('/api/cold-email', json=payload), '')
    assert out["fallback_reason"] == reason
    assert out["method"] == "template"
    assert len(out["experience_usage"]["selected"]) == 1
    assert out["experience_usage"]["selected"][0]["id"] == "experience-12"


@pytest.mark.parametrize("endpoint", ["", "stream", "variants", "refine"])
@pytest.mark.parametrize("field", ["resume_text", "text", "id", "quote"])
def test_invalid_unicode_returns_private_input_free_422(client, endpoint, field):
    evidence = resume_evidence()
    sensitive = "PRIVATE-RESUME-MARKER-" + chr(0xD800)
    if field == "resume_text":
        evidence[field] = sensitive
    elif field == "quote":
        evidence["entries"][0]["source"][field] = sensitive
    else:
        evidence["entries"][0][field] = sensitive
    payload = payload_for(endpoint, evidence)
    response = client.post(
        '/api/cold-email' + (f'/{endpoint}' if endpoint else ''),
        content=json.dumps(payload), headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    details = response.json()["detail"]
    assert details and all(set(error) == {"loc", "msg", "type"} for error in details)
    assert any(field in error["loc"] for error in details)
    assert "PRIVATE-RESUME-MARKER" not in response.text
    assert RELEVANT not in response.text


def test_exact_whole_entry_budget_and_legal_6000_character_omission():
    long_text = RELEVANT + "🧪" * (4000 - len(RELEVANT))
    result = selected(confirmed_experience(["Organized events."] * 12 + [long_text]))
    assert result.selected == [{"id": "experience-12", "revision": 1,
                                "excerpt": long_text, "source": {"kind": "manual"}}]
    assert len(result.eligible) == 13
    assert result.usage()["notices"] == ["experience_prompt_budget_omission"]
    too_long = RELEVANT + "文" * (6000 - len(RELEVANT))
    result = selected(confirmed_experience([too_long, "Organized events."]))
    assert result.eligible[0].text == too_long
    assert [item["id"] for item in result.selected] == ["experience-1"]
    assert result.usage()["notices"] == ["experience_prompt_budget_omission"]
    assert too_long not in str(result.usage())


def test_budget_skips_whole_nonfitting_entry_and_preserves_later_fit():
    texts = [RELEVANT + "a" * 2900, RELEVANT + "b" * 1900, "Organized events."]
    result = selected(confirmed_experience(texts))
    assert [item["id"] for item in result.selected] == ["experience-0", "experience-2"]
    assert all(item["excerpt"] in texts for item in result.selected)
    assert sum(len(item["excerpt"]) for item in result.selected) <= 4000
    assert result.usage()["notices"] == ["experience_prompt_budget_omission"]


@pytest.mark.parametrize("endpoint", ["", "stream", "refine"])
def test_ai_receives_whole_negative_qualifier_without_more_provider_calls(client, monkeypatch, endpoint):
    negative = ("I did not participate in " +
                "the background documentation and preliminary planning for " * 8 +
                "Renaissance cultural history projects.")
    calls = []
    def provider(messages, **kwargs):
        calls.append((messages, kwargs))
        body = "Dear Pat Lee,\n\nI am interested in Renaissance cultural history. Would you have time for a conversation?"
        return body if endpoint == "refine" else "Subject: Research inquiry\n\n" + body
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", provider)
    payload = payload_for(endpoint, confirmed_experience([negative]))
    payload["engine"] = "ai"
    out = response_body(client.post('/api/cold-email' + (f'/{endpoint}' if endpoint else ''), json=payload), endpoint)
    assert out["method"] == ("llm" if endpoint == "refine" else "ai")
    assert len(calls) == 1
    assert negative in next(m["content"] for m in calls[0][0] if m["role"] == "user")
    assert out["experience_usage"]["selected"][0]["excerpt"] == negative
    assert sum(len(item["excerpt"]) for item in out["experience_usage"]["selected"]) <= 4000


@pytest.mark.parametrize("endpoint", ["", "stream", "variants", "refine"])
def test_templates_do_not_turn_negative_tail_into_positive_experience(client, endpoint):
    negative = ("I did not participate in " +
                "the background documentation and preliminary planning for " * 8 +
                "Renaissance cultural history projects.")
    payload = payload_for(endpoint, confirmed_experience([negative]))
    if endpoint == "refine":
        payload["current_body"] = "Dear Pat Lee, I have attached my resume."
    out = response_body(client.post('/api/cold-email' + (f'/{endpoint}' if endpoint else ''), json=payload), endpoint)
    outputs = out["variants"] if endpoint == "variants" else [out]
    assert out["experience_usage"]["selected"] == []
    assert "experience_template_budget_omission" in out["experience_usage"]["notices"]
    for item in outputs:
        assert "One example of my experience:" not in item["body"]
        assert item["experience_usage"]["selected"] == []
        assert "experience_template_budget_omission" in item["experience_usage"]["notices"]


def test_local_refine_receipt_tracks_second_confirmed_fact_supplied_in_body(client):
    second = "Studied cultural history through archives."
    payload = payload_for("refine", confirmed_experience([RELEVANT, second]))
    payload["current_body"] = f"Dear Pat Lee,\n\n{second}\n\nWould you have time for a conversation?"
    out = response_body(client.post('/api/cold-email/refine', json=payload), "refine")
    assert second in out["body"]
    assert [item["id"] for item in out["experience_usage"]["selected"]] == ["experience-1"]


def test_local_receipt_keeps_existing_size_limit_and_discloses_partial_listing():
    texts = [f"Studied cultural history through archive {i}." for i in range(10)]
    selection = selected(confirmed_experience(texts))
    usage = selection.local_usage("\n".join(texts))
    assert len(usage["selected"]) == 8
    assert usage["notices"] == ["experience_usage_receipt_limit"]
    long_text = RELEVANT + "x" * 4000
    usage = selected(confirmed_experience([long_text])).local_usage(long_text)
    assert usage["selected"] == []
    assert usage["notices"] == ["experience_usage_receipt_limit"]
    assert usage["eligible_count"] == 1
