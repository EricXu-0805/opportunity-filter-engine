"""What the template e-mail says of the student and what it asks (M31, M35).

The owner scored seven template e-mails on 2026-11-06/07 and found each short
of content: the rules pinned here are what the template does about it. Every
sentence about the student is one the student confirmed; nothing is said of the
recipient that the record does not state.
"""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.lib.experience_evidence import select_experience
from backend.routes import cold_email as ce
from backend.schemas import ColdEmailRequest, ExperienceEvidence
from src.recommender.cold_email import _common_parts, generate_variants, resume_bullet_relevance
from tests.experience_fixtures import confirmed_experience, resume_line_experience

PROFILE = {"name": "Audit Student", "school": "UIUC", "home_school": "uiuc", "year": "junior",
           "major": "Electrical Engineering", "hard_skills": [], "coursework": [],
           "research_interests_text": "speech and audio signal processing"}
# A faculty profile row: a directory page, never a posting.
FACULTY = {"id": "template-rules-faculty", "source": "uiuc_faculty", "source_type": "faculty_research",
           "record_kind": "faculty_contact", "opportunity_type": "research", "school": "uiuc",
           "title": "Research with Pat Lee", "pi_name": "Pat Lee", "organization": "Test University",
           "department": "Electrical & Computer Engineering", "keywords": [],
           "eligibility": {"skills_required": []}, "application": {},
           "metadata": {"is_active": True, "faculty_title": "Professor",
                        "research_areas_raw": "Acoustic phonetics, Speech recognition, Adaptive signal processing"}}
# A listing: its keywords are the source's own "Research Area" words.
LISTING = {"id": "template-rules-listing", "source": "uiuc_sro", "source_type": "campus_program",
           "opportunity_type": "research", "school": "uiuc", "title": "Speech recognition research",
           "pi_name": "Pat Lee", "organization": "Test University", "keywords": ["speech recognition"],
           "description_raw": "Research on speech recognition.",
           "eligibility": {"skills_required": []}, "application": {}, "metadata": {"is_active": True}}

RELATED = "I trained a speech recognition model on recordings of 40 speakers."
# One word in common with the professor's research: under the two-word rule it reached no e-mail.
PROJECT = "I measured the signal-to-noise ratio of a hearing-aid prototype before and after filtering."
UNRELATED = "I ran the checkout desk at the campus bookstore for two semesters."
OPENINGS_ASK = ("Could I ask whether you have any current or upcoming research openings for a student? "
                "If so, what preparation would be useful before a brief conversation?")
ADVICE_ASK = ("Could I ask what you would suggest I learn or do first to prepare for research in this area? "
              "May I contact you again once I have done that?")


def texts(opp, experience=(), profile=PROFILE):
    return [variant["text"] for variant in generate_variants(deepcopy(profile), deepcopy(opp),
                                                             resume_bullets=list(experience))]


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    rows = {row["id"]: row for row in (FACULTY, LISTING)}
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: deepcopy(rows))
    monkeypatch.setattr(ce, "is_configured", lambda: False)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: pytest.fail("unexpected provider"))

    async def anonymous(_authorization):
        return None

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    return TestClient(app)


def served(client, opp, experience, endpoint="", **extra):
    """Bodies a template route serves, each checked as the route's own guard checks a draft."""
    payload = {"profile": PROFILE, "opportunity_id": opp["id"],
               "experience_evidence": confirmed_experience(list(experience)), **extra}
    response = client.post("/api/cold-email" + (f"/{endpoint}" if endpoint else ""), json=payload)
    assert response.status_code == 200, response.text
    out = response.json()
    items = out["variants"] if endpoint == "variants" else [out]
    request = ColdEmailRequest(**payload)
    safe = ce._contact_safe_opportunity(ce._email_target(request).public)
    parts, _selection = ce._experience_parts(request, request.profile.model_dump(), safe)
    for item in items:
        assert ce._email_grounding_findings(f"{item['subject']}\n{item['body']}", parts, safe,
                                            deterministic=True) == ([], []), item["body"]
    return out, [item["body"] for item in items]


