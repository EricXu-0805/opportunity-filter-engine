"""Checklist M13 regressions through the real consumers.

A planned or unmarked course is never written as completed, and an interest is
never written as experience: by the email template, the AI email gate on
generation and refinement, Tailor and Renovate, and the ranker. A request that
carries only the legacy ``coursework`` list reads every course as unmarked.
"""
from __future__ import annotations

import re
from copy import deepcopy

import pytest

from backend.routes import cold_email as ce
from backend.routes import matches
from backend.routes import opportunities as chat
from src.matcher.ranker import _coursework_focus_bonus, score_readiness, score_upside
from src.recommender.cold_email import generate_cold_email, generate_variants
from tests import test_resume_writing_quality as wq
from tests.test_cold_email_fact_contract import OPP, draft, email_client  # noqa: F401
from tests.test_profile_prompt_consumers import OPP as CHAT_OPP
from tests.test_profile_prompt_consumers import client  # noqa: F401
from tests.test_resume_writing_quality import endpoint  # noqa: F401

BASE = {
    "name": "Eric", "school": "UIUC", "year": "sophomore", "major": "Computer Science",
    "hard_skills": [{"name": "Python", "level": "experienced", "confirmed": True}],
    "research_interests_text": "brain-computer interfaces, hypersonics",
}
BCI = "BIOE 498 Brain-Computer Interfaces"
# What a status-aware client sends: each course's status, and the names for an
# older server.
PROFILE = {**BASE,
           "courses": [{"name": "CS 225", "status": "completed", "source": "manual"},
                       {"name": "CS 446", "status": "planned", "source": "resume"},
                       {"name": BCI, "status": "planned", "source": "resume"}],
           "coursework": ["CS 225", "CS 446", BCI]}
# What every profile stored before statuses existed sends.
LEGACY = {**BASE, "coursework": ["CS 225", BCI]}
DONE = re.compile(r"\b(?:completed|finished|took|taken|passed|includes?)\b[^.]*\b(?:CS 446|BIOE 498)", re.I)


def test_template_states_a_planned_course_as_a_plan_in_every_variant():
    emails = [generate_cold_email(PROFILE, OPP), *(v["text"] for v in generate_variants(PROFILE, OPP))]
    stated = [email for email in emails if "CS 446" in email]
    assert stated, "the coursework sentence renders in the balanced and skills-focus variants"
    for email in stated:
        assert "Relevant coursework" not in email
        assert DONE.search(email) is None, email
        assert "I have completed CS 225. I plan to take CS 446 and BIOE 498 Brain-Computer Interfaces." in email


def test_template_mentions_legacy_coursework_only_neutrally():
    emails = [generate_cold_email(LEGACY, OPP), *(v["text"] for v in generate_variants(LEGACY, OPP))]
    stated = [email for email in emails if "CS 225" in email]
    assert stated
    for email in stated:
        assert "Relevant coursework" not in email and "completed" not in email
        assert "My coursework includes CS 225 and BIOE 498 Brain-Computer Interfaces." in email


@pytest.mark.parametrize("profile", [PROFILE, LEGACY], ids=["statuses", "legacy"])
def test_template_route_serves_the_status_sentences_through_its_own_gate(email_client, profile):  # noqa: F811
    response = email_client.post("/api/cold-email", json={"profile": profile, "opportunity_id": OPP["id"],
                                                           "engine": "template"})
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    expected = ("I plan to take CS 446" if profile is PROFILE
                else "My coursework includes CS 225 and BIOE 498 Brain-Computer Interfaces.")
    assert expected in body and "Relevant coursework" not in body


