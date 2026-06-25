"""Offline tests for src.collectors.ucb_socwel_faculty.

No network: fixtures mirror Social Welfare's real markup — the Open-Berkeley card
variant with the name in an <h3> (like NST), and profiles that carry a mailto:
email and a free-text `resint` research block. The directory mixes in emeritus
faculty (dropped by the shared title filter). Locks in the shared selector-driven
parser for the SOCWEL config (h3 name), email + research extraction, social-work
keyword mapping, the emeritus drop, dedup, the external-campus output shape, and
id stability.
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
from src.collectors.ucb_socwel_faculty import SOCWEL_CONFIG


def _card(slug: str, name: str, title: str) -> str:
    return f"""
    <div class="node node-openberkeley-person node-view--card row">
      <div class="content col-md-12">
        <a href="/people/{slug}">
          <div class="openberkeley-featured-image"></div>
          <h3>{name}</h3>
          <div class="field field-name-field-openberkeley-person-title field-label-hidden">
            <div class="field-items"><div class="field-item even">{title}</div></div>
          </div>
        </a>
      </div>
    </div>
    """


# Two active faculty + one emeritus (dropped by the shared title filter).
LISTING_HTML = f"""
<div class="view-content">
  {_card("jill-duerr-berrick", "Jill Duerr Berrick", "Distinguished Professor")}
  {_card("yu-ling-chang", "Yu-Ling Chang", "Associate Professor")}
  {_card("old-timer", "Old Timer", "Emeritus Professor")}
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field field-name-field-openberkeley-person-email"><a href="mailto:dberrick@berkeley.edu">dberrick@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research interests:</div>
    <div class="field-items"><div class="field-item even"><p>Child welfare, family policy, child poverty, foster care</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact listed.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return scrape_open_berkeley_faculty(soup, SOCWEL_CONFIG)


def test_parses_h3_name_title_and_absolute_profile_link():
    people = _scrape()
    jill = next(p for p in people if p["name"] == "Jill Duerr Berrick")
    assert jill["title"] == "Distinguished Professor"
    assert jill["url"] == "https://socialwelfare.berkeley.edu/people/jill-duerr-berrick"


def test_email_and_research_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, SOCWEL_CONFIG) == "dberrick@berkeley.edu"
    interests = extract_research_interests(soup, SOCWEL_CONFIG)
    assert "Research interests" not in interests  # label stripped
    assert "foster care" in interests.lower()


def test_research_yields_social_work_keywords():
    person = {"name": "Jill Duerr Berrick", "url": "x", "title": "Professor",
              "research_areas": "Child welfare, family policy, child poverty, foster care, child abuse"}
    opp = normalize_faculty(person, SOCWEL_CONFIG)
    for kw in ("child welfare", "family policy", "poverty", "foster care", "child abuse"):
        assert kw in opp["keywords"], kw
    assert "social welfare" not in opp["keywords"]  # not the broad fallback


def test_emeritus_dropped_by_title():
    opps = [normalize_faculty(p, SOCWEL_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert "Old Timer" not in names  # "Emeritus Professor" -> dropped
    assert names == {"Jill Duerr Berrick", "Yu-Ling Chang"}


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, SOCWEL_CONFIG) is None


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Jill Duerr Berrick", "url": "https://socialwelfare.berkeley.edu/people/jill-duerr-berrick"},
        {"name": "Jill Duerr Berrick", "url": "https://socialwelfare.berkeley.edu/people/jill-duerr-berrick"},
        {"name": "Yu-Ling Chang", "url": "https://socialwelfare.berkeley.edu/people/yu-ling-chang"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Jill Duerr Berrick", "Yu-Ling Chang"]


def test_output_shape_matches_other_faculty_collectors():
    jill = next(p for p in _scrape() if p["name"] == "Jill Duerr Berrick")
    jill["email"] = "dberrick@berkeley.edu"
    jill["research_areas"] = "Child welfare, family policy, poverty"
    opp = normalize_faculty(jill, SOCWEL_CONFIG)
    assert opp["source"] == "ucb_socwel_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-socwel-")
    assert opp["contact_email"] == "dberrick@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == SOCWEL_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == SOCWEL_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    chang = next(p for p in _scrape() if p["name"] == "Yu-Ling Chang")  # no email/research
    opp = normalize_faculty(chang, SOCWEL_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["social welfare"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole Social
    Welfare corpus on the next scrape. Pin a real corpus id."""
    jill = next(p for p in _scrape() if p["name"] == "Jill Duerr Berrick")
    assert normalize_faculty(jill, SOCWEL_CONFIG)["id"] == "faculty-ucb-socwel-d4fc7298"
