"""Offline tests for src.collectors.ucb_mse_faculty.

No network: fixtures mirror MSE's real markup — a Beaver Builder grid where each
faculty member is a div.fl-post-grid-post of the people_new post type, with the
name + profile URL on a <meta itemprop="mainEntityOfPage"> (no heading link) and
a category-<role> class. Email is plain text on the profile (no mailto). Locks
in the bespoke meta-based parser, emeritus skipping, profile email extraction
via the page-wide scan, dedup, the external-campus output shape, and id
stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import (
    dedup_by_profile_url,
    extract_email_from_profile,
    normalize_faculty,
)
from src.collectors.ucb_mse_faculty import MSE_CONFIG, _scrape_mse_faculty_list


def _card(slug: str, name: str, category: str) -> str:
    return f"""
    <div class="fl-post-grid-post people_new type-people_new {category}">
      <meta itemprop="mainEntityOfPage" content="{name}"
            itemid="https://mse.berkeley.edu/people_new/{slug}/"/>
      <a href="https://mse.berkeley.edu/people_new/{slug}/">{name}</a>
    </div>
    """


# Two active faculty + one emeritus that must be skipped.
LISTING_HTML = f"""
<div class="fl-post-grid">
  {_card("al-balushi", "Zakaria Al Balushi", "category-professor")}
  {_card("asta", "Mark Asta", "category-professor")}
  {_card("old-prof", "Old Prof", "category-emeritus")}
</div>
"""

# Profile exposes the email as plain text (no mailto) and no research section.
PROFILE_HTML = '<div class="node"><p>Contact: albalushi@berkeley.edu</p></div>'
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_mse_faculty_list(soup, MSE_CONFIG["base"])


def test_parses_name_and_url_from_meta():
    people = _scrape()
    alam = next(p for p in people if p["name"] == "Zakaria Al Balushi")
    assert alam["url"] == "https://mse.berkeley.edu/people_new/al-balushi/"


def test_emeritus_category_is_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Zakaria Al Balushi", "Mark Asta"}
    assert "Old Prof" not in names


def test_email_extracted_via_page_scan():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    # No mailto/field -> shared extractor's page-wide scan finds the plain-text addr.
    assert extract_email_from_profile(soup, MSE_CONFIG) == "albalushi@berkeley.edu"


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, MSE_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Mark Asta", "url": "https://mse.berkeley.edu/people_new/asta/"},
        {"name": "Mark Asta", "url": "https://mse.berkeley.edu/people_new/asta/"},
        {"name": "Gerbrand Ceder", "url": "https://mse.berkeley.edu/people_new/ceder/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Mark Asta", "Gerbrand Ceder"]


def test_output_shape_matches_other_faculty_collectors():
    alam = next(p for p in _scrape() if p["name"] == "Zakaria Al Balushi")
    alam["email"] = "albalushi@berkeley.edu"
    opp = normalize_faculty(alam, MSE_CONFIG)
    assert opp["source"] == "ucb_mse_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-mse-")
    assert opp["contact_email"] == "albalushi@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == MSE_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == MSE_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    asta = next(p for p in _scrape() if p["name"] == "Mark Asta")  # no email
    opp = normalize_faculty(asta, MSE_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["materials science"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole MSE
    corpus on the next scrape. Pin a real corpus id."""
    alam = next(p for p in _scrape() if p["name"] == "Zakaria Al Balushi")
    assert normalize_faculty(alam, MSE_CONFIG)["id"] == "faculty-ucb-mse-fe1d5516"
