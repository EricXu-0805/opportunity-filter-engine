"""Tests for the Princeton faculty config (via the faculty_graph engine).

Registration contract + the scrape parser against an injected Princeton
``.person-card`` fixture (no network — the live dept subdomains are
Cloudflare-walled). Mirrors tests/test_faculty_graph.py.
"""

from __future__ import annotations

from src.collectors import faculty_graph as fg
from src.collectors.schools.princeton_faculty import SCHOOL
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS

# Mirrors the live Princeton central-Drupal person-card grid: a ladder professor,
# an assistant professor, and a postdoc (dropped by the ladder filter).
PERSON_CARD_HTML = """
<div class="view-content">
  <div class="views-row"><div class="person-card">
    <a class="person-card__image-link" href="/people/michael-aizenman"></a>
    <div class="person-card__content">
      <div class="person-card__name">Michael Aizenman</div>
      <div class="person-card__title">Professor</div>
    </div>
  </div></div>
  <div class="views-row"><div class="person-card">
    <a class="person-card__image-link" href="/people/guido-bosco"></a>
    <div class="person-card__content">
      <div class="person-card__name">Guido Bosco</div>
      <div class="person-card__title">Assistant Professor</div>
    </div>
  </div></div>
  <div class="views-row"><div class="person-card">
    <a class="person-card__image-link" href="/people/fraser-binns"></a>
    <div class="person-card__content">
      <div class="person-card__name">Fraser Binns</div>
      <div class="person-card__title">Postdoctoral Research Associate</div>
    </div>
  </div></div>
</div>
"""


class TestValidator:
    def test_config_is_valid(self):
        assert fg.validate(SCHOOL) == []


class TestRegistration:
    def test_source_in_source_defaults(self):
        assert SOURCE_DEFAULTS[SCHOOL["source"]] == ("princeton", "unknown")

    def test_source_in_faculty_sources(self):
        # Else stale professors are never retired by deactivate_stale_faculty.
        assert SCHOOL["source"] in FACULTY_SOURCES


class TestScrape:
    def _patch(self, monkeypatch):
        from bs4 import BeautifulSoup
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url: BeautifulSoup(PERSON_CARD_HTML, "html.parser"),
        )

    def _dept(self):
        return SCHOOL["departments"][0]

    def test_parses_person_cards(self, monkeypatch):
        self._patch(monkeypatch)
        people = fg._scrape_directory(self._dept())
        names = {p["name"] for p in people}
        assert "Michael Aizenman" in names and "Guido Bosco" in names

    def test_ladder_filter_drops_postdoc(self, monkeypatch):
        self._patch(monkeypatch)
        names = {p["name"] for p in fg._scrape_directory(self._dept())}
        assert "Fraser Binns" not in names  # postdoc, not ladder

    def test_absolutizes_profile_href(self, monkeypatch):
        self._patch(monkeypatch)
        people = {p["name"]: p for p in fg._scrape_directory(self._dept())}
        assert people["Michael Aizenman"]["url"].startswith("https://www.math.princeton.edu/people/")
