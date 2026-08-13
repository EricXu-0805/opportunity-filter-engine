"""Offline tests for src.collectors.ucb_bioe_faculty.

No network: fixtures mirror BioE's real markup — a Beaver Builder grid where
each professor is a div.fl-post-grid-post.persontype-faculty card with name +
profile link in h3.fl-post-title a, rank in p.professor-title, and research
area(s) encoded as research-area-<slug> CSS classes. Email lives only on the
profile page (a mailto: link). Locks in the bespoke listing parser, area-tag ->
keyword mapping, the no-area fallback, emeritus skipping, profile email
extraction, dedup, the external-campus output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_bioe_faculty import (
    BIOE_CONFIG,
    _research_from_profile,
    _scrape_bioe_faculty_list,
)
from src.collectors.ucb_common import (
    dedup_by_profile_url,
    extract_email_from_profile,
    normalize_faculty,
)

# Profile renders the lab description in a Beaver Builder accordion whose button
# label is "Research Description"; the prose is in the item's content panel.
PROFILE_WITH_RESEARCH_HTML = """
<div class="fl-accordion">
  <div class="fl-accordion-item">
    <a class="fl-accordion-button-label">Research Description</a>
    <div class="fl-accordion-content"><p>Anderson Lab develops new applications and
    tools for the Synthetic Biology community.</p></div>
  </div>
  <div class="fl-accordion-item">
    <a class="fl-accordion-button-label">Education</a>
    <div class="fl-accordion-content"><p>PhD, Caltech</p></div>
  </div>
</div>
"""
PROFILE_NO_RESEARCH_HTML = """
<div class="fl-accordion"><div class="fl-accordion-item">
  <a class="fl-accordion-button-label">Education</a>
  <div class="fl-accordion-content"><p>PhD, MIT</p></div>
</div></div>
"""


def test_research_description_extracted_from_accordion():
    soup = BeautifulSoup(PROFILE_WITH_RESEARCH_HTML, "html.parser")
    research = _research_from_profile(soup)
    assert "Anderson Lab" in research
    assert "Synthetic Biology" in research
    assert "PhD" not in research  # only the Research Description panel, not Education


def test_no_research_accordion_returns_empty():
    soup = BeautifulSoup(PROFILE_NO_RESEARCH_HTML, "html.parser")
    assert _research_from_profile(soup) == ""


def _card(slug_part: str, name: str, title: str, area_classes: str = "") -> str:
    return f"""
    <div class="fl-post-grid-post persontype-faculty {area_classes}">
      <div class="faculty-container">
        <div class="fl-post-text">
          <h3 class="fl-post-title">
            <a href="/person/{slug_part}" title="{name}">{name}</a>
          </h3>
          <p class="professor-title">{title}</p>
        </div>
      </div>
    </div>
    """


# Two faculty (one multi-area, one no-area) + one emeritus that must be skipped.
LISTING_HTML = f"""
<div class="fl-post-grid">
  {_card("j-christopher-anderson", "J. Christopher Anderson", "Associate Professor", "research-area-compbio")}
  {_card("adam-arkin", "Adam Arkin", "Professor", "research-area-compbio research-area-synbio")}
  {_card("jane-noarea", "Jane Noarea", "Assistant Professor")}
  {_card("old-timer", "Old Timer", "Professor Emeritus", "persontype-emeritus research-area-cell-tissue")}
</div>
"""

PROFILE_HTML = '<div class="node"><a href="mailto: jcanderson@berkeley.edu">email</a></div>'
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_bioe_faculty_list(soup, BIOE_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    anderson = next(p for p in people if p["name"] == "J. Christopher Anderson")
    assert anderson["title"] == "Associate Professor"
    assert anderson["url"] == "https://bioeng.berkeley.edu/person/j-christopher-anderson"


def test_emeritus_card_is_skipped():
    names = {p["name"] for p in _scrape()}
    assert "Old Timer" not in names
    assert names == {"J. Christopher Anderson", "Adam Arkin", "Jane Noarea"}


def test_research_area_slugs_mapped_to_readable_names():
    arkin = next(p for p in _scrape() if p["name"] == "Adam Arkin")
    # two area classes -> two readable areas, joined.
    assert arkin["research_areas"] == "Computational Biology; Synthetic Biology"


def test_no_area_card_omits_research_areas():
    jane = next(p for p in _scrape() if p["name"] == "Jane Noarea")
    assert "research_areas" not in jane


def test_area_tags_yield_topical_keywords():
    arkin = next(p for p in _scrape() if p["name"] == "Adam Arkin")
    opp = normalize_faculty(arkin, BIOE_CONFIG)
    for kw in ("computational biology", "synthetic biology", "bioinformatics"):
        assert kw in opp["keywords"], kw
    assert "bioengineering" not in opp["keywords"]  # not the broad fallback


def test_email_extracted_from_profile_mailto_with_leading_space():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    # BioE profiles write "mailto: addr" (note the space) — must be stripped.
    assert extract_email_from_profile(soup, BIOE_CONFIG) == "jcanderson@berkeley.edu"


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, BIOE_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Adam Arkin", "url": "https://bioeng.berkeley.edu/person/adam-arkin"},
        {"name": "Adam Arkin", "url": "https://bioeng.berkeley.edu/person/adam-arkin"},
        {"name": "Jane Noarea", "url": "https://bioeng.berkeley.edu/person/jane-noarea"},
    ]
    out = dedup_by_profile_url(dupes)
    assert len(out) == 2
    assert [p["name"] for p in out] == ["Adam Arkin", "Jane Noarea"]


def test_output_shape_matches_other_faculty_collectors():
    anderson = next(p for p in _scrape() if p["name"] == "J. Christopher Anderson")
    anderson["email"] = "jcanderson@berkeley.edu"
    opp = normalize_faculty(anderson, BIOE_CONFIG)
    assert opp["source"] == "ucb_bioe_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-bioe-")
    assert opp["contact_email"] == "jcanderson@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == BIOE_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == BIOE_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    jane = next(p for p in _scrape() if p["name"] == "Jane Noarea")
    opp = normalize_faculty(jane, BIOE_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["bioengineering"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole BioE
    corpus on the next scrape. Pin a real corpus id."""
    anderson = next(p for p in _scrape() if p["name"] == "J. Christopher Anderson")
    assert normalize_faculty(anderson, BIOE_CONFIG)["id"] == "faculty-ucb-bioe-9129089a"
