"""Checklist M13: one set of course-status and interest rules for every student-voice consumer."""
from __future__ import annotations

import pytest

from backend.schemas import ProfileRequest
from src.student_evidence import (
    course_claim_violations,
    course_entries,
    course_sentences,
    courses_counted_as_taken,
    interest_experience_violations,
)

COURSES = [
    {"name": "CS 225", "status": "completed", "source": "manual"},
    {"name": "ECE 448", "status": "in_progress", "source": "resume"},
    {"name": "CS 446 Machine Learning", "status": "planned", "source": "resume",
     "evidence": "Planned coursework: CS 446 Machine Learning (Spring 2027)"},
    {"name": "MATH 241", "status": "unknown", "source": "resume"},
]


def entries():
    return course_entries(ProfileRequest(name="Sample Student", courses=COURSES).model_dump())


def test_courses_reach_every_consumer_with_their_status():
    """Declared, so a route's model_dump() keeps it (pydantic drops undeclared keys silently)."""
    dumped = ProfileRequest(name="Sample Student", courses=COURSES).model_dump()
    assert [(c["name"], c["status"]) for c in dumped["courses"]] == [(c["name"], c["status"]) for c in COURSES]


def test_legacy_coursework_is_unknown_and_courses_win_per_name():
    profile = ProfileRequest(name="S", coursework=["CS 225", "cs225", "STAT 400"],
                             courses=[{"name": "CS 225", "status": "planned"}]).model_dump()
    assert [(e["name"], e["status"]) for e in course_entries(profile)] == [("CS 225", "planned"), ("STAT 400", "unknown")]
    legacy = course_entries(ProfileRequest(name="S", coursework=["CS 225", "STAT 400"]).model_dump())
    assert {e["status"] for e in legacy} == {"unknown"}


def test_an_unrecognised_status_is_never_read_as_completed():
    profile = ProfileRequest(name="S", courses=[{"name": "CS 225", "status": "done", "source": "import"}]).model_dump()
    assert profile["courses"][0]["status"] == "unknown" and profile["courses"][0]["source"] == "resume"


@pytest.mark.parametrize("courses", ["CS 225", [3], [{"name": "x" * 1001}], [{"name": "CS 1", "status": 3}]])
def test_course_input_is_bounded_and_typed(courses):
    with pytest.raises(ValueError):
        ProfileRequest(name="S", courses=courses)


def test_each_status_is_stated_in_its_own_words():
    text = course_sentences(entries(), limit=4)
    assert text == ("I have completed CS 225. I am currently taking ECE 448. My coursework includes MATH 241. "
                    "I plan to take CS 446 Machine Learning.")
    assert course_claim_violations(text, entries()) == []


@pytest.mark.parametrize(("claim", "flagged"), [
    ("I completed CS 225 in 2025.", []),
    ("I have taken CS 225.", []),
    ("I am currently taking ECE 448.", []),
    ("My coursework includes MATH 241.", []),
    ("I plan to take CS 446.", []),
    ("I have not taken CS 446 yet.", []),
    ("I am taking CS 446 next semester.", []),
    ("I completed a project in CS 225.", []),
    ("I have completed CS 446.", ["CS 446 Machine Learning"]),
    ("I took CS 446 Machine Learning last year.", ["CS 446 Machine Learning"]),
    ("Courses I have taken include CS 225 and CS 446.", ["CS 446 Machine Learning"]),
    ("I built a classifier and completed CS 446.", ["CS 446 Machine Learning"]),
    ("Completed CS 446, building an EEG classifier.", ["CS 446 Machine Learning"]),
    ("I am currently taking CS 446.", ["CS 446 Machine Learning"]),
    ("I completed MATH 241.", ["MATH 241"]),
    ("After completing MATH 241, I built a solver.", ["MATH 241"]),
    ("I have completed ECE 448.", ["ECE 448"]),
    ("I completed CS 999.", ["CS 999"]),
    ("我修过 CS 446。", ["CS 446 Machine Learning"]),
    ("我正在修改 CS 225 的作业。", []),
])
def test_only_a_course_whose_status_allows_it_may_be_claimed_done_or_current(claim, flagged):
    assert course_claim_violations(claim, entries()) == [f"unsupported course status: {name}" for name in flagged]


def test_a_planned_course_does_not_count_as_taken_for_matching():
    assert courses_counted_as_taken({"courses": COURSES, "coursework": ["STAT 400"]}) == [
        "CS 225", "ECE 448", "MATH 241", "STAT 400"]
    assert courses_counted_as_taken({"coursework": ["CS 225", "CS 225 "]}) == ["CS 225", "CS 225"]


@pytest.mark.parametrize(("claim", "facts", "flagged"), [
    ("I have experience with neural signal analysis.", "Python", ["neural signal analysis"]),
    ("Built neural signal analysis tools in Python.", "Built Python tools.", ["neural signal analysis"]),
    ("I have experience with neural signal analysis.", "Built neural signal analysis tools.", []),
    ("I have experience with Python.", "Python", []),
])
def test_an_interest_is_never_stated_as_experience(claim, facts, flagged):
    assert interest_experience_violations(claim, "neural signal analysis, robotics", facts) == flagged
