"""Offline tests for src.collectors.ucb_nst_faculty.

No network: fixtures mirror NST's real markup — the Open-Berkeley card variant
with the name in an <h3> (not <h2>), and profiles that carry a mailto: email and
a free-text research-interests field. Locks in the shared selector-driven parser
for the NST config (h3 name), email + research extraction, nutrition keyword
mapping, dedup, the external-campus output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import (
    dedup_by_profile_url,
    extract_email_from_profile,
    extract_research_interests,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)
from src.collectors.ucb_nst_faculty import NST_CONFIG

LISTING_HTML = """
<div class="openberkeley-card-grid">
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/gregory-aponte">
      <h3>Gregory Aponte</h3>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/danica-chen">
      <h3>Danica Chen</h3>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:danicac@berkeley.edu">danicac@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research interests:</div>
    <div class="field-items"><div class="field-item even"><p>Aging, stem cells, metabolism, diseases of aging</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, NST_CONFIG)


def test_parses_h3_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    aponte = next(p for p in people if p["name"] == "Gregory Aponte")
    assert aponte["title"] == "Professor"
    assert aponte["url"] == "https://nst.berkeley.edu/people/gregory-aponte"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, NST_CONFIG) == "danicac@berkeley.edu"
    interests = extract_research_interests(soup, NST_CONFIG)
    assert "Research interests" not in interests
    assert "metabolism" in interests.lower()


def test_research_yields_nutrition_keywords():
    person = {"name": "Danica Chen", "url": "x", "title": "Professor",
              "research_areas": "Aging, stem cells, metabolism, endocrinology"}
    opp = normalize_faculty(person, NST_CONFIG)
    for kw in ("aging", "stem cells", "metabolism", "endocrinology"):
        assert kw in opp["keywords"], kw
    assert "nutrition" not in opp["keywords"]  # not the broad fallback


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, NST_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Gregory Aponte", "url": "https://nst.berkeley.edu/people/gregory-aponte"},
        {"name": "Gregory Aponte", "url": "https://nst.berkeley.edu/people/gregory-aponte"},
        {"name": "Danica Chen", "url": "https://nst.berkeley.edu/people/danica-chen"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Gregory Aponte", "Danica Chen"]


def test_output_shape_matches_other_faculty_collectors():
    aponte = next(p for p in _scrape() if p["name"] == "Gregory Aponte")
    aponte["email"] = "aponte@berkeley.edu"
    aponte["research_areas"] = "Nutrition, gut microbiome, metabolism"
    opp = normalize_faculty(aponte, NST_CONFIG)
    assert opp["source"] == "ucb_nst_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-nst-")
    assert opp["contact_email"] == "aponte@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == []
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    chen = next(p for p in _scrape() if p["name"] == "Danica Chen")  # no email/research
    opp = normalize_faculty(chen, NST_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["nutrition"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole NST
    corpus on the next scrape. Pin a real corpus id."""
    aponte = next(p for p in _scrape() if p["name"] == "Gregory Aponte")
    assert normalize_faculty(aponte, NST_CONFIG)["id"] == "faculty-ucb-nst-b69af6a0"
