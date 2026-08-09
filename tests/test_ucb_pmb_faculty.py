"""Offline tests for src.collectors.ucb_pmb_faculty.

No network: fixtures mirror PMB's real markup — an Open-Berkeley views-table
(Name / Job title / Role) that mixes Staff, Graduate Group, Emeriti, and
Faculty, plus an Open-Berkeley person profile (email field + resint research).
Locks in the Role="Faculty" filter, profile email + research extraction, dedup,
the topical-keyword mapping, output shape, and id stability.
"""

from __future__ import annotations

import os
import re
import sys

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import (
    dedup_by_profile_url,
    extract_email_from_profile,
    extract_research_interests,
    normalize_faculty,
)
from src.collectors.ucb_pmb_faculty import PMB_CONFIG, _scrape_table_page


def _row(slug: str, name: str, title: str, role: str) -> str:
    return f"""
    <tr>
      <td class="views-field views-field-title"><a href="/people/{slug}">{name}</a></td>
      <td class="views-field views-field-field-openberkeley-person-title">{title}</td>
      <td class="views-field views-field-field-openberkeley-person-type">{role}</td>
    </tr>
    """


# A mix of roles: two Faculty (kept), plus Staff / Graduate Group / Emeriti (skipped).
TABLE_HTML = f"""
<table>
  <thead><tr><th>Name</th><th>Job title</th><th>Role</th></tr></thead>
  <tbody>
    {_row("rebecca-bart", "Rebecca Bart", "Adjunct Professor", "Faculty, Plant Gene Expression Center")}
    {_row("benjamin-blackman", "Benjamin Blackman", "Associate Professor", "Plant Biology, Faculty")}
    {_row("irania-alarcon", "Irania Alarcon", "Team Lead", "Staff")}
    {_row("some-student", "Some Student", "GSR", "Graduate Group in Microbiology")}
    {_row("old-prof", "Old Prof", "Professor", "Plant Biology, Emeriti")}
  </tbody>
</table>
"""

# Open-Berkeley person profile: email field + free-text research interests.
PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:bkblackman@berkeley.edu">bkblackman@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research:</div>
    <div class="field-items"><div class="field-item even"><p>Evolution and plant-microbe interactions</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact.</p></div>'


def _scrape():
    soup = BeautifulSoup(TABLE_HTML, "html.parser")
    return _scrape_table_page(soup, PMB_CONFIG["base"])


def test_keeps_only_faculty_role_rows():
    names = {p["name"] for p in _scrape()}
    assert names == {"Rebecca Bart", "Benjamin Blackman"}
    # Staff, Graduate Group, and Emeriti rows are excluded.
    for excluded in ("Irania Alarcon", "Some Student", "Old Prof"):
        assert excluded not in names


def test_name_and_absolute_profile_link():
    bart = next(p for p in _scrape() if p["name"] == "Rebecca Bart")
    assert bart["url"] == "https://pmb.berkeley.edu/people/rebecca-bart"


def test_profile_email_and_research_extracted():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, PMB_CONFIG) == "bkblackman@berkeley.edu"
    interests = extract_research_interests(soup, PMB_CONFIG)
    assert "Research:" not in interests
    assert "evolution" in interests.lower()


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, PMB_CONFIG) is None


def test_research_yields_topical_keywords():
    person = {"name": "Benjamin Blackman", "url": "x", "title": "Professor",
              "research_areas": "Evolution, plant genetics, photosynthesis, microbial ecology"}
    opp = normalize_faculty(person, PMB_CONFIG)
    for kw in ("evolution", "plant genetics", "photosynthesis", "microbial ecology"):
        assert kw in opp["keywords"], kw
    assert "plant biology" not in opp["keywords"]  # not the broad fallback


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Rebecca Bart", "url": "https://pmb.berkeley.edu/people/rebecca-bart"},
        {"name": "Rebecca Bart", "url": "https://pmb.berkeley.edu/people/rebecca-bart"},
        {"name": "Rachel Brem", "url": "https://pmb.berkeley.edu/people/rachel-brem"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Rebecca Bart", "Rachel Brem"]


def test_output_shape_with_email():
    bart = next(p for p in _scrape() if p["name"] == "Rebecca Bart")
    bart["email"] = "beckybart@berkeley.edu"
    bart["research_areas"] = "Agricultural sustainability, plant pathology"
    opp = normalize_faculty(bart, PMB_CONFIG)
    assert opp["source"] == "ucb_pmb_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-pmb-")
    assert opp["contact_email"] == "beckybart@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == PMB_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == PMB_CONFIG["work_auth_notes"]


@pytest.mark.parametrize(
    "scraped",
    [
        # What pmb.berkeley.edu actually serves, read live on 2026-08-08.
        "Job title: Associate Professor",
        "Position title: Associate Professor",
        "Title: Associate Professor",
    ],
)
def test_scraped_title_label_never_leaks_into_normalized_record(scraped):
    """Regression for the 2026-07-28 scheduled DQ failure (45 PMB rows).

    The first fix guessed the label. Open Berkeley renders this field as
    "Job title:", so the cleaner kept missing it, the description kept
    reading "Research opportunity with Job title: Professor …", and the
    Tuesday shard has not published since 2026-07-21.
    """

    person = {
        "name": "Benjamin Blackman",
        "url": "https://pmb.berkeley.edu/people/benjamin-blackman",
        "title": scraped,
    }
    opp = normalize_faculty(person, PMB_CONFIG)

    assert opp["metadata"]["faculty_title"] == "Associate Professor"
    for text in (
        opp["description_clean"],
        opp["eligibility"]["eligibility_text_raw"],
    ):
        assert not re.search(r"\btitle\s*:", text, re.IGNORECASE), text


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole PMB
    corpus on the next scrape. Pin a real corpus id."""
    bart = next(p for p in _scrape() if p["name"] == "Rebecca Bart")
    assert normalize_faculty(bart, PMB_CONFIG)["id"] == "faculty-ucb-pmb-2338f3ad"
