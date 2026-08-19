"""Tests for the rule-based auto-tagger wired into refresh_all.

The free rule-based pass fills "unknown" paid / international_friendly / skill /
year fields from text heuristics so the matcher has more signal (esp.
international_friendly, the F-1 lever). The LLM pass stays a manual opt-in.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.parsers.llm_tagger import apply_updates, needs_tagging, rule_based_tag


def _opp(**over):
    base = {
        "paid": "unknown",
        "title": "Research Assistant",
        "description_raw": "",
        "description_clean": "",
        "keywords": [],
        "eligibility": {
            "international_friendly": "unknown",
            "skills_required": [],
            "skills_preferred": [],
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
        },
    }
    for k, v in over.items():
        if k == "eligibility":
            base["eligibility"].update(v)
        else:
            base[k] = v
    return base


def test_needs_tagging_flags_unknowns():
    assert needs_tagging(_opp())
    full = _opp(
        paid="yes",
        eligibility={
            "international_friendly": "yes",
            "skills_required": ["Python"],
            "preferred_year": ["junior"],
        },
    )
    assert not needs_tagging(full)


def test_rule_based_fills_unknown_paid():
    opp = _opp(description_clean="A paid summer research position with a $5000 stipend.")
    assert apply_updates(opp, rule_based_tag(opp))
    assert opp["paid"] == "yes"


def test_rule_based_fills_skills_from_domain():
    opp = _opp(description_clean="Machine learning and computer vision research using deep learning.")
    apply_updates(opp, rule_based_tag(opp))
    skills = opp["eligibility"]["skills_required"] + opp["eligibility"]["skills_preferred"]
    assert "Python" in skills


def test_rule_based_reconciles_citizenship_when_intl_resolved():
    # When intl resolves to "no", citizenship_required is set True in lockstep —
    # so the refresh's intl-reconciliation observability metric stays at 0.
    opp = _opp(description_clean="Applicants must be U.S. citizens or permanent residents.")
    apply_updates(opp, rule_based_tag(opp))
    if opp["eligibility"]["international_friendly"] == "no":
        assert opp["eligibility"].get("citizenship_required") is True


def test_rule_based_gates_context_less_single_letter_skills():
    # Domain inference (biology → R) and the bare-\bR\b pattern (middle
    # initials, stray tokens) must not emit "R"/"C" unless the enricher's
    # context patterns ("R programming") also fire — the corpus DQ gate
    # (test_single_letter_skills_only_with_context) holds records to exactly
    # that standard, so an ungated tagger re-poisons the corpus every refresh.
    opp = _opp(description_clean="Ecology and evolution research led by John R. Smith.")
    apply_updates(opp, rule_based_tag(opp))
    skills = opp["eligibility"]["skills_required"] + opp["eligibility"]["skills_preferred"]
    assert "R" not in skills
    assert "Python" in skills


def test_faculty_profiles_are_not_opening_tag_candidates():
    # Biography/title prose cannot prove pay, eligibility, or application
    # requirements.  These phrases used to create false paid and US-only facts.
    opp = _opp(
        source_type="faculty_research",
        title="Scholarship of Teaching and Learning",
        description_clean=(
            "Senior Lecturer studying U.S. national security. Volunteer work "
            "uses Python and machine learning."
        ),
    )
    assert not needs_tagging(opp)
    assert rule_based_tag(opp) == {}
    assert not apply_updates(
        opp,
        {
            "paid": "yes",
            "international_friendly": "no",
            "citizenship_required": True,
            "skills_required": ["Python"],
            "skills_preferred": ["Machine Learning"],
            "preferred_year": ["senior"],
        },
        method="llm:llm_tagger",
    )
    assert opp["paid"] == "unknown"
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert "citizenship_required" not in opp["eligibility"]
    assert opp["eligibility"]["skills_required"] == []
    assert opp["eligibility"]["skills_preferred"] == []
    assert opp["eligibility"]["preferred_year"] == ["freshman", "sophomore", "junior", "senior"]
    assert opp.get("metadata") is None


def test_non_faculty_postings_still_infer_preferred_year():
    # The carve-out is faculty-only: a real posting that names a class year
    # must still narrow, or the F-1/year matching signal goes inert.
    opp = _opp(
        source_type="campus_program",
        description_clean="This program is open to seniors in their fourth year only.",
    )
    apply_updates(opp, rule_based_tag(opp))
    assert opp["eligibility"]["preferred_year"] == ["senior"]


def test_rule_based_keeps_single_letter_skills_with_context():
    # No "research"/"review"/"resume" anywhere (the enricher blocklists R on
    # those tokens) + an explicit "R programming" context → R survives the gate.
    opp = _opp(title="Data Analyst",
               description_clean="Statistical modeling using R programming for field data.")
    apply_updates(opp, rule_based_tag(opp))
    skills = opp["eligibility"]["skills_required"] + opp["eligibility"]["skills_preferred"]
    assert "R" in skills
