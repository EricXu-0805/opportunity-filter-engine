"""M107: every match reason the ranker or the match routes write carries a
machine-readable key, and the English lines stay exactly as served before."""

from __future__ import annotations

import functools
import gc
import json
import pathlib
import re
import time

import pytest

import backend.routes.matches as m
from backend.lib.public_projection import redact_embedded_emails
from backend.schemas import PROFILE_LIST_LIMITS, PROFILE_TEXT_LIMITS, MatchResultResponse
from src.matcher import reason_keys as rk
from src.matcher.ranker import (
    _NOT_ON_PAGE,
    _OUR_LISTING_AND_READING,
    _OUR_READING,
    _SIMPLIFY_NO_SPONSORSHIP_GAP,
    _SIMPLIFY_NO_SPONSORSHIP_REASON,
    MatchResult,
    rank_all,
    rank_opportunity,
)

_SHARDS = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed" / "shards"

# One served line per template, with the key and params served beside it.
# The frontend renders every case in zh (frontend/src/lib/match-reasons.test.ts).
_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "frontend/src/lib/__fixtures__/match-reason-keys.json"
)
_CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]

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


@pytest.mark.parametrize("case", _CASES, ids=[case["english"][:60] for case in _CASES])
def test_every_template_line_is_keyed_as_the_fixture_says(case):
    expected = {"key": case["key"], "params": case["params"]}
    if case["key"].startswith("excluded_"):
        assert m._exclusion_gap_key(case["english"]) == expected
    else:
        summary = case["english"] if case["key"] == "research_summary" else ""
        assert rk.reason_key(case["english"], case["kind"], research_summary=summary) == expected


def test_the_fixture_walks_every_template():
    exclusion_keys = {f"excluded_{code}" for code in m._EXCLUSION_GAP_TEXT}
    exclusion_keys |= {"excluded_other", "excluded_restriction"}
    assert {case["key"] for case in _CASES} == _known_keys() | exclusion_keys
    restrictions = {case["params"]["restriction"] for case in _CASES if case["key"] == "excluded_restriction"}
    assert restrictions == {key for key in _known_keys() if key.startswith("citizenship_")}


def test_the_fixture_lines_are_the_ones_the_code_writes():
    lines = {case["english"] for case in _CASES}
    assert set(m._EXCLUSION_GAP_TEXT.values()) <= lines
    for constant in (_SIMPLIFY_NO_SPONSORSHIP_GAP, _SIMPLIFY_NO_SPONSORSHIP_REASON):
        assert constant in lines
    assert any(_NOT_ON_PAGE in line for line in lines)
    assert any(_OUR_READING in line for line in lines)
    assert any(_OUR_LISTING_AND_READING in line for line in lines)
    summary = rk._summarize_research(_RESEARCH_SUMMARY_RECORD)
    assert {"kind": "fit", "english": summary, "key": "research_summary", "params": {"text": summary}} in _CASES


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


# --- Keying cost (review of M107) ---------------------------------------------
# A served line can echo profile text: one desired-field chip may be 60,000
# characters, and "Matches your interests: …" repeats it whole. The keyer runs
# on every served card inside the async routes, so no line may cost it more
# than a bounded, small time, whatever the line holds.
_LARGEST_FIELD = max(
    max(PROFILE_TEXT_LIMITS.values()), max(limit for _, limit in PROFILE_LIST_LIMITS.values()),
)
# Every literal piece of every template, so a parameter can hold the words
# the patterns split on ("also works on", "'s work on", " — 1/2 required").
_TEMPLATE_WORDS = sorted({
    piece.replace("\\", "")
    for _, pattern in rk._FIT_PATTERNS + rk._GAP_PATTERNS
    for piece in re.split(r"\(\?P<\w+>[^)]*\)", pattern.pattern)
    if piece.strip()
})
_PATTERN_CASES = [case for case in _CASES if case["key"] in {key for key, _ in rk._FIT_PATTERNS + rk._GAP_PATTERNS}]
# One keying is a few regex steps per character after the fix, well under a
# millisecond even at the length bound. 0.05 s leaves far more than 4x for a
# slow runner; before the fix a 60,000-character line took 0.4 s to minutes.
_PER_LINE_SECONDS = 0.05


def _text_params(case: dict) -> tuple[re.Match, list[str]]:
    """The case's line matched by its template, and the names of its text
    parameters (not a count, not the skill level code) in line order."""
    match = dict(rk._FIT_PATTERNS + rk._GAP_PATTERNS)[case["key"]].fullmatch(case["english"])
    names = [name for name, value in match.groupdict().items() if name != "level" and not value.isdigit()]
    return match, sorted(names, key=match.start)


