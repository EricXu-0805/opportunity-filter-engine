"""Offline tests for src.collectors.ucb_haas_faculty.

No network: fixtures mirror Haas's real WordPress markup — `.faculty-info-block`
cards inside a profile `<a>`, with the name in `h2`, the rank in a `<strong>`,
and the academic area(s) as the trailing text. The archive is paginated over
`/faculty/page/N/`. Haas publishes no emails, so every record ships "lite".
Locks in the block parser, the Professor-only role filter, multi-area "; "
splitting, the pagination loop, the emeritus drop, area_keywords mapping, the
lite output shape, dedup, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_haas_faculty import (
    HAAS_CONFIG,
    _scrape_haas_faculty,
    _scrape_haas_page,
)


def _block(slug: str, name: str, title: str, area: str) -> str:
    area_html = f"<br/>{area}" if area else ""
    return f"""
    <a href="https://haas.berkeley.edu/faculty/{slug}/">
      <div class="grid-block-wrap bio-info-block faculty-info-block">
        <div class="block-image"><img alt="{name}"/></div>
        <div class="block-content">
          <h2 class="title title-6">{name}</h2>
          <p><strong>{title}</strong>{area_html}</p>
        </div>
      </div>
    </a>
    """


PAGE_1 = f"""
<div class="grid">
  {_block("aggarwal-vinod", "Vinod K Aggarwal", "Professor", "Business & Public Policy")}
  {_block("cameron-anderson", "Cameron Anderson", "Professor", "Management of Organizations")}
  {_block("kai-adams", "Kai Adams", "Professional Faculty", "Finance")}
  {_block("john-lecturer", "John Lecturer", "Lecturer", "Marketing")}
  {_block("david-aaker", "David A. Aaker", "Professor Emeritus", "Marketing")}
</div>
"""
PAGE_2 = f"""
<div class="grid">
  {_block("multi-area", "Multi Area", "Associate Professor", "Entrepreneurship & Innovation | Finance")}
</div>
"""
EMPTY_PAGE = '<div class="grid"></div>'


def _scrape_page1():
    return _scrape_haas_page(BeautifulSoup(PAGE_1, "html.parser"), HAAS_CONFIG["base"])


def test_parses_name_title_area_and_link():
    people = _scrape_page1()
    agg = next(p for p in people if p["name"] == "Vinod K Aggarwal")
    assert agg["title"] == "Professor"
    assert agg["url"] == "https://haas.berkeley.edu/faculty/aggarwal-vinod/"
    assert agg["research_areas"] == "Business & Public Policy"


def test_professional_faculty_and_lecturers_skipped():
    names = {p["name"] for p in _scrape_page1()}
    assert "Kai Adams" not in names      # "Professional Faculty"
    assert "John Lecturer" not in names  # "Lecturer"
    # Professors (incl. the emeritus, dropped later) are kept.
    assert names == {"Vinod K Aggarwal", "Cameron Anderson", "David A. Aaker"}


def test_emeritus_dropped_at_normalize():
    opps = [normalize_faculty(p, HAAS_CONFIG) for p in _scrape_page1()]
    names = {o["pi_name"] for o in opps if o}
    assert "David A. Aaker" not in names  # "Professor Emeritus" -> dropped
    assert names == {"Vinod K Aggarwal", "Cameron Anderson"}


def test_pagination_collects_pages_then_stops_on_empty():
    pages = {
        "https://haas.berkeley.edu/faculty/": PAGE_1,
        "https://haas.berkeley.edu/faculty/page/2/": PAGE_2,
        "https://haas.berkeley.edu/faculty/page/3/": EMPTY_PAGE,
    }
    import src.collectors.ucb_haas_faculty as mod
    orig = mod.fetch_soup
    mod.fetch_soup = lambda url: BeautifulSoup(pages[url], "html.parser") if url in pages else None
    try:
        people = _scrape_haas_faculty()
    finally:
        mod.fetch_soup = orig
    names = {p["name"] for p in people}
    assert "Multi Area" in names              # page 2 collected
    assert "Vinod K Aggarwal" in names        # page 1 collected
    # page 3 is empty -> loop stops (no crash on a missing page 4)


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Vinod K Aggarwal", "url": "https://haas.berkeley.edu/faculty/aggarwal-vinod/"},
        {"name": "Vinod K Aggarwal", "url": "https://haas.berkeley.edu/faculty/aggarwal-vinod/"},
        {"name": "Cameron Anderson", "url": "https://haas.berkeley.edu/faculty/cameron-anderson/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Vinod K Aggarwal", "Cameron Anderson"]


def test_area_maps_to_business_keywords():
    anderson = next(p for p in _scrape_page1() if p["name"] == "Cameron Anderson")
    opp = normalize_faculty(anderson, HAAS_CONFIG)
    assert "organizational behavior" in opp["keywords"]
    assert "management" in opp["keywords"]
    assert "business" not in opp["keywords"]  # not the broad fallback


def test_multi_area_maps_each_area():
    multi = _scrape_haas_page(BeautifulSoup(PAGE_2, "html.parser"), HAAS_CONFIG["base"])[0]
    assert multi["research_areas"] == "Entrepreneurship & Innovation ; Finance"
    opp = normalize_faculty(multi, HAAS_CONFIG)
    for kw in ("entrepreneurship", "innovation", "finance"):
        assert kw in opp["keywords"], kw


def test_lite_output_shape_no_email():
    agg = next(p for p in _scrape_page1() if p["name"] == "Vinod K Aggarwal")
    opp = normalize_faculty(agg, HAAS_CONFIG)
    assert opp["source"] == "ucb_haas_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-haas-")
    # Haas publishes no emails -> always lite.
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["eligibility"]["majors"] == HAAS_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == HAAS_CONFIG["work_auth_notes"]


def test_no_area_falls_back_to_broad_keyword():
    person = {"name": "Max Professor", "url": "x", "title": "Professor"}  # no area
    opp = normalize_faculty(person, HAAS_CONFIG)
    assert opp["keywords"] == ["business"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole Haas
    corpus on the next scrape. Pin a real corpus id."""
    agg = next(p for p in _scrape_page1() if p["name"] == "Vinod K Aggarwal")
    assert normalize_faculty(agg, HAAS_CONFIG)["id"] == "faculty-ucb-haas-ca1074fa"
