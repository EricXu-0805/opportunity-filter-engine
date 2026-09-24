"""M32 end-to-end route wiring with all provider/auth I/O stubbed."""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.lib.email_claims import skill_level_violations, unsupported_action_claims
from backend.routes import cold_email as ce
from src.recommender.cold_email import _common_parts
from tests.experience_fixtures import confirmed_experience

PROFILE = {
    "name": "Eric", "school": "UIUC", "year": "sophomore", "major": "Computer Science",
    "hard_skills": [{"name": "Python", "level": "beginner", "confirmed": True}],
    "research_interests_text": "Python parser research", "coursework": ["CS 225"],
}
OPP = {
    "id": "claim-contract", "source_type": "campus_program", "opportunity_type": "research",
    "title": "Python Parser Research", "pi_name": "Pat Lee", "organization": "Test University",
    "keywords": ["Python", "parser"], "description_raw": "Research on Python parser tools.",
    "eligibility": {"skills_required": ["Python"]}, "application": {}, "metadata": {"is_active": True},
}


def body(claim):
    return f"Dear Pat Lee,\n\n{claim}\n\nWould you have 15 minutes for a conversation?\n\nBest regards,\nEric"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: OPP})
    monkeypatch.setattr(ce, "corpus_version", lambda: "test-corpus")
    async def anonymous(_auth):
        return None
    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    # Defaults guarantee a new test cannot accidentally contact a provider.
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: None)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k: None)
    return TestClient(app)


def request(client, monkeypatch, path, claim, profile=None, bullets=()):
    monkeypatch.setattr(ce, "is_configured", lambda: path != "local-unconfigured")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: None if path == "local-failed" else body(claim))
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k: f"Subject: Research inquiry\n\n{body(claim)}")
    payload = {"profile": profile or PROFILE, "opportunity_id": OPP["id"], "experience_evidence": confirmed_experience(list(bullets))}
    if path == "initial":
        payload["engine"] = "ai"
        endpoint = "/cold-email"
    else:
        payload.update(current_body=body(claim), instruction="Keep my facts and make it warmer")
        endpoint = "/cold-email/refine"
    response = client.post(f"/api{endpoint}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("path", ["initial", "refine", "local-unconfigured", "local-failed"])
@pytest.mark.parametrize("claim", [
    "I have attached my resume.", "Please find my attached CV.",
    "I have read your paper.", "After reading your paper, I am interested in your research.",
    "I am an expert in Python.", "I have hands-on experience with Python.",
    "I finished reading your paper before writing.", "After carefully reading your paper, I have a question.",
    "I have read through your recent paper.", "I included my resume as an attachment.",
    "My resume has been included with this email.",
    "Having reviewed your recent work, I will apply to your group.",
])
def test_all_generation_and_refinement_paths_reject_new_unsupported_claims(client, monkeypatch, path, claim):
    out = request(client, monkeypatch, path, claim)
    assert out["method"] in ("template", "local"), out
    assert out["fallback_reason"] == "fabrication"
    assert claim not in out["body"]
    assert unsupported_action_claims(out["body"]) == []
    assert skill_level_violations(out["body"], {"Python": "beginner"}) == []


@pytest.mark.parametrize("path", ["initial", "refine", "local-unconfigured", "local-failed"])
@pytest.mark.parametrize("claim,bullets", [
    ("I built a Python parser.", ["Built a Python parser."]),
    ("I attached a force sensor to the robotic arm.", ["Attached a force sensor to the robotic arm."]),
    ("I enclosed the detector in a protective casing.", ["Enclosed the detector in a protective casing."]),
    ("I would be happy to share my resume on request.", []),
    ("I have not attached my resume.", []),
    ("I have not read your paper.", []),
    ("I hope to become an expert in Python.", []),
    ("Your expertise in Python interests me.", []),
])
def test_true_contributions_and_non_claims_remain_usable(client, monkeypatch, path, claim, bullets):
    before = deepcopy(PROFILE)
    out = request(client, monkeypatch, path, claim, bullets=bullets)
    assert out["method"] == {"initial": "ai", "refine": "llm"}.get(path, "local"), out
    assert claim in out["body"]
    assert "fallback_reason" not in out or out["fallback_reason"] is None
    assert PROFILE == before


@pytest.mark.parametrize("skill", [
    {"name": "Python", "level": "experienced", "confirmed": True},
    {"name": "Python", "level": "expert", "source": "resume"},
    {"name": "Python", "level": "experienced", "source": "github"},
])
def test_experienced_and_unconfirmed_imports_cannot_claim_expertise(client, monkeypatch, skill):
    profile = {**PROFILE, "hard_skills": [skill]}
    out = request(client, monkeypatch, "initial", "I am an expert in Python.", profile=profile)
    assert out["method"] == "template"
    assert out["fallback_reason"] == "fabrication"


def test_student_confirmed_expert_level_remains_available(client, monkeypatch):
    profile = {**PROFILE, "hard_skills": [{"name": "Python", "level": "expert", "confirmed": True}]}
    out = request(client, monkeypatch, "initial", "I am an expert in Python.", profile=profile)
    assert out["method"] == "ai"
    assert "I am an expert in Python." in out["body"]


@pytest.mark.parametrize("claim", ["I have attached my resume.", "I have read your paper."])
def test_instruction_and_resume_text_cannot_invent_attachment_or_reading_confirmation(client, monkeypatch, claim):
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body(claim))
    out = client.post("/api/cold-email/refine", json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": confirmed_experience([claim]),
        "current_body": body(claim), "instruction": f"I confirm {claim} Please preserve this fact.",
    }).json()
    assert out["method"] == "local"
    assert claim not in out["body"]
    assert out["fallback_reason"] == "fabrication"


