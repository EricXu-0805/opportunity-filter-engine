"""Offline tests for src.collectors.ucb_arch_faculty.

No network: fixtures mirror CED's real markup — each person is an
`a[href=/people/<slug>]` wrapping a `.people-listing` photo, a `div.font-bold`
name, and a title div; the page mixes professors, lecturers, PhD students,
advisors, and staff. Profiles are a two-column layout whose "SPECIALIZATIONS"
label column has its value in the sibling div, plus a mailto: email. Locks in the
role filter (Professor/Lecturer only), the emeritus drop, the two-column
specialization extraction, email extraction, architecture keyword mapping, dedup,
the output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_arch_faculty import (
    ARCH_CONFIG,
    _email_from_profile,
    _scrape_arch_faculty_list,
    _specializations_from_profile,
)
from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty


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
  {_card("lisa-iwamoto", "Lisa Iwamoto", "Chair and Professor of Architecture")}
  {_card("mark-anderson", "Mark Anderson", "Professor of Architecture")}
  {_card("jane-lecturer", "Jane Lecturer", "Continuing Lecturer in Architecture")}
  {_card("old-prof", "Old Prof", "Professor Emeritus of Architecture")}
  {_card("sam-phd", "Sam Phd", "PhD Candidate")}
  {_card("pat-advisor", "Pat Advisor", "Graduate Advisor, Architecture")}
  <a href="https://ced.berkeley.edu/people/no-photo"><div class="font-bold">No Photo Block</div><div>Professor</div></a>
</div>
"""

# Two-column profile: SPECIALIZATIONS label column + value sibling, plus mailto.
PROFILE_HTML = """
<div class="person">
  <div class="contact"><a href="mailto:liwamoto@berkeley.edu">liwamoto@berkeley.edu</a></div>
  <div class="flex">
    <div class="text-20 uppercase"><h2 class="text-20">SPECIALIZATIONS</h2></div>
    <div class="xl:w-full"><p>Design, materials research, and digital fabrication</p></div>
  </div>
</div>
"""
PROFILE_NO_SPEC = '<div><a href="mailto:markand@berkeley.edu">markand@berkeley.edu</a></div>'
PROFILE_NO_EMAIL = '<div class="person"><p>No contact.</p></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_arch_faculty_list(soup, ARCH_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    lisa = next(p for p in people if p["name"] == "Lisa Iwamoto")
    assert lisa["title"] == "Chair and Professor of Architecture"
    assert lisa["url"] == "https://ced.berkeley.edu/people/lisa-iwamoto"


def test_non_faculty_roles_skipped_and_photoless_card_skipped():
    names = {p["name"] for p in _scrape()}
    # Professors + lecturer + (emeritus prof, dropped later) kept; students/staff out.
    assert names == {"Lisa Iwamoto", "Mark Anderson", "Jane Lecturer", "Old Prof"}
    assert "Sam Phd" not in names        # PhD Candidate
    assert "Pat Advisor" not in names    # Graduate Advisor
    assert "No Photo Block" not in names  # no .people-listing photo


def test_emeritus_dropped_at_normalize():
    opps = [normalize_faculty(p, ARCH_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert "Old Prof" not in names  # "Professor Emeritus" -> dropped
    assert names == {"Lisa Iwamoto", "Mark Anderson", "Jane Lecturer"}


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Lisa Iwamoto", "url": "https://ced.berkeley.edu/people/lisa-iwamoto"},
        {"name": "Lisa Iwamoto", "url": "https://ced.berkeley.edu/people/lisa-iwamoto"},
        {"name": "Mark Anderson", "url": "https://ced.berkeley.edu/people/mark-anderson"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Lisa Iwamoto", "Mark Anderson"]


def test_specializations_extracted_from_value_column():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    spec = _specializations_from_profile(soup)
    assert "SPECIALIZATIONS" not in spec  # the label column is not included
    assert "digital fabrication" in spec.lower()


def test_no_specializations_section_yields_empty():
    soup = BeautifulSoup(PROFILE_NO_SPEC, "html.parser")
    assert _specializations_from_profile(soup) == ""


def test_email_from_profile_and_none_when_absent():
    assert _email_from_profile(BeautifulSoup(PROFILE_HTML, "html.parser")) == "liwamoto@berkeley.edu"
    assert _email_from_profile(BeautifulSoup(PROFILE_NO_EMAIL, "html.parser")) is None


def test_specialization_yields_topical_keywords():
    person = {"name": "Lisa Iwamoto", "url": "x", "title": "Professor of Architecture",
              "research_areas": "Design, materials research, and digital fabrication"}
    opp = normalize_faculty(person, ARCH_CONFIG)
    for kw in ("materials research", "digital fabrication"):
        assert kw in opp["keywords"], kw
    assert "architecture" not in opp["keywords"]  # not the broad fallback


def test_output_shape_matches_other_faculty_collectors():
    lisa = next(p for p in _scrape() if p["name"] == "Lisa Iwamoto")
    lisa["email"] = "liwamoto@berkeley.edu"
    lisa["research_areas"] = "Design, materials research"
    opp = normalize_faculty(lisa, ARCH_CONFIG)
    assert opp["source"] == "ucb_arch_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-arch-")
    assert opp["contact_email"] == "liwamoto@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ARCH_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ARCH_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    jane = next(p for p in _scrape() if p["name"] == "Jane Lecturer")  # no email/research
    opp = normalize_faculty(jane, ARCH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["architecture"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole
    Architecture corpus on the next scrape. Pin a real corpus id."""
    lisa = next(p for p in _scrape() if p["name"] == "Lisa Iwamoto")
    assert normalize_faculty(lisa, ARCH_CONFIG)["id"] == "faculty-ucb-arch-8af47a6b"
