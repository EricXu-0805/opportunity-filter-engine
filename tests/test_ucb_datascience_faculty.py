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
