"""Offline tests for src.collectors.ucb_ne_faculty.

No network: fixtures mirror NE's real markup — a Beaver Builder grid where each
faculty member is a div.fl-post-grid-post with name + profile URL on a
<meta itemprop="mainEntityOfPage"> and a category-<role> class. NE is
listing-only (profiles expose no per-professor email/research), so these tests
cover the meta-based parser, emeritus skipping, dedup, the lite output shape
(no email), and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_ne_faculty import NE_CONFIG, _scrape_ne_faculty_list


def _card(slug: str, name: str, category: str) -> str:
    return f"""
    <div class="fl-post-grid-post people type-people {category}">
      <meta itemprop="mainEntityOfPage" content="{name}"
            itemid="https://nuc.berkeley.edu/people/{slug}/"/>
    </div>
    """


# Two active faculty + one emeritus that must be skipped.
LISTING_HTML = f"""
<div class="fl-post-grid">
  {_card("rebecca-abergel", "Rebecca Abergel", "category-faculty-profile")}
  {_card("massimiliano-fratoni", "Massimiliano Fratoni", "category-faculty-profile")}
  {_card("old-prof", "Old Prof", "category-emeritus")}
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_ne_faculty_list(soup, NE_CONFIG["base"])


def test_parses_name_and_url_from_meta():
    people = _scrape()
    abergel = next(p for p in people if p["name"] == "Rebecca Abergel")
    assert abergel["url"] == "https://nuc.berkeley.edu/people/rebecca-abergel/"


def test_emeritus_category_is_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Rebecca Abergel", "Massimiliano Fratoni"}
    assert "Old Prof" not in names


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Rebecca Abergel", "url": "https://nuc.berkeley.edu/people/rebecca-abergel/"},
        {"name": "Rebecca Abergel", "url": "https://nuc.berkeley.edu/people/rebecca-abergel/"},
        {"name": "Peter Hosemann", "url": "https://nuc.berkeley.edu/people/peter-hosemann/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Rebecca Abergel", "Peter Hosemann"]


def test_lite_output_shape_no_email():
    abergel = next(p for p in _scrape() if p["name"] == "Rebecca Abergel")
    opp = normalize_faculty(abergel, NE_CONFIG)
    assert opp["source"] == "ucb_ne_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-ne-")
    # NE publishes no per-professor email -> always lite.
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["nuclear engineering"]
    assert opp["eligibility"]["majors"] == NE_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == NE_CONFIG["work_auth_notes"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole NE
    corpus on the next scrape. Pin a real corpus id."""
    abergel = next(p for p in _scrape() if p["name"] == "Rebecca Abergel")
    assert normalize_faculty(abergel, NE_CONFIG)["id"] == "faculty-ucb-ne-d26a55fa"
