"""Tests for the Helen Wills Neuroscience collector (src/collectors/ucb_neuro_faculty).

The directory is a single Open-Berkeley views-table with every field inline
(name + profile link, department, research interests, mailto email), so the
parser test uses a fixture mirroring that row structure. No network.
"""

from __future__ import annotations

import pytest

from src.collectors import ucb_neuro_faculty as nf
from src.normalizers.school_audience import SOURCE_DEFAULTS

TABLE_FIXTURE = """
<html><body>
<table class="views-table">
  <tbody>
    <tr class="odd">
      <td class="views-field views-field-title"><a href="/people/hillel-adesnik">Hillel Adesnik</a></td>
      <td class="views-field views-field-field-openberkeley-person-dept">Neuroscience</td>
      <td class="views-field views-field-field-openberkeley-person-resint"><p><span>Neural basis of sensation, perception, and action</span></p></td>
      <td class="views-field views-field-field-openberkeley-person-email"><a href="mailto:hadesnik@berkeley.edu" rel="noreferrer">hadesnik@berkeley.edu</a></td>
    </tr>
    <tr class="even">
      <td class="views-field views-field-title"><a href="/people/no-email-prof">Pat Lite</a></td>
      <td class="views-field views-field-field-openberkeley-person-dept">Neuroscience</td>
      <td class="views-field views-field-field-openberkeley-person-resint">circuit dynamics</td>
      <td class="views-field views-field-field-openberkeley-person-email"></td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def _soup(html):
    bs4 = pytest.importorskip("bs4")
    return bs4.BeautifulSoup(html, "html.parser")


class TestScrapeTable:
    def test_extracts_name_url_email_research(self):
        rows = {r["name"]: r for r in nf._scrape_table(_soup(TABLE_FIXTURE), nf.NEURO_CONFIG["base"])}
        assert set(rows) == {"Hillel Adesnik", "Pat Lite"}
        a = rows["Hillel Adesnik"]
        assert a["email"] == "hadesnik@berkeley.edu"
        assert a["url"].endswith("/people/hillel-adesnik")
        assert "sensation" in a["research_areas"].lower()

    def test_missing_email_ships_lite(self):
        rows = {r["name"]: r for r in nf._scrape_table(_soup(TABLE_FIXTURE), nf.NEURO_CONFIG["base"])}
        assert rows["Pat Lite"]["email"] == ""

    def test_no_table_yields_empty(self):
        assert nf._scrape_table(_soup("<html><body><p>nothing</p></body></html>"), nf.NEURO_CONFIG["base"]) == []


class TestNormalize:
    def test_normalized_record_shape(self):
        from src.collectors.ucb_common import normalize_faculty
        rows = nf._scrape_table(_soup(TABLE_FIXTURE), nf.NEURO_CONFIG["base"])
        o = normalize_faculty(rows[0], nf.NEURO_CONFIG)
        assert o["source"] == "ucb_neuro_faculty"
        assert o["source_type"] == "faculty_research"
        assert o["contact_email"] == "hadesnik@berkeley.edu"
        assert o["pi_name"] == "Hillel Adesnik"

    def test_source_default_registered(self):
        assert SOURCE_DEFAULTS["ucb_neuro_faculty"] == ("ucb", "unknown")
