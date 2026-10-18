"""M107: every match reason the ranker or the match routes write carries a
machine-readable key, and the English lines stay exactly as served before."""

from __future__ import annotations

import functools
import json
import pathlib

import pytest

import backend.routes.matches as m
from backend.lib.public_projection import redact_embedded_emails
from backend.schemas import MatchResultResponse
from src.matcher import reason_keys as rk
from src.matcher.ranker import (
    _NOT_ON_PAGE,
    _OUR_LISTING_AND_READING,
    _OUR_READING,
    _SIMPLIFY_NO_SPONSORSHIP_GAP,
    _SIMPLIFY_NO_SPONSORSHIP_REASON,
    MatchResult,
    rank_all,
)

_SHARDS = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed" / "shards"

# One sentence per template, as the ranker writes it, with its key and params.
TEMPLATE_SAMPLES: list[tuple[str, str, str, dict[str, str]]] = [
    ("fit", "Your class year (junior) may fit this program", "year_may_fit", {"year": "junior"}),
    ("fit", "Accepts junior students", "year_accepts", {"year": "junior"}),
    ("gap", "Add your class year to confirm year eligibility", "year_missing", {}),
    ("gap", "For undergraduates — not a graduate-level opening", "year_undergrad_only", {}),
    ("gap", f"Our listing suggests this is for undergraduates{_NOT_ON_PAGE}", "year_listing_undergrad", {}),
    ("gap", "Typically targets junior, senior", "year_targets", {"years": "junior, senior"}),
    ("gap", f"Our listing suggests junior, senior students{_NOT_ON_PAGE}", "year_listing_targets",
     {"years": "junior, senior"}),
    ("fit", "This faculty member's department aligns with your major", "major_department_aligns", {}),
    ("fit", "This faculty member's department is related to your major", "major_department_related", {}),
    ("fit", "Your major may fit this field", "major_field_may_fit", {}),
    ("fit", "Your major may be related to this field", "major_field_may_relate", {}),
    ("fit", f"Our listing says this is open to all majors{_NOT_ON_PAGE}", "major_all_listing", {}),
    ("fit", "Open to all majors", "major_all", {}),
    ("fit", "Your major (Biology) may fit this program", "major_may_fit", {"major": "Biology"}),
    ("fit", "Your major (Biology) may be related to this program", "major_may_relate", {"major": "Biology"}),
    ("fit", "Your major (Biology) is a direct match", "major_direct", {"major": "Biology"}),
    ("fit", "Your major (Biology) is closely related to requirements", "major_close", {"major": "Biology"}),
    ("gap", "Prefers Biology, Chemistry", "major_prefers", {"majors": "Biology, Chemistry"}),
    ("gap", f"Our listing suggests Biology, Chemistry majors{_NOT_ON_PAGE}", "major_listing",
     {"majors": "Biology, Chemistry"}),
    ("gap", _SIMPLIFY_NO_SPONSORSHIP_GAP, "intl_listing_no_sponsorship", {"label": "Does Not Offer Sponsorship"}),
    ("gap", f"Our listing says this requires US citizenship or permanent residency{_NOT_ON_PAGE}",
     "citizenship_listing", {}),
    ("gap", f"May require US citizenship or permanent residency{_OUR_READING}", "citizenship_read", {}),
    ("gap", f"May require US citizenship or permanent residency{_OUR_LISTING_AND_READING}",
     "citizenship_listing_and_read", {}),
    ("gap", _SIMPLIFY_NO_SPONSORSHIP_REASON, "citizenship_no_sponsorship", {}),
    ("gap", "Requires US citizenship or permanent residency", "citizenship_required", {}),
    ("gap", "International eligibility unclear — many internships qualify for CPT/OPT; confirm with the employer",
     "intl_unclear_internship", {}),
    ("gap", "International eligibility is not stated — confirm when contacting the faculty member",
     "intl_unstated_faculty", {}),
    ("gap", "International eligibility unclear — verify before applying", "intl_unclear", {}),
    ("fit", f"Our listing says this is open to international students{_NOT_ON_PAGE}", "intl_open_listing", {}),
    ("fit", f"Open to international students{_OUR_READING}", "intl_open_read", {}),
    ("fit", "Open to international students", "intl_open", {}),
    ("fit", "Strong tech stack fit: Python (expert), SQL (experienced) — 2/3 required", "skills_fit_required",
     {"level": "strong", "skills": "Python (expert), SQL (experienced)", "matched": "2", "required": "3"}),
    ("fit", "Partial skill match: Python", "skills_fit", {"level": "partial", "skills": "Python"}),
    ("fit", "Tech stack overlap: Python, R", "skills_fit", {"level": "overlap", "skills": "Python, R"}),
    ("gap", "Missing skills: MATLAB, Stata", "skills_missing", {"skills": "MATLAB, Stata"}),
    ("fit", "Skills mentioned in the description: Python", "skills_mentioned", {"skills": "Python"}),
    ("fit", "Preferred skill overlap: R", "skills_preferred", {"skills": "R"}),
    ("fit", "Matches your interest in summer program", "type_match", {"type": "summer program"}),
    ("gap", "This is a internship — not your primary target type", "type_mismatch", {"type": "internship"}),
    ("gap", "Resume required — prepare one before applying", "resume_required", {}),
    ("fit", "Your experience can support a thoughtful faculty outreach", "experience_faculty", {}),
    ("fit", "Your experience level is competitive", "experience_competitive", {}),
    ("gap", "Your experience signal is limited — ask what preparation would help", "experience_limited_faculty", {}),
    ("gap", "Limited prior experience — position may be competitive", "experience_limited", {}),
    ("fit", "You're comfortable with direct outreach", "outreach_comfortable", {}),
    ("fit", "Low application effort — quick to apply", "effort_low", {}),
    ("gap", "High application effort — plan time for materials", "effort_high", {}),
    ("fit", "Paid opportunity", "paid", {}),
    ("fit", "Includes stipend", "stipend", {}),
    ("fit", "Explicitly welcomes first-time researchers", "first_time_welcome", {}),
    ("fit", "At your university", "at_your_university", {}),
    ("fit", "Faculty profile from a major research university", "brand_faculty_university", {}),
    ("fit", "Major research university — strong resume builder", "brand_university", {}),
    ("fit", "Faculty profile from a recognized research institution", "brand_faculty_institution", {}),
    ("fit", "Prestigious institution — strong resume builder", "brand_institution", {}),
    ("fit", "Potential for publication or long-term involvement", "publication_pathway", {}),
    ("fit", "Matches your interests: genomics, machine learning", "interests_match",
     {"terms": "genomics, machine learning"}),
    ("fit", "Your interest in genomics closely matches Prof. Ada Lovelace's work on genomics, proteomics",
     "interest_lab_work", {"interest": "genomics", "lab": "Prof. Ada Lovelace", "work": "genomics, proteomics"}),
    ("fit", "Prof. Ada Lovelace also works on genomics, proteomics", "lab_also_works",
     {"lab": "Prof. Ada Lovelace", "work": "genomics, proteomics"}),
    ("fit", "Your interest in genomics closely matches their work on genomics", "interest_their_work",
     {"interest": "genomics", "work": "genomics"}),
    ("fit", "They also work on genomics", "they_also_work", {"work": "genomics"}),
    ("fit", "Your research interests align with Prof. Ada Lovelace's focus area", "interests_lab_focus",
     {"lab": "Prof. Ada Lovelace"}),
    ("gap", "Research area looks different from your stated interests", "topic_mismatch", {}),
    ("gap", "Deadline has passed — verify if still accepting applications", "deadline_passed", {}),
    ("fit", "Deadline in 3 days — apply soon", "deadline_soon", {"days": "3"}),
    ("gap", "This program's start date has passed — check whether a new cycle is open", "start_passed", {}),
    ("gap", "Targets graduate / PhD students — a reach for undergraduates", "grad_level_reach", {}),
    ("fit", "Summer research — in season; applications are typically active now", "summer_in_season", {}),
    ("gap", "Faculty availability and eligibility are not confirmed — verify when you contact them",
     "faculty_unconfirmed", {}),
    ("fit", "This lab focuses on Genomics Lab — sequencing", "lab_focus", {"summary": "Genomics Lab — sequencing"}),
]

