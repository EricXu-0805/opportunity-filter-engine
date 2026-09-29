"""Controlled writing examples, not a claim about live model or human quality."""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from tests.experience_fixtures import confirmed_experience

PROFILE = {
    "name": "Audit Student", "school": "UIUC", "year": "sophomore",
    "major": "Computer Science", "hard_skills": [], "coursework": [],
    "research_interests_text": "research tools",
}
OPP = {
    "id": "writing-quality", "source_type": "campus_program", "opportunity_type": "research",
    "title": "Research Tools", "pi_name": "Pat Lee", "organization": "Test University",
    "keywords": ["Python parser tools", "Linux setup"],
    "description_raw": "Research on Python parser tools and Linux setup.",
    "eligibility": {"skills_required": []}, "application": {}, "metadata": {"is_active": True},
}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: OPP})
    monkeypatch.setattr(ce, "corpus_version", lambda: "writing-quality-fixture")
    monkeypatch.setattr(ce, "is_configured", lambda: False)

    async def anonymous(_authorization):
        return None

    def no_provider(*_args, **_kwargs):
        pytest.fail("this controlled template example must not call a provider")

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    monkeypatch.setattr(ce, "chat_completion", no_provider)
    return TestClient(app)


def payload(skill, level="experienced", evidence=()):
    return {
        "profile": {**PROFILE, "hard_skills": [{"name": skill, "level": level, "confirmed": True}]},
        "opportunity_id": OPP["id"], "experience_evidence": confirmed_experience(evidence),
    }


@pytest.mark.parametrize("path", ["/cold-email", "/cold-email/variants"])
@pytest.mark.parametrize("level,allowed", [
    ("beginner", "foundational exposure to PyTorch"),
    ("experienced", "experience with PyTorch"),
])
def test_skill_name_does_not_invent_completed_tool_applications(client, path, level, allowed):
    result = client.post(f"/api{path}", json=payload("PyTorch", level))
    assert result.status_code == 200, result.text
    data = result.json()
    bodies = [v["body"] for v in data["variants"]] if "variants" in data else [data["body"]]
    assert any(allowed in body for body in bodies)
    assert all("building and training deep learning models" not in body for body in bodies)
    assert data.get("fallback_reason") is None
    assert data["experience_usage"]["selected"] == []


@pytest.mark.parametrize("path", ["/cold-email", "/cold-email/variants"])
@pytest.mark.parametrize("skill,evidence,forbidden", [
    ("Python", "Built a Python parser for research tools.", "data processing, analysis, and scripting"),
    ("Linux", "Documented Linux setup for research tools.", "system administration and command-line tooling"),
])
def test_real_work_remains_specific_without_invented_outcomes(client, path, skill, evidence, forbidden):
    request = payload(skill, evidence=[evidence])
    before = deepcopy(request)
    response = client.post(f"/api{path}", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    variants = result.get("variants", [result])
    for variant in variants:
        assert evidence in variant["body"], variant
        assert skill in variant["body"]
        assert forbidden not in variant["body"]
        assert variant.get("fallback_reason") is None
        assert variant["experience_usage"]["selected"][0]["excerpt"] == evidence
    assert request == before


def test_no_experience_still_has_a_clear_request_without_claiming_project_work(client):
    response = client.post("/api/cold-email", json={
        "profile": PROFILE, "opportunity_id": OPP["id"],
        "experience_evidence": confirmed_experience([]),
    })
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    assert "?" in body
    assert "One example of my experience" not in body
    assert "I have experience" not in body
    assert response.json()["experience_usage"]["selected"] == []


def test_every_real_pipeline_call_receives_the_same_connection_boundary(client, monkeypatch):
    # Exercise public initial + refine routes, including actual multi-draft,
    # judge, critique and revise dispatch; only the provider itself is stubbed.
    calls = []
    evidence = "Built a Python parser for research tools."
    body = (
        f"Dear Pat Lee,\n\n{evidence}\n\nWould you have time for a conversation?"
        "\n\nBest regards,\nAudit Student"
    )

    def provider(messages, **_kwargs):
        system = messages[0]["content"]
        if "You are judging candidate" in system:
            stage, output = "judge", '{"winner":1}'
        elif "You are a strict reviewer" in system:
            stage, output = "critique", '{"verdict":"revise","revision_notes":"Keep the stated action and make the request clear."}'
        elif "You are revising" in system:
            stage, output = "revise", f"Subject: Research inquiry\n\n{body}"
        elif "You are an email editor" in system:
            stage, output = "refine", body
        else:
            stage, output = "draft", f"Subject: Research inquiry\n\n{body}"
        calls.append((stage, deepcopy(messages)))
        return output

    monkeypatch.setattr(ce, "chat_completion", provider)
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "2")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "1")
    request = payload("Python", evidence=[evidence])
    initial = client.post("/api/cold-email", json={**request, "engine": "ai"})
    refined = client.post("/api/cold-email/refine", json={
        **request, "current_body": body, "instruction": "Make the request clearer",
    })
    assert initial.status_code == refined.status_code == 200
    assert initial.json()["method"] == "ai", initial.text
    assert refined.json()["method"] == "llm", refined.text
    assert [stage for stage, _ in calls].count("draft") == 2
    assert {stage for stage, _ in calls} == {"draft", "judge", "critique", "revise", "refine"}
    for stage, messages in calls:
        system, user = messages[0]["content"], messages[1]["content"]
        assert "A skill name and self-reported level do not establish" in system, stage
        assert "Shared keywords alone do not prove research fit" in system, stage
        assert "a specific learning interest" in system, stage
        assert "without a measured outcome" in system, stage
        assert evidence in user, stage
        assert "Research Tools" in user, stage
    for response in (initial, refined):
        assert evidence in response.json()["body"]
        assert response.json()["experience_usage"]["selected"][0]["excerpt"] == evidence
        assert response.json()["pipeline_version"] == "w12.17"
