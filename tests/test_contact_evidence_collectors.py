"""Atomic producer, carry/clear, and weak-merge contact evidence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from backend.lib.contact_visibility import (
    CONTACT_EVIDENCE_FIELDS,
    build_identity_bound_contact_evidence,
    verified_send_target,
)
from src.collectors.faculty_graph import _merge_faculty_fields
from src.collectors.ucb_common import (
    _mark_fetched_soup_observation,
    clear_contact_claim,
    fetch_soup,
    normalize_faculty,
    stamp_bound_directory_contact,
    unique_bound_container_contact,
)
from src.collectors.uiuc_faculty import _carry_forward_enrichment

NOW = datetime.now(UTC).replace(microsecond=0)
CONFIG = {
    "short": "TEST",
    "name": "Test Department",
    "source": "ucb_test_faculty",
    "majors": ["Computer Science"],
    "keywords": ["computer science"],
}
LISTING_URL = "https://directory.berkeley.edu/faculty"


def _marked_soup(
    *,
    requested_url: str = LISTING_URL,
    final_url: str = LISTING_URL,
    observed_at: datetime | str = NOW,
) -> BeautifulSoup:
    return _mark_fetched_soup_observation(
        BeautifulSoup("<div class='faculty'></div>", "html.parser"),
        requested_url=requested_url,
        final_url=final_url,
        observed_at=observed_at,
    )


def _bound_record(
    *,
    email: str = "ada@berkeley.edu",
    observed_at: datetime = NOW,
) -> dict:
    evidence = build_identity_bound_contact_evidence(
        email=email,
        email_source="bound_directory_card",
        contact_source_url=LISTING_URL,
        contact_verified_at=observed_at,
    )
    assert evidence is not None
    return {
        "id": "faculty-ada",
        "pi_name": "Ada Lovelace",
        "department": "Test Department",
        "keywords": ["computing"],
        "contact_email": email.casefold(),
        "metadata": {"other": "kept", **evidence},
    }


def test_evidence_builder_returns_one_canonical_five_field_bundle():
    evidence = build_identity_bound_contact_evidence(
        email=" ADA@BERKELEY.EDU ",
        email_source="bound_directory_card",
        contact_source_url=LISTING_URL,
        contact_verified_at=NOW,
    )
    assert evidence == {
        "identity_bound": True,
        "email_source": "bound_directory_card",
        "contact_verified_email": "ada@berkeley.edu",
        "contact_source_url": LISTING_URL,
        "contact_verified_at": NOW.isoformat(),
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://directory.berkeley.edu/faculty",
        "https://localhost/faculty",
        "https://faculty.local/person",
        "https://127.0.0.1/person",
        "https://127.1/person",
        "https://0177.0.0.1/person",
        "https://10.0.0.4/person",
        "https://8.8.8.8/person",
        "https://%31%32%37.0.0.1/person",
        "https://１２７.０.０.１/person",
        "https://ada@directory.berkeley.edu/person",
    ],
)
def test_evidence_builder_rejects_weak_or_nonpublic_source_urls(url):
    assert build_identity_bound_contact_evidence(
        email="ada@berkeley.edu",
        email_source="bound_directory_card",
        contact_source_url=url,
        contact_verified_at=NOW,
    ) is None


def test_evidence_builder_rejects_noncanonical_source_and_bad_observation_time():
    assert build_identity_bound_contact_evidence(
        email="ada@berkeley.edu",
        email_source="BOUND_DIRECTORY_CARD",
        contact_source_url=LISTING_URL,
        contact_verified_at=NOW,
    ) is None
    assert build_identity_bound_contact_evidence(
        email="ada@berkeley.edu",
        email_source="bound_directory_card",
        contact_source_url=LISTING_URL,
        contact_verified_at=NOW.replace(tzinfo=None),
    ) is None
    assert build_identity_bound_contact_evidence(
        email="ada@berkeley.edu",
        email_source="bound_directory_card",
        contact_source_url=LISTING_URL,
        contact_verified_at=datetime.now(UTC) + timedelta(minutes=6),
    ) is None


def test_stamp_requires_exact_fetch_and_cites_same_host_final_response():
    final_url = "https://directory.berkeley.edu/faculty/"
    person = {"name": "Ada Lovelace", "url": "https://example.edu/ada"}
    assert stamp_bound_directory_contact(
        person,
        "Ada@berkeley.edu",
        CONFIG,
        source_soup=_marked_soup(final_url=final_url),
        requested_url=LISTING_URL,
    )
    opp = normalize_faculty(person, CONFIG)
    assert opp is not None
    assert verified_send_target(opp) == "ada@berkeley.edu"
    assert opp["metadata"]["contact_source_url"] == final_url


def test_stamp_rejects_navigation_label_as_person_identity():
    person = {"name": "Contact Us"}
    assert not stamp_bound_directory_contact(
        person,
        "helper.person@berkeley.edu",
        CONFIG,
        source_soup=_marked_soup(),
        requested_url=LISTING_URL,
    )
    assert "_contact_claim" not in person


@pytest.mark.parametrize(
    ("soup", "email"),
    [
        (BeautifulSoup("<div></div>", "html.parser"), "ada@berkeley.edu"),
        (
            _marked_soup(final_url="https://other.berkeley.edu/faculty"),
            "ada@berkeley.edu",
        ),
        (_marked_soup(), "office@berkeley.edu"),
        (_marked_soup(), "webmanager@berkeley.edu"),
        (_marked_soup(), "researchadmin@berkeley.edu"),
        (_marked_soup(), "mcbchair@berkeley.edu"),
        (_marked_soup(), "communications@berkeley.edu"),
        (_marked_soup(), "graduate@berkeley.edu"),
        (_marked_soup(), "mcbinfo@berkeley.edu"),
        (_marked_soup(), "facultycontact@berkeley.edu"),
        (_marked_soup(), "gradadvising@berkeley.edu"),
        (_marked_soup(), "departmentstaff@berkeley.edu"),
        (_marked_soup(), "mcbhr@berkeley.edu"),
        (
            _marked_soup(),
            ["ada@berkeley.edu", "grace@berkeley.edu"],
        ),
    ],
)
def test_stamp_fails_closed_without_fetch_scope_or_personal_same_host_email(
    soup, email,
):
    person = {"name": "Ada Lovelace"}
    assert not stamp_bound_directory_contact(
        person,
        email,
        CONFIG,
        source_soup=soup,
        requested_url=LISTING_URL,
    )
    assert "_contact_claim" not in person


def test_naive_fixture_time_cannot_be_promoted_by_marker():
    person = {"name": "Ada Lovelace"}
    assert not stamp_bound_directory_contact(
        person,
        "ada@berkeley.edu",
        CONFIG,
        source_soup=_marked_soup(observed_at=NOW.replace(tzinfo=None)),
        requested_url=LISTING_URL,
    )
    assert "_contact_claim" not in person


def test_empty_fixture_time_cannot_be_promoted_by_marker():
    person = {"name": "Ada Lovelace"}
    assert not stamp_bound_directory_contact(
        person,
        "ada@berkeley.edu",
        CONFIG,
        source_soup=_marked_soup(observed_at=""),
        requested_url=LISTING_URL,
    )
    assert "_contact_claim" not in person


def test_builder_cannot_invent_a_missing_fetch_timestamp():
    assert build_identity_bound_contact_evidence(
        email="ada@berkeley.edu",
        email_source="bound_directory_card",
        contact_source_url=LISTING_URL,
    ) is None


@pytest.mark.parametrize(
    "html",
    [
        (
            "<div class='card'>ada@berkeley.edu "
            "<a href='mailto:grace@berkeley.edu'>ada@berkeley.edu</a></div>"
        ),
        (
            "<div class='card'>"
            "<a href='mailto:ada@berkeley.edu?cc=grace@berkeley.edu'>"
            "ada@berkeley.edu</a></div>"
        ),
        (
            "<div class='card'>"
            "<a href=' MAILTO:grace@berkeley.edu'>ada@berkeley.edu</a></div>"
        ),
        (
            "<div class='card'>ada@berkeley.edu grace@berkeley.edu</div>"
        ),
        (
            "<div class='card'>Ada"
            "<div class='card'>grace@berkeley.edu</div></div>"
        ),
    ],
)
def test_container_contact_fails_on_href_text_recipient_or_nesting_ambiguity(
    html,
):
    container = BeautifulSoup(html, "html.parser").select_one("div.card")
    assert unique_bound_container_contact(
        container,
        CONFIG,
        nested_record_selector="div.card",
    ) is None


def test_fetch_final_url_flows_into_normalized_contact_evidence(monkeypatch):
    requested_url = "https://directory.berkeley.edu/faculty"
    final_url = "https://directory.berkeley.edu/faculty/"

    class FakeResponse:
        content = (
            b"<div class='card'><a href='mailto:ada@berkeley.edu'>"
            b"ada@berkeley.edu</a></div>"
        )
        url = final_url

        @staticmethod
        def raise_for_status():
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.verify = True

        @staticmethod
        def get(_url, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(
        "src.collectors.ucb_common.requests.Session",
        FakeSession,
    )
    soup = fetch_soup(requested_url, max_retries=1)
    assert soup is not None
    container = soup.select_one("div.card")
    email = unique_bound_container_contact(
        container,
        CONFIG,
        nested_record_selector="div.card",
    )
    person = {"name": "Ada Lovelace", "url": "https://example.edu/ada"}
    assert stamp_bound_directory_contact(
        person,
        email,
        CONFIG,
        source_soup=soup,
        requested_url=requested_url,
    )
    opp = normalize_faculty(person, CONFIG)
    assert opp["metadata"]["contact_source_url"] == final_url


def test_clear_removes_whole_evidence_bundle_and_preserves_other_metadata():
    record = _bound_record()
    clear_contact_claim(record)
    assert record["contact_email"] is None
    assert record["metadata"] == {"other": "kept"}


def test_stable_id_carry_moves_complete_bundle_without_refreshing_timestamp():
    existing = _bound_record()
    incoming = {
        "id": "faculty-ada",
        "pi_name": "Ada Lovelace",
        "department": "Test Department",
        "keywords": [],
        "metadata": {"incoming": True},
    }
    original_timestamp = existing["metadata"]["contact_verified_at"]
    _carry_forward_enrichment(existing, incoming)
    assert verified_send_target(incoming) == "ada@berkeley.edu"
    assert incoming["metadata"]["contact_verified_at"] == original_timestamp
    assert incoming["metadata"]["incoming"] is True


def test_new_same_email_observation_wins_over_older_carried_claim():
    existing = _bound_record(observed_at=NOW - timedelta(days=5))
    incoming = _bound_record(observed_at=NOW)
    incoming["metadata"]["incoming"] = True
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["contact_verified_at"] == NOW.isoformat()
    assert verified_send_target(incoming) == "ada@berkeley.edu"


def test_different_email_and_partial_or_expired_claims_fail_closed():
    existing = _bound_record()
    incoming = _bound_record(email="grace@berkeley.edu")
    # Attach the old person's proof fields to the new address: they must all go.
    incoming["metadata"].update({
        field: existing["metadata"][field] for field in CONTACT_EVIDENCE_FIELDS
    })
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "grace@berkeley.edu"
    assert CONTACT_EVIDENCE_FIELDS.isdisjoint(incoming["metadata"])

    partial = _bound_record()
    partial["metadata"].pop("contact_source_url")
    incoming_partial = {"metadata": {}, "keywords": []}
    _carry_forward_enrichment(partial, incoming_partial)
    assert incoming_partial["contact_email"] == "ada@berkeley.edu"
    assert CONTACT_EVIDENCE_FIELDS.isdisjoint(incoming_partial["metadata"])

    expired = _bound_record(observed_at=NOW - timedelta(days=61))
    incoming_expired = {"metadata": {}, "keywords": []}
    _carry_forward_enrichment(expired, incoming_expired)
    assert incoming_expired["contact_email"] == "ada@berkeley.edu"
    assert CONTACT_EVIDENCE_FIELDS.isdisjoint(incoming_expired["metadata"])


def test_weak_cross_record_merge_never_moves_bound_evidence():
    survivor = {"contact_email": None, "metadata": {"survivor": True}}
    loser = _bound_record()
    _merge_faculty_fields(survivor, loser)
    assert survivor["contact_email"] == "ada@berkeley.edu"
    assert CONTACT_EVIDENCE_FIELDS.isdisjoint(survivor["metadata"])
    assert verified_send_target(survivor) == ""
