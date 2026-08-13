"""Offline tests for src.collectors.ucb_law_faculty.

No network: fixtures mirror Berkeley Law's real markup — a filter `<select>` that
maps faculty_expertise-<id> to labels, plus `li.preview` cards carrying
`data-pname`, `data-category` (faculty_type-<id> + faculty_expertise-<id> codes),
an `<a>` to the profile, and the rank after the name. Profiles carry a personal
mailto:. Locks in the expertise-map build, the Professor-only / non-emeritus role
filter, the expertise->research-area resolution, area_keywords mapping, email
extraction, dedup, the output shape, and id stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_law_faculty import (
    LAW_CONFIG,
    _build_expertise_map,
    _email_from_profile,
    _scrape_law_faculty_list,
)

# The filter select that maps expertise ids -> labels, plus a few cards. Codes:
# faculty_type-253 Professor, 249 Emeritus, 245 Adjunct; expertise 711 AI,
# 730 Business Associations, 250 (unused).
SELECT_HTML = """
<select name="category">
  <option value="">All Faculty Profiles</option>
  <option value="faculty_type-253">Professor</option>
  <option value="faculty_type-249">Emeritus</option>
  <option value="faculty_type-245">Adjunct</option>
  <option value="faculty_expertise-711">Artificial Intelligence</option>
  <option value="faculty_expertise-730">Business Associations</option>
  <option value="faculty_expertise-678">Administrative Law</option>
</select>
"""


def _card(slug, name, types, expertise, rank):
    cats = " ".join([f"faculty_type-{t}" for t in types]
                    + [f"faculty_expertise-{e}" for e in expertise])
    return f"""
    <li class="preview" data-category="{cats}" data-pname="{name}" id="post-1">
      <a href="https://www.law.berkeley.edu/our-faculty/faculty-profiles/{slug}/">{name}</a>, {rank}
    </li>
    """


LISTING_HTML = f"""
<div class="archive-group">
  {SELECT_HTML}
  <ul class="archive-list">
    {_card("kathryn-abrams", "Kathryn Abrams", ["654", "253"], ["678"],
           "Herma Hill Kay Distinguished Professor of Law")}
    {_card("tara-ai", "Tara Ai", ["253"], ["711", "730"], "Professor of Law")}
    {_card("old-prof", "Old Prof", ["253", "249"], ["678"], "Professor of Law, Emeritus")}
    {_card("ann-adjunct", "Ann Adjunct", ["245"], ["711"], "Adjunct Professor")}
  </ul>
</div>
"""

PROFILE_HTML = '<div><a href="mailto:krabrams@law.berkeley.edu">email</a></div>'
PROFILE_NO_EMAIL = '<div><p>No contact.</p></div>'


def _soup():
    return BeautifulSoup(LISTING_HTML, "html.parser")


def _scrape():
    return _scrape_law_faculty_list(_soup(), LAW_CONFIG["base"])


def test_expertise_map_built_from_select():
    m = _build_expertise_map(_soup())
    assert m["711"] == "Artificial Intelligence"
    assert m["730"] == "Business Associations"
    assert "253" not in m  # faculty_type ids are not expertise


def test_parses_name_title_areas_and_link():
    abrams = next(p for p in _scrape() if p["name"] == "Kathryn Abrams")
    assert abrams["title"] == "Herma Hill Kay Distinguished Professor of Law"
    assert abrams["url"] == "https://www.law.berkeley.edu/our-faculty/faculty-profiles/kathryn-abrams/"
    assert abrams["research_areas"] == "Administrative Law"


def test_only_professors_kept_emeritus_and_adjunct_excluded():
    names = {p["name"] for p in _scrape()}
    assert names == {"Kathryn Abrams", "Tara Ai"}
    assert "Old Prof" not in names    # faculty_type-249 Emeritus
    assert "Ann Adjunct" not in names  # no faculty_type-253


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Kathryn Abrams", "url": "https://www.law.berkeley.edu/our-faculty/faculty-profiles/kathryn-abrams/"},
        {"name": "Kathryn Abrams", "url": "https://www.law.berkeley.edu/our-faculty/faculty-profiles/kathryn-abrams/"},
        {"name": "Tara Ai", "url": "https://www.law.berkeley.edu/our-faculty/faculty-profiles/tara-ai/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Kathryn Abrams", "Tara Ai"]


def test_expertise_maps_to_keywords_via_area_keywords():
    ai = next(p for p in _scrape() if p["name"] == "Tara Ai")
    assert ai["research_areas"] == "Artificial Intelligence; Business Associations"
    opp = normalize_faculty(ai, LAW_CONFIG)
    assert "artificial intelligence" in opp["keywords"]
    assert "corporate law" in opp["keywords"]  # "Business Associations" -> corporate law
    assert "law" not in opp["keywords"]  # not the broad fallback


def test_email_from_profile_and_none_when_absent():
    assert _email_from_profile(BeautifulSoup(PROFILE_HTML, "html.parser")) == "krabrams@law.berkeley.edu"
    assert _email_from_profile(BeautifulSoup(PROFILE_NO_EMAIL, "html.parser")) is None


def test_output_shape_matches_other_faculty_collectors():
    abrams = next(p for p in _scrape() if p["name"] == "Kathryn Abrams")
    abrams["email"] = "krabrams@law.berkeley.edu"
    opp = normalize_faculty(abrams, LAW_CONFIG)
    assert opp["source"] == "ucb_law_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-law-")
    assert opp["contact_email"] == "krabrams@law.berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["eligibility"]["majors"] == LAW_CONFIG["majors"]
    assert opp["on_campus"] is True
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == LAW_CONFIG["work_auth_notes"]


def test_lite_record_falls_back_to_broad_keyword():
    # No email and no expertise tags -> broad fallback.
    person = {"name": "Pat Lawyer", "url": "x", "title": "Professor of Law"}
    opp = normalize_faculty(person, LAW_CONFIG)
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["keywords"] == ["law"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole Law
    corpus on the next scrape. Pin a real corpus id."""
    abrams = next(p for p in _scrape() if p["name"] == "Kathryn Abrams")
    assert normalize_faculty(abrams, LAW_CONFIG)["id"] == "faculty-ucb-law-5023468e"
