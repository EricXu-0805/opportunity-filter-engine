"""Offline tests for src.collectors.ucb_mcb_faculty.

No network: fixtures mirror MCB's real markup — a "Faculty Research
Descriptions" page where each faculty member is a <p> with the name + profile
link in <a><strong>Name</strong></a> (href /faculty/<div>/<slug>), the rank in
a second <strong>, and a free-text research description as the <p>'s direct
text. MCB is listing-only (profiles publish only the chair's shared email).
Locks in the <p>-block parser, division-nav exclusion, listing research +
keywords, emeritus title drop, the lite (no-email) output shape, and id
stability.
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
    stamp_bound_directory_contact,
)
from src.collectors.ucb_mcb_faculty import (
    _DIRECTORY_URL,
    MCB_CONFIG,
    _name_key,
    _scrape_directory_emails,
    _scrape_mcb_faculty_list,
)

# The directory table page: Name/Phone/Email/Office, with separate Faculty,
# Lecturers, and Emeriti sections. Emails come from here, joined by name.
DIRECTORY_HTML = """
<div class="region region-content">
  <h2>Faculty</h2>
  <table>
    <tr><th>Name</th><th>Phone</th><th>Email</th><th>Office</th></tr>
    <tr><td><a href="/directory/search/detail/1/"><strong>Hillel Adesnik</strong></a><br/>Associate Professor</td>
        <td>(510) 642-2107</td><td><a href="mailto:hadesnik@berkeley.edu">hadesnik@berkeley.edu</a></td><td>201 Weill</td></tr>
    <tr><td><a href="/directory/search/detail/2/"><strong>Jennifer A. Doudna</strong></a><br/>Professor</td>
        <td></td><td><a href="mailto:doudna@berkeley.edu">doudna@berkeley.edu</a></td><td>708 Stanley</td></tr>
  </table>
  <h2>Emeriti</h2>
  <table>
    <tr><td><a href="/directory/search/detail/9/"><strong>Old Timer</strong></a></td>
        <td></td><td><a href="mailto:oldtimer@berkeley.edu">oldtimer@berkeley.edu</a></td><td>1 Hall</td></tr>
  </table>
</div>
"""

# Two active faculty + one emeritus (dropped at normalize) + a division-nav
# link (must NOT be parsed as a person).
LISTING_HTML = """
<div class="region region-content">
  <p><a href="/faculty/all"><strong>Faculty Research Descriptions</strong></a></p>
  <p>
    <a href="https://mcb.berkeley.edu/faculty/cdp/adesnikh"><strong>Hillel Adesnik</strong></a><br/>
    <strong>Associate Professor of Cell Biology, Development and Physiology</strong><br/>
    Dynamics of neural circuits and gene expression underlying information processing.<br/>
  </p>
  <p>
    <a href="/faculty/bbs/doudnaj.html"><strong>Jennifer A. Doudna</strong></a><br/>
    <strong>Professor of Biochemistry, Biophysics and Structural Biology</strong><br/>
    CRISPR genome engineering and RNA biology.<br/>
  </p>
  <p>
    <a href="/faculty/ggd/oldtimer.html"><strong>Old Timer</strong></a><br/>
    <strong>Professor Emeritus of Genetics</strong><br/>
    Classical genetics.<br/>
  </p>
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_mcb_faculty_list(soup, MCB_CONFIG["base"])


def _directory_soup(html: str = DIRECTORY_HTML):
    soup = BeautifulSoup(html, "html.parser")
    return _mark_fetched_soup_observation(
        soup,
        requested_url=_DIRECTORY_URL,
        final_url=_DIRECTORY_URL,
    )


def test_parses_name_title_research_and_absolute_link():
    people = _scrape()
    adesnik = next(p for p in people if p["name"] == "Hillel Adesnik")
    assert adesnik["title"].startswith("Associate Professor")
    assert adesnik["url"] == "https://mcb.berkeley.edu/faculty/cdp/adesnikh"
    assert "neural circuits" in adesnik["research_areas"].lower()


def test_division_nav_link_not_parsed_as_person():
    # /faculty/all is a 2-segment division/nav link, not /faculty/<div>/<slug>.
    names = {p["name"] for p in _scrape()}
    assert "Faculty Research Descriptions" not in names


def test_relative_html_profile_link_resolved():
    doudna = next(p for p in _scrape() if p["name"] == "Jennifer A. Doudna")
    assert doudna["url"] == "https://mcb.berkeley.edu/faculty/bbs/doudnaj.html"


def test_research_yields_topical_keywords():
    doudna = next(p for p in _scrape() if p["name"] == "Jennifer A. Doudna")
    opp = normalize_faculty(doudna, MCB_CONFIG)
    for kw in ("crispr", "rna biology", "biochemistry"):
        assert kw in opp["keywords"], kw
    assert "molecular biology" not in opp["keywords"]  # not the broad fallback


