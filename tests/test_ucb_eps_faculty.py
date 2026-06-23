"""Offline tests for src.collectors.ucb_eps_faculty.

No network: fixtures mirror EPS's real markup — the same Open-Berkeley card
variant as Chemistry (div.node-openberkeley-person, name in <h2>, href on a
/people/ link), and profiles that carry a mailto: email and a free-text
research-interests field. Locks in the shared selector-driven parser for EPS's
config, email + research extraction, earth-science keyword mapping, dedup, the
external-campus output shape, and id stability.
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
from src.collectors.ucb_eps_faculty import EPS_CONFIG

LISTING_HTML = """
<div class="openberkeley-card-grid">
  <div class="node node-openberkeley-person node-view--featured-image-left">
    <a href="/people/richard-allen">
      <h2>Richard Allen</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor &amp; Director</div></div>
      </div>
    </a>
  </div>
  <div class="node node-openberkeley-person node-view--featured-image-left">
    <a href="/people/jill-f-banfield">
      <h2>Jill Banfield</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:rallen@berkeley.edu">rallen@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research interests:</div>
    <div class="field-items"><div class="field-item even"><p>Seismology, tectonics, earthquake early warning</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, EPS_CONFIG)


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    allen = next(p for p in people if p["name"] == "Richard Allen")
    assert allen["title"].startswith("Professor")
    assert allen["url"] == "https://eps.berkeley.edu/people/richard-allen"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, EPS_CONFIG) == "rallen@berkeley.edu"
    interests = extract_research_interests(soup, EPS_CONFIG)
    assert "Research interests" not in interests  # label stripped by .field-item
    assert "seismology" in interests.lower()


def test_research_yields_earth_science_keywords():
    person = {"name": "Richard Allen", "url": "x", "title": "Professor",
              "research_areas": "Seismology, tectonics, geophysics, volcanology"}
    opp = normalize_faculty(person, EPS_CONFIG)
    for kw in ("seismology", "tectonics", "geophysics", "volcanology"):
        assert kw in opp["keywords"], kw
    assert "earth science" not in opp["keywords"]  # not the broad fallback


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, EPS_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Richard Allen", "url": "https://eps.berkeley.edu/people/richard-allen"},
        {"name": "Richard Allen", "url": "https://eps.berkeley.edu/people/richard-allen"},
        {"name": "Jill Banfield", "url": "https://eps.berkeley.edu/people/jill-f-banfield"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Richard Allen", "Jill Banfield"]


def test_output_shape_matches_other_faculty_collectors():
    allen = next(p for p in _scrape() if p["name"] == "Richard Allen")
    allen["email"] = "rallen@berkeley.edu"
    allen["research_areas"] = "Seismology, earthquake early warning"
    opp = normalize_faculty(allen, EPS_CONFIG)
    assert opp["source"] == "ucb_eps_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-eps-")
    assert opp["contact_email"] == "rallen@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == EPS_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == EPS_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    banfield = next(p for p in _scrape() if p["name"] == "Jill Banfield")  # no email/research
    opp = normalize_faculty(banfield, EPS_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["earth science"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole EPS
    corpus on the next scrape. Pin a real corpus id."""
    allen = next(p for p in _scrape() if p["name"] == "Richard Allen")
    assert normalize_faculty(allen, EPS_CONFIG)["id"] == "faculty-ucb-eps-bfe505e2"
