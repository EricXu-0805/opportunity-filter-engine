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
    stamp_bound_profile_contact,
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
PROFILE_URL = "https://statistics.berkeley.edu/people/ada-lovelace"
PROFILE_CONTRACT = {
    "container_selector": "article.node--type-faculty",
    "identity_selector": "h1.page--title",
    "contact_selector": "div.field--name-field-email",
    "nested_person_selector": (
        "article.node--type-faculty, .related-person, aside"
    ),
}


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


def _no_bound_evidence(metadata: dict) -> bool:
    """True when nothing PROVING a binding remains. The clear tombstone
    (identity_bound: False — "reviewed, not bound") is allowed; any other
    evidence field, or identity_bound True, is residue."""
    residue = {k for k in CONTACT_EVIDENCE_FIELDS if k in metadata}
    if metadata.get("identity_bound") is False:
        residue.discard("identity_bound")
    return not residue


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
        "source": "ucb_test_faculty",
        "organization": "University of California, Berkeley",
        "pi_name": "Ada Lovelace",
        "url": PROFILE_URL,
        "department": "Test Department",
        "keywords": ["computing"],
        "contact_email": email.casefold(),
        "metadata": {"other": "kept", **evidence},
    }


def _marked_profile_soup(
    html: str,
    *,
    requested_url: str = PROFILE_URL,
    final_url: str = PROFILE_URL,
    observed_at: datetime | str = NOW,
) -> BeautifulSoup:
    return _mark_fetched_soup_observation(
        BeautifulSoup(html, "html.parser"),
        requested_url=requested_url,
        final_url=final_url,
        observed_at=observed_at,
    )


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


