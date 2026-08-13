"""Offline tests for src.collectors.ucb_econ_faculty.

No network: fixtures mirror Economics's real markup — a Drupal teaser listing
(div.profile.teaser with name "Last, First" in div.display-name a and rank in
div.display-position) and a field-labeled profile (.field_value preceded by
"Email:"/"Fields:"/"Research:" labels). Locks in the teaser parser, the
Last,First name reformat, mailto email extraction, the Fields/Research join,
economics keyword mapping, dedup, output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_econ_faculty import (
    ECON_CONFIG,
    _reformat_name,
    _research_from_profile,
    _scrape_econ_faculty_list,
)


def _teaser(slug: str, name_last_first: str, position: str) -> str:
    return f"""
    <div class="views-row">
      <div about="/profile/{slug}" class="profile teaser view-mode--teaser_faculty">
        <div class="content-container"><div class="teaser_display">
          <div class="display-name"><a href="/profile/{slug}">{name_last_first}</a></div>
          <div class="display-position">{position}</div>
        </div></div>
      </div>
    </div>
    """


LISTING_HTML = f"""
<div class="view--people-faculty">
  {_teaser("matthew-backus", "Backus, Matthew", "Associate Professor")}
  {_teaser("stefano-dellavigna", "DellaVigna, Stefano", "Professor")}
</div>
"""

# Field-labeled profile: each value in a .field_value preceded by a label.
PROFILE_HTML = """
<div class="profile-full">
  <div class="row"><div class="field_label">Fields:</div><div class="field_value">Industrial Organization</div></div>
  <div class="row"><div class="field_label">Research:</div><div class="field_value">Antitrust, auctions, welfare economics</div></div>
  <div class="row"><div class="field_label">Email:</div><div class="field_value"><a href="mailto:backus@berkeley.edu">backus@berkeley.edu</a></div></div>
  <div class="row"><div class="field_label">Office:</div><div class="field_value">F685 Haas</div></div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="profile-full"><div class="field_value">No contact</div></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_econ_faculty_list(soup, ECON_CONFIG["base"])


def test_reformat_name_last_first_to_first_last():
    assert _reformat_name("Backus, Matthew") == "Matthew Backus"
    assert _reformat_name("DellaVigna, Stefano") == "Stefano DellaVigna"


def test_parses_name_position_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    backus = next(p for p in people if p["name"] == "Matthew Backus")
    assert backus["title"] == "Associate Professor"
    assert backus["url"] == "https://www.econ.berkeley.edu/profile/matthew-backus"


def test_email_and_fields_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    from src.collectors.ucb_common import extract_email_from_profile
    assert extract_email_from_profile(soup, ECON_CONFIG) == "backus@berkeley.edu"
    research = _research_from_profile(soup)
    # joins Fields + Research; Office/Email labels excluded.
    assert "Industrial Organization" in research
    assert "antitrust" in research.lower()
    assert "Haas" not in research


def test_research_yields_economics_keywords():
    person = {"name": "Matthew Backus", "url": "x", "title": "Professor",
              "research_areas": "Industrial organization; antitrust, auctions, welfare economics"}
    opp = normalize_faculty(person, ECON_CONFIG)
    for kw in ("industrial organization", "antitrust", "auctions", "welfare economics"):
        assert kw in opp["keywords"], kw
    # Topical terms present (not only the broad fallback). "economics" itself is
    # a legitimate banked term that also appears in "welfare economics".


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Matthew Backus", "url": "https://www.econ.berkeley.edu/profile/matthew-backus"},
        {"name": "Matthew Backus", "url": "https://www.econ.berkeley.edu/profile/matthew-backus"},
        {"name": "Stefano DellaVigna", "url": "https://www.econ.berkeley.edu/profile/stefano-dellavigna"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Matthew Backus", "Stefano DellaVigna"]


def test_output_shape_matches_other_faculty_collectors():
    backus = next(p for p in _scrape() if p["name"] == "Matthew Backus")
    backus["email"] = "backus@berkeley.edu"
    backus["research_areas"] = "Industrial organization, antitrust"
    opp = normalize_faculty(backus, ECON_CONFIG)
    assert opp["source"] == "ucb_econ_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-econ-")
    assert opp["contact_email"] == "backus@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ECON_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ECON_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    dv = next(p for p in _scrape() if p["name"] == "Stefano DellaVigna")  # no email/research
    opp = normalize_faculty(dv, ECON_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["economics"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole ECON
    corpus on the next scrape. Pin a real corpus id."""
    backus = next(p for p in _scrape() if p["name"] == "Matthew Backus")
    assert normalize_faculty(backus, ECON_CONFIG)["id"] == "faculty-ucb-econ-0609a603"
