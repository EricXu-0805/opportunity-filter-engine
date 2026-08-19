"""Offline tests for src.collectors.ucb_polisci_faculty.

No network: fixtures mirror Political Science's real markup — a Drupal
field-based listing (div.views-row with name in div.field--name-realname a and
rank in div.field--name-field-user-title) and a profile carrying a mailto:
email plus a div.field--name-field-research-interests block. Locks in the
listing parser, mailto email + research extraction, the political-science
keyword mapping, dedup, output shape, and id stability.
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
)
from src.collectors.ucb_polisci_faculty import (
    POLISCI_CONFIG,
    _scrape_polisci_faculty_list,
)


def _row(slug: str, name: str, title: str) -> str:
    return f"""
    <div class="views-row">
      <article about="/people/person/{slug}">
        <div class="user_header">
          <div class="field field--name-realname"><h2 class="field__item"><a href="/people/person/{slug}">{name}</a></h2></div>
          <div class="field field--name-field-user-title field__item">{title}</div>
        </div>
      </article>
    </div>
    """


LISTING_HTML = f"""
<div class="view--people-">
  {_row("vinod-k-aggarwal", "Vinod Aggarwal", "Distinguished Professor")}
  {_row("sarah-anzia", "Sarah Anzia", "Professor")}
</div>
"""

PROFILE_HTML = """
<div class="profile">
  <a href="mailto:vinod@berkeley.edu">vinod@berkeley.edu</a>
  <div class="field field--name-field-research-interests">
    <div class="field__label">Research Interests</div>
    <div class="field__items">
      <div class="field__item">International Political Economy</div>
      <div class="field__item">Comparative Regionalism</div>
    </div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="profile"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_polisci_faculty_list(soup, POLISCI_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    assert len(people) == 2
    vinod = next(p for p in people if p["name"] == "Vinod Aggarwal")
    assert vinod["title"] == "Distinguished Professor"
    assert vinod["url"] == "https://polisci.berkeley.edu/people/person/vinod-k-aggarwal"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, POLISCI_CONFIG) == "vinod@berkeley.edu"
    interests = extract_research_interests(soup, POLISCI_CONFIG)
    assert "Research Interests" not in interests  # label excluded by .field__item
    assert "international political economy" in interests.lower()


def test_research_yields_political_science_keywords():
    person = {"name": "Vinod Aggarwal", "url": "x", "title": "Professor",
              "research_areas": "International political economy; comparative politics; political theory"}
    opp = normalize_faculty(person, POLISCI_CONFIG)
    for kw in ("international political economy", "comparative politics", "political theory"):
        assert kw in opp["keywords"], kw


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, POLISCI_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Vinod Aggarwal", "url": "https://polisci.berkeley.edu/people/person/vinod-k-aggarwal"},
        {"name": "Vinod Aggarwal", "url": "https://polisci.berkeley.edu/people/person/vinod-k-aggarwal"},
        {"name": "Sarah Anzia", "url": "https://polisci.berkeley.edu/people/person/sarah-anzia"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Vinod Aggarwal", "Sarah Anzia"]


def test_output_shape_matches_other_faculty_collectors():
    vinod = next(p for p in _scrape() if p["name"] == "Vinod Aggarwal")
    vinod["email"] = "vinod@berkeley.edu"
    vinod["research_areas"] = "International political economy"
    opp = normalize_faculty(vinod, POLISCI_CONFIG)
    assert opp["source"] == "ucb_polisci_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-polisci-")
    assert opp["contact_email"] == "vinod@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == []
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    anzia = next(p for p in _scrape() if p["name"] == "Sarah Anzia")  # no email/research
    opp = normalize_faculty(anzia, POLISCI_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["political science"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole
    POLISCI corpus on the next scrape. Pin a real corpus id."""
    vinod = next(p for p in _scrape() if p["name"] == "Vinod Aggarwal")
    assert normalize_faculty(vinod, POLISCI_CONFIG)["id"] == "faculty-ucb-polisci-8b2cafe0"
