"""Offline tests for src.collectors.ucb_psych_faculty.

No network: fixtures mirror Psychology's real markup — the same Open-Berkeley
card variant as Chemistry (div.node-openberkeley-person, name in <h2>, href on
a /people/ link), and profiles that carry a mailto: email and a free-text
research-interests field. Locks in the shared selector-driven parser for the
PSYCH config, email + research extraction, psychology keyword mapping, dedup,
the external-campus output shape, and id stability.
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
from src.collectors.ucb_psych_faculty import PSYCH_CONFIG

LISTING_HTML = """
<div class="openberkeley-card-grid">
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/mariam-aly">
      <h2>Mariam Aly</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Associate Professor</div></div>
      </div>
    </a>
  </div>
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/ozlem-ayduk">
      <h2>Ozlem Ayduk</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:mariamaly@berkeley.edu">mariamaly@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research interests:</div>
    <div class="field-items"><div class="field-item even"><p>Long-term memory, perception, attention</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, PSYCH_CONFIG)


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    aly = next(p for p in people if p["name"] == "Mariam Aly")
    assert aly["title"] == "Associate Professor"
    assert aly["url"] == "https://psychology.berkeley.edu/people/mariam-aly"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, PSYCH_CONFIG) == "mariamaly@berkeley.edu"
    interests = extract_research_interests(soup, PSYCH_CONFIG)
    assert "Research interests" not in interests
    assert "memory" in interests.lower()


def test_research_yields_psychology_keywords():
    person = {"name": "Mariam Aly", "url": "x", "title": "Professor",
              "research_areas": "Memory, perception, attention, cognitive neuroscience"}
    opp = normalize_faculty(person, PSYCH_CONFIG)
    for kw in ("memory", "perception", "attention", "cognitive neuroscience"):
        assert kw in opp["keywords"], kw
    assert "psychology" not in opp["keywords"]  # not the broad fallback


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, PSYCH_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Mariam Aly", "url": "https://psychology.berkeley.edu/people/mariam-aly"},
        {"name": "Mariam Aly", "url": "https://psychology.berkeley.edu/people/mariam-aly"},
        {"name": "Ozlem Ayduk", "url": "https://psychology.berkeley.edu/people/ozlem-ayduk"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Mariam Aly", "Ozlem Ayduk"]


def test_output_shape_matches_other_faculty_collectors():
    aly = next(p for p in _scrape() if p["name"] == "Mariam Aly")
    aly["email"] = "mariamaly@berkeley.edu"
    aly["research_areas"] = "Memory, perception"
    opp = normalize_faculty(aly, PSYCH_CONFIG)
    assert opp["source"] == "ucb_psych_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-psych-")
    assert opp["contact_email"] == "mariamaly@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == PSYCH_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == PSYCH_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    ayduk = next(p for p in _scrape() if p["name"] == "Ozlem Ayduk")  # no email/research
    opp = normalize_faculty(ayduk, PSYCH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["psychology"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole PSYCH
    corpus on the next scrape. Pin a real corpus id."""
    aly = next(p for p in _scrape() if p["name"] == "Mariam Aly")
    assert normalize_faculty(aly, PSYCH_CONFIG)["id"] == "faculty-ucb-psych-adf7bfeb"
