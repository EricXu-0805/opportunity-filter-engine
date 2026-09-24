"""A late relevant experience must reach every email writer without inventing fit."""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from src.recommender.cold_email import _common_parts, _pick_resume_bullet, generate_variants

PROFILE = {
    "name": "Audit Student", "school": "UIUC", "year": "sophomore",
    "major": "Computer Science", "hard_skills": [], "coursework": [],
    "research_interests_text": "robot motion planning",
}
OPP = {
    "id": "resume-selection", "source_type": "campus_program",
    "opportunity_type": "research", "title": "Renaissance Research",
    "pi_name": "Pat Lee", "organization": "Test University",
    "keywords": ["Renaissance", "cultural history"],
    "description_raw": "Research on Renaissance cultural history.",
    "eligibility": {"skills_required": []}, "application": {},
    "metadata": {"is_active": True},
}
RELEVANT = "Analyzed Renaissance cultural history using archival manuscripts."
UNRELATED = "Built robot motion planning algorithms for autonomous navigation."
BULLETS = [f"Organized campus activity number {n}." for n in range(1, 9)] + [RELEVANT]


def test_relevant_ninth_bullet_reaches_brief_before_the_eight_bullet_limit():
    parts = _common_parts(PROFILE, OPP, resume_bullets=BULLETS)
    before = deepcopy(parts)
    brief = ce._render_student_brief(parts)
    assert RELEVANT in brief
    assert brief.index(RELEVANT) < brief.index(BULLETS[0])
    assert BULLETS[7] not in brief  # the input-order tie drops last, not the best match
    assert parts == before  # selection cannot rewrite or delete the evidence corpus
    assert BULLETS[7].lower() in ce._student_email_corpus(parts)


def test_student_interest_does_not_authenticate_template_relevance():
    parts = _common_parts(PROFILE, OPP, resume_bullets=[UNRELATED])
    assert _pick_resume_bullet(parts) == ""
    for variant in generate_variants(PROFILE, OPP, resume_bullets=[UNRELATED]):
        assert UNRELATED not in variant["text"]
    # A real experience remains admissible background, and interests remain
    # aspirations. Neither is erased just because this target is unrelated.
    brief = ce._render_student_brief(parts)
    assert UNRELATED in brief
    assert "Research interests (aspirations, NOT evidence of experience): robot motion planning" in brief


def test_template_quotes_the_selected_source_without_claiming_a_proven_connection():
    for variant in generate_variants(PROFILE, OPP, resume_bullets=BULLETS):
        assert RELEVANT in variant["text"], variant["id"]
        assert "Most relevant to your work" not in variant["text"]
        assert RELEVANT + "." not in variant["text"]


@pytest.fixture
def email_client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: OPP})
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")

    async def anonymous(_authorization):
        return None

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    return TestClient(app)


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
def test_initial_and_refine_provider_receive_the_same_ranked_sources(email_client, monkeypatch, endpoint):
    captured = []
    body = f"Dear Pat Lee,\n\n{RELEVANT}\n\nWould you have time for a conversation?\n\nBest regards,\nAudit Student"

    def provider(messages, **_kwargs):
        captured.extend(messages)
        return body if endpoint.endswith("/refine") else f"Subject: Research inquiry\n\n{body}"

    monkeypatch.setattr(ce, "chat_completion", provider)
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "resume_bullets": BULLETS}
    if endpoint.endswith("/refine"):
        payload.update(current_body="Dear Pat Lee,\n\nThank you for your time.", instruction="Use my relevant experience")
    else:
        payload["engine"] = "ai"
    response = email_client.post(f"/api{endpoint}", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["method"] == ("llm" if endpoint.endswith("/refine") else "ai"), result
    assert RELEVANT in result["body"]
    student_message = next(m["content"] for m in captured if m["role"] == "user" and "STUDENT:" in m["content"])
    student_block = student_message.split("- Real resume experience", 1)[1].split("OPPORTUNITY CONTACT:", 1)[0]
    assert RELEVANT in student_block
    assert student_block.index(RELEVANT) < student_block.index(BULLETS[0])
    assert BULLETS[7] not in student_block


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/variants"])
def test_template_endpoints_use_the_same_selected_source(email_client, monkeypatch, endpoint):
    def unexpected_provider(*_args, **_kwargs):
        pytest.fail("template requests must not call a provider")

    monkeypatch.setattr(ce, "chat_completion", unexpected_provider)
    response = email_client.post(f"/api{endpoint}", json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "resume_bullets": BULLETS,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    bodies = [v["body"] for v in result["variants"]] if "variants" in result else [result["body"]]
    assert bodies
    assert all(RELEVANT in body and "Most relevant to your work" not in body for body in bodies)
    assert result["pipeline_version"] == ce.COLD_EMAIL_PIPELINE_VERSION


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
def test_provider_failure_keeps_the_target_selected_template_example(email_client, monkeypatch, endpoint):
    monkeypatch.setattr(ce, "chat_completion", lambda *_args, **_kwargs: None)
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "resume_bullets": BULLETS}
    if endpoint.endswith("/refine"):
        payload.update(
            current_body="Dear Pat Lee,\n\nI have experience with Kubernetes.",
            instruction="make it warmer",
        )
    else:
        payload["engine"] = "ai"
    response = email_client.post(f"/api{endpoint}", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["method"] in ("local", "template")
    assert RELEVANT in result["body"]
    assert "Kubernetes" not in result["body"]
    assert "Most relevant to your work" not in result["body"]


def test_selection_changes_with_target_evidence_not_student_interest():
    bullets = [UNRELATED, RELEVANT]
    history = _common_parts(PROFILE, OPP, resume_bullets=bullets)
    changed_interest = _common_parts(
        {**PROFILE, "research_interests_text": "robot motion planning, autonomous navigation algorithms"},
        OPP, resume_bullets=bullets,
    )
    assert _pick_resume_bullet(history) == _pick_resume_bullet(changed_interest) == RELEVANT
    robotics = {**OPP, "keywords": ["robot motion planning"], "description_raw": "Robot motion planning algorithms."}
    assert _pick_resume_bullet(_common_parts(PROFILE, robotics, resume_bullets=bullets)) == UNRELATED
    assert bullets == [UNRELATED, RELEVANT]