def test_emeritus_dropped_by_title():
    opps = [normalize_faculty(p, MCB_CONFIG) for p in _scrape()]
    names = {o["pi_name"] for o in opps if o}
    assert "Old Timer" not in names  # "Professor Emeritus" -> dropped
    assert names == {"Hillel Adesnik", "Jennifer A. Doudna"}


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "Jennifer A. Doudna", "url": "https://mcb.berkeley.edu/faculty/bbs/doudnaj.html"},
        {"name": "Jennifer A. Doudna", "url": "https://mcb.berkeley.edu/faculty/bbs/doudnaj.html"},
        {"name": "Hillel Adesnik", "url": "https://mcb.berkeley.edu/faculty/cdp/adesnikh"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["Jennifer A. Doudna", "Hillel Adesnik"]


def test_lite_output_shape_no_email():
    adesnik = next(p for p in _scrape() if p["name"] == "Hillel Adesnik")
    opp = normalize_faculty(adesnik, MCB_CONFIG)
    assert opp["source"] == "ucb_mcb_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-mcb-")
    # MCB publishes no individual email -> always lite, but research is present.
    assert opp["contact_email"] is None
    assert opp["metadata"]["confidence_score"] == 0.5
    assert opp["metadata"]["research_areas_raw"]
    assert opp["eligibility"]["majors"] == []
    assert opp["on_campus"] is None
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == ""


def test_directory_emails_parsed_and_emeriti_section_skipped():
    soup = _directory_soup()
    emails = _scrape_directory_emails(soup)
    assert emails[("hillel", "adesnik")] == "hadesnik@berkeley.edu"
    assert emails[("jennifer", "doudna")] == "doudna@berkeley.edu"
    # The Emeriti table is skipped.
    assert ("old", "timer") not in emails


def test_name_key_tolerates_middle_initial():
    # research page "Jennifer A. Doudna" must join the directory "Jennifer Doudna".
    assert _name_key("Jennifer A. Doudna") == _name_key("Jennifer Doudna")


def test_email_joined_by_name_into_record():
    person = next(p for p in _scrape() if p["name"] == "Jennifer A. Doudna")
    directory_soup = _directory_soup()
    emails = _scrape_directory_emails(directory_soup)
    assert stamp_bound_directory_contact(
        person,
        emails.get(_name_key(person["name"])),
        MCB_CONFIG,
        source_soup=directory_soup,
        requested_url=_DIRECTORY_URL,
        email_source="bound_directory_name_join",
    )
    opp = normalize_faculty(person, MCB_CONFIG)
    assert opp["contact_email"] == "doudna@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7
    assert opp["metadata"]["email_source"] == "bound_directory_name_join"
    assert verified_send_target(opp) == "doudna@berkeley.edu"


def test_ambiguous_first_last_directory_join_fails_closed():
    ambiguous = DIRECTORY_HTML.replace(
        "</table>\n  <h2>Emeriti",
        """
    <tr><td><a href="/directory/search/detail/3/"><strong>Jennifer B. Doudna</strong></a></td>
        <td></td><td><a href="mailto:other@berkeley.edu">other@berkeley.edu</a></td><td></td></tr>
  </table>
  <h2>Emeriti""",
    )
    emails = _scrape_directory_emails(_directory_soup(ambiguous))
    assert ("jennifer", "doudna") not in emails


def test_duplicate_first_last_rows_are_ambiguous_even_with_same_email():
    ambiguous = DIRECTORY_HTML.replace(
        "</table>\n  <h2>Emeriti",
        """
    <tr><td><a href="/directory/search/detail/3/"><strong>Jennifer B. Doudna</strong></a></td>
        <td></td><td><a href="mailto:doudna@berkeley.edu">doudna@berkeley.edu</a></td><td></td></tr>
  </table>
  <h2>Emeriti""",
    )
    emails = _scrape_directory_emails(_directory_soup(ambiguous))
    assert ("jennifer", "doudna") not in emails


def test_duplicate_first_last_row_without_email_still_makes_join_ambiguous():
    ambiguous = DIRECTORY_HTML.replace(
        "</table>\n  <h2>Emeriti",
        """
    <tr><td><a href="/directory/search/detail/3/"><strong>Jennifer B. Doudna</strong></a></td>
        <td></td><td></td><td></td></tr>
  </table>
  <h2>Emeriti""",
    )
    emails = _scrape_directory_emails(_directory_soup(ambiguous))
    assert ("jennifer", "doudna") not in emails


def test_directory_join_reads_only_exact_faculty_section():
    with_lecturer = DIRECTORY_HTML.replace(
        "<h2>Emeriti</h2>",
        """
  <h2>Lecturers</h2>
  <table>
    <tr><td><a href="/directory/search/detail/4/"><strong>Alex Kim</strong></a></td>
        <td></td><td><a href="mailto:alexkim@berkeley.edu">alexkim@berkeley.edu</a></td><td></td></tr>
  </table>
  <h2>Emeriti</h2>""",
    )
    emails = _scrape_directory_emails(_directory_soup(with_lecturer))
    assert ("alex", "kim") not in emails


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole MCB
    corpus on the next scrape. Pin a real corpus id."""
    adesnik = next(p for p in _scrape() if p["name"] == "Hillel Adesnik")
    assert normalize_faculty(adesnik, MCB_CONFIG)["id"] == "faculty-ucb-mcb-e4cf2df2"
