"""Offline tests for src.collectors.ucb_ling_faculty.

No network: fixtures mirror Linguistics's real markup — each faculty member is a
small one-cell table (rank + "Email:" + office + "Research and teaching:") whose
name is in a preceding <h2> heading (often linking to a personal site). Locks in
the table+heading parser, the personal-site / synthetic-anchor URL, inline email
+ research, the linguistics keyword mapping, dedup, output shape, and id
stability.
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
from src.collectors.ucb_ling_faculty import LING_CONFIG, _scrape_ling_faculty_list


def _person(name: str, body: str, site: str | None) -> str:
    heading = (f'<h2><a href="{site}">{name}</a></h2>' if site else f"<h2>{name}</h2>")
    return f'{heading}<table><tr><td>{body}</td></tr></table>'


# One faculty with a personal-site link, one without (synthetic anchor URL).
LISTING_HTML = f"""
<div class="region-content">
  {_person("Gašper Beguš",
           "Associate Professor of Linguistics Email: begus@berkeley.edu Office: 1213 Dwinelle "
           "Research and teaching: Phonology, phonetics, computational linguistics",
           "https://www.gasperbegus.com/")}
  {_person("Amy Rose Deal",
           "Professor Email: ardeal@berkeley.edu Office: 1226 Dwinelle "
           "Research and teaching: Syntax, semantics, fieldwork",
           None)}
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=LING_CONFIG["url"],
        final_url=LING_CONFIG["url"],
    )
    return _scrape_ling_faculty_list(soup, LING_CONFIG["base"], LING_CONFIG["url"])


def test_parses_name_title_email_research():
    people = _scrape()
    begus = next(p for p in people if p["name"] == "Gašper Beguš")
    assert begus["title"] == "Associate Professor of Linguistics"
    assert begus["_contact_claim"]["contact_email"] == "begus@berkeley.edu"
    assert "phonology" in begus["research_areas"].lower()
    assert "Email:" not in begus["research_areas"]


def test_personal_site_link_used_as_url():
    begus = next(p for p in _scrape() if p["name"] == "Gašper Beguš")
    assert begus["url"] == "https://www.gasperbegus.com/"


def test_no_link_gets_synthetic_anchor_url():
    deal = next(p for p in _scrape() if p["name"] == "Amy Rose Deal")
    assert deal["url"] == "https://linguistics.berkeley.edu/faculty#amy-rose-deal"


def test_research_yields_linguistics_keywords():
    person = {"name": "Amy Rose Deal", "url": "x", "title": "Professor",
              "research_areas": "Syntax, semantics, phonology, fieldwork"}
    opp = normalize_faculty(person, LING_CONFIG)
    for kw in ("syntax", "semantics", "phonology"):
        assert kw in opp["keywords"], kw


def test_dedup_keeps_distinct_synthetic_and_real_urls():
    out = dedup_by_profile_url(_scrape())
    assert len(out) == 2  # distinct URLs -> both kept


def test_output_shape_with_email():
    begus = next(p for p in _scrape() if p["name"] == "Gašper Beguš")
    opp = normalize_faculty(begus, LING_CONFIG)
    assert opp["source"] == "ucb_ling_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-ling-")
    assert opp["contact_email"] == "begus@berkeley.edu"
    assert verified_send_target(opp) == "begus@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == LING_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == LING_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    person = {"name": "Gašper Beguš", "url": "x", "title": "Professor"}  # no email/research
    opp = normalize_faculty(person, LING_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["linguistics"]


def test_unrelated_later_table_cannot_reuse_previous_professor_heading():
    html = (
        _person(
            "Ada Lovelace",
            "Professor Email: ada@berkeley.edu Research and teaching: Computing",
            None,
        )
        + "<div>Unrelated content</div><table><tr><td>"
        "Email: helper.person@berkeley.edu"
        "</td></tr></table>"
    )
    soup = BeautifulSoup(html, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=LING_CONFIG["url"],
        final_url=LING_CONFIG["url"],
    )
    people = _scrape_ling_faculty_list(
        soup,
        LING_CONFIG["base"],
        LING_CONFIG["url"],
    )
    assert [person["name"] for person in people] == ["Ada Lovelace"]
    opp = normalize_faculty(people[0], LING_CONFIG)
    assert verified_send_target(opp) == "ada@berkeley.edu"


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole LING
    corpus on the next scrape. Pin a real corpus id."""
    begus = next(p for p in _scrape() if p["name"] == "Gašper Beguš")
    assert normalize_faculty(begus, LING_CONFIG)["id"] == "faculty-ucb-ling-ac3cb928"
