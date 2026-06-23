"""Offline tests for src.collectors.ucb_ib_faculty.

No network: fixtures mirror IB's real markup — Name/Phone/Email/Office tables
under "Faculty", "Lecturers", "Emeriti" headings, where each row's name cell is
<a><strong>Name</strong></a><br/>Title and the email cell holds a mailto:.
Only the Faculty table is read. Locks in the table parser, the
Lecturers/Emeriti-table skip, inline email + title, dedup, output shape, and id
stability.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import dedup_by_profile_url, normalize_faculty
from src.collectors.ucb_ib_faculty import IB_CONFIG, _scrape_ib_faculty_list


def _row(detail_id: str, name: str, title: str, email: str) -> str:
    return f"""
    <tr>
      <td><a href="/people/directory/detail/{detail_id}/"><strong>{name}</strong></a><br/>{title}</td>
      <td>(510) 642-0000</td>
      <td><a href="mailto:{email}">{email}</a></td>
      <td>1 VLSB</td>
    </tr>
    """


# Three tables: Faculty (read), Lecturers (skip), Emeriti (skip).
LISTING_HTML = f"""
<div class="region region-content">
  <h2>Faculty</h2>
  <table><tr><th>Name</th><th>Phone</th><th>Email</th><th>Office</th></tr>
    {_row("5436", "David Ackerly", "Dean and Professor", "dackerly@berkeley.edu")}
    {_row("5500", "Doris Bachtrog", "Professor", "dbachtrog@berkeley.edu")}
  </table>
  <h2>Lecturers</h2>
  <table>{_row("6000", "Some Lecturer", "Lecturer", "lecturer@berkeley.edu")}</table>
  <h2>Emeriti</h2>
  <table>{_row("7000", "Old Timer", "Professor Emeritus", "oldtimer@berkeley.edu")}</table>
</div>
"""


def _scrape():
    soup = BeautifulSoup(LISTING_HTML, "html.parser")
    return _scrape_ib_faculty_list(soup, IB_CONFIG["base"])


def test_parses_only_faculty_table():
    names = {p["name"] for p in _scrape()}
    assert names == {"David Ackerly", "Doris Bachtrog"}
    assert "Some Lecturer" not in names  # Lecturers table skipped
    assert "Old Timer" not in names  # Emeriti table skipped


def test_name_title_email_and_absolute_link():
    ackerly = next(p for p in _scrape() if p["name"] == "David Ackerly")
    assert ackerly["title"] == "Dean and Professor"
    assert ackerly["email"] == "dackerly@berkeley.edu"
    assert ackerly["url"] == "https://ib.berkeley.edu/people/directory/detail/5436/"


def test_dedup_collapses_same_profile_url():
    dupes = [
        {"name": "David Ackerly", "url": "https://ib.berkeley.edu/people/directory/detail/5436/"},
        {"name": "David Ackerly", "url": "https://ib.berkeley.edu/people/directory/detail/5436/"},
        {"name": "Doris Bachtrog", "url": "https://ib.berkeley.edu/people/directory/detail/5500/"},
    ]
    out = dedup_by_profile_url(dupes)
    assert [p["name"] for p in out] == ["David Ackerly", "Doris Bachtrog"]


def test_output_shape_with_email():
    ackerly = next(p for p in _scrape() if p["name"] == "David Ackerly")
    opp = normalize_faculty(ackerly, IB_CONFIG)
    assert opp["source"] == "ucb_ib_faculty"
    assert opp["source_type"] == "faculty_research"
    assert opp["organization"] == "University of California, Berkeley"
    assert opp["id"].startswith("faculty-ucb-ib-")
    assert opp["contact_email"] == "dackerly@berkeley.edu"
    assert opp["metadata"]["confidence_score"] == 0.7  # has email
    assert opp["eligibility"]["majors"] == IB_CONFIG["majors"]
    assert opp["on_campus"] is False
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["work_auth_notes"] == IB_CONFIG["work_auth_notes"]
    # No research from the listing -> broad department keyword.
    assert opp["keywords"] == ["integrative biology"]


def test_known_record_id_is_byte_stable():
    """Ids are the upsert key — a drifted derivation duplicates the whole IB
    corpus on the next scrape. Pin a real corpus id."""
    ackerly = next(p for p in _scrape() if p["name"] == "David Ackerly")
    assert normalize_faculty(ackerly, IB_CONFIG)["id"] == "faculty-ucb-ib-cf4b614c"
