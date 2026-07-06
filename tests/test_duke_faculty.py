"""Tests for the Duke faculty config (via the faculty_graph engine)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg
from src.collectors.schools.duke_faculty import SCHOOL
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS


class TestValidator:
    def test_config_is_valid(self):
        assert fg.validate(SCHOOL) == []


class TestRegistration:
    def test_source_in_source_defaults(self):
        assert SOURCE_DEFAULTS[SCHOOL["source"]] == ("duke", "unknown")

    def test_source_in_faculty_sources(self):
        assert SCHOOL["source"] in FACULTY_SOURCES

    def test_pratt_depts_render_shared_selectors(self):
        for short in ("ECE", "BME", "MEMS", "CEE"):
            d = next(x for x in SCHOOL["departments"] if x["short"] == short)
            assert d["scrape"].get("render") is True
            assert d["scrape"]["selectors"]["card"] == ".faculty-overview"


# Mirrors the live Pratt ``.faculty-overview`` card: name + profile link, a
# public mailto, and a research-interests block.
FACULTY_OVERVIEW_HTML = """
<article class="faculty-overview">
  <div class="faculty-overview__info">
    <h3><a href="https://ece.duke.edu/people/jane-roe/">Jane Roe</a></h3>
    <a class="faculty-overview__email" href="mailto:jane.roe@duke.edu">jane.roe@duke.edu</a>
    <p>Associate Professor in the Department of Electrical and Computer Engineering</p>
  </div>
  <div class="faculty-overview__research">Machine learning, computer vision, robotics</div>
</article>
"""


class TestScrape:
    def _dept(self):
        return next(d for d in SCHOOL["departments"] if d["short"] == "ECE")

    def test_parses_name_email_research(self, monkeypatch):
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(FACULTY_OVERVIEW_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._dept())}
        assert "Jane Roe" in people
        assert people["Jane Roe"]["email"] == "jane.roe@duke.edu"
        assert people["Jane Roe"]["url"].endswith("/people/jane-roe/")
