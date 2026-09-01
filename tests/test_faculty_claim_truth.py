"""Fail-closed contract for faculty directory contacts.

A faculty profile is a useful person to contact, but it is not evidence that
the lab has an opening or that any eligibility/application default is true.
These tests protect the legacy corpus at load time and the user-facing ranking
and Ask-AI paths that previously amplified template defaults as facts.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend import data_loader
from backend.routes import cold_email as cold_email_routes
from backend.routes import matches as match_routes
from backend.routes import opportunities as opportunity_routes
from backend.routes.opportunities import _build_chat_system_prompt, _local_chat_fallback
from src.evidence import (
    faculty_availability_is_source_negative,
    faculty_availability_status,
    faculty_safe_eligibility,
    faculty_safe_public_record,
    stamp_inferred,
)
from src.matcher import ranker as ranker_module
from src.matcher.ranker import rank_opportunity, score_upside
from src.normalizers.normalizer import _compute_effort
from src.saved_searches.filter import match_filter

_ALL_YEARS = ["freshman", "sophomore", "junior", "senior"]
_FORBIDDEN_FIT_CLAIMS = (
    "Accepts freshman students",
    "Explicitly welcomes first-time researchers",
    "Low application effort",
    "Paid opportunity",
    "Includes stipend",
    "work authorization concerns",
)


def _legacy_faculty(**overrides) -> dict:
    record = {
        "id": "faculty-test-ada",
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "title": "Research with Prof. Ada Lovelace",
        "organization": "Test University",
        "department": "Computer Science",
        "pi_name": "Ada Lovelace, Ph.D.",
        "lab_or_program": "Prof. Ada Lovelace's Research Group",
        "url": "https://example.edu/ada",
        "school": "testu",
        "audience": "campus",
        "on_campus": True,
        "remote_option": "yes",
        "opportunity_type": "research",
        "paid": "yes",
        "compensation_details": "Funding varies by project",
        "is_rolling": True,
        "duration": "Semester or academic year",
        "deadline": "2026-12-01",
        "deadline_is_estimate": False,
        "start_date": "2027-01-15",
        "posted_date": "2026-08-01",
        "keywords": ["machine learning"],
        "eligibility": {
            "preferred_year": list(_ALL_YEARS),
            "min_gpa": 3.8,
            "majors": ["Computer Science"],
            "skills_required": ["FAKE_REQUIRED_SKILL"],
            "skills_preferred": ["FAKE_PREFERRED_SKILL"],
            "first_time_researchers": True,
            "citizenship_required": False,
            "international_friendly": "yes",
            "work_auth_notes": "On-campus research — no work authorization required",
            "eligibility_text_raw": "POISON juniors/Python/apply Friday",
        },
        "application": {
            "contact_method": "SECRET_APPLICATION_FORM",
            "requires_resume": "yes",
            "requires_cover_letter": "yes",
            "requires_transcript": "yes",
            "requires_recommendation": "yes",
            "application_effort": "low",
            "application_url": "https://example.edu/ada",
        },
        "description_raw": (
            "Research opportunity with Prof. Ada Lovelace. Contact the professor "
            "to inquire about undergraduate research positions in their lab."
        ),
        "description_clean": (
            "Research opportunity with Prof. Ada Lovelace. Contact the professor "
            "to inquire about undergraduate research positions in their lab."
        ),
        "metadata": {
            "is_active": True,
            "manually_reviewed": False,
            "research_areas_raw": (
                "machine learning, publications, papers, conference research"
            ),
            "deadline_note": "Rolling applications",
        },
    }
    for key, value in overrides.items():
        if key in {"eligibility", "application", "metadata"}:
            record[key] = {**record[key], **value}
        else:
            record[key] = value
    return record


def test_loader_downgrades_legacy_faculty_templates_before_registration():
    out = data_loader._sanitize_opportunity(_legacy_faculty())

    assert out["eligibility"]["preferred_year"] == ["unknown"]
    assert out["eligibility"]["min_gpa"] is None
    assert out["eligibility"]["majors"] == []
    assert out["eligibility"]["skills_required"] == []
    assert out["eligibility"]["skills_preferred"] == []
    assert out["eligibility"]["first_time_researchers"] is None
    assert out["eligibility"]["international_friendly"] == "unknown"
    assert out["eligibility"]["citizenship_required"] is None
    assert out["eligibility"]["work_auth_notes"] == ""
    assert out["application"]["application_effort"] == "unknown"
    assert out["application"]["contact_method"] == "unknown"
    assert out["application"]["application_url"] is None
    for requirement in (
        "requires_resume",
        "requires_cover_letter",
        "requires_transcript",
        "requires_recommendation",
    ):
        assert out["application"][requirement] == "unknown"
    assert out["on_campus"] is None
    assert out["remote_option"] == "unknown"
    assert out["paid"] == "unknown"
    assert out["compensation_details"] == ""
    assert out["is_rolling"] is False
    assert out["duration"] is None
    assert out["deadline"] is None
    assert out["deadline_is_estimate"] is None
    assert out["start_date"] is None
    assert out["posted_date"] is None
    assert out["audience"] == "unknown"
    assert "deadline_note" not in out["metadata"]
    assert out["lab_or_program"] == ""
    assert out["title"] == "Ada Lovelace, Ph.D."
    assert out["description_raw"] == out["description_clean"]
    assert "currently available" in out["description_clean"]
    assert "Research opportunity with" not in out["description_clean"]


def test_loader_preserves_only_source_stated_restrictions_not_review_flags():
    unsupported_restriction = data_loader._sanitize_opportunity(
        _legacy_faculty(
            eligibility={
                "international_friendly": "no",
                "citizenship_required": True,
            },
        ),
    )
    assert unsupported_restriction["eligibility"]["international_friendly"] == "unknown"
    assert unsupported_restriction["eligibility"]["citizenship_required"] is None

    stated_raw = _legacy_faculty(
        eligibility={
            "international_friendly": "no",
            "citizenship_required": True,
            "eligibility_text_raw": "Applicants must be U.S. citizens.",
            "work_auth_notes": "U.S. citizenship is required.",
        },
    )
    twice_neutralized = data_loader.neutralize_unverified_faculty_claims(
        deepcopy(stated_raw),
    )
    data_loader.neutralize_unverified_faculty_claims(twice_neutralized)
    assert twice_neutralized["eligibility"]["citizenship_required"] is True

    stated_restriction = data_loader._sanitize_opportunity(deepcopy(stated_raw))
    assert stated_restriction["eligibility"]["international_friendly"] == "no"
    assert stated_restriction["eligibility"]["citizenship_required"] is True
    assert stated_restriction["eligibility"]["work_auth_notes"] == "Applicants must be U.S. citizens."
    # The loader removes the bulky raw excerpt; the compact canonical marker
    # must keep every later boundary on the same explicit restriction.
    safe_after_loader = faculty_safe_eligibility(stated_restriction)
    assert safe_after_loader["international_friendly"] == "no"
    assert safe_after_loader["citizenship_required"] is True

    restricted_context = ranker_module._filter_context({
        "home_school": "testu",
        "include_cross_school": True,
        "international_student": True,
        "seeking_type": ["research"],
        "preferences": {"exclude_citizenship_restricted": True},
    })
    assert (
        ranker_module.hard_exclusion(stated_restriction, restricted_context)
        == "citizenship_restricted"
    )
    restricted_prompt = _build_chat_system_prompt(stated_restriction, None)
    assert "International friendly: no" in restricted_prompt
    assert "Citizenship required: yes" in restricted_prompt

    generic_reviewed = data_loader._sanitize_opportunity(
        _legacy_faculty(metadata={"manually_reviewed": True}),
    )
    assert generic_reviewed["paid"] == "unknown"
    assert generic_reviewed["is_rolling"] is False

    dedicated_marker = data_loader._sanitize_opportunity(
        _legacy_faculty(
            metadata={"manually_reviewed": True, "faculty_opening_verified": True},
        ),
    )
    assert dedicated_marker["paid"] == "unknown"
    assert dedicated_marker["is_rolling"] is False

    posting_raw = _legacy_faculty(source_type="campus_program")
    posting = data_loader._sanitize_opportunity(deepcopy(posting_raw))
    assert posting["eligibility"]["preferred_year"] == _ALL_YEARS
    assert posting["application"]["application_effort"] == "low"
    assert posting["on_campus"] is True
    assert posting["paid"] == "yes"
    assert posting["is_rolling"] is True


@pytest.mark.parametrize(
    ("source_text", "expected_status", "expected_reason", "expected_phrase"),
    [
        (
            "Not accepting additional undergraduate, masters, or PhD students at this time.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "Not taking students at this time.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "I am not accepting undergraduates at this time.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "The lab is no longer accepting undergraduate researchers.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            # Verbatim from faculty-mcb-0c3fca33, live and is_active in the
            # served corpus: "accepting/taking" alone let a retired professor
            # through every availability gate.
            "Professor Nelson has retired from the university and is no longer "
            "recruiting undergraduate or graduate students to his lab.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "This lab is not accepting applications this semester.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "The group is not accepting new applications at this time.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "This faculty member does not accept applications from undergraduate students.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "The lab is not taking on undergraduate researchers this year.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "The group is not admitting students this semester.",
            "not_accepting_undergraduates",
            "faculty_not_accepting",
            "not currently accepting undergraduate students or researchers",
        ),
        (
            "This faculty member is not currently research active.",
            "research_inactive",
            None,
            "not currently conducting active research",
        ),
        (
            "While I am not currently conducting research, I support students' Honors Theses.",
            "research_inactive",
            None,
            "not currently conducting active research",
        ),
        (
            "The faculty member is no longer conducting research.",
            "research_inactive",
            None,
            "not currently conducting active research",
        ),
    ],
)
def test_source_stated_faculty_unavailability_survives_loader_and_blocks_actions(
    source_text,
    expected_status,
    expected_reason,
    expected_phrase,
):
    raw = _legacy_faculty(
        description_raw=source_text,
        description_clean=source_text,
        metadata={"research_areas_raw": source_text},
    )
    loaded = data_loader._sanitize_opportunity(deepcopy(raw))

    assert faculty_availability_is_source_negative(raw) is True
    assert faculty_availability_is_source_negative(loaded) is True
    assert faculty_availability_status(raw) == expected_status
    assert faculty_availability_status(loaded) == expected_status
    assert loaded["metadata"]["faculty_availability_status"] == expected_status
    assert loaded["faculty_availability_status"] == expected_status
    assert expected_phrase in loaded["description_clean"].lower()
    assert "contact this faculty member to ask whether" not in (
        loaded["description_clean"].lower()
    )
    if expected_status == "research_inactive":
        assert "not currently accepting undergraduate" not in (
            loaded["description_clean"].lower()
        )
    context = ranker_module._filter_context({
        "home_school": "testu",
        "international_student": False,
        "seeking_type": ["research"],
    })
    assert ranker_module.hard_exclusion(raw, context) == expected_reason
    assert ranker_module.hard_exclusion(loaded, context) == expected_reason
    prompt = _build_chat_system_prompt(loaded, None)
    assert expected_phrase in prompt.lower()
    fallback = _local_chat_fallback(loaded, "Should I contact them?")
    assert expected_phrase in fallback.lower()
    if expected_status == "not_accepting_undergraduates":
        with pytest.raises(HTTPException) as exc_info:
            cold_email_routes._assert_outreach_allowed(loaded)
        assert exc_info.value.status_code == 409
        assert expected_phrase in str(exc_info.value.detail).lower()
    else:
        assert cold_email_routes._assert_outreach_allowed(loaded) is None


@pytest.mark.parametrize(
    "text",
    [
        "I am not accepting graduate students at this time.",
        # Both attested in the served corpus, both graduate-only: widening the
        # verb set must not start blocking undergraduate outreach on them.
        "NO LONGER TAKING NEW GRADUATE STUDENTS",
        "I am not admitting new graduate students for Fall 2025 admission.",
        "Not currently accepting doctoral graduate students",
        "This lab does not accept graduate applications.",
        "Not accepting applications from graduate students this semester.",
        "Not accepting graduate-student applications this semester.",
        "Not accepting grad students this semester.",
        "Not accepting grad-student applications this semester.",
        "Not accepting graduate students, but welcoming undergraduate researchers.",
    ],
)
def test_graduate_only_unavailability_does_not_suppress_undergraduate_contact(text):
    record = _legacy_faculty(
        description_raw=text,
        description_clean=text,
        metadata={"research_areas_raw": text},
    )
    assert faculty_availability_is_source_negative(record) is False
    assert faculty_availability_status(record) == "unknown"
    loaded = data_loader._sanitize_opportunity(record)
    assert faculty_availability_is_source_negative(loaded) is False
    assert faculty_availability_status(loaded) == "unknown"
    assert loaded["metadata"]["faculty_availability_status"] == "unknown"
    assert loaded["faculty_availability_status"] == "unknown"


@pytest.mark.parametrize(
    "eligibility_text_raw",
    [
        (
            "Research opportunity with Professor of Nutritional Sciences Richard "
            "Eisenstein in the Department of Nutritional Sciences at University of "
            "Wisconsin-Madison. Research areas: Cellular and Genetic Toxicology. "
            "Iron. Regulation of iron metabolism. Molecular regulation of the "
            "synthesis of iron transport and storage proteins (not currently taking "
            "grad students) Contact the professor directly to inquire about "
            "undergraduate research positions in their lab."
        ),
        (
            "Research opportunity with Professor of Nutritional Sciences Guy "
            "Groblewski in the Department of Nutritional Sciences at University of "
            "Wisconsin-Madison. Research areas: Intracellular signal transduction "
            "and membrane/protein trafficking in gastrointestinal epithelial cells "
            "(not currently taking grad students) Contact the professor directly to "
            "inquire about undergraduate research positions in their lab."
        ),
        (
            "Research opportunity with Professor of Nutritional Sciences Huichuan "
            "Lai in the Department of Nutritional Sciences at University of "
            "Wisconsin-Madison. Research areas: Precision nutrition in cystic "
            "fibrosis: clinical and epidemiological studies linking nutrition and "
            "disease outcomes (not currently taking grad students) Contact the "
            "professor directly to inquire about undergraduate research positions "
            "in their lab."
        ),
        (
            "Research opportunity with Associate Professor of Nutritional Sciences "
            "Beth Olson in the Department of Nutritional Sciences at University of "
            "Wisconsin-Madison. Research areas: Breastfeeding support for low-income "
            "and working women, improving infant feeding practices in low income "
            "families (not currently taking grad students) Contact the professor "
            "directly to inquire about undergraduate research positions in their lab."
        ),
    ],
)
def test_real_wisc_constructed_grad_only_text_does_not_block_undergrad_outreach(
    eligibility_text_raw,
):
    """The four current Wisc rows put a graduate-only note in parentheses
    before constructed undergraduate-outreach prose.  The bounded classifier
    must stop at the closing parenthesis instead of borrowing the later word
    ``undergraduate`` as the negative object's target."""
    raw = _legacy_faculty(
        description_raw=eligibility_text_raw,
        description_clean=eligibility_text_raw,
        eligibility={"eligibility_text_raw": eligibility_text_raw},
        metadata={"research_areas_raw": eligibility_text_raw},
    )
    assert faculty_availability_status(raw) == "unknown"

    loaded = data_loader._sanitize_opportunity(deepcopy(raw))
    assert loaded["faculty_availability_status"] == "unknown"
    assert loaded["metadata"]["faculty_availability_scan_version"] == 1