def request(http, monkeypatch, route, claim, profile):
    body = draft(claim)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k: f"Subject: Research inquiry\n\n{body}")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body)
    payload = {"profile": profile, "opportunity_id": OPP["id"]}
    if route == "/cold-email":
        payload["engine"] = "ai"
    else:
        payload.update(current_body=draft("I am interested in hypersonics."), instruction="make it warmer")
    response = http.post(f"/api{route}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("route", ["/cold-email", "/cold-email/refine"])
@pytest.mark.parametrize(("profile", "claim"), [
    (PROFILE, "I have completed CS 446."),
    (PROFILE, "I took CS 446 last year."),
    (PROFILE, "I am currently taking CS 446."),
    (PROFILE, "I have completed BIOE 498 Brain-Computer Interfaces."),
    # A planned course's title is not the student's knowledge of its topic.
    (PROFILE, "I have experience with brain-computer interfaces."),
    (PROFILE, "I have experience with brain-computer interfaces from BIOE 498."),
    (LEGACY, "I completed CS 225 in 2025."),
    (LEGACY, "I have taken CS 225."),
    (LEGACY, "I have experience with brain-computer interfaces."),
], ids=lambda value: value if isinstance(value, str) else ("statuses" if value is PROFILE else "legacy"))
def test_ai_gate_refuses_a_course_claimed_beyond_its_status_or_an_interest_as_experience(
        email_client, monkeypatch, route, profile, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, profile)
    assert out["method"] in ("local", "template")
    assert out["fallback_reason"] == "fabrication"
    assert claim not in out["body"]


@pytest.mark.parametrize("route", ["/cold-email", "/cold-email/refine"])
@pytest.mark.parametrize(("profile", "claim"), [
    (PROFILE, "I completed CS 225 in 2025."),
    (PROFILE, "I plan to take CS 446 next spring."),
    (PROFILE, "I am interested in brain-computer interfaces."),
    (LEGACY, "My coursework includes CS 225."),
    (LEGACY, "My coursework includes BIOE 498 Brain-Computer Interfaces."),
], ids=lambda value: value if isinstance(value, str) else ("statuses" if value is PROFILE else "legacy"))
def test_ai_gate_serves_each_course_as_its_status_allows(email_client, monkeypatch, route, profile, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, profile)
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


def test_ai_brief_labels_each_course_with_its_status(email_client, monkeypatch):  # noqa: F811
    captured = []
    monkeypatch.setattr(ce, "chat_completion", lambda messages, **_k: captured.append(messages) or None)
    email_client.post("/api/cold-email", json={"profile": PROFILE, "opportunity_id": OPP["id"], "engine": "ai"})
    brief = next(m["content"] for messages in captured for m in messages if "STUDENT:" in m["content"])
    assert '"course": "CS 446", "status": "planned' in brief
    assert '"course": "CS 225", "status": "completed' in brief
    system = next(m["content"] for messages in captured for m in messages if m["role"] == "system")
    assert "Only a completed course may be stated as completed or taken" in system


@pytest.mark.parametrize("path", wq.PATHS)
@pytest.mark.parametrize(("profile", "line"), [
    (PROFILE, "CS 225 (completed), CS 446 (planned), BIOE 498 Brain-Computer Interfaces (planned)"),
    (LEGACY, "CS 225 (unknown), BIOE 498 Brain-Computer Interfaces (unknown)"),
], ids=["statuses", "legacy"])
def test_tailor_and_renovate_context_shows_each_course_with_its_status(endpoint, monkeypatch, path, profile, line):  # noqa: F811
    monkeypatch.setattr(wq, "PROFILE", profile)
    original = "Analyzed measurements for a classroom experiment."
    _result, calls = wq.write(endpoint, monkeypatch, path, original, original.replace("Analyzed", "Examined"))
    prompt = "\n".join(m["content"] for messages in calls for m in messages
                       if "STUDENT CONTEXT (direction only" in m["content"])
    assert f"- Coursework: {line}\n" in prompt


@pytest.mark.parametrize("path", wq.PATHS)
@pytest.mark.parametrize(("profile", "original", "proposed"), [
    (PROFILE, "Built an EEG classifier in CS 446.", "Completed CS 446, building an EEG classifier."),
    (PROFILE, "Built an EEG classifier for the CS 446 project.", "Built an EEG classifier after completing CS 446."),
    (LEGACY, "Built a Python parser in CS 225.", "Completed CS 225, building a Python parser."),
    (PROFILE, "Built a Python signal toolkit.", "Built a Python brain-computer interfaces toolkit."),
    (PROFILE, "Analyzed signals in Python.", "Analyzed brain-computer interfaces signals in Python."),
], ids=["planned", "planned-after", "legacy", "interest", "interest-relabel"])
def test_tailor_and_renovate_never_write_a_planned_course_as_completed_or_an_interest_as_experience(
        endpoint, monkeypatch, path, profile, original, proposed):  # noqa: F811
    monkeypatch.setattr(wq, "PROFILE", profile)
    result, _calls = wq.write(endpoint, monkeypatch, path, original, proposed)
    wq.assert_rejected(path, result, original)


@pytest.mark.parametrize("stream", [False, True])
def test_ask_ai_chat_lists_each_course_with_its_status(client, monkeypatch, stream):  # noqa: F811
    calls = []

    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        return iter(["Controlled reply."]) if stream else "Controlled reply."
    monkeypatch.setattr(chat, "chat_completion_stream" if stream else "chat_completion", provider)
    response = client.post(f"/api/opportunities/{CHAT_OPP['id']}/chat?stream={int(stream)}",
                           json={"message": "Am I eligible?", "profile": PROFILE})
    assert response.status_code == 200, response.text
    text = "\n".join(m["content"] for m in calls[0])
    assert "CS 225 (completed), CS 446 (planned)" in text


def _lab(*keywords):
    return {"id": "o1", "title": "Lab", "description": "", "source_type": "faculty_research",
            "keywords": list(keywords), "eligibility": {}, "application": {}}


def test_ranker_does_not_count_a_planned_course_as_taken():
    lab = _lab("machine learning", "computer science")
    planned = {"search_weight": 100, "courses": [{"name": "CS 446 Machine Learning", "status": "planned"}],
               "coursework": ["CS 446 Machine Learning"]}
    blank = {"search_weight": 100, "coursework": []}
    assert score_readiness(planned, lab)[0] == score_readiness(blank, lab)[0]
    assert _coursework_focus_bonus(planned, lab) == 0.0
    for status in ("completed", "in_progress", "unknown"):
        counted = {**planned, "courses": [{"name": "CS 446 Machine Learning", "status": status}]}
        assert score_readiness(counted, lab)[0] > score_readiness(blank, lab)[0], status
        assert _coursework_focus_bonus(counted, lab) > 0.0, status


def test_ranker_counts_legacy_coursework_as_it_did():
    lab = _lab("machine learning", "computer science")
    legacy = {"search_weight": 100, "coursework": ["CS 446 Machine Learning"]}
    unmarked = {"search_weight": 100, "courses": [{"name": "CS 446 Machine Learning", "status": "unknown"}]}
    assert score_readiness(legacy, lab)[0] == score_readiness(unmarked, lab)[0]
    assert _coursework_focus_bonus(legacy, lab) == _coursework_focus_bonus(unmarked, lab) > 0.0


def test_match_snapshot_moves_when_only_a_course_status_changes():
    def key(status):
        profile = {**PROFILE, "courses": [{"name": "CS 446", "status": status}]}
        return matches._snapshot_key(profile, False, "probe")
    assert key("planned") != key("completed")


def test_match_reason_never_calls_the_students_interests_their_background():
    opportunity = {"id": "o2", "title": "Research", "pi_name": "Pat Lee", "source_type": "campus_program",
                   "opportunity_type": "research", "description_raw": "Neural decoding research.",
                   "keywords": [], "eligibility": {}, "application": {}, "metadata": {}}
    _score, fit, _gap = score_upside({"research_interests_text": "neural decoding"}, opportunity,
                                     precomputed_sim=0.6)
    tied = [reason for reason in fit if "Pat Lee" in reason]
    assert tied == ["Your research interests align with Prof. Pat Lee's focus area"]
    assert not any(re.search(r"\b(?:background|experience)\b", reason, re.I) for reason in fit)
