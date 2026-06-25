"""Offline tests for src.collectors.ucb_philos_faculty.

No network: fixtures mirror Philosophy's real markup — a custom Rails theme where
each faculty member is a `div.PersonListing` whose `div.PersonDescription p`
opens with the name + profile link in `a > b` (href /people/detail/<id>),
followed by the rank, a degree parenthetical, and a research biography. Profiles
carry the personal email as the first mailto: (the department mailbox is second).
Locks in the listing parser (name / rank / biography split), the emeritus drop,
the mailbox-safe email extraction, philosophy keyword mapping, dedup, the output
shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_philos_faculty import (
    PHILOS_CONFIG,
    _email_from_profile,
    _enrich_philos_profiles,
    _scrape_philos_faculty_list,
)


def _listing(detail: str, name: str, body: str) -> str:
    return f"""
    <div class="PersonListing">
      <div class="PersonPhoto"><img alt="photo of {name}"/></div>
      <div class="PersonDescription">
        <p><a href="/people/detail/{detail}"><b>{name}</b></a> {body}</p>
      </div>
    </div>
    """


# Two active faculty + one emeritus (dropped) + a block with no link (skipped).
LISTING_HTML = f"""
<div class="people">
  {_listing("571", "Olivia Bailey",
            "Assistant Professor of Philosophy (Ph.D., Harvard University). "
            "She works on questions in moral psychology and the history of moral philosophy.")}
  {_listing("420", "Joshua Cohen",
            "Distinguished Senior Fellow (Ph.D., Harvard University). "
            "A specialist in political philosophy.")}
  {_listing("9", "Janet Broughton",
            "Professor Emerita (Ph.D., Princeton University). A scholar of early modern philosophy.")}
  <div class="PersonListing"><div class="PersonDescription"><p><b>No Link</b> Lecturer.</p></div></div>
</div>
"""

# Profile with the personal mailto FIRST and the department mailbox second.
PROFILE_WITH_EMAIL = """
<div class="PersonDetail">
  <a href="mailto:obailey@berkeley.edu">obailey@berkeley.edu</a>
  <a href="mailto:phildept@berkeley.edu">phildept@berkeley.edu</a>
</div>
"""

# Only the department mailbox present — must be ignored.
PROFILE_NO_PERSONAL_EMAIL = (
    '<div><a href="mailto:phildept@berkeley.edu">phildept</a></div>'
)


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_philos_faculty_list(soup, PHILOS_CONFIG["base"])


def test_parses_name_rank_biography_and_profile_link():
    people = _scrape()
    bailey = next(p for p in people if p["name"] == "Olivia Bailey")
    assert bailey["title"] == "Assistant Professor of Philosophy"
    assert bailey["url"] == "https://philosophy.berkeley.edu/people/detail/571"
    assert "moral psychology" in bailey["research_areas"].lower()


def test_emeritus_dropped_and_linkless_block_skipped():
    opps = [normalize_faculty(p, PHILOS_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert names == {"Olivia Bailey", "Joshua Cohen"}
    assert "Janet Broughton" not in names  # "Professor Emerita" -> dropped


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Olivia Bailey", "url": "https://philosophy.berkeley.edu/people/detail/571"},
        {"name": "Olivia Bailey", "url": "https://philosophy.berkeley.edu/people/detail/571"},
        {"name": "Joshua Cohen", "url": "https://philosophy.berkeley.edu/people/detail/420"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Olivia Bailey", "Joshua Cohen"]


def test_email_takes_personal_mailto_and_skips_department_mailbox():
    soup = BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    assert _email_from_profile(soup) == "obailey@berkeley.edu"


def test_department_mailbox_alone_yields_no_email():
    soup = BeautifulSoup(PROFILE_NO_PERSONAL_EMAIL, "html.parser")
    assert _email_from_profile(soup) is None


def test_enrich_attaches_email_keeping_listing_research():
    people = [{"name": "Olivia Bailey", "url": "x", "research_areas": "moral psychology"}]
    import src.collectors.ucb_philos_faculty as mod
    orig = mod.fetch_soup
    mod.fetch_soup = lambda url: BeautifulSoup(PROFILE_WITH_EMAIL, "html.parser")
    try:
        _enrich_philos_profiles(people, PHILOS_CONFIG)
    finally:
        mod.fetch_soup = orig
    assert people[0]["email"] == "obailey@berkeley.edu"
    assert people[0]["research_areas"] == "moral psychology"  # listing field untouched


def test_biography_yields_topical_keyword():
    cohen = next(p for p in _scrape() if p["name"] == "Joshua Cohen")
    opp = normalize_faculty(cohen, PHILOS_CONFIG)
    assert "political philosophy" in opp["keywords"]
    assert opp["keywords"] != ["philosophy"]  # not the broad fallback


def test_output_shape_matches_other_faculty_collectors():
    bailey = next(p for p in _scrape() if p["name"] == "Olivia Bailey")
    bailey["email"] = "obailey@berkeley.edu"
    opp = normalize_faculty(bailey, PHILOS_CONFIG)
    assert opp["source"] == "ucb_philos_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-phil-")
    assert opp["contact_email"] == "obailey@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == PHILOS_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == PHILOS_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    # No email and a biography that maps to no topical keyword -> broad fallback.
    person = {"name": "Pat Philosopher", "url": "x", "title": "Lecturer",
              "research_areas": "A generalist with wide-ranging interests."}
    opp = normalize_faculty(person, PHILOS_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["philosophy"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole
    Philosophy corpus on the next scrape. Pin a real corpus id."""
    bailey = next(p for p in _scrape() if p["name"] == "Olivia Bailey")
    assert normalize_faculty(bailey, PHILOS_CONFIG)["id"] == "faculty-ucb-phil-948b797e"
