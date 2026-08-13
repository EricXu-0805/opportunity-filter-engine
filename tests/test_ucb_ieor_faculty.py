"""Offline tests for src.collectors.ucb_ieor_faculty.

No network: fixtures mirror IEOR's real markup — a Beaver Builder callout grid
where each professor is a div.fl-callout with name + profile link in
h2.fl-callout-title a and rank in div.fl-callout-text. Email appears only as a
mailto: link (the page also carries footer/admin addresses that must NOT be
picked up); research lives in a "Research" accordion on every profile (with an
older div.group-faculty-research field as fallback). Locks in the bespoke
parser, mailto + (at)-obfuscated + footer-safe email extraction, accordion
research extraction, the no-signal fallback, dedup, output shape, and id
stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_ieor_faculty import (
    IEOR_CONFIG,
    _email_from_profile,
    _enrich_ieor_profiles,
    _research_from_profile,
    _scrape_ieor_faculty_list,
)

# Every IEOR profile has a "Research" accordion (distinct from "Publications");
# a "Research Areas:" label, when present, must be stripped. An older
# div.group-faculty-research field is the fallback when no accordion is present.
PROFILE_RESEARCH_ACCORDION = """
<div class="fl-page">
  <div class="fl-accordion-item">
    <a class="fl-accordion-button-label">Research</a>
    <div class="fl-accordion-content"><p>Research Areas: Integer optimization, logistics, power systems</p></div>
  </div>
  <div class="fl-accordion-item">
    <a class="fl-accordion-button-label">Publications</a>
    <div class="fl-accordion-content"><p>Too many to list</p></div>
  </div>
</div>
"""
PROFILE_RESEARCH_FALLBACK = """
<div class="fl-page"><div class="group-faculty-research">Mathematical Programming Game Theory</div></div>
"""


def test_research_extracted_from_accordion_and_label_stripped():
    soup = BeautifulSoup(PROFILE_RESEARCH_ACCORDION, "html.parser")
    research = _research_from_profile(soup, IEOR_CONFIG)
    assert research.startswith("Integer optimization")  # "Research Areas:" stripped
    assert "logistics" in research.lower()
    assert "Too many to list" not in research  # not the Publications panel


def test_research_falls_back_to_group_field():
    soup = BeautifulSoup(PROFILE_RESEARCH_FALLBACK, "html.parser")
    research = _research_from_profile(soup, IEOR_CONFIG)
    assert "Mathematical Programming" in research


def test_accordion_research_yields_topical_keywords():
    person = {"name": "Test", "url": "x", "title": "Professor",
              "research_areas": "Integer optimization, logistics, supply chain, game theory"}
    opp = normalize_faculty(person, IEOR_CONFIG)
    for kw in ("optimization", "logistics", "supply chain", "game theory"):
        assert kw in opp["keywords"], kw
    assert "operations research" not in opp["keywords"]  # not the broad fallback


def _callout(slug: str, name: str, title_html: str, has_link: bool = True) -> str:
    title_block = (
        f'<a class="fl-callout-title-link" href="/people/{slug}/"><span>{name}</span></a>'
        if has_link else f"<span>{name}</span>"
    )
    return f"""
    <div class="fl-callout fl-callout-has-photo">
      <div class="fl-callout-content">
        <h2 class="fl-callout-title">{title_block}</h2>
        <div class="fl-callout-text-wrap">
          <div class="fl-callout-text"><p>{title_html}</p></div>
        </div>
      </div>
    </div>
    """


# Two faculty callouts + one section callout without a /people/ link (skipped).
LISTING_HTML = f"""
<div class="fl-row-content">
  {_callout("ilan-adler", "Ilan Adler", "Professor<br/>Head MEng Advisor")}
  {_callout("ying-cui", "Ying Cui", "Assistant Professor")}
  {_callout("about", "About the Department", "Learn more", has_link=False)}
</div>
"""

# Profile with a real mailto AND the footer/admin address — only the mailto wins.
PROFILE_WITH_EMAIL = """
<div class="fl-page">
  <div class="group-faculty-research field">Optimization Convex Analysis</div>
  <a href="mailto:yingcui@berkeley.edu">email</a>
  <footer><a href="mailto:ieor-student-services@berkeley.edu">dept</a></footer>
</div>
"""

# No mailto and no personal address at all — only the footer/admin address,
# which must be ignored (literal @, not an obfuscated "(at)" token).
PROFILE_NO_PERSONAL_EMAIL = """
<div class="fl-page">
  <div class="group-faculty-research field">Mathematical Programming Game Theory</div>
  <footer>Contact: ieor-student-services@berkeley.edu</footer>
