"""The same student facts must constrain initial emails and later edits."""

import re
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.lib.email_contact_context import contact_claim_violations, contact_context_parts
from backend.lib.grounding import numeric_achievement_violations
from backend.routes import cold_email as ce
from src.recommender.cold_email import generate_variants
from tests.experience_fixtures import confirmed_experience

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


def request_email(client, monkeypatch, endpoint, claim, bullets=(), current=None, context=None):
    body = draft(claim)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k: f"Subject: Research inquiry\n\n{body}")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body)
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": confirmed_experience(list(bullets))}
    if context is not None:
        payload["contact_context"] = context
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
    # A coordinated list is one claim. The first splitter cut this at "and",
    # so the interest rode into the draft on the back of a real skill.
    "I have experience with Python and machine learning.",
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
        "experience_evidence": confirmed_experience(["Improved throughput by 45% using Python."]),
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


# D31: the wet-lab prompt asked for "10-15+ hours per week" and every gate let
# the model's offer through, so a student who never stated availability was
# committed to it in their own voice.
COMMITMENT = "I can commit 10-15 hours per week to the lab."


def availability(text):
    return {"version": 1, "purpose": "first_contact", "availability": {"text": text, "confirmed": True}}


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
def test_an_unstated_time_commitment_is_not_a_student_fact(email_client, monkeypatch, endpoint):
    out = request_email(email_client, monkeypatch, endpoint, COMMITMENT, current=draft(COMMITMENT))
    assert out["fallback_reason"] == "fabrication"
    assert "hours per week" not in out["body"]


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
def test_a_time_commitment_beyond_the_stated_availability_is_rejected(email_client, monkeypatch, endpoint):
    stated = "I can contribute 6 hours per week during the semester."
    claim = f"{stated} {COMMITMENT}"
    out = request_email(email_client, monkeypatch, endpoint, claim, current=draft(claim), context=availability(stated))
    assert out["fallback_reason"] == "fabrication"
    assert "10-15 hours" not in out["body"]


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
@pytest.mark.parametrize(("stated", "claim"), [
    (COMMITMENT, COMMITMENT),
    # The confirmed sentence, then the same quantity in other words.
    ("I can contribute 10–15 hrs/week during the semester.",
     "I can contribute 10–15 hrs/week during the semester. I could commit 10-15 hours per week to the lab."),
])
def test_a_time_commitment_matching_the_stated_availability_stays_usable(
    email_client, monkeypatch, endpoint, stated, claim,
):
    out = request_email(email_client, monkeypatch, endpoint, claim, context=availability(stated))
    assert out["method"] == ("ai" if endpoint == "/cold-email" else "llm"), out
    assert claim in out["body"]


@pytest.mark.parametrize("sentence", [
    COMMITMENT,
    "I could dedicate around 10 hours a week.",
    "I would be able to contribute 8–10 hrs/week this semester.",
    "I am available 12 hours each week.",
    "I'd be glad to put in two afternoons a week.",
    "I can work 4 hours a day during the summer.",
    "I can commit to at least two semesters.",
    "I can start in January and stay for two semesters.",
    "I am available for the full 10 weeks of the program.",
    "I have about 10 hours per week available.",
    "My availability is 2.5 hours per day.",
    "My schedule this semester allows for 10-15 hours per week in the lab.",
    "I really can commit 10 hours a week.",
    "Our club meets on Fridays, so I could work up to 12 hours a week in a lab.",
])
def test_an_offered_time_commitment_needs_the_stated_availability(sentence):
    assert contact_claim_violations(sentence, contact_context_parts(None)) == ["unsupported time commitment"]


@pytest.mark.parametrize("sentence", [
    "Would you have 15 minutes for a conversation?",
    "I am available on September 15.",
    "I am available for a 30-minute call next week.",
    "I can start in two weeks.",
    "I will graduate in two semesters.",
    "If I do not hear back, I will follow up by email in two weeks.",
    "The program runs for 10 weeks, and I would love to participate.",
    "I would love to join your 10-week summer program.",
    "I have worked in a yeast lab since January 2026 (10 hours/week).",
    "I have worked 10 hours per week in a yeast genetics lab since January 2026.",
    "I currently work 10 hours a week as a teaching assistant.",
    "I have 3 years of experience with Python.",
    "I will have completed four semesters of chemistry by May.",
    "I took CS 225 two semesters ago.",
    "I am available to start in two weeks.",
    "I will be available two weeks from now.",
    "I would love to join your program, which runs for 10 weeks.",
    "I would like to help with any project the lab has planned for the next two semesters.",
])
def test_time_words_that_offer_no_commitment_pass(sentence):
    assert contact_claim_violations(sentence, contact_context_parts(None)) == []


