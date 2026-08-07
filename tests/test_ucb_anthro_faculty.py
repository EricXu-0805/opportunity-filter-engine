"""Offline tests for src.collectors.ucb_anthro_faculty.

No network: fixtures mirror Anthropology's real markup — each faculty member is
a div.field-name-field-basic-text-text block with a name <a> linking to a
/<name-slug> profile, the rank, comma-separated subfield areas, an office, and
an "EMAIL:" address. Locks in the block parser, inline email + research, the
anthropology keyword mapping, dedup, output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.lib.contact_visibility import verified_send_target
from src.collectors.ucb_anthro_faculty import ANTHRO_CONFIG, _scrape_anthro_page
from src.collectors.ucb_common import (
    _mark_fetched_soup_observation,
    dedup_by_profile_url,
    normalize_faculty,
)


def _block(slug: str, name: str, body: str) -> str:
    return f"""
    <div class="field field-name-field-basic-text-text">
      <a href="/{slug}">{name}</a> {body}
    </div>
    """


LISTING_HTML = f"""
<div class="region-content">
  {_block("sabrina-c-agarwal", "Sabrina C. Agarwal",
          "Department Chair Professor Archaeology, Biological Anthropology "
          "OFFICE: 212 ARF EMAIL: agarwal@berkeley.edu")}
  {_block("charles-l-briggs", "Charles L. Briggs",
          "Professor Medical Anthropology, Sociocultural Anthropology, Folklore "
          "OFFICE: 307 EMAIL: clbriggs@berkeley.edu")}
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=ANTHRO_CONFIG["url"],
        final_url=ANTHRO_CONFIG["url"],
    )
    return _scrape_anthro_page(
        soup,
        ANTHRO_CONFIG["base"],
        ANTHRO_CONFIG["url"],
    )


def test_parses_name_title_email_and_link():
    people = _scrape()
    assert len(people) == 2
    agarwal = next(p for p in people if p["name"] == "Sabrina C. Agarwal")
    assert agarwal["title"] == "Professor"
    assert agarwal["_contact_claim"]["contact_email"] == "agarwal@berkeley.edu"
    assert agarwal["url"] == "https://anthropology.berkeley.edu/sabrina-c-agarwal"


def test_research_areas_extracted_before_office_and_email():
    agarwal = next(p for p in _scrape() if p["name"] == "Sabrina C. Agarwal")
    ra = agarwal["research_areas"].lower()
    assert "archaeology" in ra
    assert "biological anthropology" in ra
    assert "office" not in ra and "email" not in ra and "@" not in ra


def test_research_yields_anthropology_keywords():
    person = {"name": "Charles L. Briggs", "url": "x", "title": "Professor",
              "research_areas": "Medical anthropology, sociocultural anthropology, folklore"}
    opp = normalize_faculty(person, ANTHRO_CONFIG)
    for kw in ("medical anthropology", "sociocultural anthropology", "folklore"):
        assert kw in opp["keywords"], kw


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Sabrina C. Agarwal", "url": "https://anthropology.berkeley.edu/sabrina-c-agarwal"},
        {"name": "Sabrina C. Agarwal", "url": "https://anthropology.berkeley.edu/sabrina-c-agarwal"},
        {"name": "Charles L. Briggs", "url": "https://anthropology.berkeley.edu/charles-l-briggs"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Sabrina C. Agarwal", "Charles L. Briggs"]


def test_output_shape_with_email():
    agarwal = next(p for p in _scrape() if p["name"] == "Sabrina C. Agarwal")
    opp = normalize_faculty(agarwal, ANTHRO_CONFIG)
    assert opp["source"] == "ucb_anthro_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-anthro-")
    assert opp["contact_email"] == "agarwal@berkeley.edu"
    assert verified_send_target(opp) == "agarwal@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ANTHRO_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ANTHRO_CONFIG["work_auth_notes"]
    assert opp["metadata"]["research_areas_raw"]


def test_lite_record_falls_back_to_broad_keyword():
    person = {"name": "Sabrina C. Agarwal", "url": "x", "title": "Professor"}  # no email/research
    opp = normalize_faculty(person, ANTHRO_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["anthropology"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole ANTHRO
    corpus on the next scrape. Pin a real corpus id."""
    agarwal = next(p for p in _scrape() if p["name"] == "Sabrina C. Agarwal")
    assert normalize_faculty(agarwal, ANTHRO_CONFIG)["id"] == "faculty-ucb-anthro-7c5aba2b"
