"""Offline tests for src.collectors.ucb_astro_faculty.

No network: fixtures mirror Astronomy's real markup — the same Open-Berkeley
card variant as Chemistry (div.node-openberkeley-person, name in <h2>, href on
a /people/ link), and profiles that carry a mailto: email and a free-text
research-interests field. Locks in the shared selector-driven parser for the
ASTRO config, email + research extraction, astronomy keyword mapping, dedup,
the external-campus output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_astro_faculty import ASTRO_CONFIG
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
    <a href="/people/jenny-bergner">
      <h2>Jenny Bergner</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Assistant Professor</div></div>
      </div>
    </a>
  </div>
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/eliot-quataert">
      <h2>Eliot Quataert</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:jbergner@berkeley.edu">jbergner@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research interests:</div>
    <div class="field-items"><div class="field-item even"><p>Star formation, exoplanets, interstellar medium chemistry</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, ASTRO_CONFIG)


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    jb = next(p for p in people if p["name"] == "Jenny Bergner")
    assert jb["title"] == "Assistant Professor"
    assert jb["url"] == "https://astro.berkeley.edu/people/jenny-bergner"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, ASTRO_CONFIG) == "jbergner@berkeley.edu"
    interests = extract_research_interests(soup, ASTRO_CONFIG)
    assert "Research interests" not in interests
    assert "star formation" in interests.lower()


def test_research_yields_astronomy_keywords():
    person = {"name": "Jenny Bergner", "url": "x", "title": "Professor",
              "research_areas": "Star formation, exoplanets, interstellar medium, cosmology"}
    opp = normalize_faculty(person, ASTRO_CONFIG)
    for kw in ("star formation", "exoplanets", "interstellar medium", "cosmology"):
        assert kw in opp["keywords"], kw
    assert "astronomy" not in opp["keywords"]  # not the broad fallback


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, ASTRO_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Jenny Bergner", "url": "https://astro.berkeley.edu/people/jenny-bergner"},
        {"name": "Jenny Bergner", "url": "https://astro.berkeley.edu/people/jenny-bergner"},
        {"name": "Eliot Quataert", "url": "https://astro.berkeley.edu/people/eliot-quataert"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Jenny Bergner", "Eliot Quataert"]


def test_output_shape_matches_other_faculty_collectors():
    jb = next(p for p in _scrape() if p["name"] == "Jenny Bergner")
    jb["email"] = "jbergner@berkeley.edu"
    jb["research_areas"] = "Star formation, exoplanets"
    opp = normalize_faculty(jb, ASTRO_CONFIG)
    assert opp["source"] == "ucb_astro_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-astro-")
    assert opp["contact_email"] == "jbergner@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ASTRO_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ASTRO_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    eq = next(p for p in _scrape() if p["name"] == "Eliot Quataert")  # no email/research
    opp = normalize_faculty(eq, ASTRO_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["astronomy"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole ASTRO
    corpus on the next scrape. Pin a real corpus id."""
    jb = next(p for p in _scrape() if p["name"] == "Jenny Bergner")
    assert normalize_faculty(jb, ASTRO_CONFIG)["id"] == "faculty-ucb-astro-096e8176"