def test_keyword_only_source_unavailability_is_preserved_and_blocks_outreach():
    raw = _legacy_faculty(
        description_raw="Faculty research profile. Contact to ask about openings.",
        description_clean="Faculty research profile. Contact to ask about openings.",
        keywords=["Not taking students at this time", "entomology"],
        metadata={"research_areas_raw": ""},
    )
    assert faculty_availability_status(raw) == "not_accepting_undergraduates"

    loaded = data_loader._sanitize_opportunity(raw)
    assert loaded["faculty_availability_status"] == "not_accepting_undergraduates"
    with pytest.raises(HTTPException) as exc_info:
        cold_email_routes._assert_outreach_allowed(loaded)
    assert exc_info.value.status_code == 409


def test_stale_cached_unknown_is_rescanned_and_upgraded():
    """Old cache markers predate the expanded source vocabulary. They must not
    pin a now-detectable refusal to unknown forever."""
    source_text = "Not accepting applications this semester."
    raw = _legacy_faculty(
        description_raw=source_text,
        description_clean=source_text,
        metadata={
            "faculty_availability_status": "unknown",
            "research_areas_raw": source_text,
        },
    )
    assert faculty_availability_status(raw) == "not_accepting_undergraduates"

    loaded = data_loader._sanitize_opportunity(deepcopy(raw))
    assert loaded["faculty_availability_status"] == "not_accepting_undergraduates"
    assert loaded["metadata"]["faculty_availability_scan_version"] == 1