_RESEARCH_SUMMARY_RECORD = {
    "id": "m107-summary",
    "pi_name": "Ada Lovelace",
    "lab_or_program": "Lovelace Lab",
    "department": "Biology",
    "opportunity_type": "research",
    "description_raw": "We study protein folding.",
}


def _known_keys() -> set[str]:
    keys = {key for key, _ in rk._FIT_EXACT.values()} | {key for key, _ in rk._GAP_EXACT.values()}
    keys |= {key for key, _ in rk._FIT_PATTERNS} | {key for key, _ in rk._GAP_PATTERNS}
    return keys | {"research_summary"}


@pytest.mark.parametrize(("kind", "sentence", "key", "params"), TEMPLATE_SAMPLES)
def test_every_template_sentence_is_keyed(kind, sentence, key, params):
    assert rk.reason_key(sentence, kind) == {"key": key, "params": params}


def test_the_samples_walk_every_template():
    walked = {key for _, _, key, _ in TEMPLATE_SAMPLES} | {"research_summary"}
    assert walked == _known_keys()


def test_research_summary_headline_is_keyed_as_the_records_own_text():
    summary = rk._summarize_research(_RESEARCH_SUMMARY_RECORD)
    assert summary
    keys = rk.reason_keys([summary, "Paid opportunity"], "fit", record=_RESEARCH_SUMMARY_RECORD)
    assert keys == [{"key": "research_summary", "params": {"text": summary}}, {"key": "paid", "params": {}}]
    assert rk.reason_keys([summary], "fit") == [None]


