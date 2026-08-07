"""Offline contact-evidence tests for the UCB Classics directory parser."""

from __future__ import annotations

from bs4 import BeautifulSoup

from backend.lib.contact_visibility import verified_send_target
from src.collectors.ucb_classics_faculty import (
    CLASSICS_CONFIG,
    _scrape_classics_faculty_list,
)
from src.collectors.ucb_common import (
    _mark_fetched_soup_observation,
    normalize_faculty,
)

LISTING_HTML = """
<div class="views-row">
  <h3><a href="/people/susanna-elm">SusannaElm</a></h3>
  <p>Professor · susanna.elm@berkeley.edu</p>
</div>
<div class="views-row">
  <h3><a href="/people/r-f-smith">RFSmith</a></h3>
  <p>Professor</p>
</div>
"""


def _scrape() -> list[dict]:
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=CLASSICS_CONFIG["url"],
        final_url=CLASSICS_CONFIG["url"],
    )
    return _scrape_classics_faculty_list(soup, CLASSICS_CONFIG["base"])


def test_inline_email_is_one_pending_claim():
    elm = next(person for person in _scrape() if person["name"] == "Susanna Elm")
    assert "email" not in elm
    assert elm["_contact_claim"]["contact_email"] == "susanna.elm@berkeley.edu"
    assert (
        elm["_contact_claim"]["metadata"]["email_source"]
        == "bound_directory_card"
    )


def test_normalized_claim_passes_server_gate():
    elm = next(person for person in _scrape() if person["name"] == "Susanna Elm")
    opportunity = normalize_faculty(elm, CLASSICS_CONFIG)
    assert opportunity["contact_email"] == "susanna.elm@berkeley.edu"
    assert verified_send_target(opportunity) == "susanna.elm@berkeley.edu"


def test_missing_email_remains_lite_without_partial_evidence():
    smith = next(person for person in _scrape() if person["name"] == "R F Smith")
    opportunity = normalize_faculty(smith, CLASSICS_CONFIG)
    assert opportunity["contact_email"] is None
    assert "identity_bound" not in opportunity["metadata"]
    assert "email_source" not in opportunity["metadata"]
    assert "contact_verified_email" not in opportunity["metadata"]
    assert "contact_source_url" not in opportunity["metadata"]
    assert "contact_verified_at" not in opportunity["metadata"]
