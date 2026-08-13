"""Offline tests for src.collectors.ucb_cbe_faculty.

No network: fixtures mirror CBE's real markup — the same Open-Berkeley card
variant as Chemistry (div.node-openberkeley-person, name in <h2>, href on a
/people/ link), and profiles that carry a mailto: email and a free-text
research-interests field. Locks in the shared selector-driven parser for CBE's
config, email + research extraction, the no-research fallback, dedup, the
external-campus output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_cbe_faculty import CBE_CONFIG
from src.collectors.ucb_common import (
    dedup_by_profile_url,
    extract_email_from_profile,
    extract_research_interests,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)

LISTING_HTML = """
<div class="openberkeley-card-grid">
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/keith-alexander">
      <h2>Keith Alexander</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/nitash-balsara">
      <h2>Nitash P. Balsara</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:kalexand@berkeley.edu">kalexand@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research:</div>
    <div class="field-items"><div class="field-item even"><p>Catalysis, polymer thermodynamics, electrochemistry</p></div></div>
  </div>
</div>
"""

PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, CBE_CONFIG)


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    keith = next(p for p in people if p["name"] == "Keith Alexander")
    assert keith["title"] == "Professor"
    assert keith["url"] == "https://chemistry.berkeley.edu/people/keith-alexander"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, CBE_CONFIG) == "kalexand@berkeley.edu"
    interests = extract_research_interests(soup, CBE_CONFIG)
    assert "Research:" not in interests  # label stripped by .field-item
    assert "catalysis" in interests.lower()


def test_research_yields_topical_keywords():
    person = {"name": "Keith Alexander", "url": "x", "title": "Professor",
              "research_areas": "Catalysis, polymer thermodynamics, electrochemistry"}
    opp = normalize_faculty(person, CBE_CONFIG)
    for kw in ("catalysis", "thermodynamics"):
        assert kw in opp["keywords"], kw
    assert "chemical engineering" not in opp["keywords"]  # not the broad fallback


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, CBE_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Keith Alexander", "url": "https://chemistry.berkeley.edu/people/keith-alexander"},
        {"name": "Keith Alexander", "url": "https://chemistry.berkeley.edu/people/keith-alexander"},
        {"name": "Nitash P. Balsara", "url": "https://chemistry.berkeley.edu/people/nitash-balsara"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Keith Alexander", "Nitash P. Balsara"]


def test_output_shape_matches_other_faculty_collectors():
    keith = next(p for p in _scrape() if p["name"] == "Keith Alexander")
    keith["email"] = "kalexand@berkeley.edu"
    keith["research_areas"] = "Catalysis, polymer thermodynamics"
    opp = normalize_faculty(keith, CBE_CONFIG)
    assert opp["source"] == "ucb_cbe_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-cbe-")
    assert opp["contact_email"] == "kalexand@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == CBE_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == CBE_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    balsara = next(p for p in _scrape() if p["name"] == "Nitash P. Balsara")  # no email/research
    opp = normalize_faculty(balsara, CBE_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["chemical engineering"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole CBE
    corpus on the next scrape. Pin a real corpus id."""
    keith = next(p for p in _scrape() if p["name"] == "Keith Alexander")
    assert normalize_faculty(keith, CBE_CONFIG)["id"] == "faculty-ucb-cbe-e27a7168"