def _with_text_params(case: dict, grow) -> tuple[str, dict[str, str]]:
    """The case's line and params with each text parameter replaced by ``grow(value)``."""
    match, names = _text_params(case)
    line, params = case["english"], dict(case["params"])
    for name in reversed(names):
        params[name] = grow(params[name])
        line = line[: match.start(name)] + params[name] + line[match.end(name):]
    return line, params


def _adversarial_lines(case: dict, size: int) -> list[str]:
    """The case's line with each text parameter grown to ``size`` characters:
    one template word or separator repeated, or every template word in turn,
    ending in a newline, a newline and a word, or neither. Each also cut off
    after its first parameter: a line that opens like the template but that
    no template wrote, which every pattern scans and rejects."""
    match, names = _text_params(case)
    runs = [*_TEMPLATE_WORDS, ", ", "".join(_TEMPLATE_WORDS), "\n".join(_TEMPLATE_WORDS)]
    lines = []
    for tail in ("", "\n", "\nx"):
        for run in runs:
            line, params = _with_text_params(
                case, lambda value, run=run, tail=tail: (value + run * (size // len(run) + 1))[: size - len(tail)] + tail,
            )
            lines.append(line)
            if names:
                lines.append(case["english"][: match.start(names[0])] + params[names[0]])
    return lines


def _slowest_keying(lines: list[str], kind: str) -> tuple[float, int]:
    """The longest time one line took to key, and that line's length, with the
    collector paused (as tests/test_student_course_status.py times): the bound
    is the keyer's own cost, not a collection of the corpus the suite holds."""
    gc.collect()
    gc.disable()
    try:
        slowest = (0.0, 0)
        for line in lines:
            began = time.perf_counter()
            rk.reason_key(line, kind)
            slowest = max(slowest, (time.perf_counter() - began, len(line)))
        return slowest
    finally:
        gc.enable()


@pytest.mark.parametrize("case", _PATTERN_CASES, ids=[case["key"] for case in _PATTERN_CASES])
def test_keying_an_adversarial_line_at_the_largest_field_size_is_quick(case):
    seconds, length = _slowest_keying(_adversarial_lines(case, _LARGEST_FIELD), case["kind"])
    assert seconds < _PER_LINE_SECONDS, (length, f"{seconds:.3f}s")


@pytest.mark.parametrize("case", _PATTERN_CASES, ids=[case["key"] for case in _PATTERN_CASES])
def test_keying_an_adversarial_line_at_the_length_bound_is_quick(case):
    """Just under the bound the patterns do run, so their own cost is bounded."""
    fixed = len(case["english"]) - sum(len(value) for value in case["params"].values())
    size = (rk.MAX_KEYED_REASON_CHARACTERS - fixed) // len(case["params"])
    lines = _adversarial_lines(case, size)
    assert max(map(len, lines)) <= rk.MAX_KEYED_REASON_CHARACTERS
    seconds, length = _slowest_keying(lines, case["kind"])
    assert seconds < _PER_LINE_SECONDS, (length, f"{seconds:.3f}s")


def test_a_parameter_holding_a_newline_is_keyed_by_its_own_template():
    for case in _PATTERN_CASES:
        line, params = _with_text_params(case, lambda value: f"{value}\nx")
        assert rk.reason_key(line, case["kind"]) == {"key": case["key"], "params": params}, line


def test_a_long_interest_chip_with_a_newline_is_keyed_quickly_or_shown_in_english():
    """The review's repro: the chip is echoed whole in "Matches your interests"."""
    record = {"id": "r1", "title": "ML lab", "opportunity_type": "research",
              "keywords": ["machine learning"], "description_clean": "We study machine learning.",
              "eligibility": {}}
    for repeats, keyed in ((100, True), (4000, False)):
        chip = "machine learning" + " also works on" * repeats + "\nx"
        profile = {"year": "junior", "major": "Computer Science", "desired_fields": [chip],
                   "seeking_type": ["research"], "experience_level": "some"}
        result = rank_opportunity(profile, record)
        line = f"Matches your interests: {chip}"
        assert line in result.reasons_fit
        keys = rk.reason_keys(result.reasons_fit, "fit", record=record)
        expected = {"key": "interests_match", "params": {"terms": chip}} if keyed else None
        assert keys[result.reasons_fit.index(line)] == expected
        seconds, _ = _slowest_keying(result.reasons_fit, "fit")
        assert seconds < _PER_LINE_SECONDS, f"{seconds:.3f}s"