def test_profile_stamp_requires_one_strong_identity_and_one_contact_container():
    final_url = f"{PROFILE_URL}/"
    soup = _marked_profile_soup(
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <div class="field--name-field-email">
            <a href="mailto:ada@berkeley.edu">ada@berkeley.edu</a>
          </div>
        </article>
        """,
        final_url=final_url,
    )
    person = {"name": "Ada Lovelace", "url": PROFILE_URL}
    assert stamp_bound_profile_contact(
        person,
        CONFIG,
        source_soup=soup,
        requested_url=PROFILE_URL,
        **PROFILE_CONTRACT,
    )
    opp = normalize_faculty(person, CONFIG)
    assert opp is not None
    assert verified_send_target(opp) == "ada@berkeley.edu"
    assert opp["metadata"]["contact_source_url"] == final_url
    assert opp["metadata"]["contact_verified_at"] == NOW.isoformat()


@pytest.mark.parametrize(
    "html",
    [
        # A weak browser title or body mention cannot override another person's
        # strong name node.
        """
        <title>Ada Lovelace | Faculty</title>
        <article class="node--type-faculty">
          <h1 class="page--title">Grace Hopper</h1>
          <p>Ada Lovelace collaborated with this group.</p>
          <div class="field--name-field-email">grace@berkeley.edu</div>
        </article>
        """,
        # Middle initials are identity-bearing: John A is not John B.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada B. Lovelace</h1>
          <div class="field--name-field-email">ada@berkeley.edu</div>
        </article>
        """,
        # The address is outside the reviewed person container.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
        </article>
        <footer><div class="field--name-field-email">ada@berkeley.edu</div></footer>
        """,
        # Two disjoint person containers are ambiguous even if only one matches.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <div class="field--name-field-email">ada@berkeley.edu</div>
        </article>
        <article class="node--type-faculty">
          <h1 class="page--title">Grace Hopper</h1>
          <div class="field--name-field-email">grace@berkeley.edu</div>
        </article>
        """,
        # Visible and mailto recipients disagree.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <div class="field--name-field-email">
            <a href="mailto:grace@berkeley.edu">ada@berkeley.edu</a>
          </div>
        </article>
        """,
        # More than one address is not resolved by choosing the first.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <div class="field--name-field-email">
            ada@berkeley.edu assistant@berkeley.edu
          </div>
        </article>
        """,
        # Role/unit mailboxes never become a professor send target.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <div class="field--name-field-email">smithlab@berkeley.edu</div>
        </article>
        """,
        # Nested person identity under the reviewed container is ambiguous.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <div class="related-person">
            <h1 class="page--title">Grace Hopper</h1>
            <div class="field--name-field-email">grace@berkeley.edu</div>
          </div>
        </article>
        """,
        # A related person can use a different template and heading level. The
        # reviewed nested-person contract must still reject their contact.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <aside>
            <h2>Grace Hopper</h2>
            <div class="field--name-field-email">grace@berkeley.edu</div>
          </aside>
        </article>
        """,
        # Arbitrary future wrapper names cannot evade the exact owner scope.
        """
        <article class="node--type-faculty">
          <h1 class="page--title">Ada Lovelace</h1>
          <section class="person-card">
            <h2>Grace Hopper</h2>
            <div class="field--name-field-email">grace@berkeley.edu</div>
          </section>
        </article>
        """,
    ],
)
def test_profile_stamp_fails_closed_on_identity_or_contact_ambiguity(html):
    person = {"name": "Ada Lovelace", "url": PROFILE_URL}
    assert not stamp_bound_profile_contact(
        person,
        CONFIG,
        source_soup=_marked_profile_soup(html),
        requested_url=PROFILE_URL,
        **PROFILE_CONTRACT,
    )
    assert "_contact_claim" not in person


@pytest.mark.parametrize(
    ("expected_name", "observed_name"),
    [
        ("Ada Ma", "Ada"),
        ("Ma Li", "Li"),
        ("Ada Lovelace", "Ada Lovelace, PhD"),
        ("王 Ada", "李 Ada"),
    ],
)
def test_profile_stamp_never_drops_name_or_degree_looking_identity_tokens(
    expected_name,
    observed_name,
):
    soup = _marked_profile_soup(
        f"""
        <article class="node--type-faculty">
          <h1 class="page--title">{observed_name}</h1>
          <div class="field--name-field-email">ada@berkeley.edu</div>
        </article>
        """
    )
    person = {"name": expected_name, "url": PROFILE_URL}
    assert not stamp_bound_profile_contact(
        person,
        CONFIG,
        source_soup=soup,
        requested_url=PROFILE_URL,
        **PROFILE_CONTRACT,
    )
    assert "_contact_claim" not in person


@pytest.mark.parametrize(
    ("soup", "requested_url", "person_url"),
    [
        (
            BeautifulSoup(
                """
                <article class="node--type-faculty">
                  <h1 class="page--title">Ada Lovelace</h1>
                  <div class="field--name-field-email">ada@berkeley.edu</div>
                </article>
                """,
                "html.parser",
            ),
            PROFILE_URL,
            PROFILE_URL,
        ),
        (
            _marked_profile_soup(
                """
                <article class="node--type-faculty">
                  <h1 class="page--title">Ada Lovelace</h1>
                  <div class="field--name-field-email">ada@berkeley.edu</div>
                </article>
                """,
                final_url="https://statistics.berkeley.edu/people/grace",
            ),
            PROFILE_URL,
            PROFILE_URL,
        ),
        (
            _marked_profile_soup(
                """
                <article class="node--type-faculty">
                  <h1 class="page--title">Ada Lovelace</h1>
                  <div class="field--name-field-email">ada@berkeley.edu</div>
                </article>
                """,
                final_url="https://profiles.berkeley.edu/people/ada-lovelace",
            ),
            PROFILE_URL,
            PROFILE_URL,
        ),
        (
            _marked_profile_soup(
                """
                <article class="node--type-faculty">
                  <h1 class="page--title">Ada Lovelace</h1>
                  <div class="field--name-field-email">ada@berkeley.edu</div>
                </article>
                """,
            ),
            PROFILE_URL,
            "https://statistics.berkeley.edu/people/grace",
        ),
        (
            _marked_profile_soup(
                """
                <article class="node--type-faculty">
                  <h1 class="page--title">Ada Lovelace</h1>
                  <div class="field--name-field-email">ada@berkeley.edu</div>
                </article>
                """,
                requested_url=(
                    "https://statistics.berkeley.edu/people/grace"
                ),
            ),
            PROFILE_URL,
            PROFILE_URL,
        ),
    ],
)
def test_profile_stamp_requires_exact_fetch_scoped_profile_url(
    soup,
    requested_url,
    person_url,
):
    person = {"name": "Ada Lovelace", "url": person_url}
    assert not stamp_bound_profile_contact(
        person,
        CONFIG,
        source_soup=soup,
        requested_url=requested_url,
        **PROFILE_CONTRACT,
    )
    assert "_contact_claim" not in person


def test_clear_removes_whole_evidence_bundle_and_preserves_other_metadata():
    record = _bound_record()
    clear_contact_claim(record)
    assert record["contact_email"] is None
    assert record["metadata"] == {"other": "kept", "identity_bound": False}


def test_stable_id_carry_moves_complete_bundle_without_refreshing_timestamp():
    existing = _bound_record()
    incoming = {
        "id": "faculty-ada",
        "source": "ucb_test_faculty",
        "organization": "University of California, Berkeley",
        "pi_name": "Ada Lovelace",
        "url": PROFILE_URL,
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


def test_directory_bound_carry_requires_stable_profile_identity():
    existing = _bound_record()
    incoming = {
        "id": "faculty-ada",
        "source": "ucb_test_faculty",
        "organization": "University of California, Berkeley",
        "pi_name": "Ada Lovelace",
        "url": "https://statistics.berkeley.edu/people/grace",
        "keywords": [],
        "metadata": {},
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "ada@berkeley.edu"
    assert _no_bound_evidence(incoming["metadata"])
    assert verified_send_target(incoming) == ""

    application_only = {
        "id": "faculty-ada",
        "source": "ucb_test_faculty",
        "organization": "University of California, Berkeley",
        "pi_name": "Ada Lovelace",
        "application": {"application_url": LISTING_URL},
        "keywords": [],
        "metadata": {},
    }
    existing_application_only = {
        **existing,
        "url": None,
        "application": {"application_url": LISTING_URL},
    }
    _carry_forward_enrichment(existing_application_only, application_only)
    assert application_only["contact_email"] == "ada@berkeley.edu"
    assert _no_bound_evidence(
        application_only["metadata"]
    )
    assert verified_send_target(application_only) == ""


def test_different_email_and_partial_or_expired_claims_fail_closed():
    existing = _bound_record()
    incoming = _bound_record(email="grace@berkeley.edu")
    # Attach the old person's proof fields to the new address: they must all go.
    incoming["metadata"].update({
        field: existing["metadata"][field] for field in CONTACT_EVIDENCE_FIELDS
    })
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "grace@berkeley.edu"
    assert _no_bound_evidence(incoming["metadata"])

    partial = _bound_record()
    partial["metadata"].pop("contact_source_url")
    incoming_partial = {"metadata": {}, "keywords": []}
    _carry_forward_enrichment(partial, incoming_partial)
    assert incoming_partial["contact_email"] == "ada@berkeley.edu"
    assert _no_bound_evidence(incoming_partial["metadata"])

    expired = _bound_record(observed_at=NOW - timedelta(days=61))
    incoming_expired = {"metadata": {}, "keywords": []}
    _carry_forward_enrichment(expired, incoming_expired)
    assert incoming_expired["contact_email"] == "ada@berkeley.edu"
    assert _no_bound_evidence(incoming_expired["metadata"])


def test_weak_cross_record_merge_never_moves_bound_evidence():
    survivor = {"contact_email": None, "metadata": {"survivor": True}}
    loser = _bound_record()
    _merge_faculty_fields(survivor, loser)
    assert survivor["contact_email"] == "ada@berkeley.edu"
    assert _no_bound_evidence(survivor["metadata"])
    assert verified_send_target(survivor) == ""


def test_bound_profile_carry_requires_same_id_name_and_profile_url():
    evidence = build_identity_bound_contact_evidence(
        email="ada@berkeley.edu",
        email_source="bound_profile_container",
        contact_source_url=PROFILE_URL,
        contact_verified_at=NOW,
    )
    assert evidence is not None
    existing = {
        "id": "faculty-ada",
        "source": "ucb_test_faculty",
        "organization": "University of California, Berkeley",
        "pi_name": "Ada Lovelace",
        "url": PROFILE_URL,
        "source_url": PROFILE_URL,
        "application": {"application_url": PROFILE_URL},
        "contact_email": "ada@berkeley.edu",
        "keywords": ["computing"],
        "metadata": evidence,
    }

    matching = {
        "id": "faculty-ada",
        "source": "ucb_test_faculty",
        "organization": "University of California, Berkeley",
        "pi_name": "Ada Lovelace",
        "url": f"{PROFILE_URL}/",
        "source_url": PROFILE_URL,
        "application": {"application_url": PROFILE_URL},
        "keywords": [],
        "metadata": {},
    }
    _carry_forward_enrichment(existing, matching)
    assert verified_send_target(matching) == "ada@berkeley.edu"
    assert matching["metadata"]["contact_verified_at"] == NOW.isoformat()

    for changed in (
        {
            "id": "faculty-other",
            "source": "ucb_test_faculty",
            "organization": "University of California, Berkeley",
            "pi_name": "Ada Lovelace",
            "url": PROFILE_URL,
        },
        {
            "id": "faculty-ada",
            "source": "ucb_test_faculty",
            "organization": "University of California, Berkeley",
            "pi_name": "Grace Hopper",
            "url": PROFILE_URL,
        },
        {
            "id": "faculty-ada",
            "source": "ucb_test_faculty",
            "organization": "University of California, Berkeley",
            "pi_name": "Ada Lovelace",
            "url": "https://statistics.berkeley.edu/people/grace",
            "source_url": PROFILE_URL,
        },
        {
            "id": "faculty-ada",
            "source": "ucb_test_faculty",
            "organization": "University of California, Berkeley",
            "pi_name": "Ada Lovelace",
            "url": PROFILE_URL,
            "source_url": PROFILE_URL,
            "application": {
                "application_url": (
                    "https://statistics.berkeley.edu/people/grace"
                ),
            },
        },
        {
            "id": "",
            "source": "ucb_test_faculty",
            "organization": "University of California, Berkeley",
            "pi_name": "Ada Lovelace",
            "url": PROFILE_URL,
        },
    ):
        incoming = {**changed, "keywords": [], "metadata": {}}
        _carry_forward_enrichment(existing, incoming)
        assert incoming["contact_email"] == "ada@berkeley.edu"
        assert _no_bound_evidence(incoming["metadata"])
        assert verified_send_target(incoming) == ""
