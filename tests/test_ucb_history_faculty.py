"""Offline tests for src.collectors.ucb_history_faculty.

No network: fixtures mirror History's real markup — an Open Berkeley landing page
whose roster is a grid of `div.openberkeley-widgets-label-inner` widgets, each
with the name + profile link in `h2 > a` and a curated research field (e.g.
"Early Modern Europe", "East Asia") in the following `<p>`. Cross-listed faculty
link to area-studies subdomains; profiles carry the personal email as the first
mailto: (the department mailbox is second). Locks in the widget parser, the
emeritus drop, the cross-domain absolute-URL preservation, the mailbox-safe email
extraction, history keyword mapping, dedup, the output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_history_faculty import (
    HISTORY_CONFIG,
    _email_from_profile,
    _enrich_history_profiles,
    _scrape_history_faculty_list,
)


def _widget(href: str, name: str, field: str) -> str:
    return f"""
    <div class="openberkeley-widgets-label-inner">
      <h2><a class="openberkeley-widgets-thumbnail-link" href="{href}">{name}</a></h2>
      <p>{field}</p>
    </div>
    """


# Three active faculty (one cross-listed on another subdomain) + one emeritus
# (dropped) + a widget with no link (skipped by the selector).
LISTING_HTML = f"""
<div class="region-content">
  {_widget("https://history.berkeley.edu/diliana-angelova", "Diliana Angelova", "Byzantine")}
  {_widget("https://history.berkeley.edu/jonathan-sheehan", "Jonathan Sheehan", "Early Modern Europe")}
  {_widget("https://sseas.berkeley.edu/people/munis-d-faruqui", "Munis D. Faruqui", "South Asia")}
  {_widget("https://ethnicstudies.berkeley.edu/people/david-montejano-1/", "David Montejano", "Ethnic Studies (Emeritus)")}
  <div class="openberkeley-widgets-label-inner"><h2>No Link Person</h2><p>Science</p></div>
</div>
"""

# Profile with the personal mailto FIRST and the department mailbox second
# (must be skipped).
PROFILE_WITH_EMAIL = """
<div class="node">
  <a href="mailto:angelova@berkeley.edu">angelova@berkeley.edu</a>
  <a href="mailto:history@berkeley.edu">history@berkeley.edu</a>
</div>
"""

# Only the department mailbox present — must be ignored.
PROFILE_NO_PERSONAL_EMAIL = (
    '<div class="node"><a href="mailto:history@berkeley.edu">history</a></div>'
)


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_history_faculty_list(soup, HISTORY_CONFIG["base"])


def test_parses_name_research_field_and_profile_link():
    people = _scrape()
    angelova = next(p for p in people if p["name"] == "Diliana Angelova")
    assert angelova["research_areas"] == "Byzantine"
    assert angelova["url"] == "https://history.berkeley.edu/diliana-angelova"


def test_cross_listed_absolute_url_is_preserved():
    faruqui = next(p for p in _scrape() if p["name"] == "Munis D. Faruqui")
    assert faruqui["url"] == "https://sseas.berkeley.edu/people/munis-d-faruqui"


def test_emeritus_field_dropped_and_linkless_widget_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Diliana Angelova", "Jonathan Sheehan", "Munis D. Faruqui"}
    assert "David Montejano" not in names  # "(Emeritus)" in the research field
    assert "No Link Person" not in names   # no h2 > a


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Diliana Angelova", "url": "https://history.berkeley.edu/diliana-angelova"},
        {"name": "Diliana Angelova", "url": "https://history.berkeley.edu/diliana-angelova"},
        {"name": "Jonathan Sheehan", "url": "https://history.berkeley.edu/jonathan-sheehan"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Diliana Angelova", "Jonathan Sheehan"]


def test_email_takes_personal_mailto_and_skips_department_mailbox():
    soup = BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    assert _email_from_profile(soup) == "angelova@berkeley.edu"


def test_department_mailbox_alone_yields_no_email():
    soup = BeautifulSoup(PROFILE_NO_PERSONAL_EMAIL, "html.parser")
    assert _email_from_profile(soup) is None


def test_enrich_attaches_email_keeping_listing_research():
    people = [{"name": "Diliana Angelova", "url": "x", "research_areas": "Byzantine"}]
    import src.collectors.ucb_history_faculty as mod
    orig = mod.fetch_soup
    mod.fetch_soup = lambda url: BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    try:
        _enrich_history_profiles(people, HISTORY_CONFIG)
    finally:
        mod.fetch_soup = orig
    assert people[0]["email"] == "angelova@berkeley.edu"
    assert people[0]["research_areas"] == "Byzantine"  # listing field untouched


def test_research_field_yields_topical_keyword():
    sheehan = next(p for p in _scrape() if p["name"] == "Jonathan Sheehan")
    opp = normalize_faculty(sheehan, HISTORY_CONFIG)
    assert "early modern europe" in opp["keywords"]
    assert opp["keywords"] != ["history"]  # not the broad fallback


def test_output_shape_matches_other_faculty_collectors():
    angelova = next(p for p in _scrape() if p["name"] == "Diliana Angelova")
    angelova["email"] = "angelova@berkeley.edu"
    opp = normalize_faculty(angelova, HISTORY_CONFIG)
    assert opp["source"] == "ucb_history_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-hist-")
    assert opp["contact_email"] == "angelova@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == HISTORY_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == HISTORY_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    # No email and a field that maps to no topical keyword -> broad fallback.
    person = {"name": "Pat Historian", "url": "x", "research_areas": "Jewish"}
    opp = normalize_faculty(person, HISTORY_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["history"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole History
    corpus on the next scrape. Pin a real corpus id."""
    angelova = next(p for p in _scrape() if p["name"] == "Diliana Angelova")
    assert normalize_faculty(angelova, HISTORY_CONFIG)["id"] == "faculty-ucb-hist-4f71b77d"