def test_current_version_cached_unknown_short_circuits_rescan(monkeypatch):
    """A current neutralizer pass closes the 127k-row hot path in O(1)."""
    loaded = data_loader._sanitize_opportunity(
        _legacy_faculty(
            description_raw="Research in archival methods.",
            description_clean="Research in archival methods.",
            keywords=["archival methods"],
            metadata={"research_areas_raw": "archival methods"},
        ),
    )
    assert loaded["faculty_availability_status"] == "unknown"
    assert loaded["metadata"]["faculty_availability_scan_version"] == 1

    import src.evidence as evidence_module

    def boom(_text):
        raise AssertionError("current-version unknown must not rescan raw candidates")

    monkeypatch.setattr(
        evidence_module,
        "_faculty_not_accepting_undergraduates",
        boom,
    )
    assert faculty_availability_status(loaded) == "unknown"


def test_source_restriction_overrides_contradictory_legacy_defaults():
    record = data_loader._sanitize_opportunity(
        _legacy_faculty(
            eligibility={
                "international_friendly": "yes",
                "citizenship_required": False,
                "eligibility_text_raw": "Applicants must be U.S. citizens.",
                "work_auth_notes": "No work authorization required.",
            },
        ),
    )
    assert record["eligibility"]["international_friendly"] == "no"
    assert record["eligibility"]["citizenship_required"] is True
    assert record["eligibility"]["work_auth_notes"] == "Applicants must be U.S. citizens."