@pytest.mark.parametrize("experience", [(), (UNRELATED,)], ids=["no-experience", "nothing-in-the-area"])
def test_a_student_with_nothing_in_the_professors_area_asks_for_advice_not_about_openings(experience):
    for text in texts(FACULTY, experience):
        assert text.count(ADVICE_ASK) == 1
        assert "openings" not in text and "If so" not in text


def test_the_advice_ask_names_no_area_when_the_record_states_none():
    sparse = {**FACULTY, "metadata": {"is_active": True, "faculty_title": "Professor"}}
    for text in texts(sparse):
        assert ("Could I ask what you would suggest I learn or do first to prepare for research? "
                "May I contact you again once I have done that?") in text
        assert "this area" not in text and "openings" not in text


def test_a_student_with_an_experience_in_the_professors_area_keeps_the_openings_ask():
    for text in texts(FACULTY, (UNRELATED, RELATED)):
        assert text.count(OPENINGS_ASK) == 1
        assert "learn or do first" not in text


@pytest.mark.parametrize("experience", [(), (RELATED,)])
def test_a_listing_keeps_its_own_ask(experience):
    for text in texts(LISTING, experience):
        assert "What would be a useful first step for a student interested in this work?" in text
        assert "learn or do first" not in text
    # A question the source's own conditions call for is asked whatever the student has done.
    parts = _common_parts(PROFILE, LISTING, resume_bullets=list(experience))
    parts["target_conditions_template_request"] = "Could you confirm the current application deadline?"
    for variant in generate_variants(PROFILE, LISTING, parts_cache=parts):
        assert "Could you confirm the current application deadline?" in variant["text"]
        assert "learn or do first" not in variant["text"]


@pytest.mark.parametrize("endpoint", ["", "variants"])
@pytest.mark.parametrize("experience, ask", [((), ADVICE_ASK), ((UNRELATED,), ADVICE_ASK), ((RELATED,), OPENINGS_ASK)],
                         ids=["no-experience", "nothing-in-the-area", "in-the-area"])
def test_every_template_route_serves_the_ask_and_it_passes_every_fact_check(client, endpoint, experience, ask):
    out, bodies = served(client, FACULTY, experience, endpoint)
    assert bodies and all(body.count(ask) == 1 for body in bodies)
    if not endpoint:
        assert out["method"] == "template" and out["fallback_reason"] is None


def test_a_rejected_ai_draft_falls_back_to_the_same_ask(client, monkeypatch):
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k:
                        "Subject: Research inquiry\n\nDear Professor Pat Lee,\n\nI have attached my resume.")
    out, bodies = served(client, FACULTY, (), engine="ai")
    assert out["method"] == "template" and out["fallback_reason"] == "fabrication"
    assert bodies[0].count(ADVICE_ASK) == 1


def test_the_fixture_sentences_overlap_the_professors_research_as_the_tests_assume():
    parts = _common_parts(PROFILE, FACULTY)
    assert [resume_bullet_relevance(parts, text) for text in (RELATED, PROJECT, UNRELATED)] == [2, 1, 0]


def test_the_template_quotes_the_two_experiences_closest_to_the_target_in_that_order():
    for text in texts(FACULTY, (UNRELATED, PROJECT, RELATED)):
        assert f"\n\n{RELATED}\n\n{PROJECT}\n\n" in text
        assert UNRELATED not in text
    # A listing is no different: its own words order the student's sentences.
    for text in texts(LISTING, (UNRELATED, RELATED)):
        assert f"\n\n{RELATED}\n\n{UNRELATED}\n\n" in text


def test_overlap_orders_the_experiences_and_no_longer_hides_them():
    for text in texts(FACULTY, (UNRELATED, PROJECT)):
        assert f"\n\n{PROJECT}\n\n{UNRELATED}\n\n" in text
    for text in texts(FACULTY, (UNRELATED,)):
        assert text.count(f"\n\n{UNRELATED}\n\n") == 1
    # Ties keep the order the student gave.
    second = "I tutored first-year students in calculus for a year."
    for text in texts(FACULTY, (UNRELATED, second)):
        assert f"\n\n{UNRELATED}\n\n{second}\n\n" in text