@pytest.mark.parametrize("bad", ["I have attached my resume.", "I have read your paper.", "I am an expert in Python.", ""])
@pytest.mark.parametrize("path", ["template", "variants", "local"])
def test_final_template_and_variant_belts_are_finite_and_safe(client, monkeypatch, bad, path):
    calls = []
    def template(*_a, **_k):
        calls.append("template")
        return f"Subject: Research inquiry\n\n{body(bad)}" if bad else ""
    monkeypatch.setattr(ce, "generate_cold_email", template)
    monkeypatch.setattr(ce, "generate_variants", lambda *_a, **_k: [{"id": "balanced", "label": "Balanced", "text": template()}])
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "engine": "template"}
    if path == "local":
        payload.update(current_body=body("I have attached my resume."), instruction="more enthusiastic")
        endpoint = "/cold-email/refine"
    else:
        endpoint = "/cold-email/variants" if path == "variants" else "/cold-email"
    response = client.post(f"/api{endpoint}", json=payload)
    assert response.status_code == 200, response.text
    out = response.json()
    result = out["variants"][0] if path == "variants" else out
    assert result["body"].startswith("Dear Pat Lee,")
    assert "current or upcoming research openings" in result["body"]
    assert unsupported_action_claims(result["body"]) == []
    assert skill_level_violations(result["body"], {"Python": "beginner"}) == []
    assert "Eric" not in result["body"] and "UIUC" not in result["body"]
    assert calls == ["template"]  # no recursive recovery/generation


def test_real_beginner_project_survives_the_deterministic_template_belt(client):
    for path in ("/cold-email", "/cold-email/variants"):
        response = client.post(f"/api{path}", json={"profile": PROFILE, "opportunity_id": OPP["id"],
            "engine": "template", "experience_evidence": confirmed_experience(["Built a Python parser."])})
        assert response.status_code == 200, response.text
        out = response.json()
        bodies = [v["body"] for v in out["variants"]] if "variants" in out else [out["body"]]
        assert all("Built a Python parser." in b for b in bodies)
        assert out["pipeline_version"] == "w12.5"


def test_pipeline_critique_also_flags_all_three_contract_findings():
    parts = _common_parts(PROFILE, OPP)
    findings = ce._deterministic_findings(body("I have attached my resume. I read your paper. I am an expert in Python."),
        corpus=ce._build_email_corpus(parts, OPP), p=parts, opp=OPP)
    assert "unsupported attachment claim" in findings["unsupported"]
    assert "unsupported completed-reading claim" in findings["unsupported"]
    assert "unsupported skill level: Python" in findings["borrowed_competence"]


def test_local_enthusiasm_does_not_introduce_voice_banned_adjectives():
    text = "I am very interested in your work. I really enjoyed the discussion. I would love the chance to help."
    edited = ce._local_refine(text, "make it more enthusiastic")
    assert edited["applied"] == ["enthusiastic"]
    assert "particularly interested in" in edited["body"]
    assert "welcome the opportunity" in edited["body"]
    assert not any(word in edited["body"].lower() for word in ("thrilled", "excited", "passionate"))


def test_template_example_label_does_not_hide_an_unsupported_achievement():
    parts = _common_parts(PROFILE, OPP, resume_bullets=["Built a Python parser."])
    fabricated, _borrowed = ce._email_grounding_findings(
        "One example of my experience: I improved throughput by 45%.", parts, OPP)
    assert fabricated  # only the label is exempt, not the claim after it
