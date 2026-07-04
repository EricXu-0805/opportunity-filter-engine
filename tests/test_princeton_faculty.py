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


# The CS directory is client-side rendered — reached via the engine's render mode
# (headless Chromium). Cards carry the rank + per-area research links.
CS_CARD_HTML = """
<ul>
  <li class="custom_card">
    <div class="custom_card__content">
      <h3 class="custom_card__heading"><a class="custom_card__heading-link" href="/people/profile/abtahi">Parastoo Abtahi</a></h3>
      <div class="custom_card__snippet">
        <div class="position">Assistant Professor</div>
        <div class="research_areas"><a href="/research/areas/robotics">Robotics</a><a href="/research/areas/hci">Human-Computer Interaction</a></div>
      </div>
    </div>
  </li>
  <li class="custom_card">
    <div class="custom_card__content">
      <h3 class="custom_card__heading"><a class="custom_card__heading-link" href="/people/profile/emeritus">Old Timer</a></h3>
      <div class="custom_card__snippet"><div class="position">Professor Emeritus</div></div>
    </div>
  </li>
</ul>
"""


class TestRenderMode:
    """CS uses scrape.render=True → the engine fetches via _render_soup (Playwright)
    instead of a plain request. Patch _render_soup with a fixture so no browser is
    needed; also confirm a dead plain-fetch does NOT starve the render path."""

    def _cs_dept(self):
        return next(d for d in SCHOOL["departments"] if d["short"] == "CS")

    def test_render_dept_uses_render_soup(self, monkeypatch):
        from bs4 import BeautifulSoup
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(CS_CARD_HTML, "html.parser"))
        # plain fetch returns None — if the engine used it, we'd get nothing.
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", lambda url: None)
        people = {p["name"]: p for p in fg._scrape_directory(self._cs_dept())}
        assert "Parastoo Abtahi" in people

    def test_render_captures_research_and_filters_emeritus(self, monkeypatch):
        from bs4 import BeautifulSoup
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(CS_CARD_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._cs_dept())}
        assert "Old Timer" not in people  # emeritus dropped by ladder_filter
        kws = people["Parastoo Abtahi"].get("keywords") or []
        assert "Robotics" in kws and "Human-Computer Interaction" in kws


# The Cloudflare-walled dept subdomains share a "Site Builder" theme:
# .content-list-item rows with theme-wide field classes for name/rank/email.
SITEBUILDER_HTML = """
<div class="view-content">
  <div class="content-list-item">
    <a href="/people/jane-roe"><img alt="Jane Roe"/></a>
    <div class="content-list-item-details">
      <span class="field field--name-title">Jane Roe</span>
      <div class="field field--name-field-ps-people-position">Associate Professor</div>
      <div class="field field--name-field-ps-people-email">
        <a class="link-purpose-mailto" href="mailto:jroe@princeton.edu">jroe@princeton.edu</a>
      </div>
    </div>
  </div>
  <div class="content-list-item">
    <a href="/people/postdoc-person"><img alt="Post Doc"/></a>
    <div class="content-list-item-details">
      <span class="field field--name-title">Post Doc</span>
      <div class="field field--name-field-ps-people-position">Postdoctoral Research Associate</div>
    </div>
  </div>
</div>
"""


# Physics (and CEE) additionally file each person under a research subfield via
# the sitewide-category taxonomy — the source _SB_SELECTORS["research_items"] mines.
SITEBUILDER_CATEGORY_HTML = """
<div class="view-content">
  <div class="content-list-item">
    <a href="/people/dmitry-abanin"><img alt="Dmitry Abanin"/></a>
    <div class="content-list-item-details">
      <span class="field field--name-title">Dmitry Abanin</span>
      <div class="field field--name-field-ps-people-position">Professor of Physics</div>
      <div class="content-list-item-bottom">
        <div class="field field--name-field-ps-sitewide-category">
          <div class="tid-4 field__item">Condensed Matter Theory</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


class TestSiteBuilderDepts:
    def _dept(self, short):
        return next(d for d in SCHOOL["departments"] if d["short"] == short)

    def test_sitebuilder_depts_are_render_and_shared_selectors(self):
        for short in ("MAE", "PHY", "EEB", "CBE", "CEE"):
            sc = self._dept(short)["scrape"]
            assert sc.get("render") is True
            assert sc["selectors"]["card"] == ".content-list-item"

    def test_parses_name_rank_email_and_ladder_filters(self, monkeypatch):
        from bs4 import BeautifulSoup
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(SITEBUILDER_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._dept("MAE"))}
        assert "Jane Roe" in people and "Post Doc" not in people  # postdoc dropped
        assert people["Jane Roe"]["email"] == "jroe@princeton.edu"
        assert people["Jane Roe"]["url"].endswith("/people/jane-roe")

    def test_research_category_becomes_keywords(self, monkeypatch):
        # Departments that file people under a research subfield (Physics → "…
        # Theory", CEE → thrusts) expose it via the sitewide-category taxonomy;
        # the shared _SB_SELECTORS research_items selector mines it into keywords.
        from bs4 import BeautifulSoup
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(SITEBUILDER_CATEGORY_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._dept("PHY"))}
        assert "Condensed Matter Theory" in (people["Dmitry Abanin"].get("keywords") or [])
