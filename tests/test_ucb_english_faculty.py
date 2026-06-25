"""Offline tests for src.collectors.ucb_english_faculty.

No network: fixtures mirror English's real markup — a standard Open-Berkeley
directory of `div.node-openberkeley-person` teaser cards (name in `h2 > a`, rank
in the title field), paginated over `?page=N`, with profiles that carry a mailto:
email and a free-text biography (`field-name-body`) used as the research signal.
Locks in the shared selector-driven card parser for the English config, the
pagination loop, email + biography extraction (label stripped), literary keyword
mapping, emeritus drop, dedup, the output shape, and id stability.
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
    scrape_open_berkeley_faculty,
)
from src.collectors.ucb_english_faculty import ENGLISH_CONFIG, _scrape_english_faculty


def _card(slug: str, name: str, title: str) -> str:
    return f"""
    <div class="views-row">
      <div class="node node-openberkeley-person node-teaser clearfix">
        <h2><a href="/people/{slug}">{name}</a></h2>
        <div class="content">
          <div class="field field-name-field-openberkeley-person-title field-label-hidden">
            <div class="field-items"><div class="field-item even">{title}</div></div>
          </div>
        </div>
      </div>
    </div>
    """


def _page(*cards: str) -> str:
    return f'<div class="view-content">{"".join(cards)}</div>'


PAGE_0 = _page(
    _card("hilton-als", "Hilton Als", "Teaching Professor"),
    _card("oliver-arnold", "Oliver Arnold", "Associate Professor"),
)
PAGE_1 = _page(
    _card("ian-duncan", "Ian Duncan", "Professor"),
    _card("old-timer", "Old Timer", "Professor Emeritus"),  # dropped at normalize
)
EMPTY_PAGE = _page()

# Open-Berkeley person profile: mailto: email + a biography body (the "Biography:"
# label sits in field-label and must be stripped by the .field-item selector).
PROFILE_HTML = """
<div class="node node-openberkeley-person">
  <div class="field field-name-field-openberkeley-person-email">
    <a href="mailto:halsfriend@berkeley.edu">halsfriend@berkeley.edu</a>
  </div>
  <div class="field field-name-body field-type-text-with-summary">
    <div class="field-label">Biography:</div>
    <div class="field-items"><div class="field-item even">
      <p>A theatre critic and essayist; his work spans drama, narrative nonfiction, and creative writing.</p>
    </div></div>
  </div>
</div>
"""
PROFILE_NO_EMAIL = '<div class="node"><p>No contact listed.</p></div>'


def _scrape_page0():
    soup = BeautifulSoup(PAGE_0, "html.parser")
    return scrape_open_berkeley_faculty(soup, ENGLISH_CONFIG)


def test_parses_h2_name_title_and_absolute_profile_link():
    people = _scrape_page0()
    als = next(p for p in people if p["name"] == "Hilton Als")
    assert als["title"] == "Teaching Professor"
    assert als["url"] == "https://english.berkeley.edu/people/hilton-als"


def test_pagination_collects_all_pages_then_stops_on_empty():
    pages = [PAGE_0, PAGE_1, EMPTY_PAGE]
    import src.collectors.ucb_english_faculty as mod
    orig = mod.fetch_soup

    def fake_fetch(url):
        page = int(url.rsplit("page=", 1)[1])
        return BeautifulSoup(pages[page], "html.parser") if page < len(pages) else None

    mod.fetch_soup = fake_fetch
    try:
        people = _scrape_english_faculty()
    finally:
        mod.fetch_soup = orig
    names = {p["name"] for p in people}
    # Page 0 + page 1 collected; the empty page 2 halts the loop.
    assert names == {"Hilton Als", "Oliver Arnold", "Ian Duncan", "Old Timer"}


def test_emeritus_dropped_by_title():
    soup = BeautifulSoup(PAGE_1, "html.parser")
    opps = [normalize_faculty(p, ENGLISH_CONFIG)
            for p in scrape_open_berkeley_faculty(soup, ENGLISH_CONFIG)]
    names = {o["pi_name"] for o in opps if o}
    assert "Ian Duncan" in names
    assert "Old Timer" not in names  # "Professor Emeritus" -> dropped


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Hilton Als", "url": "https://english.berkeley.edu/people/hilton-als"},
        {"name": "Hilton Als", "url": "https://english.berkeley.edu/people/hilton-als"},
        {"name": "Oliver Arnold", "url": "https://english.berkeley.edu/people/oliver-arnold"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Hilton Als", "Oliver Arnold"]


def test_email_and_biography_extracted_from_profile():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    assert extract_email_from_profile(soup, ENGLISH_CONFIG) == "halsfriend@berkeley.edu"
    research = extract_research_interests(soup, ENGLISH_CONFIG)
    assert "Biography:" not in research  # label stripped
    assert "creative writing" in research.lower()


def test_no_email_on_profile_returns_none():
    soup = BeautifulSoup(PROFILE_NO_EMAIL, "html.parser")
    assert extract_email_from_profile(soup, ENGLISH_CONFIG) is None


def test_biography_yields_topical_keywords():
    person = {"name": "Hilton Als", "url": "x", "title": "Teaching Professor",
              "research_areas": "A theatre critic; his work spans drama, narrative, and creative writing."}
    opp = normalize_faculty(person, ENGLISH_CONFIG)
    for kw in ("theatre", "drama", "creative writing"):
        assert kw in opp["keywords"], kw
    assert "english literature" not in opp["keywords"]  # not the broad fallback


def test_output_shape_matches_other_faculty_collectors():
    als = next(p for p in _scrape_page0() if p["name"] == "Hilton Als")
    als["email"] = "halsfriend@berkeley.edu"
    als["research_areas"] = "Drama, the novel, and American literature."
    opp = normalize_faculty(als, ENGLISH_CONFIG)
    assert opp["source"] == "ucb_english_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-engl-")
    assert opp["contact_email"] == "halsfriend@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == ENGLISH_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ENGLISH_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    arnold = next(p for p in _scrape_page0() if p["name"] == "Oliver Arnold")  # no email/research
    opp = normalize_faculty(arnold, ENGLISH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["english literature"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole English
    corpus on the next scrape. Pin a real corpus id."""
    als = next(p for p in _scrape_page0() if p["name"] == "Hilton Als")
    assert normalize_faculty(als, ENGLISH_CONFIG)["id"] == "faculty-ucb-engl-0dae47b2"
