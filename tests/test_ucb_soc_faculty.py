"""Offline tests for src.collectors.ucb_soc_faculty.

No network: fixtures mirror Sociology's real markup — a Name/Contact/Special
Interests table where each row carries name + rank (td.views-field-name: an <a>
plus a <div>), email (td.views-field-mail), and research interests
(td.views-field-field-special) inline. Locks in the table parser, inline email +
research, the sociology keyword mapping, dedup, output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import verified_send_target
from src.collectors.ucb_common import (
    _mark_fetched_soup_observation,
    dedup_by_profile_url,
    normalize_faculty,
)
from src.collectors.ucb_soc_faculty import SOC_CONFIG, _scrape_soc_faculty_list


def _row(slug: str, name: str, title: str, email: str, research: str) -> str:
    return f"""
    <tr>
      <td class="views-field views-field-name views-field-field-academic-title">
        <a href="/faculty/{slug}">{name}</a><div>{title}</div>
      </td>
      <td class="views-field views-field-field-phone-1 views-field-mail">{email}</td>
      <td class="views-field views-field-field-special">{research}</td>
    </tr>
    """


LISTING_HTML = f"""
<table class="table table-hover table-striped">
  <thead><tr><th>Name</th><th>Contact</th><th>Special Interests</th></tr></thead>
  <tbody>
    {_row("robert-braun", "Robert Braun", "Associate Professor", "robert.braun@berkeley.edu",
          "Comparative Historical Sociology; Social Movements")}
    {_row("eliza-brown", "Eliza Brown", "Assistant Professor", "",
          "Economic Sociology; Gender")}
  </tbody>
</table>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=SOC_CONFIG["url"],
        final_url=SOC_CONFIG["url"],
    )
    return _scrape_soc_faculty_list(soup, SOC_CONFIG["base"])


def test_parses_name_title_email_research_and_link():
    people = _scrape()
    braun = next(p for p in people if p["name"] == "Robert Braun")
    assert braun["title"] == "Associate Professor"
    assert braun["url"] == "https://sociology.berkeley.edu/faculty/robert-braun"
    assert braun["_contact_claim"]["contact_email"] == "robert.braun@berkeley.edu"
    assert "social movements" in braun["research_areas"].lower()


def test_missing_email_cell_leaves_record_lite():
    brown = next(p for p in _scrape() if p["name"] == "Eliza Brown")
    assert "email" not in brown
    assert "economic sociology" in brown["research_areas"].lower()


def test_research_yields_sociology_keywords():
    person = {"name": "Robert Braun", "url": "x", "title": "Professor",
              "research_areas": "Historical sociology; social movements; immigration; criminology"}
    opp = normalize_faculty(person, SOC_CONFIG)
    for kw in ("historical sociology", "social movements", "immigration", "criminology"):
        assert kw in opp["keywords"], kw


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Robert Braun", "url": "https://sociology.berkeley.edu/faculty/robert-braun"},
        {"name": "Robert Braun", "url": "https://sociology.berkeley.edu/faculty/robert-braun"},
        {"name": "Eliza Brown", "url": "https://sociology.berkeley.edu/faculty/eliza-brown"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Robert Braun", "Eliza Brown"]


def test_output_shape_with_email():
    braun = next(p for p in _scrape() if p["name"] == "Robert Braun")
    opp = normalize_faculty(braun, SOC_CONFIG)
    assert opp["source"] == "ucb_soc_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-soc-")
    assert opp["contact_email"] == "robert.braun@berkeley.edu"
    assert verified_send_target(opp) == "robert.braun@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == SOC_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == SOC_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    # A row with no research -> broad fallback keyword.
    person = {"name": "Robert Braun", "url": "x", "title": "Professor"}
    opp = normalize_faculty(person, SOC_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["sociology"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole SOC
    corpus on the next scrape. Pin a real corpus id."""
    braun = next(p for p in _scrape() if p["name"] == "Robert Braun")
    assert normalize_faculty(braun, SOC_CONFIG)["id"] == "faculty-ucb-soc-1281a8b0"
