"""Offline tests for src.collectors.ucb_me_faculty.

No network: fixtures mirror ME's real markup — a Beaver Builder grid where each
faculty member is a div.fl-post-grid-post with name + profile link in
h3.fl-post-title a and an empty (JS-populated) div.professor-title, while the
email lives on the profile page as a mailto:. Locks in the bespoke listing
parser, the empty-title handling, profile email extraction, dedup, the
external-campus output shape, the broad-keyword fallback, and id stability.
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
from src.collectors.ucb_me_faculty import ME_CONFIG, _scrape_me_faculty_list


def _card(slug: str, name: str, title_html: str = "") -> str:
    return f"""
    <div class="fl-post-grid-post people type-people">
      <div class="faculty-container">
        <div class="faculty-member">
          <a href="https://me.berkeley.edu/people/{slug}/" title="{name}"><img alt="x"/></a>
        </div>
        <div class="fl-post-text">
          <h3 class="fl-post-title"><a href="https://me.berkeley.edu/people/{slug}/">{name}</a></h3>
          <div class="professor-title">{title_html}</div>
        </div>
      </div>
    </div>
    """


# Two faculty: one with an (unusually) populated title, one with the empty slot.
LISTING_HTML = f"""
<div class="fl-post-grid">
  {_card("m-reza-alam", "M. Reza Alam")}
  {_card("francesco-borrelli", "Francesco Borrelli", "Professor")}
</div>
"""

PROFILE_HTML = '<div class="node"><a href="mailto:reza.alam@berkeley.edu">email</a></div>'
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_me_faculty_list(soup, ME_CONFIG["base"])


def test_parses_name_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    alam = next(p for p in people if p["name"] == "M. Reza Alam")
    assert alam["url"] == "https://me.berkeley.edu/people/m-reza-alam/"


def test_empty_title_slot_is_omitted_but_present_title_kept():
    alam = next(p for p in _scrape() if p["name"] == "M. Reza Alam")
    assert "title" not in alam  # empty professor-title div -> no title
    borrelli = next(p for p in _scrape() if p["name"] == "Francesco Borrelli")
    assert borrelli["title"] == "Professor"


def test_email_extracted_from_profile_mailto():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, ME_CONFIG) == "reza.alam@berkeley.edu"


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, ME_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "M. Reza Alam", "url": "https://me.berkeley.edu/people/m-reza-alam/"},
        {"name": "M. Reza Alam", "url": "https://me.berkeley.edu/people/m-reza-alam/"},
        {"name": "Chris Dames", "url": "https://me.berkeley.edu/people/chris-dames/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["M. Reza Alam", "Chris Dames"]


def test_output_shape_matches_other_faculty_collectors():
    alam = next(p for p in _scrape() if p["name"] == "M. Reza Alam")
    alam["email"] = "reza.alam@berkeley.edu"
    opp = normalize_faculty(alam, ME_CONFIG)
    assert opp["source"] == "ucb_me_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-me-")
    assert opp["contact_email"] == "reza.alam@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ME_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ME_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    alam = next(p for p in _scrape() if p["name"] == "M. Reza Alam")  # no email
    opp = normalize_faculty(alam, ME_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["mechanical engineering"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole ME
    corpus on the next scrape. Pin a real corpus id."""
    alam = next(p for p in _scrape() if p["name"] == "M. Reza Alam")
    assert normalize_faculty(alam, ME_CONFIG)["id"] == "faculty-ucb-me-f7d379a9"
