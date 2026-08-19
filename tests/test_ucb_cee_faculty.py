"""Offline tests for src.collectors.ucb_cee_faculty.

No network: fixtures mirror CEE's real markup, a 3-column grid where each
professor is a span.views-field-field-faculty-info carrying name + profile link
+ rank AND inline "Research Interests:" text, while the email lives only on the
profile page (a mailto: link). Locks in the bespoke listing parser, listing
research-interest extraction, the no-interest fallback, profile email
extraction, dedup, the external-campus output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_cee_faculty import CEE_CONFIG, _scrape_cee_faculty_list
from src.collectors.ucb_common import (
    dedup_by_profile_url,
    extract_email_from_profile,
    normalize_faculty,
)

# One card with research interests, one without (to exercise the fallback).
# Name sits inside the <a> after a headshot <img>; the first non-label
# <span class="bold"> is the rank; a later "Research Interests:" label precedes
# the interest text in the same parent block.
LISTING_HTML = """
<div class="views-row clearfix row-1">
  <div class="views-col col-1">
    <div class="views-field views-field-nothing">
      <span class="field-content views-field-field-faculty-info">
        <div class="container-fluid">
          <div class="row"><div class="col-md-12">
            <span class="h4">
              <a href="/people/faculty/abrahamson" title="Norman Abrahamson Faculty Profile">
                <img alt="Abrahamson headshot" src="/x.jpg"/>Norman Abrahamson</a>
            </span>
          </div></div>
          <div class="row"><div class="col-md-12"><span class="bold">Adjunct Professor</span></div></div>
          <div class="row"><div class="col-md-12">GeoSystems Engineering</div></div>
          <div class="row"><div class="col-md-12 tp-spacer">
            <span class="bold">Research Interests:</span>
            Earthquake ground motions, spectral attenuation relations
          </div></div>
        </div>
      </span>
    </div>
  </div>
  <div class="views-col col-2">
    <div class="views-field views-field-nothing">
      <span class="field-content views-field-field-faculty-info">
        <div class="container-fluid">
          <div class="row"><div class="col-md-12">
            <span class="h4">
              <a href="/people/faculty/no-interests"><img alt="x"/>Jane Builder</a>
            </span>
          </div></div>
          <div class="row"><div class="col-md-12"><span class="bold">Professor</span></div></div>
        </div>
      </span>
    </div>
  </div>
</div>
"""

PROFILE_HTML = """
<div class="node">
  <a href="mailto:abrahamson@berkeley.edu">abrahamson@berkeley.edu</a>
</div>
"""

PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_cee_faculty_list(soup, CEE_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    norm = next(p for p in people if p["name"] == "Norman Abrahamson")
    assert norm["title"] == "Adjunct Professor"  # first non-label bold, not "Research Interests:"
    assert norm["url"] == "https://ce.berkeley.edu/people/faculty/abrahamson"


def test_research_interests_extracted_from_listing():
    norm = next(p for p in _scrape() if p["name"] == "Norman Abrahamson")
    interests = norm["research_areas"]
    assert "Research Interests" not in interests  # label stripped
    assert "earthquake ground motions" in interests.lower()
    assert "spectral attenuation" in interests.lower()


def test_no_research_interest_card_omits_research_areas():
    jane = next(p for p in _scrape() if p["name"] == "Jane Builder")
    assert "research_areas" not in jane


def test_email_extracted_from_profile_mailto():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, CEE_CONFIG) == "abrahamson@berkeley.edu"


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, CEE_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Norman Abrahamson", "url": "https://ce.berkeley.edu/people/faculty/abrahamson"},
        {"name": "Norman Abrahamson", "url": "https://ce.berkeley.edu/people/faculty/abrahamson"},
        {"name": "Jane Builder", "url": "https://ce.berkeley.edu/people/faculty/no-interests"},
    ]
    out = dedup_by_profile_url(dupes)
    assert len(out) == 2
    assert [p["name"] for p in out] == ["Norman Abrahamson", "Jane Builder"]


def test_output_shape_matches_other_faculty_collectors():
    norm = next(p for p in _scrape() if p["name"] == "Norman Abrahamson")
    norm["email"] = "abrahamson@berkeley.edu"
    opp = normalize_faculty(norm, CEE_CONFIG)
    assert opp["source"] == "ucb_cee_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-cee-")
    assert opp["contact_email"] == "abrahamson@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == []
    # External campus, same as the other UCB collectors.
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""
    # Listing research text is preserved even when keywords fall back to broad.
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    jane = next(p for p in _scrape() if p["name"] == "Jane Builder")
    opp = normalize_faculty(jane, CEE_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["civil and environmental engineering"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole CEE
    corpus on the next scrape. Pin a real corpus id."""
    norm = next(p for p in _scrape() if p["name"] == "Norman Abrahamson")
    assert normalize_faculty(norm, CEE_CONFIG)["id"] == "faculty-ucb-cee-03e55076"


def test_cee_domain_terms_yield_topical_keywords():
    """KEYWORD_BANK carries civil/environmental terms so CEE records rank by
    topical fit instead of 58/64 of them sharing the broad department keyword
    (measured against the live directory when the bank was extended)."""
    person = {
        "name": "Test Professor",
        "url": "https://ce.berkeley.edu/people/faculty/test",
        "title": "Professor",
        "research_areas": "Geotechnical engineering, earthquake engineering, "
                          "transportation infrastructure, air quality modeling",
    }
    opp = normalize_faculty(person, CEE_CONFIG)
    for kw in ("geotechnical", "earthquake engineering", "transportation",
               "infrastructure", "air quality"):
        assert kw in opp["keywords"], kw
    assert "civil and environmental engineering" not in opp["keywords"]
