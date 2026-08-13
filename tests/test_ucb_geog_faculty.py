"""Offline tests for src.collectors.ucb_geog_faculty.

No network: fixtures mirror Geography's real markup — each faculty member is a
two-column table whose content cell has an <h3><a> name (+ profile link), a <p>
with rank / office / mailto: email, and an <em> with research interests. Locks
in the table parser, inline email + research, the geography keyword mapping,
dedup, output shape, and id stability.
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
from src.collectors.ucb_geog_faculty import GEOG_CONFIG, _scrape_geog_faculty_list


def _table(slug: str, name: str, rank: str, email: str, research: str) -> str:
    return f"""
    <table><tbody><tr>
      <td><p><img alt="{name}" src="/x.png"/></p></td>
      <td>
        <h3><a href="https://geography.berkeley.edu/{slug}">{name}</a></h3>
        <p>{rank}<br/>589 McCone Hall<br/><a href="mailto:{email}">{email}</a></p>
        <p><em>{research}</em></p>
      </td>
    </tr></tbody></table>
    """


LISTING_HTML = f"""
<div class="pane-node-content">
  <h2>Regular Faculty</h2>
  {_table("assistant-professor-geronimo-barrera", "Gerónimo Barrera de la Torre",
          "Assistant Professor", "gbarrera@berkeley.edu",
          "Social mapping, political ecology, historical and political geography")}
  {_table("professor-jeffrey-chambers", "Jeffrey Q. Chambers",
          "Professor", "jqchambers@berkeley.edu",
          "Biogeography and the biosphere; forests, remote sensing")}
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=GEOG_CONFIG["url"],
        final_url=GEOG_CONFIG["url"],
    )
    return _scrape_geog_faculty_list(soup)


def test_parses_name_title_email_research_and_link():
    people = _scrape()
    assert len(people) == 2
    g = next(p for p in people if p["name"] == "Gerónimo Barrera de la Torre")
    assert g["title"] == "Assistant Professor"
    assert g["_contact_claim"]["contact_email"] == "gbarrera@berkeley.edu"
    assert g["url"] == "https://geography.berkeley.edu/assistant-professor-geronimo-barrera"
    assert "political ecology" in g["research_areas"].lower()


def test_research_yields_geography_keywords():
    person = {"name": "Jeffrey Q. Chambers", "url": "x", "title": "Professor",
              "research_areas": "Biogeography, remote sensing, political ecology, cartography"}
    opp = normalize_faculty(person, GEOG_CONFIG)
    for kw in ("biogeography", "remote sensing", "political ecology", "cartography"):
        assert kw in opp["keywords"], kw


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Jeffrey Q. Chambers", "url": "https://geography.berkeley.edu/professor-jeffrey-chambers"},
        {"name": "Jeffrey Q. Chambers", "url": "https://geography.berkeley.edu/professor-jeffrey-chambers"},
        {"name": "Gerónimo Barrera de la Torre", "url": "https://geography.berkeley.edu/assistant-professor-geronimo-barrera"},
    ]
    out = dedup_by_profile_url(dupes)
    assert len(out) == 2


def test_output_shape_with_email():
    g = next(p for p in _scrape() if p["name"] == "Gerónimo Barrera de la Torre")
    opp = normalize_faculty(g, GEOG_CONFIG)
    assert opp["source"] == "ucb_geog_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-geog-")
    assert opp["contact_email"] == "gbarrera@berkeley.edu"
    assert verified_send_target(opp) == "gbarrera@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == GEOG_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == GEOG_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    person = {"name": "Gerónimo Barrera de la Torre", "url": "x", "title": "Professor"}
    opp = normalize_faculty(person, GEOG_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["geography"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole GEOG
    corpus on the next scrape. Pin a real corpus id."""
    g = next(p for p in _scrape() if p["name"] == "Gerónimo Barrera de la Torre")
    assert normalize_faculty(g, GEOG_CONFIG)["id"] == "faculty-ucb-geog-efedd03e"