@pytest.mark.parametrize("endpoint", ["", "variants"])
def test_template_routes_quote_two_confirmed_experiences_and_the_receipt_lists_them(client, endpoint):
    out, bodies = served(client, FACULTY, (UNRELATED, PROJECT, RELATED), endpoint)
    assert bodies and all(f"\n\n{RELATED}\n\n{PROJECT}\n\n" in body and UNRELATED not in body for body in bodies)
    assert all(body.count(OPENINGS_ASK) == 1 for body in bodies)
    assert [item["excerpt"] for item in out["experience_usage"]["selected"]] == [RELATED, PROJECT]


@pytest.mark.parametrize("endpoint", ["", "variants"])
def test_two_experiences_outside_the_area_are_quoted_and_pass_every_fact_check(client, endpoint):
    out, bodies = served(client, FACULTY, (UNRELATED, PROJECT), endpoint)
    assert bodies and all(f"\n\n{PROJECT}\n\n{UNRELATED}\n\n" in body for body in bodies)
    assert all(body.count(ADVICE_ASK) == 1 for body in bodies)
    assert [item["excerpt"] for item in out["experience_usage"]["selected"]] == [PROJECT, UNRELATED]


def test_a_rejected_ai_draft_falls_back_to_the_two_experiences(client, monkeypatch):
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setattr(ce, "_pipeline_generate", lambda *_a, **_k:
                        "Subject: Research inquiry\n\nDear Professor Pat Lee,\n\nI have attached my resume.")
    out, bodies = served(client, FACULTY, (PROJECT, UNRELATED, RELATED), engine="ai")
    assert out["method"] == "template" and out["fallback_reason"] == "fabrication"
    assert f"\n\n{RELATED}\n\n{PROJECT}\n\n" in bodies[0] and UNRELATED not in bodies[0]
    assert [item["excerpt"] for item in out["experience_usage"]["selected"]] == [RELATED, PROJECT]


def test_a_refine_that_recovers_through_the_template_gets_the_same_two_experiences(client):
    response = client.post("/api/cold-email/refine", json={
        "profile": PROFILE, "opportunity_id": FACULTY["id"],
        "experience_evidence": confirmed_experience([UNRELATED, PROJECT, RELATED]),
        "current_body": "Dear Professor Pat Lee,\n\nI have three years of experience with Kubernetes.",
        "instruction": "make it warmer"})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["method"] == "local" and "Kubernetes" not in out["body"]
    assert RELATED in out["body"] and PROJECT in out["body"] and UNRELATED not in out["body"]
    assert [item["excerpt"] for item in out["experience_usage"]["selected"]] == [RELATED, PROJECT]


def test_what_was_kept_out_of_the_template_stays_out():
    too_long = "I organised " + "weekly review sessions and " * 9 + "office hours."
    role_line = "Undergraduate Research Assistant, Speech Lab (UIUC), Jan 2026 - Present"
    evidence = confirmed_experience([too_long, role_line, UNRELATED, "I have not confirmed this line.", PROJECT, PROJECT])
    evidence["entries"][3]["status"] = "candidate"
    selection = select_experience(ExperienceEvidence.model_validate(evidence), _common_parts(PROFILE, FACULTY))
    assert len(too_long) > 220
    # Over the template's 220 characters, a role line, unconfirmed: none is
    # quoted, and a sentence confirmed twice is quoted once.
    assert [item["excerpt"] for item in selection.templates] == [PROJECT, UNRELATED]
    assert "experience_template_budget_omission" in selection.quoted_usage("")["notices"]


def test_a_resume_line_whose_source_changed_is_not_quoted():
    evidence = resume_line_experience(RELATED + "\n" + PROJECT)
    evidence["entries"][0]["source"]["quote"] = "x" * len(RELATED)
    selection = select_experience(ExperienceEvidence.model_validate(evidence), _common_parts(PROFILE, FACULTY))
    assert [item["excerpt"] for item in selection.templates] == [PROJECT]
    assert selection.excluded == [{"id": evidence["entries"][0]["id"], "revision": 1, "reason": "source_quote_mismatch"}]