def test_a_sentence_no_template_wrote_has_no_key():
    assert rk.reason_key("Focuses on GPU systems, not medical imaging", "gap") is None
    # A fit template is not read on the gap side, nor the reverse.
    assert rk.reason_key("Paid opportunity", "gap") is None
    assert rk.reason_key("Prefers Biology", "fit") is None
    assert rk.reason_key("", "fit") is None


def test_model_written_gap_line_stays_unkeyed_whatever_it_looks_like():
    model = "Prefers students with wet-lab experience"
    keys = rk.reason_keys(["Prefers Biology", model], "gap", model_reason=model)
    assert keys == [{"key": "major_prefers", "params": {"majors": "Biology"}}, None]


@pytest.mark.parametrize("code", sorted(m._EXCLUSION_GAP_TEXT) + ["something_new"])
def test_exclusion_lines_are_keyed(code):
    line = m._exclusion_gap_text(code, {})
    expected = "excluded_other" if code == "something_new" else f"excluded_{code}"
    assert m._exclusion_gap_key(line) == {"key": expected, "params": {}}


@pytest.mark.parametrize(
    ("restriction", "inner"),
    [
        ("Requires US citizenship or permanent residency", "citizenship_required"),
        (_SIMPLIFY_NO_SPONSORSHIP_REASON, "citizenship_no_sponsorship"),
        (f"Our listing says this requires US citizenship or permanent residency{_NOT_ON_PAGE}",
         "citizenship_listing"),
        (f"May require US citizenship or permanent residency{_OUR_READING}", "citizenship_read"),
        (f"May require US citizenship or permanent residency{_OUR_LISTING_AND_READING}",
         "citizenship_listing_and_read"),
    ],
)
def test_citizenship_exclusion_line_carries_its_restrictions_key(monkeypatch, restriction, inner):
    monkeypatch.setattr(m, "citizenship_restriction_reason", lambda _opp: restriction)
    line = m._exclusion_gap_text("citizenship_restricted", {})
    assert m._exclusion_gap_key(line) == {"key": "excluded_restriction", "params": {"restriction": inner}}
    assert m._exclusion_gap_key("Prefers Biology") is None


# Twelve profiles across schools: domestic and international, with and
# without courses and skills, faculty-contact and listing seekers.
PROFILES: list[dict] = [
    {"year": "junior", "major": "Computer Science", "home_school": "uiuc", "international_student": True,
     "hard_skills": [{"name": "Python", "level": "expert"}, {"name": "SQL", "level": "experienced"}],
     "coursework": ["CS 225", "CS 374"], "desired_fields": ["machine learning"],
     "research_interests_text": "machine learning for health", "experience_level": "some",
     "seeking_type": ["research", "internship"], "can_cold_email": True},
    {"year": "freshman", "major": "Biology", "home_school": "duke", "international_student": False,
     "hard_skills": [], "coursework": [], "desired_fields": ["genomics"], "experience_level": "none",
     "seeking_type": ["research", "summer_program"]},
    {"year": "sophomore", "major": "Chemistry", "home_school": "caltech", "international_student": True,
     "hard_skills": ["Python"], "coursework": [], "desired_fields": [], "experience_level": "beginner",
     "seeking_type": ["summer_program", "fellowship"], "resume_ready": True},
    {"year": "senior", "major": "Economics", "home_school": "umich", "international_student": False,
     "hard_skills": ["Stata", "R"], "coursework": [{"name": "ECON 401", "status": "completed"}],
     "desired_fields": ["public policy"], "research_interests_text": "labor economics and inequality",
     "experience_level": "strong", "seeking_type": ["research", "internship", "fellowship"]},
    {"year": "", "major": "", "home_school": "uiuc", "international_student": True,
     "hard_skills": [], "coursework": [], "experience_level": "none"},
    {"year": "PhD", "major": "Electrical Engineering", "home_school": "jhu", "international_student": True,
     "hard_skills": ["MATLAB", "C++"], "coursework": [], "desired_fields": ["robotics"],
     "experience_level": "strong", "seeking_type": ["research"]},
    {"year": "junior", "major": "Psychology", "home_school": "duke", "international_student": False,
     "hard_skills": ["SPSS"], "coursework": ["PSY 101"], "desired_fields": ["neuroscience"],
     "research_interests_text": "memory and sleep", "experience_level": "some", "exploring": True,
     "seeking_type": ["research", "summer_program"], "can_cold_email": True},
    {"year": "sophomore", "major": "Mechanical Engineering", "home_school": "umich", "international_student": True,
     "hard_skills": ["SolidWorks", "Python"], "coursework": [], "desired_fields": ["energy"],
     "experience_level": "beginner", "seeking_type": ["internship"], "resume_ready": False},
    {"year": "senior", "major": "History", "home_school": "jhu", "international_student": False,
     "hard_skills": [], "coursework": ["HIST 200"], "desired_fields": ["archives"],
     "experience_level": "none", "seeking_type": ["fellowship", "summer_program"]},
    {"year": "freshman", "major": "Data Science", "home_school": "caltech", "international_student": False,
     "hard_skills": ["Python", "SQL", "Tableau"], "coursework": [], "desired_fields": ["data science", "climate"],
     "experience_level": "some", "seeking_type": ["internship", "research"], "secondary_interests": ["Statistics"]},
    {"year": "junior", "major": "Mathematics", "home_school": "uiuc", "international_student": False,
     "hard_skills": [], "coursework": ["MATH 415"], "desired_fields": [],
     "research_interests_text": "number theory and cryptography", "experience_level": "beginner"},
    {"year": "Masters", "major": "Public Health", "home_school": "duke", "international_student": True,
     "hard_skills": ["R"], "coursework": [], "desired_fields": ["epidemiology"],
     "experience_level": "some", "seeking_type": ["research", "fellowship"], "can_cold_email": True},
]

