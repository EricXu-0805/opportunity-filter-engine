"""Offline tests for src.collectors.ucb_education_faculty.

No network: fixtures mirror BSE's real markup — a grid of `div.fieldable-panels-pane`
cards (single profile `a[href]` + caption with the name in a `<strong>` and the
rank in an adjacent `openberkeley-widgets-label-inner`), and profiles carrying a
controlled `field-openberkeley-topics` tag set ("<Cluster> topic page") plus a
mailto: email. Locks in the pane parser (both caption layouts), the emeritus
drop, the topic-tag extraction (suffix stripped, "; "-joined), the area_keywords
cluster mapping, the name-matched email guard (rejects an assistant's address),
dedup, the output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_education_faculty import (
    EDUCATION_CONFIG,
    _personal_email,
    _scrape_education_faculty_list,
    _topics_from_profile,
)


def _pane_name_in_inner(slug: str, name: str, title: str) -> str:
    """Caption layout A: name <strong> sits inside the first inner div."""
    return f"""
    <div class="fieldable-panels-pane">
      <a href="https://bse.berkeley.edu/{slug}"><img alt="{name}"/></a>
      <div class="field field-name-field-basic-image-caption">
        <div class="field-items"><div class="field-item even">
          <div class="openberkeley-widgets-label">
            <div class="openberkeley-widgets-label-inner"><strong>{name}</strong></div>
            <div class="openberkeley-widgets-label-inner">{title}</div>
          </div>
        </div></div>
      </div>
    </div>
    """


def _pane_name_outside_inner(slug: str, name: str, title: str) -> str:
    """Caption layout B (e.g. Travis Bristol): the name <strong> is outside the
    inner divs; the single inner holds only the title."""
    return f"""
    <div class="fieldable-panels-pane">
      <a href="https://bse.berkeley.edu/{slug}"><img alt="{name}"/></a>
      <div class="field field-name-field-basic-image-caption">
        <strong>{name}</strong>
        <div class="openberkeley-widgets-label">
          <div class="openberkeley-widgets-label-inner">{title}</div>
        </div>
      </div>
    </div>
    """


LISTING_HTML = f"""
<div class="pane-content">
  {_pane_name_in_inner("dor-abrahamson", "Dor Abrahamson", "Professor")}
  {_pane_name_outside_inner("travis-j-bristol", "Travis J. Bristol", "Associate Professor")}
  {_pane_name_in_inner("old-timer", "Old Timer", "Professor Emeritus")}
  <div class="fieldable-panels-pane"><strong>No Link</strong></div>
  <div class="fieldable-panels-pane"><a href="https://bse.berkeley.edu/no-name"><img/></a></div>
</div>
"""

PROFILE_WITH_TOPICS = """
<div class="node">
  <div class="field field-name-field-basic-text-text"><div class="field-items"><div class="field-item even">
    <a href="mailto:dor@berkeley.edu">dor@berkeley.edu</a>
  </div></div></div>
  <div class="field field-name-field-openberkeley-topics field-type-taxonomy">
    <a href="/learning-sciences">Learning Sciences &amp; Human Development topic page</a>
  </div>
</div>
"""

# Only an assistant's address as the sole mailto: (no name token) -> rejected.
PROFILE_ASSISTANT_EMAIL = """
<div class="node">
  <div class="field field-name-field-basic-text-text"><div class="field-items"><div class="field-item even">
    <a href="mailto:annalisa.cf@berkeley.edu">annalisa.cf@berkeley.edu</a>
  </div></div></div>
  <div class="field field-name-field-openberkeley-topics">
    <a href="/x">Critical Studies of Race, Class, &amp; Gender topic page</a>
  </div>
</div>
"""

PROFILE_NO_TOPICS = (
    '<div class="node"><a href="mailto:glynda@berkeley.edu">glynda@berkeley.edu</a></div>'
)


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_education_faculty_list(soup, EDUCATION_CONFIG["base"])


def test_parses_name_from_strong_for_both_caption_layouts():
    people = _scrape()
    dor = next(p for p in people if p["name"] == "Dor Abrahamson")
    assert dor["title"] == "Professor"
    assert dor["url"] == "https://bse.berkeley.edu/dor-abrahamson"
    travis = next(p for p in people if p["name"] == "Travis J. Bristol")
    assert travis["title"] == "Associate Professor"  # name <strong> outside the inner
    assert travis["url"] == "https://bse.berkeley.edu/travis-j-bristol"


def test_emeritus_dropped_and_incomplete_panes_skipped():
    opps = [normalize_faculty(p, EDUCATION_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert names == {"Dor Abrahamson", "Travis J. Bristol"}
    assert "Old Timer" not in names  # "Professor Emeritus" -> dropped
    # The link-less pane and the strong-less pane are skipped by the parser.
    assert len(_scrape()) == 3  # Dor, Travis, Old Timer (emeritus dropped later)


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Dor Abrahamson", "url": "https://bse.berkeley.edu/dor-abrahamson"},
        {"name": "Dor Abrahamson", "url": "https://bse.berkeley.edu/dor-abrahamson"},
        {"name": "Travis J. Bristol", "url": "https://bse.berkeley.edu/travis-j-bristol"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Dor Abrahamson", "Travis J. Bristol"]


def test_topics_extracted_suffix_stripped_and_joined():
    soup = BeautifulSoup(PROFILE_WITH_TOPICS, "html.parser")
    assert _topics_from_profile(soup) == "Learning Sciences & Human Development"


def test_no_topics_field_yields_empty():
    soup = BeautifulSoup(PROFILE_NO_TOPICS, "html.parser")
    assert _topics_from_profile(soup) == ""


def test_cluster_tag_maps_to_education_keywords():
    person = {"name": "Dor Abrahamson", "url": "x", "title": "Professor",
              "research_areas": "Learning Sciences & Human Development"}
    opp = normalize_faculty(person, EDUCATION_CONFIG)
    for kw in ("learning sciences", "cognition and development", "child development"):
        assert kw in opp["keywords"], kw
    assert "education" not in opp["keywords"]  # not the broad fallback


def test_personal_email_accepts_name_match():
    soup = BeautifulSoup(PROFILE_WITH_TOPICS, "html.parser")
    assert _personal_email(soup, "Dor Abrahamson") == "dor@berkeley.edu"


def test_personal_email_rejects_assistant_address():
    soup = BeautifulSoup(PROFILE_ASSISTANT_EMAIL, "html.parser")
    # "annalisa.cf" carries no token of "Travis Bristol" -> no email (ships lite).
    assert _personal_email(soup, "Travis J. Bristol") is None


def test_output_shape_matches_other_faculty_collectors():
    dor = next(p for p in _scrape() if p["name"] == "Dor Abrahamson")
    dor["email"] = "dor@berkeley.edu"
    dor["research_areas"] = "Learning Sciences & Human Development"
    opp = normalize_faculty(dor, EDUCATION_CONFIG)
    assert opp["source"] == "ucb_education_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-educ-")
    assert opp["contact_email"] == "dor@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == EDUCATION_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == EDUCATION_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    # No email and no topic tags -> broad fallback.
    person = {"name": "Pat Educator", "url": "x", "title": "Lecturer"}
    opp = normalize_faculty(person, EDUCATION_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["education"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole
    Education corpus on the next scrape. Pin a real corpus id."""
    dor = next(p for p in _scrape() if p["name"] == "Dor Abrahamson")
    assert normalize_faculty(dor, EDUCATION_CONFIG)["id"] == "faculty-ucb-educ-8d0a8af2"
