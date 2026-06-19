"""Offline tests for src.collectors.ucb_ne_faculty.

No network: fixtures mirror NE's real markup — a Beaver Builder grid where each
faculty member is a div.fl-post-grid-post with name + profile URL on a
<meta itemprop="mainEntityOfPage"> and a category-<role> class. Profiles
obfuscate the email with SQUARE brackets ("name[at]berkeley.edu") and carry a
"Research Interests" accordion. Locks in the meta-based parser, emeritus
skipping, [at] email de-obfuscation (and footer-address safety), accordion
research extraction, NE topical keywords, dedup, output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_ne_faculty import (
    NE_CONFIG,
    _email_from_profile,
    _research_from_profile,
    _scrape_ne_faculty_list,
)


def _card(slug: str, name: str, category: str) -> str:
    return f"""
    <div class="fl-post-grid-post people type-people {category}">
      <meta itemprop="mainEntityOfPage" content="{name}"
            itemid="https://nuc.berkeley.edu/people/{slug}/"/>
    </div>
    """


LISTING_HTML = f"""
<div class="fl-post-grid">
  {_card("rebecca-abergel", "Rebecca Abergel", "category-faculty-profile")}
  {_card("massimiliano-fratoni", "Massimiliano Fratoni", "category-faculty-profile")}
  {_card("old-prof", "Old Prof", "category-emeritus")}
</div>
"""

# Profile: [at]-obfuscated personal email + the literal footer Student Services
# address (must NOT win) + a Research Interests accordion.
PROFILE_HTML = """
<div class="fl-page">
  <div class="contact">4109 Etcheverry Hall abergel[at]berkeley.edu (510) 643-9984</div>
  <div class="fl-accordion-item">
    <a class="fl-accordion-button-label">Research Interests</a>
    <div class="fl-accordion-content"><p>Heavy element and inorganic isotope nuclear chemistry, fission product separation, radioactive waste management.</p></div>
  </div>
  <div class="fl-accordion-item">
    <a class="fl-accordion-button-label">Honors</a>
    <div class="fl-accordion-content"><p>NSF CAREER</p></div>
  </div>
  <footer>Student Services jpyon1@berkeley.edu</footer>
</div>
"""
PROFILE_NO_EMAIL_HTML = '<div class="fl-page"><footer>Student Services jpyon1@berkeley.edu</footer></div>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_ne_faculty_list(soup, NE_CONFIG["base"])


def test_parses_name_and_url_from_meta():
    abergel = next(p for p in _scrape() if p["name"] == "Rebecca Abergel")
    assert abergel["url"] == "https://nuc.berkeley.edu/people/rebecca-abergel/"


def test_emeritus_category_is_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Rebecca Abergel", "Massimiliano Fratoni"}


def test_email_deobfuscated_from_square_brackets():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    # "abergel[at]berkeley.edu" -> abergel@berkeley.edu, NOT the footer jpyon1@.
    assert _email_from_profile(soup) == "abergel@berkeley.edu"


def test_footer_address_not_returned_when_no_personal_email():
    soup = BeautifulSoup(PROFILE_NO_EMAIL_HTML, "html.parser")
    # Only the literal footer address present (no [at] token) -> None.
    assert _email_from_profile(soup) is None


def test_research_interests_extracted_from_accordion():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    research = _research_from_profile(soup)
    assert "nuclear chemistry" in research.lower()
    assert "NSF CAREER" not in research  # only the Research Interests panel


def test_research_yields_nuclear_keywords():
    person = {
        "name": "Test Professor", "url": "x", "title": "Professor",
        "research_areas": "Heavy element nuclear chemistry, fission product separation, "
                          "radioactive waste management, nuclear fuel reprocessing",
    }
    opp = normalize_faculty(person, NE_CONFIG)
    for kw in ("nuclear chemistry", "fission", "radioactive waste", "nuclear fuel"):
        assert kw in opp["keywords"], kw
    assert "nuclear engineering" not in opp["keywords"]  # not the broad fallback


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Rebecca Abergel", "url": "https://nuc.berkeley.edu/people/rebecca-abergel/"},
        {"name": "Rebecca Abergel", "url": "https://nuc.berkeley.edu/people/rebecca-abergel/"},
        {"name": "Peter Hosemann", "url": "https://nuc.berkeley.edu/people/peter-hosemann/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Rebecca Abergel", "Peter Hosemann"]


def test_output_shape_matches_other_faculty_collectors():
    abergel = next(p for p in _scrape() if p["name"] == "Rebecca Abergel")
    abergel["email"] = "abergel@berkeley.edu"
    opp = normalize_faculty(abergel, NE_CONFIG)
    assert opp["source"] == "ucb_ne_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-ne-")
    assert opp["contact_email"] == "abergel@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == NE_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == NE_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    fratoni = next(p for p in _scrape() if p["name"] == "Massimiliano Fratoni")  # no email/research
    opp = normalize_faculty(fratoni, NE_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["nuclear engineering"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole NE
    corpus on the next scrape. Pin a real corpus id."""
    abergel = next(p for p in _scrape() if p["name"] == "Rebecca Abergel")
    assert normalize_faculty(abergel, NE_CONFIG)["id"] == "faculty-ucb-ne-d26a55fa"
