"""Offline tests for src.collectors.ucb_math_faculty.

No network: fixtures mirror Math's real markup — the same Open-Berkeley card
variant as Chemistry (div.node-openberkeley-person, name in <h2>, href on a
/people/ link), and profiles that carry a mailto: email plus the department
front-office mailto and a free-text research-interests field. Locks in the
shared selector-driven parser for Math's config, email extraction (including
skipping the front-office address), research extraction, the no-research
fallback, dedup, the external-campus output shape, and id stability.
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
from src.collectors.ucb_math_faculty import MATH_CONFIG

LISTING_HTML = """
<div class="openberkeley-card-grid">
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/faculty/mina-aganagic">
      <h2>Mina Aganagic</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
  <div class="node node-openberkeley-person node-view--card">
    <a href="/people/faculty/ian-agol">
      <h2>Ian Agol</h2>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-items"><div class="field-item even">Professor</div></div>
      </div>
    </a>
  </div>
</div>
"""

# Personal mailto + the front-office mailto (must be skipped) + research field.
PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:mina@math.berkeley.edu">mina@math.berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research interests:</div>
    <div class="field-items"><div class="field-item even"><p><span>String theory, mathematical physics</span></p></div></div>
  </div>
  <footer><a href="mailto:frontoffice@math.berkeley.edu">front office</a></footer>
</div>
"""

# Non-Berkeley personal email listed before the front-office address: the
# extractor's berkeley-preference must NOT promote the front office over it.
PROFILE_NONBERKELEY_HTML = """
<div class="node">
  <a href="mailto:hbarcelo@msri.org">hbarcelo@msri.org</a>
  <a href="mailto:frontoffice@math.berkeley.edu">front office</a>
</div>
"""

PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, MATH_CONFIG)


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    mina = next(p for p in people if p["name"] == "Mina Aganagic")
    assert mina["title"] == "Professor"
    assert mina["url"] == "https://math.berkeley.edu/people/faculty/mina-aganagic"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, MATH_CONFIG) == "mina@math.berkeley.edu"
    interests = extract_research_interests(soup, MATH_CONFIG)
    assert "Research interests" not in interests  # label stripped by .field-item
    assert "string theory" in interests.lower()


def test_front_office_address_not_promoted_over_nonberkeley_personal():
    soup = BeautifulSoup(PROFILE_NONBERKELEY_HTML, "html.parser")
    # frontoffice@math.berkeley.edu is in NOISE_EMAILS, so the personal address wins.
    assert extract_email_from_profile(soup, MATH_CONFIG) == "hbarcelo@msri.org"


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, MATH_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Mina Aganagic", "url": "https://math.berkeley.edu/people/faculty/mina-aganagic"},
        {"name": "Mina Aganagic", "url": "https://math.berkeley.edu/people/faculty/mina-aganagic"},
        {"name": "Ian Agol", "url": "https://math.berkeley.edu/people/faculty/ian-agol"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Mina Aganagic", "Ian Agol"]


def test_output_shape_matches_other_faculty_collectors():
    mina = next(p for p in _scrape() if p["name"] == "Mina Aganagic")
    mina["email"] = "mina@math.berkeley.edu"
    mina["research_areas"] = "String theory, mathematical physics"
    opp = normalize_faculty(mina, MATH_CONFIG)
    assert opp["source"] == "ucb_math_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-math-")
    assert opp["contact_email"] == "mina@math.berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == MATH_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == MATH_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    ian = next(p for p in _scrape() if p["name"] == "Ian Agol")  # no email, no research
    opp = normalize_faculty(ian, MATH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["mathematics"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole MATH
    corpus on the next scrape. Pin a real corpus id."""
    mina = next(p for p in _scrape() if p["name"] == "Mina Aganagic")
    assert normalize_faculty(mina, MATH_CONFIG)["id"] == "faculty-ucb-math-ff32f072"
