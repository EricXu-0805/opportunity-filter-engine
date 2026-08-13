"""Offline tests for src.collectors.ucb_larch_faculty.

No network: fixtures mirror CED's real markup — each person is an
`a[href=/people/<slug>]` wrapping a `.people-listing` photo, a `div.font-bold`
name, and a title div; the page mixes professors, lecturers, PhD students,
advisors, and staff. Profiles are a two-column layout whose "SPECIALIZATIONS"
label column has its value in the sibling div, plus a mailto: email. Locks in the
role filter (Professor/Lecturer only), the emeritus drop, the two-column
specialization extraction, email extraction, landscape/planning keyword mapping,
dedup, the output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_larch_faculty import (
    LARCH_CONFIG,
    _email_from_profile,
    _scrape_larch_faculty_list,
    _specializations_from_profile,
)


def _card(slug: str, name: str, title: str) -> str:
    return f"""
    <a class="mb-8 no-underline" href="https://ced.berkeley.edu/people/{slug}">
      <div class="flex w-full">
        <div class="people-listing w-40"><picture><img alt="{name}"/></picture></div>
        <div class="w-full pl-4">
          <div class="font-bold text-lg underline">{name}</div>
          <div class="text-sm">{title}</div>
        </div>
      </div>
    </a>
    """


LISTING_HTML = f"""
<div class="sm:grid grid-cols-2 lg:grid-cols-3">
  {_card("richard-hindle", "Richard Hindle", "Associate Professor of Landscape Architecture")}
  {_card("danika-cooper", "Danika Cooper", "Associate Professor of Landscape Architecture")}
  {_card("jane-lecturer", "Jane Lecturer", "Lecturer in Landscape Architecture")}
  {_card("old-prof", "Old Prof", "Professor Emeritus of Landscape Architecture")}
  {_card("sam-phd", "Sam Phd", "PhD Student")}
  {_card("blake-mgr", "Blake Manager", "Blake Garden Manager")}
</div>
"""

PROFILE_HTML = """
<div class="person">
  <div class="contact"><a href="mailto:rlhindle@berkeley.edu">rlhindle@berkeley.edu</a></div>
  <div class="flex">
    <div class="text-20 uppercase"><h2 class="text-20">SPECIALIZATIONS</h2></div>
    <div class="xl:w-full"><p>Green infrastructure, ecological restoration, landscape design.</p></div>
  </div>
</div>
"""
PROFILE_NO_SPEC = '<div><a href="mailto:cooper@berkeley.edu">cooper@berkeley.edu</a></div>'
PROFILE_NO_EMAIL = '<div class="person"><p>No contact.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_larch_faculty_list(soup, LARCH_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    hindle = next(p for p in people if p["name"] == "Richard Hindle")
    assert hindle["title"] == "Associate Professor of Landscape Architecture"
    assert hindle["url"] == "https://ced.berkeley.edu/people/richard-hindle"


def test_non_faculty_roles_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Richard Hindle", "Danika Cooper", "Jane Lecturer", "Old Prof"}
    assert "Sam Phd" not in names         # PhD Student
    assert "Blake Manager" not in names   # Blake Garden Manager (staff)


def test_emeritus_dropped_at_normalize():
    opps = [normalize_faculty(p, LARCH_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert "Old Prof" not in names  # "Professor Emeritus" -> dropped
    assert names == {"Richard Hindle", "Danika Cooper", "Jane Lecturer"}


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Richard Hindle", "url": "https://ced.berkeley.edu/people/richard-hindle"},
        {"name": "Richard Hindle", "url": "https://ced.berkeley.edu/people/richard-hindle"},
        {"name": "Danika Cooper", "url": "https://ced.berkeley.edu/people/danika-cooper"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Richard Hindle", "Danika Cooper"]


def test_specializations_extracted_from_value_column():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    spec = _specializations_from_profile(soup)
    assert "SPECIALIZATIONS" not in spec
    assert "ecological restoration" in spec.lower()


def test_no_specializations_section_yields_empty():
    soup = BeautifulSoup(PROFILE_NO_SPEC, "html.parser")
    assert _specializations_from_profile(soup) == ""


def test_email_from_profile_and_none_when_absent():
    assert _email_from_profile(BeautifulSoup(PROFILE_HTML, "html.parser")) == "rlhindle@berkeley.edu"
    assert _email_from_profile(BeautifulSoup(PROFILE_NO_EMAIL, "html.parser")) is None


def test_specialization_yields_topical_keywords():
    person = {"name": "Richard Hindle", "url": "x", "title": "Professor",
              "research_areas": "Green infrastructure, ecological restoration, landscape design."}
    opp = normalize_faculty(person, LARCH_CONFIG)
    for kw in ("green infrastructure", "ecological restoration", "landscape design"):
        assert kw in opp["keywords"], kw
    assert "landscape architecture" not in opp["keywords"]  # not the broad fallback


def test_output_shape_matches_other_faculty_collectors():
    hindle = next(p for p in _scrape() if p["name"] == "Richard Hindle")
    hindle["email"] = "rlhindle@berkeley.edu"
    hindle["research_areas"] = "Green infrastructure, landscape design"
    opp = normalize_faculty(hindle, LARCH_CONFIG)
    assert opp["source"] == "ucb_larch_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-laep-")
    assert opp["contact_email"] == "rlhindle@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == LARCH_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == LARCH_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    # No email, no research, and a title with no topical term -> broad fallback.
    person = {"name": "Pat Designer", "url": "x", "title": "Lecturer"}
    opp = normalize_faculty(person, LARCH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["landscape architecture"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole LAEP
    corpus on the next scrape. Pin a real corpus id."""
    hindle = next(p for p in _scrape() if p["name"] == "Richard Hindle")
    assert normalize_faculty(hindle, LARCH_CONFIG)["id"] == "faculty-ucb-laep-5f036cc3"
