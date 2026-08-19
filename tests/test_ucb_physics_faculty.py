"""Offline tests for src.collectors.ucb_physics_faculty.

No network: fixtures mirror Physics's per-area pages (the same Open-Berkeley
card variant as Chemistry: div.node-openberkeley-person, name in <h2>, href on
a /people/faculty/ link) and a profile page (personal mailto + the department
admin mailto). Locks in card parsing, faculty-only filtering, the multi-area
merge, area->keyword mapping, email extraction that skips the admin address,
output shape, lite fallback, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.collectors.ucb_physics_faculty as mod
from src.collectors.ucb_common import (
    extract_email_from_profile,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)
from src.collectors.ucb_physics_faculty import PHYS_CONFIG, _scrape_physics_faculty


def _person_card(slug: str, name: str, title: str, path: str = "people/faculty") -> str:
    return f"""
    <div class="node node-openberkeley-person node-view--card">
      <a href="/{path}/{slug}">
        <h2>{name}</h2>
        <div class="field-name-field-openberkeley-person-title">
          <div class="field-items"><div class="field-item even">{title}</div></div>
        </div>
      </a>
    </div>
    """


# An area page with one faculty card + one grad-student card (must be filtered).
AREA_HTML = f"""
<div class="openberkeley-card-grid">
  {_person_card("ehud-altman", "Ehud Altman", "Professor")}
  {_person_card("some-student", "Some Student", "Graduate Student", path="people/graduate-student")}
</div>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:ehud.altman@berkeley.edu">x</a></div>
  <footer><a href="mailto:physics_admin@berkeley.edu">admin</a></footer>
</div>
"""

# Non-Berkeley personal address listed before the admin one.
PROFILE_LBL_HTML = """
<div class="node">
  <a href="mailto:someprof@lbl.gov">x</a>
  <a href="mailto:physics_admin@berkeley.edu">admin</a>
</div>
"""


def test_card_parse_and_faculty_only_filter():
    soup = BeautifulSoup(AREA_HTML, "html.parser")
    people = scrape_open_berkeley_faculty(soup, PHYS_CONFIG)
    fac = [p for p in people if "/people/faculty/" in p["url"]]
    assert len(fac) == 1
    assert fac[0]["name"] == "Ehud Altman"
    assert fac[0]["title"] == "Professor"
    assert fac[0]["url"] == "https://physics.berkeley.edu/people/faculty/ehud-altman"


def test_multi_area_merge(monkeypatch):
    # Serve the same Altman card for two area slugs; None for the rest.
    def fake_fetch(url):
        if url.endswith(("/astrophysics", "/condensed-matter")):
            return BeautifulSoup(AREA_HTML, "html.parser")
        return None
    monkeypatch.setattr(mod, "fetch_soup", fake_fetch)
    people = _scrape_physics_faculty()
    assert len(people) == 1  # one unique faculty across the two areas
    areas = people[0]["research_areas"]
    assert "Astrophysics" in areas and "Condensed Matter Physics" in areas


def test_area_tag_yields_topical_keywords():
    person = {"name": "Ehud Altman", "url": "x", "title": "Professor",
              "research_areas": "Condensed Matter Physics; Quantum Information Science"}
    opp = normalize_faculty(person, PHYS_CONFIG)
    for kw in ("condensed matter", "materials science", "quantum"):
        assert kw in opp["keywords"], kw
    assert "physics" not in opp["keywords"]  # not the broad fallback


def test_email_extracted_and_admin_skipped():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, PHYS_CONFIG) == "ehud.altman@berkeley.edu"


def test_admin_not_promoted_over_nonberkeley_personal():
    soup = BeautifulSoup(PROFILE_LBL_HTML, "html.parser")
    # physics_admin@berkeley.edu is in NOISE_EMAILS, so the lbl.gov address wins.
    assert extract_email_from_profile(soup, PHYS_CONFIG) == "someprof@lbl.gov"


def test_output_shape_matches_other_faculty_collectors():
    person = {"name": "Ehud Altman", "url": "https://physics.berkeley.edu/people/faculty/ehud-altman",
              "title": "Professor", "research_areas": "Condensed Matter Physics",
              "email": "ehud.altman@berkeley.edu"}
    opp = normalize_faculty(person, PHYS_CONFIG)
    assert opp["source"] == "ucb_physics_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-phys-")
    assert opp["contact_email"] == "ehud.altman@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == []
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""
    assert opp["metadata"]["research_areas_raw"]


def test_emeritus_dropped_by_title():
    person = {"name": "Old Prof", "url": "x", "title": "Professor Emeritus",
              "research_areas": "Astrophysics"}
    assert normalize_faculty(person, PHYS_CONFIG) is None


def test_lite_record_falls_back_to_broad_keyword():
    person = {"name": "Bare Prof", "url": "x", "title": "Professor"}  # no email/areas
    opp = normalize_faculty(person, PHYS_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["physics"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole PHYS
    corpus on the next scrape. Pin a real corpus id."""
    person = {"name": "Ehud Altman", "url": "x", "title": "Professor"}
    assert normalize_faculty(person, PHYS_CONFIG)["id"] == "faculty-ucb-phys-3ec7499e"
