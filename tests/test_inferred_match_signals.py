"""Inferred subject/skill labels are positive signals, not invented barriers."""
from copy import deepcopy

import pytest

from src.evidence import stamp_inferred
from src.matcher.ranker import score_eligibility


def profile(skills=(), major="Art History"):
    return {"year": "sophomore", "major": major, "hard_skills": list(skills),
            "international_student": False, "seeking_type": ["research"]}


def opportunity(**eligibility):
    return {"id": "terms-example", "source_type": "program", "opportunity_type": "research",
            "eligibility": {"majors": [], "skills_required": [], "skills_preferred": [], **eligibility},
            "metadata": {}}


def mark(record, field):
    stamp_inferred(record["metadata"], field, "rule:opportunity_terms")
    return record


def test_inferred_major_mismatch_has_no_score_penalty_or_false_preference():
    neutral = opportunity()
    derived = mark(opportunity(majors=["CS"]), "eligibility.majors")
    assert score_eligibility(profile(), derived)[0] == score_eligibility(profile(), neutral)[0]
    assert not any("Prefers" in text for text in score_eligibility(profile(), derived)[2])
    stated = opportunity(majors=["CS"])
    assert score_eligibility(profile(), stated)[0] < score_eligibility(profile(), neutral)[0]


def test_inferred_major_fit_is_useful_but_does_not_claim_requirement():
    derived = mark(opportunity(majors=["CS"]), "eligibility.majors")
    score, fit, _ = score_eligibility(profile(major="CS"), derived)
    assert score > score_eligibility(profile(major="CS"), opportunity())[0]
    assert any("may fit" in text for text in fit)
    assert not any("requirement" in text or "direct match" in text for text in fit)


def test_legacy_inferred_missing_skills_cannot_score_below_unknown_requirements():
    derived = mark(opportunity(skills_required=["Python", "MATLAB"]), "eligibility.skills_required")
    assert score_eligibility(profile(), derived)[0] == score_eligibility(profile(), opportunity())[0]
    skilled = profile([{"name": "Python", "level": "experienced"}])
    assert score_eligibility(skilled, derived)[0] > score_eligibility(profile(), derived)[0]
    assert not any("required" in text for text in score_eligibility(skilled, derived)[1])
    assert not any("Missing skills" in text for text in score_eligibility(profile(), derived)[2])


def test_recorded_mentions_help_matching_without_manufacturing_a_gap():
    mentioned = opportunity()
    mentioned["metadata"]["skill_mentions"] = ["Python"]
    mark(mentioned, "metadata.skill_mentions")
    assert score_eligibility(profile(), mentioned)[0] == score_eligibility(profile(), opportunity())[0]
    score, fit, gaps = score_eligibility(profile(["Python"]), mentioned)
    assert score > score_eligibility(profile(["Python"]), opportunity())[0]
    assert any("Python" in text and "mentioned" in text for text in fit)
    assert not any("required" in text or "Missing skills" in text for text in fit + gaps)


@pytest.mark.parametrize("value", ["Python", {"skill": "Python"}, ["Python", 1], ["Python"] * 513])
def test_malformed_mentions_are_ignored(value):
    mentioned = opportunity()
    mentioned["metadata"]["skill_mentions"] = value
    mark(mentioned, "metadata.skill_mentions")
    assert score_eligibility(profile(["Python"]), mentioned) == score_eligibility(profile(["Python"]), opportunity())


def test_unstamped_mentions_cannot_act_as_matching_provenance():
    mentioned = opportunity()
    mentioned["metadata"]["skill_mentions"] = ["Python"]
    assert score_eligibility(profile(["Python"]), mentioned) == score_eligibility(profile(["Python"]), opportunity())


def test_optional_match_does_not_hide_a_stated_required_skill_gap():
    stated = opportunity(skills_required=["MATLAB"], skills_preferred=["Python"])
    bare = opportunity(skills_required=["MATLAB"])
    skilled = profile(["Python"])
    assert score_eligibility(skilled, stated)[0] == score_eligibility(skilled, bare)[0]
    assert "Missing skills: MATLAB" in score_eligibility(skilled, stated)[2]


def test_explicit_preferred_skill_is_positive_only():
    preferred = opportunity(skills_preferred=["Python"])
    assert score_eligibility(profile(), preferred)[0] == score_eligibility(profile(), opportunity())[0]
    score, fit, gaps = score_eligibility(profile(["Python"]), preferred)
    assert score > score_eligibility(profile(["Python"]), opportunity())[0]
    assert any("Python" in text and "preferred" in text.lower() for text in fit)
    assert not any("required" in text or "Missing skills" in text for text in fit + gaps)


def test_ranking_does_not_mutate_signal_record():
    mentioned = mark(opportunity(), "metadata.skill_mentions")
    mentioned["metadata"]["skill_mentions"] = ["Python"]
    before = deepcopy(mentioned)
    score_eligibility(profile(["Python"]), mentioned)
    assert mentioned == before


@pytest.mark.parametrize("value", ["Python", {"skill": "Python"}, ["Python", 1], ["Python"] * 513])
@pytest.mark.parametrize("inferred", [False, True])
def test_malformed_required_skills_do_not_crash_or_invent_gaps(value, inferred):
    row = opportunity(skills_required=value)
    if inferred:
        mark(row, "eligibility.skills_required")
    assert score_eligibility(profile(["Python"]), row) == score_eligibility(profile(["Python"]), opportunity())
