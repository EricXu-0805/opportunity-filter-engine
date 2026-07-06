"""Tests for the Purdue faculty config (via the faculty_graph engine)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg
from src.collectors.schools.purdue_faculty import SCHOOL
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS


class TestValidator:
    def test_config_is_valid(self):
        assert fg.validate(SCHOOL) == []


class TestRegistration:
    def test_source_in_source_defaults(self):
        assert SOURCE_DEFAULTS[SCHOOL["source"]] == ("purdue", "unknown")

    def test_source_in_faculty_sources(self):
        assert SCHOOL["source"] in FACULTY_SOURCES


# Mirrors the live Purdue CS ``.people-item`` grid (server-rendered): name +
# rank, no email on the listing (recovered per-profile). A lecturer is dropped
# by the ladder filter.
PEOPLE_ITEM_HTML = """
<div class="people-item" data-position="Professor of Computer Science">
  <p class="people-name"><a href="https://www.cs.purdue.edu/people/faculty/roe.html">Jane Roe</a></p>
  <p class="people-title">Professor</p>
  <p class="people-campus">West Lafayette</p>
</div>
<div class="people-item">
  <p class="people-name"><a href="https://www.cs.purdue.edu/people/faculty/doe.html">John Doe</a></p>
  <p class="people-title">Lecturer</p>
</div>
"""


class TestScrape:
    def _dept(self):
        return SCHOOL["departments"][0]

    def test_parses_name_rank_and_ladder_filters(self, monkeypatch):
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(PEOPLE_ITEM_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._dept())}
        assert "Jane Roe" in people and "John Doe" not in people  # lecturer dropped
        assert people["Jane Roe"]["title"] == "Professor"
        assert people["Jane Roe"]["url"].endswith("/faculty/roe.html")
