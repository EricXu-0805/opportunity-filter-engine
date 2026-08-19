"""Offline tests for src.collectors.ucb_journalism_faculty.

No network: fixtures mirror Journalism's real WordPress markup — `div.faculty-profile`
media blocks with the name + profile link in `h4.media-heading a`, the role in
`p.title span.faculty` and rank in `span.chair`, and the personal email in
`p.contact-me a[mailto]`. The collector is listing-only (no bio hop). Locks in
the block parser, title parenthetical stripping, the role-prefix strip for
lecturers, the emeritus drop, email extraction (NOISE-skipped), title-derived
keywords (named chair -> topical, plain rank -> broad fallback), dedup, the
output shape, and id stability.
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
from src.collectors.ucb_journalism_faculty import (
    JOURNALISM_CONFIG,
    _scrape_journalism_faculty_list,
)


def _block(slug: str, name: str, *, role: str = "", chair: str = "",
           plain_title: str = "", email: str | None = "x@berkeley.edu") -> str:
    if chair:
        title_html = (f'<span class="faculty">{role}</span> – '
                      f'<span class="chair">{chair}</span>')
    elif role:
        title_html = f'<span class="faculty">{role}</span> – {plain_title}'
    else:
        title_html = plain_title
    contact = (f'<p class="contact-me"><a href="mailto:{email}"><i class="fa"></i></a></p>'
               if email else "")
    return f"""
    <div class="media faculty-profile">
      <div class="pull-left"><a href="https://journalism.berkeley.edu/person/{slug}/"><img/></a></div>
      <div class="media-body">
        <h4 class="media-heading"><a href="https://journalism.berkeley.edu/person/{slug}/">{name}</a></h4>
        <p class="title">{title_html}</p>
        {contact}
      </div>
    </div>
    """


LISTING_HTML = f"""
<div class="faculty-list">
  {_block("geeta-anand", "Geeta Anand", role="Faculty",
          chair="Professor (On sabbatical Fall 2026)", email="geeta_anand@berkeley.edu")}
  {_block("david-barstow", "David Barstow", role="Faculty",
          chair="Distinguished Chair in Investigative Journalism", email="barstow@berkeley.edu")}
  {_block("john-battelle", "John Battelle", plain_title="Lecturer", email=None)}
  {_block("old-timer", "Old Timer", role="Emeritus", chair="Professor Emeritus")}
  <div class="media faculty-profile"><div class="media-body"><p>No name link here</p></div></div>
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    _mark_fetched_soup_observation(
        soup,
        requested_url=JOURNALISM_CONFIG["url"],
        final_url=JOURNALISM_CONFIG["url"],
    )
    return _scrape_journalism_faculty_list(soup, JOURNALISM_CONFIG["base"])


def test_parses_name_title_email_and_strips_parenthetical():
    people = _scrape()
    geeta = next(p for p in people if p["name"] == "Geeta Anand")
    assert geeta["title"] == "Professor"  # "(On sabbatical ...)" stripped
    assert geeta["url"] == "https://journalism.berkeley.edu/person/geeta-anand/"
    assert geeta["_contact_claim"]["contact_email"] == "geeta_anand@berkeley.edu"


def test_lecturer_role_has_no_prefix_and_no_email_ships_lite():
    battelle = next(p for p in _scrape() if p["name"] == "John Battelle")
    assert battelle["title"] == "Lecturer"
    assert "email" not in battelle  # no contact-me -> lite


def test_emeritus_dropped_and_linkless_block_skipped():
    names = {p["name"] for p in _scrape()}
    assert names == {"Geeta Anand", "David Barstow", "John Battelle"}
    assert "Old Timer" not in names  # role "Emeritus" -> skipped


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Geeta Anand", "url": "https://journalism.berkeley.edu/person/geeta-anand/"},
        {"name": "Geeta Anand", "url": "https://journalism.berkeley.edu/person/geeta-anand/"},
        {"name": "David Barstow", "url": "https://journalism.berkeley.edu/person/david-barstow/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Geeta Anand", "David Barstow"]


def test_named_chair_title_yields_topical_keyword():
    barstow = next(p for p in _scrape() if p["name"] == "David Barstow")
    opp = normalize_faculty(barstow, JOURNALISM_CONFIG)
    assert "investigative journalism" in opp["keywords"]
    assert opp["keywords"] != ["journalism"]  # not the broad fallback


def test_plain_rank_falls_back_to_broad_keyword():
    geeta = next(p for p in _scrape() if p["name"] == "Geeta Anand")
    opp = normalize_faculty(geeta, JOURNALISM_CONFIG)
    assert opp["keywords"] == ["journalism"]  # "Professor" has no topical term


def test_output_shape_matches_other_faculty_collectors():
    geeta = next(p for p in _scrape() if p["name"] == "Geeta Anand")
    opp = normalize_faculty(geeta, JOURNALISM_CONFIG)
    assert opp["source"] == "ucb_journalism_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-jour-")
    assert opp["contact_email"] == "geeta_anand@berkeley.edu"
    assert verified_send_target(opp) == "geeta_anand@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == []
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""


def test_lite_record_has_lower_confidence():
    battelle = next(p for p in _scrape() if p["name"] == "John Battelle")
    opp = normalize_faculty(battelle, JOURNALISM_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole
    Journalism corpus on the next scrape. Pin a real corpus id."""
    geeta = next(p for p in _scrape() if p["name"] == "Geeta Anand")
    assert normalize_faculty(geeta, JOURNALISM_CONFIG)["id"] == "faculty-ucb-jour-93cb4eb3"