@pytest.mark.parametrize(("stated", "claim", "accepted"), [
    ("I can contribute 10-15 hours per week.", "I can commit 10–15 hrs/week to the lab.", True),
    ("Ten to fifteen hours per week.", COMMITMENT, True),
    ("I am free 10-15 hours per week and can stay for two semesters.", "I can also stay for two semesters.", True),
    ("I can contribute 6 hours per week.", COMMITMENT, False),
    ("I can contribute 10-15 hours per week.", "I could dedicate 10-15 hours a week to the lab.", True),
    ("I can contribute 15 hours per week.", "I can commit 15+ hours per week to the lab.", False),
    ("I can stay for two semesters.", "I can commit to at least two semesters.", False),
    ("I can contribute 10-15 hours per week.", "I can also stay for two semesters.", False),
    ("I am free Tuesday and Thursday afternoons.", "I can work two afternoons a week.", False),
    ("I can start in two weeks.", "I can commit for two weeks.", False),
])
def test_another_time_commitment_must_repeat_the_stated_quantities(stated, claim, accepted):
    parts = contact_context_parts(availability(stated))
    findings = contact_claim_violations(f"{stated} {claim}", parts)
    assert findings == ([] if accepted else ["unsupported time commitment"])


_HOUR_FIGURE = re.compile(r"\d+\s*(?:[-–]\s*\d+\s*)?\+?\s*(?:hours?|hrs?)\b", re.I)


def test_the_wet_lab_prompt_names_no_hour_figure(email_client, monkeypatch):
    wet = {**OPP, "id": "wet-facts", "department": "Biology", "keywords": ["PCR", "cell culture", "microscopy"],
           "description_raw": "Cell culture and microscopy research with PCR."}
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {wet["id"]: wet})
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    systems = []

    def provider(messages, **_kwargs):
        systems.append(messages[0]["content"])
        return f"Subject: Research inquiry\n\n{draft('I am interested in cell culture.')}"

    monkeypatch.setattr(ce, "chat_completion", provider)
    response = email_client.post("/api/cold-email", json={
        "profile": PROFILE, "opportunity_id": wet["id"], "engine": "ai",
        "experience_evidence": confirmed_experience([]),
    })
    assert response.status_code == 200, response.text
    wet_prompts = [system for system in systems if "Wet-lab tone" in system]
    assert wet_prompts
    assert not any(_HOUR_FIGURE.search(system) for system in wet_prompts)
    for is_faculty in (False, True):
        assert not _HOUR_FIGURE.search(ce._lab_type_tone("wet", is_faculty=is_faculty))


def test_the_reviser_is_told_to_drop_an_unstated_time_commitment(email_client, monkeypatch):
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    revise_requests = []

    def provider(messages, **_kwargs):
        if "revising a student's cold email" in messages[0]["content"]:
            revise_requests.append(messages[1]["content"])
            return f"Subject: Research inquiry\n\n{draft('I am interested in hypersonics.')}"
        return f"Subject: Research inquiry\n\n{draft(COMMITMENT)}"

    monkeypatch.setattr(ce, "chat_completion", provider)
    response = email_client.post("/api/cold-email", json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "engine": "ai",
        "experience_evidence": confirmed_experience([]),
    })
    assert response.status_code == 200, response.text
    assert response.json()["method"] == "ai"
    assert "hours per week" not in response.json()["body"]
    assert any("unsupported time commitment" in request for request in revise_requests)


# D31, the rest: the wet-lab prompt invited an undergraduate's "willingness to
# volunteer initially" and the dry-lab prompt "to complete a technical
# assessment or coding challenge", and no gate read either offer, so a student
# who never offered unpaid work or a test was committed to one in their voice.
VOLUNTEER = "I would be happy to volunteer in the lab initially."
CHALLENGE = "I would be glad to complete a coding challenge."


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
@pytest.mark.parametrize("claim", [VOLUNTEER, CHALLENGE, "I am willing to work for course credit."])
def test_an_unstated_commitment_is_not_a_student_fact(email_client, monkeypatch, endpoint, claim):
    out = request_email(email_client, monkeypatch, endpoint, claim, current=draft(claim))
    assert out["fallback_reason"] == "fabrication"
    assert claim not in out["body"]


@pytest.mark.parametrize("endpoint", ["/cold-email", "/cold-email/refine"])
def test_a_commitment_the_stated_availability_names_stays_usable(email_client, monkeypatch, endpoint):
    stated = "I am open to volunteering in the lab during the semester."
    claim = f"{stated} {VOLUNTEER}"
    out = request_email(email_client, monkeypatch, endpoint, claim, context=availability(stated))
    assert out["method"] == ("ai" if endpoint == "/cold-email" else "llm"), out
    assert claim in out["body"]


