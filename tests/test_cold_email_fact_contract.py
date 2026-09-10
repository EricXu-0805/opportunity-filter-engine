"""The same student facts must constrain initial emails and later edits."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.lib.grounding import numeric_achievement_violations
from backend.routes import cold_email as ce
from src.recommender.cold_email import generate_variants

PROFILE = {
    "name": "Eric", "school": "UIUC", "year": "sophomore",
    "major": "Computer Science", "coursework": ["CS 225"],
    "hard_skills": [{"name": "Python", "level": "experienced", "confirmed": True}],
    "research_interests_text": "hypersonics, machine learning",
}
OPP = {
    "id": "email-facts", "source_type": "campus_program",
    "opportunity_type": "research", "title": "Research Program",
    "pi_name": "Pat Lee", "organization": "Test University",
    "department": "Engineering", "keywords": ["hypersonics", "PyTorch"],
    "description_raw": "Hypersonics research with PyTorch. Our team improved throughput by 45%.",
    "eligibility": {"skills_required": ["Python", "PyTorch"]},
    "application": {}, "metadata": {"is_active": True},
}


@pytest.fixture
def email_client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: OPP})
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    return TestClient(app)


def draft(claim):
    return f"Dear Pat Lee,\n\n{claim}\n\nWould you have 15 minutes for a conversation?\n\nBest regards,\nEric"


def request_email(client, monkeypatch, endpoint, claim, bullets=(), current=None):
    body = draft(claim)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k: f"Subject: Research inquiry\n\n{body}")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body)
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "resume_bullets": list(bullets)}
    if endpoint == "/cold-email":
        payload["engine"] = "ai"
    else:
        payload.update(current_body=current or draft("I am interested in hypersonics."), instruction="make it warmer")
    response = client.post(f"/api{endpoint}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
@pytest.mark.parametrize("claim", [
    "I have experience with hypersonics.",
    "I have experience with machine learning.",
    "I have hands-on experience with hypersonics.",
    "I am an expert in hypersonics.",
    "My expertise is in hypersonics.",
    "I’ve worked on hypersonics.",
    "I have experience with PyTorch.",
    "I improved throughput by 45%.",
    "I improved throughput by 45x.",
    "I improved throughput by 4.5x.",
    "My model achieved 98% accuracy.",
    "I analyzed 10,000 samples.",
    # Competence phrasing the first regex could not see at all.
    "I have three years of experience with Kubernetes.",
    "I am quite experienced with Kubernetes.",
    "I am comfortable with Rust.",
])
def test_interest_target_and_unsupported_numbers_are_not_student_facts(email_client, monkeypatch, endpoint, claim):
    out = request_email(email_client, monkeypatch, endpoint, claim, current=draft(claim))
    assert out["method"] in ("local", "template")
    assert out["fallback_reason"] == "fabrication"
    assert claim not in out["body"]


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
@pytest.mark.parametrize(("claim", "bullets"), [
    ("I have experience with hypersonics.", ["Built hypersonics experiments using Python."]),
    ("I have hands-on experience with hypersonics.", ["Built hypersonics experiments using Python."]),
    ("I have experience with machine learning.", ["Built machine learning models using Python."]),
    ("I improved throughput by 45%.", ["Improved throughput by 45% using Python."]),
    ("I improved throughput by 45x.", ["Improved throughput by 45x using Python."]),
    ("I improved throughput by 4.5x.", ["Improved throughput by 4.5 times using Python."]),
    ("I analyzed 10,000 samples.", ["Analyzed 10000 samples using Python."]),
    ("I completed CS 225 in 2025.", []),
    ("I have experience with Python and I am interested in machine learning.", []),
    ("I built a Python parser and would appreciate a 15-minute conversation.", ["Built a Python parser."]),
    ("I have no experience with hypersonics yet, and I am interested in learning.", []),
    # The claim's own verb is not a fabrication ("proficient", "worked", "includes").
    ("I am proficient in Python.", []),
    ("I’ve worked on hypersonics.", ["Built hypersonics experiments using Python."]),
    ("My coursework includes CS 225.", []),
    # A GPA is a decimal over a decimal, not a course number or a date.
    ("I have a 3.8 GPA.", ["GPA 3.8/4.0."]),
    # The aspiration after "that I" is an interest, exactly like after "and I".
    ("I have experience with Python that I hope to apply to machine learning.", []),
    # Same fact, written two ways on the two sides.
    ("I have 3 years of robotics experience.", ["Three years of competitive robotics experience."]),
    ("I cut inference latency from 200 ms to 50 ms.", ["Cut inference latency from 200ms to 50ms."]),
    # A meeting ask that shares a clause with the word "experience".
    ("Could I have 15 minutes to discuss how my experience might fit your lab?", []),
])
def test_real_evidence_interests_and_benign_numbers_stay_usable(email_client, monkeypatch, endpoint, claim, bullets):
    out = request_email(email_client, monkeypatch, endpoint, claim, bullets)
    assert out["method"] == ("ai" if endpoint == "/cold-email" else "llm"), out
    assert claim in out["body"]
    assert "15 minutes" in out["body"]


@pytest.mark.parametrize(("claim", "evidence"), [
    ("I improved throughput by 45%.", "Improved throughput by 4.5%."),
    ("I improved throughput by 45%.", "Analyzed 45 samples."),
    ("I improved throughput by 45x.", "Improved throughput by 4.5x."),
    ("I improved throughput by 4.5x.", "Improved throughput by 45x."),
    ("I have 3 years of experience.", "Studied CS 3 in 2025."),
])
def test_quantities_do_not_borrow_decimal_digits_units_or_course_numbers(claim, evidence):
    assert numeric_achievement_violations(claim, evidence)


@pytest.mark.parametrize("claim", [
    "Would you have 15 minutes for a conversation?",
    "I completed CS 225 in 2025.",
    "I built a Python model for CS 225 in September 2025.",
    "I developed a 3D model for ECE 391.",
    "Your paper from 2025 caught my attention.",
    "I am available on September 15.",
])
def test_numeric_achievement_gate_does_not_become_a_global_date_or_course_filter(claim):
    assert numeric_achievement_violations(claim, "") == []


def test_refine_receives_both_evidence_briefs_and_can_add_a_real_omitted_fact(email_client, monkeypatch):
    captured = []
    claim = "I improved throughput by 45%."

    def provider(messages, **_kwargs):
        captured.extend(messages)
        return draft(claim)

    monkeypatch.setattr(ce, "chat_completion", provider)
    response = email_client.post("/api/cold-email/refine", json={
        "profile": PROFILE, "opportunity_id": OPP["id"],
        "resume_bullets": ["Improved throughput by 45% using Python."],
        "current_body": draft("I am interested in hypersonics."),
        "instruction": "Emphasize the achievement in my resume",
    })
    assert response.status_code == 200
    assert response.json()["method"] == "llm"
    assert claim in response.json()["body"]
    assert "Improved throughput by 45% using Python." in captured[1]["content"]
    assert "Hypersonics research with PyTorch" in captured[1]["content"]
    assert "NOT new factual evidence" in captured[0]["content"]


@pytest.mark.parametrize("provider_available", [False, True])
@pytest.mark.parametrize("claim,safe", [
    ("I have experience with Python.", True),
    ("I have experience with machine learning.", False),
    ("I improved throughput by 45%.", False),
])
def test_local_fallback_preserves_factual_body_but_not_pasted_inventions(
    email_client, monkeypatch, provider_available, claim, safe,
):
    monkeypatch.setattr(ce, "is_configured", lambda: provider_available)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: None)
    response = email_client.post("/api/cold-email/refine", json={
        "profile": PROFILE, "opportunity_id": OPP["id"],
        "current_body": draft(claim), "instruction": "make it warmer",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["method"] == "local"
    if safe:
        assert claim in result["body"]
        assert "fallback_reason" not in result
    else:
        assert claim not in result["body"]
        assert result["fallback_reason"] == "fabrication"


def test_mixed_level_templates_do_not_upgrade_an_unconfirmed_import():
    profile = {**PROFILE, "hard_skills": [
        {"name": "Python", "level": "experienced", "confirmed": True},
        {"name": "PyTorch", "level": "experienced", "source": "resume"},
    ]}
    for variant in generate_variants(profile, OPP):
        sentences = variant["text"].split(".")
        claims = [s for s in sentences if any(v in s for v in ("experience with", "proficiency in", "background in"))]
        assert any("Python" in s for s in claims), variant
        assert all("PyTorch" not in s for s in claims), variant
        if variant["id"] in ("balanced", "concise"):
            assert "foundational exposure to PyTorch" in variant["text"]