def test_unknown_material_requirements_do_not_become_low_effort():
    unknown = {
        "requires_resume": "unknown",
        "requires_cover_letter": "unknown",
        "requires_transcript": "unknown",
        "requires_recommendation": "unknown",
    }
    assert _compute_effort(unknown) == "unknown"
    assert _compute_effort({key: "no" for key in unknown}) == "low"


def test_ranked_faculty_contact_never_emits_template_fit_claims():
    opportunity = data_loader._sanitize_opportunity(_legacy_faculty())
    profile = {
        "year": "freshman",
        "major": "Computer Science",
        "secondary_interests": [],
        "international_student": True,
        "seeking_type": ["research"],
        "hard_skills": [],
        "coursework": [],
        "experience_level": "none",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "machine learning",
        "desired_fields": ["machine learning"],
        "home_school": "testu",
    }
    result = rank_opportunity(profile, opportunity, precomputed_sim=0.5)
    joined = "\n".join(result.reasons_fit)
    for claim in _FORBIDDEN_FIT_CLAIMS:
        assert claim not in joined
    assert "opportunity.preferred_year" in result.unknowns
    assert "opportunity.application_effort" in result.unknowns
    assert "opportunity.on_campus" in result.unknowns
    assert "opportunity.paid" in result.unknowns
    assert any("not confirmed" in reason.lower() for reason in result.reasons_gap)
    assert result.next_steps == ["Open the faculty profile and verify a contact channel"]
    assert not any("send a brief cold email" in step.lower() for step in result.next_steps)
    assert not any("review the posting" in step.lower() for step in result.next_steps)
    assert not any("apply before deadline" in step.lower() for step in result.next_steps)
    assert not any("prepare a research-focused resume" in step.lower() for step in result.next_steps)
    all_user_text = "\n".join(
        [*result.reasons_fit, *result.reasons_gap, *result.next_steps]
    ).lower()
    for forbidden in (
        "position may be competitive",
        "verify before applying",
        "targets graduate / phd",
        "potential for publication or long-term involvement",
        "strong resume builder",
        "review the posting",
        "application materials",
    ):
        assert forbidden not in all_user_text


