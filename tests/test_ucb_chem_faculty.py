"""Offline tests for src.collectors.ucb_chem_faculty.

No network: fixtures mirror Chemistry's real Open-Berkeley markup, which differs
from Statistics — listing cards are div.node-openberkeley-person with the name
in an <h2> and the href on the wrapping <a> (separate name/link selectors), and
profiles carry a mailto: email plus a free-text resint research block. Locks in
the selector-driven parser, profile email + research-interest enrichment, the
external-campus schema, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_chem_faculty import CHEM_CONFIG
from src.collectors.ucb_common import (
    extract_email_from_profile,
    extract_research_interests,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)

# Two faculty cards (name in <h2>, href on the wrapping <a>) plus a non-person
# card lacking a /people/ link, which must be skipped.
LISTING_HTML = """
<div class="view-content">
  <div class="node node-openberkeley-person node-view--card row">
    <div class="content col-md-12">
      <a href="/people/brooks-abel">
        <h2>Brooks Abel</h2>
        <div class="field field-name-field-openberkeley-person-title field-label-hidden">
          <div class="field-items"><div class="field-item even">Assistant Professor of Chemistry</div></div>
        </div>
      </a>
    </div>
  </div>
  <div class="node node-openberkeley-person node-view--card row">
    <div class="content col-md-12">
      <a href="/people/anne-baranger">
        <h2>Anne Baranger</h2>
        <div class="field field-name-field-openberkeley-person-title field-label-hidden">
          <div class="field-items"><div class="field-item even">Professor of Chemistry</div></div>
        </div>
      </a>
    </div>
  </div>
  <div class="node node-openberkeley-person node-view--card row">
    <div class="content col-md-12">
      <a href="/about/some-page"><h2>Not A Person</h2></a>
    </div>
  </div>
</div>
"""

# Real profile structure: mailto: email + a free-text resint block whose
# .field-item value is preceded by a "Research:" label that must be excluded.
PROFILE_HTML = """
<article class="node-openberkeley-person">
  <div class="field field-name-field-openberkeley-person-email field-type-email">
    <a href="mailto:brooks.abel@berkeley.edu">brooks.abel@berkeley.edu</a>
  </div>
  <div class="field field-name-field-openberkeley-person-resint field-type-text-long field-label-inline">
    <div class="field-label">Research:</div>
    <div class="field-items"><div class="field-item even">Polymer chemistry, organic
    chemistry, stereoselective catalysis, and polymer recycling.</div></div>
  </div>
</article>
"""

PROFILE_NO_RESEARCH_HTML = """
<article class="node-openberkeley-person">
  <div class="field field-name-field-openberkeley-person-email field-type-email">
    <a href="mailto:someone@berkeley.edu">someone@berkeley.edu</a>
  </div>
</article>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, CHEM_CONFIG)


def test_parser_handles_separate_name_and_link_selectors():
    people = _scrape()
    # The card without a /people/ link is skipped.
    assert len(people) == 2
    abel = next(p for p in people if p["name"] == "Brooks Abel")
    assert abel["title"] == "Assistant Professor of Chemistry"
    assert abel["url"] == "https://chemistry.berkeley.edu/people/brooks-abel"


def test_email_extracted_from_mailto():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, CHEM_CONFIG) == "brooks.abel@berkeley.edu"


def test_research_interests_extracted_without_label():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    interests = extract_research_interests(soup, CHEM_CONFIG)
    assert "Research:" not in interests  # label excluded by .field-item
    assert "organic" in interests.lower() and "catalysis" in interests.lower()


def test_no_research_section_returns_empty():
    soup = BeautifulSoup(PROFILE_NO_RESEARCH_HTML, "html.parser")
    assert extract_research_interests(soup, CHEM_CONFIG) == ""


def test_normalize_produces_chem_record_with_keywords():
    abel = next(p for p in _scrape() if p["name"] == "Brooks Abel")
    abel["email"] = "brooks.abel@berkeley.edu"
    abel["research_areas"] = "Polymer chemistry, organic chemistry, stereoselective catalysis"
    opp = normalize_faculty(abel, CHEM_CONFIG)
    assert opp["source"] == "ucb_chem_faculty"
    assert opp["id"].startswith("faculty-ucb-chem-")
    assert opp["contact_email"] == "brooks.abel@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == CHEM_CONFIG["majors"]
    # research-interest enrichment yields topical keywords, not the lite fallback.
    assert "organic chemistry" in opp["keywords"]
    assert "catalysis" in opp["keywords"]
    # external campus, same as the other UCB collectors.
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"


def test_lite_record_falls_back_to_broad_keyword():
    # No email, no research areas -> lite record with broad department keyword.
    baranger = next(p for p in _scrape() if p["name"] == "Anne Baranger")
    opp = normalize_faculty(baranger, CHEM_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["chemistry"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole CHEM
    corpus on the next scrape. Pin a real corpus id."""
    abel = next(p for p in _scrape() if p["name"] == "Brooks Abel")
    assert normalize_faculty(abel, CHEM_CONFIG)["id"] == "faculty-ucb-chem-988f716c"
