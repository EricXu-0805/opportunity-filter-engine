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
    mask_course_names,
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


# Fix round 1 (reviews of 8724591c). A planned CS 446 throughout.
PLANNED = [{"name": "CS 446", "status": "planned"}, {"name": "CS 225", "status": "completed"}]
TITLED = [{"name": "CS 446 Machine Learning", "status": "planned"},
          {"name": "CS 225 Data Structures", "status": "completed"}]


@pytest.mark.parametrize("claim", [
    # A future word elsewhere in the sentence is not the claim's own.
    "I have completed CS 446 and am available to start next semester.",
    "I took CS 446 and hope to join your lab in the fall.",
    "Having completed CS 446, I hope to join your lab next semester.",
    "I am currently taking CS 446 and will finish it next semester.",
    # Nor is a "would" or "once" outside the claim's own verb phrase.
    "I would love to join your lab and have completed CS 446.",
    "I would like to mention that I have completed CS 446.",
    "Because I would like to contribute, I took CS 446.",
    "I would love to contribute, having completed CS 446.",
    "Once I joined UIUC, I took CS 446.",
    "I once took CS 446.",
    # "Not only" negates nothing.
    "I have not only completed CS 446 but also built a classifier.",
    # A title with its code in parentheses is the course its code names.
    "I have completed Machine Learning (CS 446).",
    "I have completed Data Structures (CS 225) and Machine Learning (CS 446).",
    # Someone who is the student.
    "As someone who has completed CS 446, I can help.",
])
def test_an_exemption_applies_only_to_the_claims_own_verb_phrase(claim):
    assert course_claim_violations(claim, PLANNED) == ["unsupported course status: CS 446"]


@pytest.mark.parametrize("claim", [
    "I have completed Machine Learning.",
    "I have completed Data Structures and Machine Learning.",
    "I have completed data structures and machine learning.",
])
def test_a_listed_course_is_found_by_its_title(claim):
    assert course_claim_violations(claim, TITLED) == ["unsupported course status: CS 446 Machine Learning"]


@pytest.mark.parametrize(("claim", "courses"), [
    ("I have not taken CS 446 yet.", PLANNED),
    ("I am taking CS 446 next semester.", PLANNED),
    ("Next semester, I am taking CS 446.", PLANNED),
    ("If I took CS 446, I would know more.", PLANNED),
    ("Once I have completed CS 446, I will apply.", PLANNED),
    ("I would have completed CS 446 by then.", PLANNED),
    ("I have completed Data Structures (CS 225).", PLANNED),
    ("I have completed Data Structures.", TITLED),
    # "While taking" says the course was taken at some point: a completed one was.
    ("While taking CS 225, I built a Python parser.", PLANNED),
    ("While taking CS 225, I built a Python parser.", [{"name": "CS 225", "status": "in_progress"}]),
    # A requirement restated about other students claims nothing for this one.
    ("Your program asks for students who have completed CS 225, which I am currently taking.",
     [{"name": "CS 225", "status": "in_progress"}]),
])
def test_a_claim_the_courses_status_allows_or_that_claims_nothing_passes(claim, courses):
    assert course_claim_violations(claim, courses) == []


def test_while_taking_still_needs_a_course_that_was_taken():
    assert course_claim_violations("While taking CS 446, I built a classifier.", PLANNED) == [
        "unsupported course status: CS 446"]


def test_the_students_own_confirmed_line_repeated_verbatim_is_theirs():
    legacy = [{"name": "CS 225", "status": "unknown"}]
    line = "Completed CS 225 project: built a Python parser"
    text = f"One example of my experience:\n\n{line}."
    assert course_claim_violations(text, legacy) == ["unsupported course status: CS 225"]
    assert course_claim_violations(text, legacy, student_lines=[line]) == []
    # Only the line itself: the model's own claim beside it is still checked,
    # and a line that states no course exempts nothing.
    assert course_claim_violations(f"{text} I have completed CS 225.", legacy, student_lines=[line]) == [
        "unsupported course status: CS 225"]
    assert course_claim_violations("I have completed CS 225.", legacy, student_lines=["CS 225"]) == [
        "unsupported course status: CS 225"]


@pytest.mark.parametrize(("text", "masked"), [
    # A coursework listing may name any listed course, whatever its status.
    ("My coursework includes Machine Learning.", "My coursework includes  ."),
    # Elsewhere the name is ordinary words, judged by the competence check.
    ("I have experience with machine learning.", "I have experience with machine learning."),
    ("My coursework includes Machine Learning, so I have experience with machine learning.",
     "My coursework includes  , so I have experience with machine learning."),
])
def test_only_a_coursework_listing_hides_a_courses_name(text, masked):
    assert mask_course_names(text, [{"name": "Machine Learning", "status": "planned"}]) == masked