def test_ranked_faculty_identity_and_brand_language_are_rank_neutral():
    opportunity = data_loader._sanitize_opportunity(
        _legacy_faculty(
            id="faculty-test-lecturer",
            school="uiuc",
            metadata={
                "faculty_title": "Senior Lecturer",
                "research_areas_raw": "machine learning",
            },
        ),
    )
    profile = {
        "year": "junior",
        "major": "Computer Science",
        "secondary_interests": [],
        "international_student": False,
        "seeking_type": ["research"],
        "hard_skills": [],
        "coursework": [],
        "experience_level": "some",
        "resume_ready": True,
        "can_cold_email": False,
        "research_interests_text": "machine learning",
        "desired_fields": ["machine learning"],
        "home_school": "uiuc",
    }
    result = rank_opportunity(profile, opportunity, precomputed_sim=0.5)
    user_text = "\n".join(
        [*result.reasons_fit, *result.reasons_gap, *result.next_steps]
    )
    assert "Ada Lovelace" in user_text
    assert "Prof. Ada Lovelace" not in user_text
    assert "Professor Ada Lovelace" not in user_text
    assert "strong resume builder" not in user_text.lower()
    assert "Faculty profile from a major research university" in user_text


def test_sanitized_faculty_can_offer_verified_cold_email_without_application_method(
    monkeypatch,
):
    opportunity = data_loader._sanitize_opportunity(_legacy_faculty())
    assert opportunity["application"]["contact_method"] == "unknown"
    monkeypatch.setattr(ranker_module, "verified_send_target", lambda _record: "ada@example.edu")
    profile = {
        "year": "junior",
        "major": "Computer Science",
        "international_student": False,
        "seeking_type": ["research"],
        "hard_skills": [],
        "coursework": [],
        "experience_level": "some",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "machine learning",
        "desired_fields": ["machine learning"],
        "home_school": "testu",
    }

    result = rank_opportunity(profile, opportunity, precomputed_sim=0.5)
    assert "Send a brief cold email to the PI expressing interest" in result.next_steps