_SAMPLE_SHARDS = ("national", "uiuc", "duke", "caltech", "umich", "jhu")


@functools.lru_cache(maxsize=1)
def _sample_records() -> tuple[dict, ...]:
    records: list[dict] = []
    for name in _SAMPLE_SHARDS:
        path = _SHARDS / f"{name}.json"
        if not path.exists():
            pytest.skip("corpus shards not present")
        rows = json.loads(path.read_text())
        records.extend(rows[:: max(1, len(rows) // 700)])
    return tuple(records)


def _rank(profile: dict) -> list[MatchResult]:
    profile = {
        **profile,
        "preferences": {"min_match_threshold": 0, "exclude_citizenship_restricted": False},
    }
    return rank_all(profile, list(_sample_records()))


@pytest.mark.parametrize("profile_index", range(len(PROFILES)))
def test_served_reasons_are_unchanged_and_every_one_is_keyed(profile_index):
    records = {record["id"]: record for record in _sample_records()}
    results = _rank(PROFILES[profile_index])
    assert results
    differences = unkeyed = 0
    for result in results:
        record = records[result.opportunity_id]
        card = m._match_card(record)
        rows = {result.opportunity_id: m._view_row_from_card(card, record)}
        served = m._match_result_response(result, {result.opportunity_id: card}, rows)
        # The English lines are what the response served before the keys.
        differences += served.reasons_fit != redact_embedded_emails(result.reasons_fit)
        differences += served.reasons_gap != redact_embedded_emails(result.reasons_gap)
        assert len(served.reasons_fit_keys) == len(served.reasons_fit)
        assert len(served.reasons_gap_keys) == len(served.reasons_gap)
        unkeyed += sum(key is None for key in served.reasons_fit_keys + served.reasons_gap_keys)
    assert differences == 0
    assert unkeyed == 0


def test_response_without_keys_still_validates():
    """An older backend's payload (no key fields) is still a valid response."""
    response = MatchResultResponse(
        opportunity_id="x", eligibility_score=1, readiness_score=1, upside_score=1, final_score=1,
        bucket="reach", reasons_fit=["Paid opportunity"], reasons_gap=[], next_steps=[], opportunity={},
    )
    assert response.reasons_fit_keys is None and response.reasons_gap_keys is None


def test_model_gap_line_from_the_rerank_is_served_unkeyed():
    result = MatchResult(
        opportunity_id="m107", eligibility_score=1, readiness_score=1, upside_score=1, final_score=1,
        bucket="reach", reasons_fit=[], reasons_gap=["Prefers Biology"], next_steps=[],
    )
    model = "Prefers students with wet-lab experience"
    result.reasons_gap.append(model)
    result.ai_gap_reason = model
    served = m._match_result_response(result, {"m107": {}})
    assert served.reasons_gap == ["Prefers Biology", model]
    assert [key and key.key for key in served.reasons_gap_keys] == ["major_prefers", None]
