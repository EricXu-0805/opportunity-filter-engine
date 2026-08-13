"""Offline tests for src.collectors.ucb_sph_faculty.

No network: fixtures mirror SPH's real markup — a UIkit grid where each faculty
member is an `a.uk-link-toggle[href*='/people/']` with the name in a
`span.bph-text-serif` and the rank/department in a `span.uk-text-small`, and
profile pages that carry the personal email as the first mailto: (the school-wide
publichealth@berkeley.edu mailbox is a second mailto that must be skipped) plus a
"Research Interests" heading followed by a (malformed, nesting) <ul> of interests.
Locks in the bespoke listing parser, the mailbox-safe email extraction, the
nested-<li> research parse, public-health keyword mapping, emeritus drop, dedup,
the external-campus output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_sph_faculty import (
    SPH_CONFIG,
    _email_from_profile,
    _enrich_sph_profiles,
    _research_from_profile,
    _scrape_sph_faculty_list,
)


def _card(slug: str, name: str, title: str) -> str:
    return f"""
    <div>
      <a class="bph-border-bottom uk-link-toggle" href="https://publichealth.berkeley.edu/people/{slug}" target="_self">
        <div class="bph-base-line-height-1-25 uk-padding-small uk-link-text">
          <span class="bph-text-serif">{name}</span>
          <div class="bph-base-line-height-1 uk-margin-small">
            <span class="uk-text-small">{title}</span>
          </div>
        </div>
      </a>
    </div>
    """


# Two active faculty + one emerita (dropped at normalize) + a non-person nav
# link (no uk-link-toggle, must be skipped by the selector).
LISTING_HTML = f"""
<div class="bph-block-people">
  <div class="uk-grid-match uk-child-width-1-4@m">
    {_card("jennifer-ahern", "Jennifer Ahern", "Professor, Epidemiology")}
    {_card("joshua-apte", "Joshua Apte", "Associate Professor, Environmental Health Sciences")}
    {_card("barbara-abrams", "Barbara Abrams", "Professor Emerita, Epidemiology and Community Health Sciences")}
  </div>
  <a href="/people/all" class="uk-button">See all people</a>
</div>
"""

# Profile with the personal mailto FIRST and the school-wide mailbox second
# (must be skipped), plus a "Research Interests" section. The <ul> markup nests
# (the real site emits unclosed <li>s), so only each <li>'s own direct text is a
# single interest.
PROFILE_WITH_EMAIL = """
<div class="profile">
  <a href="mailto:apte@berkeley.edu">apte@berkeley.edu</a>
  <a href="mailto:publichealth@berkeley.edu">publichealth@berkeley.edu</a>
  <h2 class="uk-h3">Research Interests</h2>
  <ul class="uk-list uk-list-large">
    <li>Air pollution
      <li>Exposure assessment
        <li>Climate change mitigation</li>
      </li>
    </li>
  </ul>
  <h2 class="uk-h3">Education</h2>
</div>
"""

# No personal mailto — only the school-wide mailbox, which must be ignored.
PROFILE_NO_PERSONAL_EMAIL = """
<div class="profile">
  <a href="mailto:publichealth@berkeley.edu">publichealth@berkeley.edu</a>
  <h2>Research Interests</h2>
  <ul class="uk-list"><li>Social epidemiology<li>Substance use</li></li></ul>
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_sph_faculty_list(soup, SPH_CONFIG["base"])


def test_parses_name_title_and_absolute_profile_link():
    people = _scrape()
    ahern = next(p for p in people if p["name"] == "Jennifer Ahern")
    assert ahern["title"] == "Professor, Epidemiology"
    assert ahern["url"] == "https://publichealth.berkeley.edu/people/jennifer-ahern"


def test_non_person_nav_link_is_skipped():
    # The "See all people" link has no uk-link-toggle / span.bph-text-serif.
    names = {p["name"] for p in _scrape()}
    assert names == {"Jennifer Ahern", "Joshua Apte", "Barbara Abrams"}


def test_emerita_dropped_by_title():
    opps = [normalize_faculty(p, SPH_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert "Barbara Abrams" not in names  # "Professor Emerita" -> dropped
    assert names == {"Jennifer Ahern", "Joshua Apte"}


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Joshua Apte", "url": "https://publichealth.berkeley.edu/people/joshua-apte"},
        {"name": "Joshua Apte", "url": "https://publichealth.berkeley.edu/people/joshua-apte"},
        {"name": "Jennifer Ahern", "url": "https://publichealth.berkeley.edu/people/jennifer-ahern"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Joshua Apte", "Jennifer Ahern"]


def test_email_takes_personal_mailto_and_skips_school_mailbox():
    soup = BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    assert _email_from_profile(soup) == "apte@berkeley.edu"


def test_school_mailbox_alone_yields_no_email():
    soup = BeautifulSoup(PROFILE_NO_PERSONAL_EMAIL, "html.parser")
    assert _email_from_profile(soup) is None


def test_research_parses_one_interest_per_nested_li():
    soup = BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    research = _research_from_profile(soup)
    # Malformed nesting must NOT bleed every item into the first.
    assert research == "Air pollution, Exposure assessment, Climate change mitigation"


def test_research_stops_at_research_interests_section():
    soup = BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    research = _research_from_profile(soup)
    assert "Education" not in research


def test_enrich_attaches_email_and_research_from_profile():
    people = [{"name": "Joshua Apte", "url": "x"}]
    import src.collectors.ucb_sph_faculty as mod
    orig = mod.fetch_soup
    mod.fetch_soup = lambda url: BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    try:
        _enrich_sph_profiles(people, SPH_CONFIG)
    finally:
        mod.fetch_soup = orig
    assert people[0]["email"] == "apte@berkeley.edu"
    assert "exposure assessment" in people[0]["research_areas"].lower()


def test_research_yields_topical_keywords():
    person = {"name": "Joshua Apte", "url": "x", "title": "Professor",
              "research_areas": "Air pollution, Exposure assessment, Climate change mitigation"}
    opp = normalize_faculty(person, SPH_CONFIG)
    for kw in ("air pollution", "exposure assessment"):
        assert kw in opp["keywords"], kw
    assert "public health" not in opp["keywords"]  # not the broad fallback


def test_output_shape_matches_other_faculty_collectors():
    apte = next(p for p in _scrape() if p["name"] == "Joshua Apte")
    apte["email"] = "apte@berkeley.edu"
    apte["research_areas"] = "Air pollution, exposure assessment, environmental justice"
    opp = normalize_faculty(apte, SPH_CONFIG)
    assert opp["source"] == "ucb_sph_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-sph-")
    assert opp["contact_email"] == "apte@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == SPH_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == SPH_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    # A faculty member with no email, no research, and no topical term in the
    # title falls back to the broad department keyword.
    person = {"name": "Pat Lecturer", "url": "x", "title": "Lecturer"}
    opp = normalize_faculty(person, SPH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["public health"]


def test_title_field_seeds_keyword_for_lite_record():
    # When the listing title names the department (no email/research yet), that
    # term is recovered even for a lite record.
    ahern = next(p for p in _scrape() if p["name"] == "Jennifer Ahern")
    opp = normalize_faculty(ahern, SPH_CONFIG)
    assert opp["contact_email"] is None
    assert opp["keywords"] == ["epidemiology"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole SPH
    corpus on the next scrape. Pin a real corpus id."""
    ahern = next(p for p in _scrape() if p["name"] == "Jennifer Ahern")
    assert normalize_faculty(ahern, SPH_CONFIG)["id"] == "faculty-ucb-sph-62ba77d3"