def test_ranker_itself_neutralizes_unsanitized_faculty_opening_claims():
    raw = _legacy_faculty(school="uiuc")
    neutral = data_loader._sanitize_opportunity(deepcopy(raw))
    profile = {
        "year": "freshman",
        "major": "Computer Science",
        "secondary_interests": [],
        "international_student": True,
        "seeking_type": ["research"],
        "hard_skills": [{"name": "FAKE_REQUIRED_SKILL", "level": "expert"}],
        "coursework": [],
        "experience_level": "none",
        "resume_ready": False,
        "can_cold_email": True,
        "research_interests_text": "machine learning",
        "desired_fields": ["machine learning"],
        "home_school": "uiuc",
    }

    direct = rank_opportunity(profile, raw, precomputed_sim=0.5)
    baseline = rank_opportunity(profile, neutral, precomputed_sim=0.5)
    assert direct.eligibility_score == baseline.eligibility_score
    assert direct.readiness_score == baseline.readiness_score
    assert direct.upside_score == baseline.upside_score
    assert direct.final_score == baseline.final_score
    assert direct.unknowns == baseline.unknowns
    user_text = "\n".join(
        [*direct.reasons_fit, *direct.reasons_gap, *direct.next_steps]
    ).lower()
    for forbidden in (
        "accepts freshman",
        "major (computer science) is a direct match",
        "open to international students",
        "fake_required_skill",
        "explicitly welcomes first-time researchers",
        "paid opportunity",
        "at your university",
        "low application effort",
        "apply before deadline",
        "prepare a research-focused resume",
        "prof. ada lovelace",
    ):
        assert forbidden not in user_text

    cross_school = deepcopy(raw)
    cross_school["school"] = "ucb"
    context = ranker_module._filter_context({
        **profile,
        "include_cross_school": True,
        "preferences": {"exclude_citizenship_restricted": True},
    })
    assert ranker_module.hard_exclusion(cross_school, context) is None


def test_year_eligibility_is_not_first_time_research_evidence():
    opportunity = {
        "id": "explicit-freshman",
        "opportunity_type": "research",
        "on_campus": True,
        "school": "testu",
        "eligibility": {"preferred_year": ["freshman"]},
        "application": {},
        "metadata": {},
    }
    profile = {
        "international_student": True,
        "home_school": "testu",
        "research_interests_text": "",
    }
    _, fit, _ = score_upside(profile, opportunity)
    assert "Explicitly welcomes first-time researchers" not in fit
    assert not any("work authorization" in reason.lower() for reason in fit)


