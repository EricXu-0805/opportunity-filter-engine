"""Checklist M13: one set of course-status and interest rules for every student-voice consumer."""
from __future__ import annotations

import time

import pytest

from backend.schemas import ProfileRequest
from src.student_evidence import (
    COURSE_STATUSES,
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
    ("我修过 CS 446。", ["CS 446 Machine Learning"]),
    ("我正在修改 CS 225 的作业。", []),
])
def test_only_a_course_whose_status_allows_it_may_be_claimed_done_or_current(claim, flagged):
    assert course_claim_violations(claim, entries()) == [f"unsupported course status: {name}" for name in flagged]


@pytest.mark.parametrize("claim", [
    "I completed CS 999.",
    "I have completed COVID-19 lab safety training.",
    "I have completed OSHA 10 safety training.",
    "I passed IEEE 754 compliance testing.",
    "Completed SAT 1550 and ACT 34 test prep.",
])
def test_only_courses_the_student_listed_are_checked(claim):
    """Text naming a course code or title the student never listed is not a course claim (fix round 3)."""
    assert course_claim_violations(claim, entries()) == []
    # An unlisted code beside a listed course does not hide the listed one.
    assert course_claim_violations("I completed CS 999 and CS 446.", entries()) == [
        "unsupported course status: CS 446 Machine Learning"]


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
    # A time phrase never makes a completion future: these falls are past.
    "I completed CS 446 in the fall.",
    "In the fall, I took CS 446.",
    # Nor is a "would" or "once" outside the claim's own verb phrase.
    "I would love to join your lab and have completed CS 446.",
    "I would like to mention that I have completed CS 446.",
    "Because I would like to contribute, I took CS 446.",
    "I would love to contribute, having completed CS 446.",
    "Once I joined UIUC, I took CS 446.",
    "I once took CS 446.",
    # "Not only" negates nothing.
    "I have not only completed CS 446 but also built a classifier.",
    # Nor does "yet" as a conjunction, and "I'd" alone is "I had".
    "I am only a sophomore, yet I have already completed CS 446.",
    "I'd completed CS 446 before joining.",
    # A title with its code in parentheses is the course its code names.
    "I have completed Machine Learning (CS 446).",
    "I have completed Data Structures (CS 225) and Machine Learning (CS 446).",
    # Someone who is the student.
    "As someone who has completed CS 446, I can help.",
])
def test_an_exemption_applies_only_to_the_claims_own_verb_phrase(claim):
    assert course_claim_violations(claim, PLANNED) == ["unsupported course status: CS 446"]


@pytest.mark.parametrize(("claim", "courses"), [
    ("I have completed Machine Learning.", TITLED),
    ("I have completed Data Structures and Machine Learning.", TITLED),
    # A code is the course in any case, as typed in the list or in the text.
    ("I have completed cs 446.", TITLED),
    ("I have completed CS 446.", [{"name": "cs 446", "status": "planned"}]),
])
def test_a_listed_course_is_found_by_its_code_or_its_title(claim, courses):
    assert course_claim_violations(claim, courses) == [f"unsupported course status: {courses[0]['name']}"]


@pytest.mark.parametrize(("claim", "courses"), [
    ("I have completed data structures and machine learning.", TITLED),
    ("I completed a machine learning project.", [{"name": "Machine Learning", "status": "unknown"}]),
])
def test_a_title_names_the_course_only_as_the_list_capitalises_it(claim, courses):
    """Lower-case, "machine learning" is the topic, not the listed course (fix round 3)."""
    assert course_claim_violations(claim, courses) == []


# Fix round 4 (review of a678cc04): a legacy list, every course unknown.
LEGACY_TITLES = [{"name": name, "status": "unknown"}
                 for name in ["CS 225", "Machine Learning", "Data Structures", "Computer Vision"]]


@pytest.mark.parametrize(("claim", "flagged"), [
    ("I have completed coursework in machine learning and data structures.", ["Data Structures", "Machine Learning"]),
    ("I've taken courses in machine learning and data structures.", ["Data Structures", "Machine Learning"]),
    ("I have taken machine learning courses.", ["Machine Learning"]),
    ("I am currently taking a computer vision course.", ["Computer Vision"]),
    ("I have completed a machine learning course.", ["Machine Learning"]),
    ("I have completed a Machine Learning course.", ["Machine Learning"]),
    ("Completed coursework in machine learning.", ["Machine Learning"]),
])
def test_a_title_beside_a_course_noun_is_the_course_in_any_case(claim, flagged):
    assert course_claim_violations(claim, LEGACY_TITLES) == [f"unsupported course status: {name}" for name in flagged]


@pytest.mark.parametrize(("claim", "courses"), [
    ("I completed a Machine Learning project in Python.", LEGACY_TITLES),
    ("I took a Machine Learning approach to the problem.", LEGACY_TITLES),
    ("I completed a Machine Learning internship.", LEGACY_TITLES),
    ("I completed a machine learning project in Python.", LEGACY_TITLES),
    ("I completed a machine learning project.", [{"name": "machine learning", "status": "unknown"}]),
])
def test_after_a_or_an_a_title_is_the_course_only_before_a_course_noun(claim, courses):
    assert course_claim_violations(claim, courses) == []