</div>
"""

# Most IEOR faculty publish an (at)-obfuscated address (anti-scraping) instead
# of a mailto. The footer admin address (literal @) sits on the same page and
# must NOT win over the de-obfuscated personal one.
PROFILE_OBFUSCATED = """
<div class="fl-page">
  <p>E-mail: aaswani(at)berkeley.edu</p>
  <footer>ieor-student-services@berkeley.edu</footer>
</div>
"""

PROFILE_OBFUSCATED_SPACED = '<p>E-mail: candiyano (at) berkeley.edu</p>'


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_ieor_faculty_list(soup, IEOR_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    adler = next(p for p in people if p["name"] == "Ilan Adler")
    # Only the first line of the callout text is the rank.
    assert adler["title"] == "Professor"
    assert adler["url"] == "https://ieor.berkeley.edu/people/ilan-adler/"


def test_section_callout_without_people_link_is_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Ilan Adler", "Ying Cui"}
    assert "About the Department" not in names


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Ilan Adler", "url": "https://ieor.berkeley.edu/people/ilan-adler/"},
        {"name": "Ilan Adler", "url": "https://ieor.berkeley.edu/people/ilan-adler/"},
        {"name": "Ying Cui", "url": "https://ieor.berkeley.edu/people/ying-cui/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Ilan Adler", "Ying Cui"]


def test_enrich_takes_mailto_and_research_ignoring_footer_address():
    people = [{"name": "Ying Cui", "url": "x"}]
    # Patch fetch to return the fixture instead of hitting the network.
    import src.collectors.ucb_ieor_faculty as mod
    orig = mod.fetch_soup
    mod.fetch_soup = lambda url: BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    try:
        _enrich_ieor_profiles(people, IEOR_CONFIG)
    finally:
        mod.fetch_soup = orig
    assert people[0]["email"] == "yingcui@berkeley.edu"  # mailto, not the footer addr
    assert "optimization" in people[0]["research_areas"].lower()


def test_enrich_ignores_footer_address_when_no_mailto():
    people = [{"name": "Ilan Adler", "url": "x"}]
    import src.collectors.ucb_ieor_faculty as mod
    orig = mod.fetch_soup
    mod.fetch_soup = lambda url: BeautifulSoup(PROFILE_NO_PERSONAL_EMAIL, "html.parser")
    try:
        _enrich_ieor_profiles(people, IEOR_CONFIG)
    finally:
        mod.fetch_soup = orig
    # No personal mailto -> stays lite; the footer admin address is not used.
    assert "email" not in people[0]
    assert "mathematical programming" in people[0]["research_areas"].lower()


def test_deobfuscates_at_email_and_skips_footer_admin():
    soup = BeautifulSoup(PROFILE_OBFUSCATED, "html.parser")
    # "aaswani(at)berkeley.edu" wins over the literal footer admin address.
    assert _email_from_profile(soup) == "aaswani@berkeley.edu"


def test_deobfuscation_handles_spaced_at():
    soup = BeautifulSoup(PROFILE_OBFUSCATED_SPACED, "html.parser")
    assert _email_from_profile(soup) == "candiyano@berkeley.edu"


def test_footer_admin_literal_email_is_never_returned():
    soup = BeautifulSoup(PROFILE_NO_PERSONAL_EMAIL, "html.parser")
    # Only a literal-@ footer address present -> not an obfuscated token -> None.
    assert _email_from_profile(soup) is None


def test_output_shape_matches_other_faculty_collectors():
    cui = next(p for p in _scrape() if p["name"] == "Ying Cui")
    cui["email"] = "yingcui@berkeley.edu"
    opp = normalize_faculty(cui, IEOR_CONFIG)
    assert opp["source"] == "ucb_ieor_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-ieor-")
    assert opp["contact_email"] == "yingcui@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == IEOR_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == IEOR_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    adler = next(p for p in _scrape() if p["name"] == "Ilan Adler")
    opp = normalize_faculty(adler, IEOR_CONFIG)  # no email, no research
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["operations research"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole IEOR
    corpus on the next scrape. Pin a real corpus id."""
    adler = next(p for p in _scrape() if p["name"] == "Ilan Adler")
    assert normalize_faculty(adler, IEOR_CONFIG)["id"] == "faculty-ucb-ieor-eb9a258e"