def test_ask_ai_receives_unknowns_instead_of_faculty_templates():
    # Pass the deliberately poisoned raw fixture. The prompt builder is a
    # second fail-closed boundary, not a harness that assumes the loader ran.
    opportunity = _legacy_faculty()
    prompt = _build_chat_system_prompt(opportunity, None)

    assert "Preferred years: (unspecified)" in prompt
    assert "International friendly: unknown" in prompt
    assert "Citizenship required: unknown" in prompt
    assert "Record status: faculty contact profile" in prompt
    assert "Outreach/application requirements: not confirmed" in prompt
    assert "on-campus: unknown" in prompt
    assert "- Remote: unknown" in prompt
    assert "- Paid: unknown; compensation: —" in prompt
    assert "- Deadline: not confirmed (faculty profile; not rolling evidence)" in prompt
    assert "rolling: unknown" in prompt
    assert "- Start date: —; duration: —" in prompt
    assert "Source/profile URL: https://example.edu/ada" in prompt
    assert "Apply URL:" not in prompt
    assert "- Description:" not in prompt
    assert "FAKE_REQUIRED_SKILL" not in prompt
    for opening_poison in (
        "Funding varies by project",
        "2026-12-01",
        "2027-01-15",
        "Semester or academic year",
        "2026-08-01",
        "SECRET_APPLICATION_FORM",
        "requires_resume=yes",
        "effort=low",
    ):
        assert opening_poison not in prompt
    assert "Computer Science" not in next(
        line for line in prompt.splitlines() if line.startswith("- Related majors")
    )
    assert "no work authorization required" not in prompt.lower()

    fallback = _local_chat_fallback(opportunity, "Am I eligible?")
    assert "Current opening, pay, timing, eligibility" in fallback
    assert "Faculty profile: https://example.edu/ada" in fallback
    assert "Apply at:" not in fallback


def test_public_route_projections_neutralize_raw_faculty_without_mutating_source():
    raw = _legacy_faculty()
    detail = opportunity_routes._redact(raw)
    list_card = opportunity_routes._list_card(raw)
    match_card = match_routes._match_card(raw)

    for projected in (detail, list_card, match_card):
        assert projected["paid"] == "unknown"
        assert projected["deadline"] is None
        assert projected["on_campus"] is None
        assert projected["eligibility"]["international_friendly"] == "unknown"
        assert projected["eligibility"]["skills_required"] == []
        assert "eligibility_text_raw" not in projected["eligibility"]
        assert projected.get("application", {}).get("application_url") is None
        assert projected.get("application", {}).get("contact_method") == "unknown"
    assert detail["remote_option"] == "unknown"
    assert list_card["remote_option"] == "unknown"
    assert "remote_option" not in match_card
    assert raw["paid"] == "yes"
    assert raw["deadline"] == "2026-12-01"
    assert raw["application"]["application_url"] == "https://example.edu/ada"


def test_faculty_contact_does_not_match_rolling_saved_search_even_with_legacy_stamp():
    filters = {
        "paid": "",
        "intl": "",
        "source": "",
        "onCampus": "",
        "deadline": "rolling",
        "minScore": 0,
    }
    assert match_filter(_legacy_faculty(), filters) is False


def test_public_opportunity_counts_separate_faculty_contacts(monkeypatch):
    faculty = _legacy_faculty(
        source="uiuc_faculty",
        metadata={"is_active": True},
    )
    listing = {
        **_legacy_faculty(
            id="listing-active",
            source="uiuc_program",
            source_type="campus_program",
            metadata={"is_active": True},
        ),
    }
    inactive_listing = {
        **listing,
        "id": "listing-inactive",
        "metadata": {"is_active": False},
    }
    monkeypatch.setattr(
        opportunity_routes,
        "load_opportunities",
        lambda: [faculty, listing, inactive_listing],
    )
    opportunity_routes._stats_cache = None
    opportunity_routes._stats_cache_time = 0

    coverage = asyncio.run(opportunity_routes.opportunity_coverage())
    assert coverage["counts"] == {"uiuc": 1}
    assert coverage["faculty_contacts"] == {"uiuc": 1}

    stats = asyncio.run(opportunity_routes.get_stats())
    # `total` is the user-facing discovery count — what a student could act on
    # today — so inactive, closed and reference-only records are excluded. It
    # previously counted the deactivated listing too, which advertised stock
    # nobody could apply to. Historical inventory, if Admin ever needs it,
    # belongs in a separately named field, never folded back into this one.
    assert stats["total"] == 1
    assert stats["active"] == 1
    assert stats["faculty_contact_total"] == 1
    opportunity_routes._stats_cache = None
    opportunity_routes._stats_cache_time = 0


