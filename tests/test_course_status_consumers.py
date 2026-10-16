"""Checklist M13 regressions through the real consumers.

A planned or unmarked course is never written as completed, and an interest is
never written as experience: by the email template, the AI email gate on
generation and refinement, Tailor and Renovate, and the ranker. A request that
carries only the legacy ``coursework`` list reads every course as unmarked.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy

import pytest

from backend.routes import cold_email as ce
from backend.routes import matches
from backend.routes import opportunities as chat
from src.matcher.ranker import _coursework_focus_bonus, score_readiness, score_upside
from src.recommender.cold_email import generate_cold_email, generate_variants
from src.student_evidence import COURSE_STATUS_LABELS
from tests import test_resume_writing_quality as wq
from tests.experience_fixtures import confirmed_experience
from tests.test_cold_email_fact_contract import OPP, draft, email_client  # noqa: F401
from tests.test_cold_email_fact_contract import request_email as fact_request
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
    # Fix round 1: a future phrase elsewhere in the sentence, or a title before
    # the code, no longer lets the claim through.
    (PROFILE, "I have completed CS 446 and am available to start next semester."),
    (PROFILE, "I have completed Machine Learning (CS 446)."),
    # Fix round 3: "yet" as a conjunction negates nothing.
    (PROFILE, "I am only a sophomore, yet I have already completed CS 446."),
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
    # Fix round 3: a time phrase after the course, and "I'll have", are future.
    (PROFILE, "I am taking CS 446 in the fall."),
    (PROFILE, "I'll have completed CS 446 by May."),
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
    # Grouped by status, each status's rule said once.
    assert f'"{COURSE_STATUS_LABELS["planned"]}": ["CS 446", "{BCI}"]' in brief
    assert f'"{COURSE_STATUS_LABELS["completed"]}": ["CS 225"]' in brief
    assert brief.count(COURSE_STATUS_LABELS["planned"]) == 1
    system = next(m["content"] for messages in captured for m in messages if m["role"] == "system")
    assert "Only a completed course may be stated as completed or taken" in system
    # A posting's prerequisite may still be restated as the posting's.
    assert "Never name a course the student did not list" not in system


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
    # Unknown is "the student has not said", never "not taken" (fix round 1).
    system = "\n".join(m["content"] for messages in calls for m in messages if m["role"] == "system")
    assert "unknown means the student has not said" in system or "未标注表示学生没有说明" in system
    assert "Only a completed course was taken" not in system


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


def test_ask_ai_chat_says_an_unmarked_course_is_neither_taken_nor_not_taken(client, monkeypatch):  # noqa: F811
    """Every course stored before statuses existed is unknown: the student has not said either way."""
    calls = []
    monkeypatch.setattr(chat, "chat_completion", lambda messages, **_k: calls.append(deepcopy(messages)) or "Reply.")
    response = client.post(f"/api/opportunities/{CHAT_OPP['id']}/chat?stream=0",
                           json={"message": "Am I eligible?", "profile": LEGACY})
    assert response.status_code == 200, response.text
    line = next(row for m in calls[0] for row in m["content"].splitlines() if row.startswith("- Coursework"))
    assert "unknown means the student has not said" in line and "CS 225 (unknown)" in line
    assert "only completed courses were taken" not in line


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


def test_rank_all_reads_the_counted_courses_once_per_profile(monkeypatch):
    """Not once per opportunity: 512 courses made a 24k-record ranking 7x slower (fix round 1)."""
    from src.matcher import ranker
    calls = []
    real = ranker.courses_counted_as_taken
    monkeypatch.setattr(ranker, "courses_counted_as_taken", lambda profile: calls.append(1) or real(profile))
    records = [{**_lab("machine learning"), "id": f"o{i}"} for i in range(5)]
    planned = {"search_weight": 100, "courses": [{"name": "CS 446 Machine Learning", "status": "planned"}]}
    assert len(ranker.rank_all(planned, records)) == 5
    assert len(calls) == 1


def test_match_snapshot_ignores_a_courses_source_and_evidence_line():
    def key(**course):
        return matches._snapshot_key({**PROFILE, "courses": [{"name": "CS 446", "status": "planned", **course}]},
                                     False, "probe")
    assert key(source="resume", evidence="Planned: CS 446") == key(source="manual") == key()


# Fix round 1: a course's title stands for its topic only once the course is
# completed or in progress; a coursework listing may name any listed course.
ML = {**BASE, "research_interests_text": "machine learning, robotics"}
ROUTES = ["/cold-email", "/cold-email/refine"]
# An interest named like the course, and a title of uncommon words.
TITLES = [("Machine Learning", "I have experience with machine learning."),
          ("Computational Neuroscience", "I have extensive experience in computational neuroscience.")]


def titled(status, name="Machine Learning"):
    return {**ML, "courses": [{"name": name, "status": status}], "coursework": [name]}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("status", ["planned", "unknown", "legacy"])
@pytest.mark.parametrize(("name", "claim"), [
    *TITLES,
    ("Machine Learning", "My coursework includes Machine Learning, so I have experience with machine learning."),
])
def test_a_planned_or_unmarked_course_title_never_grounds_a_competence_claim(
        email_client, monkeypatch, route, status, name, claim):  # noqa: F811
    profile = {**ML, "coursework": [name]} if status == "legacy" else titled(status, name)
    out = request(email_client, monkeypatch, route, claim, profile)
    assert out["fallback_reason"] == "fabrication" and claim not in out["body"]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("status", ["completed", "in_progress"])
@pytest.mark.parametrize(("name", "claim"), TITLES)
def test_a_completed_or_current_course_title_grounds_its_topic_as_before(
        email_client, monkeypatch, route, status, name, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, titled(status, name))
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("status", ["completed", "in_progress", "planned", "unknown"])
def test_a_coursework_listing_names_a_course_of_any_status(email_client, monkeypatch, route, status):  # noqa: F811
    claim = "My coursework includes Machine Learning and Computational Neuroscience."
    profile = {**ML, "courses": [{"name": "Machine Learning", "status": status},
                                 {"name": "Computational Neuroscience", "status": status}]}
    out = request(email_client, monkeypatch, route, claim, profile)
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


@pytest.mark.parametrize("route", ROUTES)
def test_a_planned_course_named_like_an_interest_never_grounds_it(email_client, monkeypatch, route):  # noqa: F811
    profile = {**BASE, "courses": [{"name": "Hypersonics", "status": "planned"}]}
    claim = "I have experience with hypersonics."
    out = request(email_client, monkeypatch, route, claim, profile)
    assert out["fallback_reason"] == "fabrication" and claim not in out["body"]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("status", "claim", "bullets"), [
    # A completed course was taken, so "while taking" it is true.
    ("completed", "While taking CS 225, I built a Python parser.", ["Built a Python parser."]),
    # A requirement restated about other students claims nothing for this one.
    ("in_progress", "Your program asks for students who have completed CS 225, which I am currently taking.", []),
    # The student's own confirmed line, quoted verbatim, is theirs.
    ("unknown", "One example of my experience: Completed CS 225 project: built a Python parser.",
     ["Completed CS 225 project: built a Python parser."]),
])
def test_what_the_student_may_say_about_a_course_is_served(
        email_client, monkeypatch, route, status, claim, bullets):  # noqa: F811
    profile = {**BASE, "courses": [{"name": "CS 225", "status": status}]}
    out = fact_request(email_client, monkeypatch, route, claim, bullets=bullets, profile=profile)
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("profile", "claim", "bullets"), [
    # Fix round 3: only courses the student listed are checked, and a listed
    # title is the course only as the list capitalises it.
    (LEGACY, "I have completed OSHA 10 safety training.", ["Completed OSHA 10 safety training."]),
    ({**BASE, "coursework": ["Machine Learning"]}, "I completed a machine learning project in Python.", []),
], ids=["unlisted_code", "lowercase_title"])
def test_text_naming_no_listed_course_is_no_course_claim(
        email_client, monkeypatch, route, profile, claim, bullets):  # noqa: F811
    out = fact_request(email_client, monkeypatch, route, claim, bullets=bullets, profile=profile)
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


# Fix round 4: beside a course noun a listed title is the course in any case;
# right after "a" or "an" it is the course only before a course noun.
LEGACY_TITLES = {**BASE, "coursework": ["CS 225", "Machine Learning", "Data Structures", "Computer Vision"]}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("claim", [
    "I have completed coursework in machine learning and data structures.",
    "I've taken courses in machine learning and data structures.",
    "I have taken machine learning courses.",
    "I am currently taking a computer vision course.",
    "I have completed a machine learning course.",
    "I have completed a Machine Learning course.",
])
def test_a_title_beside_a_course_noun_is_the_course_in_any_case(email_client, monkeypatch, route, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, LEGACY_TITLES)
    assert out["fallback_reason"] == "fabrication" and claim not in out["body"], out


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("claim", [
    "I completed a Machine Learning project in Python.",
    "I took a Machine Learning approach to the problem.",
    "I completed a Machine Learning internship.",
    "I completed a machine learning project in Python.",
])
def test_after_a_or_an_a_title_is_the_course_only_before_a_course_noun(
        email_client, monkeypatch, route, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, LEGACY_TITLES)
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


# Fix round 5: a course noun at the end of a list of listed titles names every
# title in it; after a course noun, ", and" starts a new clause.
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("claim", [
    "I have taken both a Machine Learning and a Computer Vision course.",
    "I have taken a Machine Learning and Computer Vision course.",
    "I have completed machine learning and data structures courses.",
])
def test_a_course_noun_ending_a_list_names_every_listed_title_in_it(
        email_client, monkeypatch, route, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, LEGACY_TITLES)
    assert out["fallback_reason"] == "fabrication" and claim not in out["body"], out


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("claim", [
    "I have completed several courses, and machine learning became my main interest.",
    "I took a statistics class, and machine learning quickly became my favorite topic.",
])
def test_after_a_course_noun_a_comma_and_and_start_a_new_clause(
        email_client, monkeypatch, route, claim):  # noqa: F811
    out = request(email_client, monkeypatch, route, claim, LEGACY_TITLES)
    assert out["method"] == ("ai" if route == "/cold-email" else "llm"), out
    assert claim in out["body"]


def test_the_template_may_quote_the_students_own_course_line(email_client):  # noqa: F811
    line = "Completed CS 225 project: built a PyTorch model of hypersonics flow data in Python."
    response = email_client.post("/api/cold-email", json={
        "profile": LEGACY, "opportunity_id": OPP["id"], "engine": "template",
        "experience_evidence": confirmed_experience([line])})
    assert response.status_code == 200, response.text
    assert line in response.json()["body"]


# What the ColdEmailModal "Add coursework" quick action now inserts (phase 1a:
# the neutral listing every status allows), and what it inserted before, in a
# draft the student refines. A course claim already in the student's draft is
# their own text, so only a claim new to the reply is refused. Only a listed
# course is checked, so the new claim's CS 446 is listed too.
QUICK = "My coursework includes CS 225, CS 374."
OLD_QUICK = "I have completed relevant coursework including CS 225, CS 374."
QUICK_PROFILE = {**BASE, "coursework": ["CS 225", "CS 374", "CS 446"]}
QUICK_PROFILES = {"legacy": QUICK_PROFILE,
                  "statuses": {**BASE, "courses": [{"name": "CS 225", "status": "unknown"},
                                                   {"name": "CS 374", "status": "planned"},
                                                   {"name": "CS 446", "status": "planned"}]}}


def refine_quick(http, monkeypatch, profile, current, reply, instruction="make it warmer"):
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: draft(f"I am very interested in hypersonics.\n\n{reply}"))
    response = http.post("/api/cold-email/refine", json={
        "profile": profile, "opportunity_id": OPP["id"], "instruction": instruction,
        "current_body": draft(f"I am interested in hypersonics.\n\n{current}")})
    assert response.status_code == 200, response.text
    return response.json()


def select_quick(http, monkeypatch, profile, sentence, replacement):
    old = "I am interested in hypersonics."
    whole = draft(f"{old}\n\n{sentence}")
    start = len(whole[:whole.index(old)].encode("utf-16-le")) // 2
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: json.dumps({"replacement": replacement}))
    response = http.post("/api/cold-email/refine", json={
        "profile": profile, "opportunity_id": OPP["id"], "current_body": whole, "subject": "Research inquiry",
        "instruction": "Make only this selection clearer.",
        "selection": {"start_utf16": start, "end_utf16": start + len(old), "text": old}})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("provider", [True, False], ids=["reply", "no_provider"])
@pytest.mark.parametrize("profile", QUICK_PROFILES.values(), ids=QUICK_PROFILES)
@pytest.mark.parametrize("sentence", [QUICK, OLD_QUICK], ids=["quick", "old_quick"])
def test_refine_keeps_a_draft_holding_the_coursework_quick_action(
        email_client, monkeypatch, sentence, profile, provider):  # noqa: F811
    monkeypatch.setattr(ce, "is_configured", lambda: provider)
    out = refine_quick(email_client, monkeypatch, profile, sentence, sentence)
    assert out.get("fallback_reason") is None and out["method"] == ("llm" if provider else "local"), out
    assert sentence in out["body"], out


@pytest.mark.parametrize("profile", QUICK_PROFILES.values(), ids=QUICK_PROFILES)
@pytest.mark.parametrize("sentence", [QUICK, OLD_QUICK], ids=["quick", "old_quick"])
def test_selection_refine_beside_the_coursework_quick_action(email_client, monkeypatch, sentence, profile):  # noqa: F811
    out = select_quick(email_client, monkeypatch, profile, sentence, "I am very interested in hypersonics.")
    assert out.get("outcome") == "proposal", out


@pytest.mark.parametrize("profile", QUICK_PROFILES.values(), ids=QUICK_PROFILES)
@pytest.mark.parametrize(("current", "reply", "instruction"), [
    (OLD_QUICK, f"{OLD_QUICK} I have completed CS 446.", "make it warmer"),
    (OLD_QUICK, "I have completed relevant coursework including CS 225, CS 374, CS 446.", "make it warmer"),
    # An edit request is not the student's draft.
    (OLD_QUICK, f"{OLD_QUICK} I have completed CS 446.", "Say that I have completed CS 446."),
    # The same course, claimed completed where the draft said currently taking.
    ("I am currently taking CS 446.", "I have completed CS 446.", "make it warmer"),
], ids=["new_course", "widened_list", "instruction", "taking_to_completed"])
def test_refine_still_refuses_a_course_claim_new_to_the_reply(
        email_client, monkeypatch, profile, current, reply, instruction):  # noqa: F811
    out = refine_quick(email_client, monkeypatch, profile, current, reply, instruction)
    assert out["method"] == "local" and out["fallback_reason"] == "fabrication", out
    assert reply not in out["body"]


@pytest.mark.parametrize("profile", QUICK_PROFILES.values(), ids=QUICK_PROFILES)
def test_selection_refine_still_refuses_a_course_claim_new_to_the_draft(email_client, monkeypatch, profile):  # noqa: F811
    out = select_quick(email_client, monkeypatch, profile, OLD_QUICK,
                       "I am very interested in hypersonics. I have completed CS 446.")
    assert out.get("outcome") == "no_change" and out["reason"] == "fabrication", out


@pytest.mark.parametrize("route", ["/cold-email", "/cold-email/stream"])
@pytest.mark.parametrize("profile", QUICK_PROFILES.values(), ids=QUICK_PROFILES)
def test_generation_still_refuses_the_old_coursework_sentence_from_the_model(
        email_client, monkeypatch, route, profile):  # noqa: F811
    body = draft(OLD_QUICK)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k: f"Subject: Research inquiry\n\n{body}")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body)
    response = email_client.post(f"/api{route}", json={"profile": profile, "opportunity_id": OPP["id"], "engine": "ai"})
    assert response.status_code == 200, response.text
    out = (next(json.loads(line[6:]) for line in response.text.splitlines()
                if line.startswith("data: ") and json.loads(line[6:]).get("stage") == "done")
           if route.endswith("stream") else response.json())
    assert out["fallback_reason"] == "fabrication" and OLD_QUICK not in out["body"], out
