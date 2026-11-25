"""The default card, detail, ranking and template agree on what a student can do."""
from datetime import UTC, datetime, timedelta

import pytest

from backend.lib.contact_visibility import build_identity_bound_contact_evidence
from backend.lib.email_target_conditions import build_target_conditions
from backend.routes.matches import _match_card
from backend.routes.opportunities import _list_card, _redact
from src.evidence import faculty_safe_public_record
from src.matcher.ranker import rank_opportunity
from src.recommender.cold_email import generate_cold_email, generate_variants

STUDENT = {"name": "Sample Student", "major": "Physics", "year": "sophomore",
           "research_interests_text": "physics", "can_cold_email": True}


@pytest.mark.parametrize(("name", "row_id", "age", "status"), [
    ("Sergei Gukov", "faculty-caltech-phys-b6dd07e7", None, "unavailable"),
    ("Ahmed Alaa", "faculty-ucb-eecs-d683bc2c", 1, "sign_in_required"),
    ("Ahmed Alaa", "faculty-ucb-eecs-d683bc2c", 70, "unavailable"),
])
def test_faculty_identity_does_not_create_a_vacancy(name, row_id, age, status):
    # Reduced shapes of real faculty directory records. The contact and dates
    # are synthetic to keep this independent of the next refresh and the clock.
    profile_url = "https://example.edu/people/" + row_id
    record = {"id": row_id, "title": name, "pi_name": name, "source": "caltech_faculty" if age is None else "ucb_eecs_faculty",
              "source_type": "faculty_research", "department": "Physics", "organization": "Caltech" if age is None else "UC Berkeley",
              "url": profile_url, "source_url": profile_url, "contact_email": "sample@example.edu" if age is not None else None,
              "description_clean": "Faculty directory", "metadata": {"faculty_title": "Professor"},
              "eligibility": {}, "application": {"application_url": profile_url},
              "contact_email_status": "revealed"}
    if age is not None:
        evidence = build_identity_bound_contact_evidence(
            email=record["contact_email"], email_source="bound_directory_card", contact_source_url=profile_url,
            contact_verified_at=datetime.now(UTC) - timedelta(days=age))
        record["metadata"].update(evidence)
    for projection in (_match_card, _list_card, _redact):
        public = projection(record)
        assert public["record_kind"] == "faculty_contact"
        assert public["contact_email_status"] == status
        assert not public.get("contact_email")
        assert public["target_truth"]["accepting_state"] == "unknown"
        assert not public["application"].get("application_url")
    safe = faculty_safe_public_record(record)
    steps = rank_opportunity(STUDENT, safe).next_steps
    assert ("Send a brief cold email to the PI expressing interest" in steps) == (status == "sign_in_required")
    assert ("Open the faculty profile and verify a contact channel" in steps) == (status == "unavailable")
    assert build_target_conditions(safe)["record_kind"] == "faculty_contact"
    draft = generate_cold_email(STUDENT, safe)
    assert "?" in draft and "your open position" not in draft.casefold() and "you are hiring" not in draft.casefold()


@pytest.mark.parametrize("opportunity_type", [None, "internship"])
def test_posted_internship_keeps_its_application_action(opportunity_type):
    url = "https://job-boards.greenhouse.io/octaura/jobs/4662934007"
    record = {"id": "simplify-intern-3ea65aaa-0297-4b8f-9378-51e35478fb95", "source_type": "internship",
              "source": "simplify_internships", "title": "Data Engineer Intern", "organization": "Octaura",
              "url": url, "source_url": url, "application": {"application_url": url}, "metadata": {}}
    for projection in (_match_card, _list_card, _redact):
        public = projection(record)
        assert public["record_kind"] == "listing" and public["target_truth"]["actionable"]
        assert public["application"]["application_url"] == url
    assert build_target_conditions(record)["record_kind"] == "listing"
    if opportunity_type:
        record["opportunity_type"] = opportunity_type
    draft = generate_cold_email(STUDENT, record)
    assert record["title"] in draft
    for email in [draft, *(variant["text"] for variant in generate_variants(STUDENT, record))]:
        assert email.splitlines()[0] == "Subject: Internship inquiry — Data Engineer Intern"


@pytest.mark.parametrize("official_subject", [None, "2027 summer application"])
def test_posted_internship_fallback_preserves_role_and_official_subject(official_subject):
    from backend.routes.cold_email import _guard_email_output
    from src.recommender.cold_email import _common_parts

    record = {"source_type": "internship", "title": "Data Engineer Intern"}
    if official_subject:
        record["contact_instructions"] = {"version": 1, "status": "known",
                                          "rules": [{"kind": "subject", "subject": official_subject}]}
    parts = _common_parts(STUDENT, record)
    subject, body, recovered = _guard_email_output("", "", parts, record)
    assert recovered and subject == (official_subject or "Internship inquiry")
    assert "internship application" in body and "research openings" not in body