def test_citizenship_restriction_note_survives_a_second_projection():
    """The loader canonicalizes the restriction and drops the raw excerpt; the
    route projection then runs again on that record. Reading the excerpt with
    no fallback stringified ``None`` over the preserved note, so the one fact
    this branch exists to keep — why the record is US-only — was replaced by
    the literal text "None"."""
    excerpt = "U.S. citizenship is required for this project."
    record = _legacy_faculty(
        eligibility={
            "international_friendly": "yes",
            "eligibility_text_raw": excerpt,
        },
    )
    loaded = data_loader._sanitize_opportunity(deepcopy(record))
    assert loaded["eligibility"]["international_friendly"] == "no"
    assert loaded["eligibility"]["citizenship_required"] is True
    assert loaded["eligibility"]["work_auth_notes"] == excerpt
    assert "eligibility_text_raw" not in loaded["eligibility"]

    # Idempotent: the same record projected again keeps the same facts.
    projected = faculty_safe_public_record(loaded)
    assert projected["eligibility"]["international_friendly"] == "no"
    assert projected["eligibility"]["citizenship_required"] is True
    assert projected["eligibility"]["work_auth_notes"] == excerpt

    again = faculty_safe_public_record(projected)
    assert again["eligibility"]["work_auth_notes"] == excerpt

    # A present-but-empty legacy raw field must not erase a bounded note.
    with_empty_raw = deepcopy(projected)
    with_empty_raw["eligibility"]["eligibility_text_raw"] = ""
    assert (
        faculty_safe_public_record(with_empty_raw)["eligibility"]["work_auth_notes"]
        == excerpt
    )


def _skills_profile(skills):
    return {
        "major": "Biology",
        "grade": "Sophomore",
        "seeking_type": ["research"],
        "hard_skills": skills,
        "coursework": [],
        "experience_level": "none",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "molecular biology",
        "desired_fields": ["molecular biology"],
        "home_school": "testu",
    }


def _skills_opportunity(*, inferred: bool):
    opp = {
        "id": "sro-invented",
        "title": "Summer Molecular Sciences REU",
        "source_type": "program",
        "organization": "Test University",
        "opportunity_type": "summer_program",
        "eligibility": {"skills_required": ["Python", "MATLAB"]},
        "metadata": {},
    }
    if inferred:
        stamp_inferred(opp["metadata"], "eligibility.skills_required", "rule:llm_tagger")
    return opp


def test_a_requirement_we_invented_is_never_a_shortfall_told_to_the_student():
    """Production, found by a tester walking the free flow: a wet-lab biology
    REU whose own page lists only timing and a deadline showed "REQUIRED
    SKILLS / Python / MATLAB" and returned reasons_gap ["Missing skills:
    Python, MATLAB"]. 2,767 of the 6,349 records carrying required skills —
    43.6% — are stamped rule:llm_tagger, and nothing in the matcher had ever
    read that stamp.
    """
    profile = _skills_profile([])
    stated = rank_opportunity(profile, _skills_opportunity(inferred=False), precomputed_sim=0.5)
    assert any("Missing skills" in g for g in stated.reasons_gap)

    ours = rank_opportunity(profile, _skills_opportunity(inferred=True), precomputed_sim=0.5)
    assert not any("Missing skills" in g for g in ours.reasons_gap)


def test_an_invented_requirement_is_not_counted_as_one_in_a_fit_reason():
    # The positive half makes the same claim: "2/2 required" asserts the
    # program requires two things. The overlap itself is still worth saying.
    profile = _skills_profile([{"name": "Python", "level": "experienced"}])
    stated = rank_opportunity(profile, _skills_opportunity(inferred=False), precomputed_sim=0.5)
    assert any("required" in f for f in stated.reasons_fit)

    ours = rank_opportunity(profile, _skills_opportunity(inferred=True), precomputed_sim=0.5)
    assert any("Python" in f for f in ours.reasons_fit)
    assert not any("required" in f for f in ours.reasons_fit)


def test_the_score_still_uses_an_inferred_requirement():
    # Only the SENTENCES are withdrawn. The tagger's guess carries a real topic
    # signal, and dropping it from scoring would be a second, opposite error.
    profile = _skills_profile([{"name": "Python", "level": "experienced"}])
    with_skill = rank_opportunity(profile, _skills_opportunity(inferred=True), precomputed_sim=0.5)
    without = rank_opportunity(_skills_profile([]), _skills_opportunity(inferred=True),
                               precomputed_sim=0.5)
    assert with_skill.final_score > without.final_score
