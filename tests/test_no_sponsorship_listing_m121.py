"""M121: a Simplify internship whose one restriction is its listing label
"Does Not Offer Sponsorship" stays in an international student's results, with
a gap line that quotes the label. Every other citizenship restriction is
excluded exactly as before.
"""
from __future__ import annotations

import pytest

from src.collectors.simplify_internships import normalize_listing as simplify_listing
from src.evidence import CONFIGURED_PROGRAM_METHOD
from src.matcher.config import ELIG_MAJOR_WEIGHT, INTL_UNKNOWN_INTERNSHIP_SCORE, MATCHER_VERSION
from src.matcher.ranker import _filter_context, hard_exclusion, rank_all, score_eligibility

LABEL_LINE = (
    'Listing says: "Does Not Offer Sponsorship" '
    "(our note: CPT/OPT may still apply for internships; check with the employer)"
)


def _listing(sponsorship: str = "Does Not Offer Sponsorship", ident: str = "d07dc6c0") -> dict:
    return simplify_listing({
        "id": ident, "company_name": "Veeva", "title": "Intern Software Engineer",
        "url": f"https://example.com/jobs/{ident}", "locations": ["Remote"], "terms": ["Summer 2026"],
        "category": "Software", "sponsorship": sponsorship,
    })


def _profile(international: bool) -> dict:
    return {
        "year": "sophomore", "major": "Computer Science", "international_student": international,
        "seeking_type": ["internship"], "hard_skills": ["Python"],
        "preferences": {"min_match_threshold": 0, "exclude_citizenship_restricted": True},
    }


def test_an_international_student_sees_the_listing_with_its_label():
    listing = _listing()
    assert hard_exclusion(listing, _filter_context(_profile(True))) is None
    [result] = rank_all(_profile(True), [listing])
    assert LABEL_LINE in result.reasons_gap
    # The label is no citizenship rule, and the card says only what it says.
    assert not any("citizenship" in gap.lower() for gap in result.reasons_gap)
    # A sentence and a score the hashed knobs cannot see.
    assert int(MATCHER_VERSION.split(".")[0]) >= 27


def test_the_label_costs_a_little_more_than_an_unstated_answer():
    # Below an internship that states nothing (the listing does say something
    # against the student), far above a stated citizenship rule.
    profile = _profile(True)
    profile["preferences"]["exclude_citizenship_restricted"] = False
    labelled = score_eligibility(profile, _listing())[0]
    unstated = score_eligibility(profile, _listing("Other"))[0]
    citizens_only = score_eligibility(profile, _listing("U.S. Citizenship is Required"))[0]
    intl_weight = (1.0 - ELIG_MAJOR_WEIGHT) * 0.25
    assert unstated - labelled == pytest.approx(intl_weight * (INTL_UNKNOWN_INTERNSHIP_SCORE - 60.0))
    assert labelled - citizens_only == pytest.approx(intl_weight * 60.0)


def test_a_domestic_students_result_does_not_read_the_label():
    profile = _profile(False)
    labelled = _listing()
    assert hard_exclusion(labelled, _filter_context(profile)) is None
    unlabelled = _listing()
    unlabelled["eligibility"].update(international_friendly="unknown", work_auth_notes="")
    assert score_eligibility(profile, labelled) == score_eligibility(profile, unlabelled)
    [result] = rank_all(profile, [labelled])
    assert not any("sponsorship" in gap.lower() for gap in result.reasons_gap)


def _citizens_only() -> dict:
    return _listing("U.S. Citizenship is Required")


def _label_and_read_citizenship() -> dict:
    listing = _listing()
    listing["eligibility"]["citizenship_required"] = True
    listing["metadata"]["inferred_fields"] = {"eligibility.citizenship_required": "rule:text_scan"}
    return listing


def _label_read_off_the_page() -> dict:
    listing = _listing()
    listing["metadata"]["inferred_fields"] = {"eligibility.international_friendly": "rule:text_scan"}
    return listing


def _label_configured() -> dict:
    listing = _listing()
    listing["metadata"]["inferred_fields"] = {"eligibility.international_friendly": CONFIGURED_PROGRAM_METHOD}
    return listing


def _sentence_on_another_source() -> dict:
    listing = _listing()
    listing["source"] = "handshake"
    return listing


def _sentence_without_the_label() -> dict:
    listing = _listing()
    listing["metadata"]["simplify_sponsorship"] = "Other"
    return listing


@pytest.mark.parametrize("build", [
    _citizens_only, _label_and_read_citizenship, _label_read_off_the_page, _label_configured,
    _sentence_on_another_source, _sentence_without_the_label,
])
def test_every_other_citizenship_restriction_stays_excluded(build):
    listing = build()
    assert hard_exclusion(listing, _filter_context(_profile(True))) == "citizenship_restricted"
    assert rank_all(_profile(True), [listing]) == []
    assert LABEL_LINE not in score_eligibility(_profile(True), listing)[2]


# The card's badge (M121 step 2). The listing says "Does Not Offer
# Sponsorship", not "US only": the card and favorites badge read one field the
# public projector sets with the ranker's own rule, for every student.
_OTHER_RESTRICTIONS = [
    _citizens_only, _label_and_read_citizenship, _label_read_off_the_page, _label_configured,
    _sentence_on_another_source, _sentence_without_the_label,
]


@pytest.mark.parametrize("international", [True, False])
def test_the_card_names_the_label_for_every_student(international):
    from backend.routes.matches import _match_card
    from backend.routes.opportunities import _list_card

    listing = _listing()
    [result] = rank_all(_profile(international), [listing])
    assert result.opportunity_id == listing["id"]
    assert _match_card(listing)["international_basis"] == "no_sponsorship"
    assert _list_card(listing)["international_basis"] == "no_sponsorship"


@pytest.mark.parametrize("build", _OTHER_RESTRICTIONS)
def test_a_card_whose_restriction_is_not_the_label_keeps_no_basis(build):
    from backend.routes.matches import _match_card
    from backend.routes.opportunities import _list_card

    listing = build()
    assert "international_basis" not in _match_card(listing)
    assert "international_basis" not in _list_card(listing)