@pytest.mark.parametrize("sentence", [
    VOLUNTEER,
    CHALLENGE,
    "I can volunteer.",
    "I'd also gladly volunteer in the lab.",
    "I'm happy to start as a volunteer.",
    "I am available to volunteer on weekends.",
    "I would be open to an unpaid position.",
    "I can work without pay this summer.",
    "I am glad to help for free.",
    "I am willing to work for course credit.",
    "I could earn course credit through CHEM 499.",
    "I am happy to complete a technical assessment.",
    "If helpful, I can complete a short coding exercise.",
    "I could take a short test on lab safety.",
    "I am happy to do a take-home assignment.",
    "I would be open to starting on a trial basis.",
])
def test_an_offered_commitment_needs_the_stated_availability(sentence):
    assert contact_claim_violations(sentence, contact_context_parts(None)) == ["unsupported commitment"]


@pytest.mark.parametrize("sentence", [
    "I have volunteered at a free clinic since 2024.",
    "I volunteered as a tutor last year.",
    "I would like to continue my volunteer work at the hospital.",
    "I would love to join your summer volunteer program.",
    "I would like to be considered for the unpaid position.",
    "I understand the position is unpaid.",
    "The program offers course credit, and I would love to participate.",
    "I would be glad to complete the coding challenge in the posting.",
    "I would love to learn about your research on volunteer computing.",
    "I would like to study volunteer motivation in nonprofits.",
    "I would like to learn how your lab tests catalysts.",
    "I can help design a test suite for the simulator.",
    "I will take a test-driven approach.",
    "I would like to help run clinical trials.",
    "I would like to learn more about your trial design.",
    "I would be glad to share my coding project.",
    "I took a technical writing course.",
])
def test_words_that_offer_no_commitment_pass(sentence):
    assert contact_claim_violations(sentence, contact_context_parts(None)) == []


@pytest.mark.parametrize(("stated", "claim", "accepted"), [
    ("I am open to volunteering.", "I can volunteer on Fridays.", True),
    ("I can work for course credit.", "I would be open to an unpaid position.", True),
    ("I am happy to complete a coding challenge.", "I could take a short test first.", True),
    ("I am open to volunteering.", CHALLENGE, False),
    ("I am happy to complete a coding challenge.", VOLUNTEER, False),
    ("I can contribute 6 hours per week.", VOLUNTEER, False),
])
def test_another_commitment_must_be_of_a_kind_the_availability_names(stated, claim, accepted):
    parts = contact_context_parts(availability(stated))
    findings = contact_claim_violations(f"{stated} {claim}", parts)
    assert findings == ([] if accepted else ["unsupported commitment"])


@pytest.mark.parametrize("lab_type", ["wet", "dry", "humanities", None])
@pytest.mark.parametrize("is_faculty", [False, True])
def test_no_lab_tone_invites_unpaid_work_or_a_test(lab_type, is_faculty):
    tone = ce._lab_type_tone(lab_type, is_faculty=is_faculty)
    assert "volunteer initially" not in tone
    assert "technical assessment or coding challenge" not in tone
    assert "acceptable to offer" not in tone


def test_the_reviser_is_told_to_drop_an_unstated_commitment(email_client, monkeypatch):
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")
    revise_requests = []

    def provider(messages, **_kwargs):
        if "revising a student's cold email" in messages[0]["content"]:
            revise_requests.append(messages[1]["content"])
            return f"Subject: Research inquiry\n\n{draft('I am interested in hypersonics.')}"
        return f"Subject: Research inquiry\n\n{draft(VOLUNTEER)}"

    monkeypatch.setattr(ce, "chat_completion", provider)
    response = email_client.post("/api/cold-email", json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "engine": "ai",
        "experience_evidence": confirmed_experience([]),
    })
    assert response.status_code == 200, response.text
    assert response.json()["method"] == "ai"
    assert "volunteer" not in response.json()["body"]
    assert any("unsupported commitment" in request for request in revise_requests)


@pytest.mark.parametrize("unit", [
    "I can volunteer ", "I would be happy to take a ", "I can I would we could I'd ",
    "I can complete a a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a ", "I can volunteer 10 hours a week for credit, ",
])
def test_the_commitment_checks_stay_bounded_at_the_edit_limit(unit):
    # The local refine path runs these on the event loop for a 5000-character body.
    text = (unit * (5000 // len(unit) + 1))[:5000]
    began = time.perf_counter()
    contact_claim_violations(text, contact_context_parts(None))
    assert time.perf_counter() - began < 1.0


def test_the_formal_quick_edit_never_swaps_in_a_commitment(email_client, monkeypatch):
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    current = draft("I am interested in hypersonics. I am a fast learner.")
    response = email_client.post("/api/cold-email/refine", json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": confirmed_experience([]),
        "current_body": current, "instruction": "make it more formal",
    })
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["method"] == "local" and "formal" in out["applied"], out
    assert "committed" not in out["body"]
    assert "I learn new material quickly." in out["body"]
