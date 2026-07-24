"""Tests for the CDSS / Data Science collector (src/collectors/ucb_datascience_faculty).

Both CDSS unit directories (DSUS, CCB) list faculty as name headings with a
role/department line and a profile link, and expose no email. The parser test
uses a fixture mirroring that heading structure. No network.
"""

from __future__ import annotations

import pytest

from src.collectors import ucb_datascience_faculty as ds
from src.normalizers.school_audience import SOURCE_DEFAULTS

HEADING_FIXTURE = """
<html><body>
  <div class="content-wrapper">
    <h2>DSUS Faculty Leadership</h2>
  </div>
  <div class="content-wrapper">
    <h2>Dennis Feehan</h2>
    <p>Associate Professor, Department of Demography</p>
    <a href="https://dennisfeehan.org">profile</a>
  </div>
  <div class="content-wrapper">
    <h2>Michael Boots</h2>
    <p>Professor of Integrative Biology</p>
    <a href="/people/michael-boots">profile</a>
  </div>
</body></html>
"""


def _soup(html):
    bs4 = pytest.importorskip("bs4")
    return bs4.BeautifulSoup(html, "html.parser")


class TestScrapeHeadings:
    def test_extracts_people_skips_section_headings(self):
        rows = {r["name"]: r for r in ds._scrape_headings(_soup(HEADING_FIXTURE), "https://ccb.berkeley.edu")}
        # "DSUS Faculty Leadership" is a section label, not a person → excluded.
        assert set(rows) == {"Dennis Feehan", "Michael Boots"}

    def test_captures_title_and_profile_link(self):
        rows = {r["name"]: r for r in ds._scrape_headings(_soup(HEADING_FIXTURE), "https://ccb.berkeley.edu")}
        assert rows["Dennis Feehan"]["url"] == "https://dennisfeehan.org"
        # "Professor of X" prefix stripped from the title.
        assert rows["Michael Boots"]["url"].endswith("/people/michael-boots")
        assert "Integrative Biology" in rows["Michael Boots"]["title"]

    def test_directories_expose_no_email(self):
        rows = ds._scrape_headings(_soup(HEADING_FIXTURE), "https://ccb.berkeley.edu")
        assert all(r["email"] == "" for r in rows)

    def test_no_headings_yields_empty(self):
        assert ds._scrape_headings(_soup("<html><body><p>x</p></body></html>"), "https://x.edu") == []


class TestNormalize:
    def test_normalized_record_shape(self):
        from src.collectors.ucb_common import normalize_faculty
        rows = ds._scrape_headings(_soup(HEADING_FIXTURE), "https://ccb.berkeley.edu")
        row = next(r for r in rows if r["name"] == "Dennis Feehan")
        o = normalize_faculty(row, ds.CDSS_CONFIG)
        assert o["source"] == "ucb_datascience_faculty"
        assert o["source_type"] == "faculty_research"
        assert o["pi_name"] == "Dennis Feehan"
        assert o["contact_email"] is None  # lite
        assert isinstance(o["keywords"], list) and o["keywords"]

    def test_source_default_registered(self):
        assert SOURCE_DEFAULTS["ucb_datascience_faculty"] == ("ucb", "unknown")


class TestDedupKeepRicher:
    """The DSUS listing repeats people across sections (link-less leadership
    card + home-department card with a real profile URL). Live probe 2026-07:
    first-wins kept the poorer card for Lisa Yan / John DeNero / Zachary
    Pardos, dropping their real profile URLs."""

    def test_richer_later_duplicate_wins(self):
        raw = [
            {"name": "Lisa Yan", "url": "",
             "title": "Faculty Director of Instruction"},
            {"name": "Ada Unique", "url": "/people/ada", "title": "Professor"},
            {"name": "Lisa Yan",
             "url": "https://www2.eecs.berkeley.edu/Faculty/Homepages/yanlisa.html",
             "title": "Department of Electrical Engineering and Computer Sciences"},
        ]
        out = ds._dedup_keep_richer(raw)
        assert [r["name"] for r in out] == ["Lisa Yan", "Ada Unique"]  # order kept
        assert out[0]["url"].startswith("https://www2.eecs")

    def test_poorer_later_duplicate_loses(self):
        raw = [
            {"name": "John DeNero", "url": "http://denero.org",
             "title": "Department of EECS"},
            {"name": "John DeNero", "url": "", "title": ""},
        ]
        out = ds._dedup_keep_richer(raw)
        assert len(out) == 1
        assert out[0]["url"] == "http://denero.org"

    def test_specific_title_beats_bare_professor(self):
        raw = [
            {"name": "A B", "url": "", "title": "Professor"},
            {"name": "A B", "url": "", "title": "Statistics, Data Science Undergraduate Studies"},
        ]
        assert ds._dedup_keep_richer(raw)[0]["title"].startswith("Statistics")

    def test_nameless_rows_dropped(self):
        assert ds._dedup_keep_richer([{"name": "  ", "url": "x", "title": "y"}]) == []
