"""Offline tests for src.collectors.ucb_espm_faculty.

No network: fixtures mirror ESPM's real markup — an Open-Berkeley views-table
(Name / Title / Role) that mixes Graduate Students, Postdocs, Emeriti, and
Faculty, plus an Open-Berkeley person profile (email field + resint research).
Locks in the Role="Faculty" filter, profile email + research extraction, dedup,
the environmental keyword mapping, output shape, and id stability.
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
from src.collectors.ucb_espm_faculty import ESPM_CONFIG, _scrape_table_page


def _row(slug: str, name: str, title: str, role: str) -> str:
    return f"""
    <tr>
      <td class="views-field views-field-title"><a href="/people/{slug}">{name}</a></td>
      <td class="views-field views-field-field-openberkeley-person-title">{title}</td>
      <td class="views-field views-field-field-openberkeley-person-type">{role}</td>
    </tr>
    """


TABLE_HTML = f"""
<table>
  <thead><tr><th>Name</th><th>Title</th><th>Role</th></tr></thead>
  <tbody>
    {_row("david-ackerly", "David Ackerly", "Professor", "Faculty, Organisms & Environment")}
    {_row("ronald-amundson", "Ronald Amundson", "Professor", "Faculty, Ecosystem Sciences")}
    {_row("anna-abramova", "Anna Abramova", "GSR", "Graduate Student")}
    {_row("some-postdoc", "Some Postdoc", "Postdoc", "Postdoctoral Researcher")}
    {_row("old-prof", "Old Prof", "Professor", "Ecosystem Sciences, Emeriti")}
  </tbody>
</table>
"""

PROFILE_HTML = """
<div class="node">
  <div class="field-name-field-openberkeley-person-email"><a href="mailto:earthy@berkeley.edu">earthy@berkeley.edu</a></div>
  <div class="field field-name-field-openberkeley-person-resint">
    <div class="field-label">Research:</div>
    <div class="field-items"><div class="field-item even"><p>Soil science, biogeochemistry, climate</p></div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="node"><p>No contact.</p></div>'


def _scrape():
    soup = BeautifulSoup(TABLE_HTML, "html.parser")
    return _scrape_table_page(soup, ESPM_CONFIG["base"])


def test_keeps_only_faculty_role_rows():
    names = {p["name"] for p in _scrape()}
    assert names == {"David Ackerly", "Ronald Amundson"}
    for excluded in ("Anna Abramova", "Some Postdoc", "Old Prof"):
        assert excluded not in names


def test_name_and_absolute_profile_link():
    ackerly = next(p for p in _scrape() if p["name"] == "David Ackerly")
    assert ackerly["url"] == "https://ourenvironment.berkeley.edu/people/david-ackerly"


def test_profile_email_and_research_extracted():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, ESPM_CONFIG) == "earthy@berkeley.edu"
    interests = extract_research_interests(soup, ESPM_CONFIG)
    assert "Research:" not in interests
    assert "soil science" in interests.lower()


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    assert extract_email_from_profile(soup, ESPM_CONFIG) is None


def test_research_yields_environmental_keywords():
    person = {"name": "Ronald Amundson", "url": "x", "title": "Professor",
              "research_areas": "Soil science, biogeochemistry, conservation biology, forestry"}
    opp = normalize_faculty(person, ESPM_CONFIG)
    for kw in ("soil science", "conservation biology", "forestry"):
        assert kw in opp["keywords"], kw
    assert "environmental science" not in opp["keywords"]  # not the broad fallback


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "David Ackerly", "url": "https://ourenvironment.berkeley.edu/people/david-ackerly"},
        {"name": "David Ackerly", "url": "https://ourenvironment.berkeley.edu/people/david-ackerly"},
        {"name": "Ronald Amundson", "url": "https://ourenvironment.berkeley.edu/people/ronald-amundson"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["David Ackerly", "Ronald Amundson"]


def test_output_shape_with_email():
    ackerly = next(p for p in _scrape() if p["name"] == "David Ackerly")
    ackerly["email"] = "dackerly@berkeley.edu"
    ackerly["research_areas"] = "Plant ecology, biodiversity"
    opp = normalize_faculty(ackerly, ESPM_CONFIG)
    assert opp["source"] == "ucb_espm_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-espm-")
    assert opp["contact_email"] == "dackerly@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ESPM_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ESPM_CONFIG["work_auth_notes"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole ESPM
    corpus on the next scrape. Pin a real corpus id."""
    ackerly = next(p for p in _scrape() if p["name"] == "David Ackerly")
    assert normalize_faculty(ackerly, ESPM_CONFIG)["id"] == "faculty-ucb-espm-d213a3f3"


# --- Pagination -------------------------------------------------------------

_GRAD_ONLY_TABLE = f"""
<table><tbody>
  {_row("grad-one", "Grad One", "GSR", "Graduate Student")}
  {_row("grad-two", "Grad Two", "GSR", "Graduate Student")}
</tbody></table>
"""

_PAGE2_TABLE = f"""
<table><tbody>
  {_row("justin-luong", "Justin Luong", "Professor", "Faculty, Ecosystem Sciences")}
</tbody></table>
"""

_EMPTY_TABLE = "<table><tbody></tbody></table>"


def test_pagination_survives_faculty_free_middle_page(monkeypatch):
    """The directory sorts all roles together, so a full middle page can hold
    zero Faculty-role rows (live page 10, 2026-07 — 20 rows, all Graduate
    Students; breaking there lost pages 11-21, 29 of 68 faculty). Only an empty
    TABLE ends the walk."""
    from src.collectors import ucb_espm_faculty as espm

    pages = {0: TABLE_HTML, 1: _GRAD_ONLY_TABLE, 2: _PAGE2_TABLE, 3: _EMPTY_TABLE}
    fetched: list[int] = []

    def fake_fetch(url):
        page = int(url.rsplit("?page=", 1)[1])
        fetched.append(page)
        html = pages.get(page)
        return BeautifulSoup(html, "html.parser") if html is not None else None

    monkeypatch.setattr(espm, "fetch_soup", fake_fetch)
    names = {p["name"] for p in espm._scrape_espm_faculty()}
    assert names == {"David Ackerly", "Ronald Amundson", "Justin Luong"}
    # walked past the faculty-free page 1, stopped at the truly empty page 3
    assert fetched == [0, 1, 2, 3]