# Fix round 5 (review of 17f05698): a course noun at the end of a list of listed
# titles names every title in it, "a" or "an" included; after a course noun,
# ", and" or ", but" starts a new clause.
@pytest.mark.parametrize(("claim", "flagged"), [
    ("I have taken both a Machine Learning and a Computer Vision course.", ["Computer Vision", "Machine Learning"]),
    ("I have taken a Machine Learning and Computer Vision course.", ["Computer Vision", "Machine Learning"]),
    ("I have completed machine learning and data structures courses.", ["Data Structures", "Machine Learning"]),
])
def test_a_course_noun_ending_a_list_names_every_listed_title_in_it(claim, flagged):
    assert course_claim_violations(claim, LEGACY_TITLES) == [f"unsupported course status: {name}" for name in flagged]


@pytest.mark.parametrize("claim", [
    "I have completed several courses, and machine learning became my main interest.",
    "I took a statistics class, and machine learning quickly became my favorite topic.",
    "I completed a Machine Learning and Data Structures project.",
])
def test_a_new_clause_or_a_list_ending_on_another_noun_names_no_course(claim):
    assert course_claim_violations(claim, LEGACY_TITLES) == []


@pytest.mark.parametrize(("claim", "flagged"), [
    ("I have completed several courses, and CS 225 was my favorite.", ["CS 225"]),
    ("I have completed several courses, and Machine Learning was my favorite.", ["Machine Learning"]),
])
def test_after_a_new_clause_a_code_or_a_title_as_written_still_names_the_course(claim, flagged):
    assert course_claim_violations(claim, LEGACY_TITLES) == [f"unsupported course status: {name}" for name in flagged]


@pytest.mark.parametrize(("claim", "courses"), [
    ("I have not taken CS 446 yet.", PLANNED),
    ("I am taking CS 446 next semester.", PLANNED),
    ("Next semester, I am taking CS 446.", PLANNED),
    # The time phrase after the courses, however it is introduced (fix round 3).
    ("I am taking CS 446 in the fall.", PLANNED),
    ("I am registered for CS 446 in the spring.", PLANNED),
    ("I am enrolled in CS 446 for next semester.", PLANNED),
    ("I am taking CS 446 Machine Learning in the fall semester.", TITLED),
    ("If I took CS 446, I would know more.", PLANNED),
    ("Once I have completed CS 446, I will apply.", PLANNED),
    ("I would have completed CS 446 by then.", PLANNED),
    ("I'll have completed CS 446 by May.", PLANNED),
    ("I'd have completed CS 446 by then.", PLANNED),
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


# Fix round 5 (review of 17f05698): the check runs on every draft and on the
# student's own draft at refine, so its time must not grow with how often a
# claim repeats or how many courses are listed. The review's two worst inputs at
# the request limits (a 5000-character body; 512 courses and 512 legacy
# coursework strings filling the profile): 10.5 s and 1.4 s on 17f05698, about
# 15-35 ms per call now.
TOPIC_WORDS = ["Advanced", "Topics", "in", "Applied", "Systems", "Theory", "Design", "Machine", "Learning", "Data"]


def full_profile_entries():
    names = ["Machine Learning", "CS 225", "Data Structures"] + [
        f"ZZ {100 + i} " + " ".join(f"{TOPIC_WORDS[(i * 3 + k) % 10]}{(i + k) % 7}" for k in range(14))
        for i in range(1021)]
    profile = ProfileRequest(name="S", coursework=names[512:], courses=[
        {"name": name, "status": COURSE_STATUSES[i % 4]} for i, name in enumerate(names[:512])])
    return course_entries(profile.model_dump())


def test_a_listed_name_of_more_than_24_words_and_numbers_is_not_read():
    def course(words):
        return [{"name": " ".join(f"Word{chr(97 + i % 26)}" for i in range(words)), "status": "planned"}]
    for words, flagged in ((24, True), (25, False)):
        claim = f"I have completed {course(words)[0]['name']}."
        assert bool(course_claim_violations(claim, course(words))) is flagged, words


def test_the_course_check_reads_each_course_list_on_its_own():
    claim = "I have completed CS 446."
    assert course_claim_violations(claim, [{"name": "CS 446", "status": "completed"}]) == []
    assert course_claim_violations(claim, [{"name": "CS 446", "status": "planned"}]) == [
        "unsupported course status: CS 446"]
    assert course_claim_violations(claim, [{"name": "CS 446", "status": "completed"}]) == []


def test_a_refine_request_of_nested_names_takes_bounded_time():
    # The slowest valid input found: 368 names nested inside each other. A
    # refine checks its draft up to five times against the same bullets and
    # the student's own subject and body. About 0.1 s for all five here; about
    # 1.5 s for each one before the 24-piece bound and the per-content cache.
    names = [("a " * i).strip() for i in range(1, 369)]
    listed = course_entries(ProfileRequest(name="S", courses=[
        {"name": name, "status": "planned"} for name in names]).model_dump())
    body = "I took " + ("A " * 2500)[:4990]
    bullets = ["I took " + ("A " * 250)[:490]] * 12
    began = time.perf_counter()
    for _ in range(5):
        course_claim_violations(body, listed, student_lines=bullets, student_draft=body[:2000] + " " + body)
    assert time.perf_counter() - began < 0.75


@pytest.mark.parametrize("unit", ["Completed coursework, ", "I took "])
def test_the_course_check_takes_about_the_same_time_at_the_request_limits(unit):
    text = (unit * (5000 // len(unit) + 1))[:5000]
    listed = full_profile_entries()
    assert len(listed) == 1024
    for checked in ({"text": text}, {"text": "Thank you.", "student_draft": text}):
        began = time.perf_counter()
        course_claim_violations(entries=listed, **checked)
        assert time.perf_counter() - began < 0.5
