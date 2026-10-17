"""Inferred subject/skill labels are positive signals, not invented barriers."""
from copy import deepcopy

import pytest

from src.evidence import stamp_inferred
from src.matcher.ranker import _filter_context, hard_exclusion, score_eligibility


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


def test_an_inferred_all_majors_list_stays_neutral():
    # A posted ["all"] is a full major fit, as a direct match is; one we
    # derived is nobody's answer and scores as no list does.
    stated = opportunity(majors=["all"])
    score, fit, _ = score_eligibility(profile(), stated)
    assert score == score_eligibility(profile(), opportunity(majors=["Art History"]))[0]
    assert "Open to all majors" in fit
    derived = mark(opportunity(majors=["all"]), "eligibility.majors")
    score, fit, _ = score_eligibility(profile(), derived)
    assert score == score_eligibility(profile(), opportunity())[0]
    assert not any("all majors" in text for text in fit)


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


def stated(**eligibility):
    """A row whose skill lists a person typed in from the posting."""
    return {**opportunity(**eligibility), "source": "manual"}


def test_optional_match_does_not_hide_a_stated_required_skill_gap():
    stated_row = stated(skills_required=["MATLAB"], skills_preferred=["Python"])
    bare = stated(skills_required=["MATLAB"])
    skilled = profile(["Python"])
    assert score_eligibility(skilled, stated_row)[0] == score_eligibility(skilled, bare)[0]
    assert "Missing skills: MATLAB" in score_eligibility(skilled, stated_row)[2]


def test_explicit_preferred_skill_is_positive_only():
    preferred = stated(skills_preferred=["Python"])
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


# M22: a skill list with no inference stamp is still ours outside hand-curated
# rows, by the rule the detail facts and the wire's skills_attribution use
# (backend.lib.opportunity_detail.skills_basis): NSF REU lists are a keyword
# bank run over the award abstract, campus program lists a scan of prose. A
# keyword bank put "Python, MATLAB" on Caltech's Amgen Scholars biology program.
@pytest.mark.parametrize("source", [None, "nsf_reu", "caltech_external_research"])
def test_an_unstamped_skill_list_outside_curated_rows_is_a_hint_not_a_requirement(source):
    row = opportunity(skills_required=["Python", "MATLAB"])
    row["source"] = source
    neutral = opportunity()
    neutral["source"] = source
    assert score_eligibility(profile(), row)[0] == score_eligibility(profile(), neutral)[0]
    assert not any("Missing skills" in text for text in score_eligibility(profile(), row)[2])
    skilled = profile([{"name": "Python", "level": "experienced"}])
    score, fit, gaps = score_eligibility(skilled, row)
    assert score > score_eligibility(profile(), row)[0]
    assert any("Python" in text for text in fit)
    assert not any("required" in text or "Missing skills" in text for text in fit + gaps)
    ctx = _filter_context(skilled)
    assert hard_exclusion(row, ctx) == hard_exclusion(neutral, ctx)


def test_an_unstamped_preferred_list_outside_curated_rows_is_not_called_preferred():
    row = opportunity(skills_preferred=["Python"])
    row["source"] = "nsf_reu"
    fit = score_eligibility(profile(["Python"]), row)[1]
    assert "Skills mentioned in the description: Python" in fit
    assert not any("Preferred" in text for text in fit)


def test_a_curated_skill_list_keeps_its_requirement_sentences_and_score():
    row = stated(skills_required=["Python", "MATLAB"], skills_preferred=["R"])
    neutral = stated()
    assert score_eligibility(profile(), row)[0] < score_eligibility(profile(), neutral)[0]
    assert "Missing skills: Python, MATLAB" in score_eligibility(profile(), row)[2]
    score, fit, gaps = score_eligibility(profile(["Python", "R"]), row)
    assert "Partial skill match: Python — 1/2 required" in fit
    assert "Missing skills: MATLAB" in gaps
    # An optional match cannot stand in for the stated requirement it misses.
    assert not any(text.startswith("Preferred skill overlap") for text in fit)
    # A stamp still wins on a curated row, as it always has.
    mark(row, "eligibility.skills_required")
    fit, gaps = score_eligibility(profile(["Python"]), row)[1:]
    assert "Partial skill match: Python" in fit
    assert not any("Missing skills" in text for text in gaps)
