"""Tests for the University of Michigan faculty config (via faculty_graph).

Registration contract + curated-seed floor + the three live-scrape theme
parsers, each against an injected fixture mirroring the real (Cloudflare-walled,
render-mode) directory markup — no network. Mirrors tests/test_princeton_faculty.py.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg
from src.collectors.schools.umich_faculty import SCHOOL
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS


class TestValidator:
    def test_config_is_valid(self):
        assert fg.validate(SCHOOL) == []


class TestRegistration:
    def test_source_in_source_defaults(self):
        assert SOURCE_DEFAULTS[SCHOOL["source"]] == ("umich", "unknown")

    def test_source_in_faculty_sources(self):
        # Else stale professors are never retired by deactivate_stale_faculty.
        assert SCHOOL["source"] in FACULTY_SOURCES


class TestCuratedSeed:
    """The seed layer is the always-on, offline-safe floor (no network)."""

    def test_seed_only_yields_records_offline(self):
        recs = fg.fetch_and_normalize(SCHOOL, deep=False)
        assert len(recs) >= 100
        assert all(r["source"] == "umich_faculty" for r in recs)
        # Every curated seed ships keyworded (that's the point of hand-curation).
        assert all(r.get("keywords") for r in recs)


# ---- LSA "Michigan LSA" AEM theme (lsa.umich.edu): .person card grid ----------
LSA_HTML = """
<div class="person-wrap"><div class="person">
  <a href="/physics/people/faculty/fca.html"><div class="profile-image"></div></a>
  <div class="info">
    <h2 class="name"><a class="themeText themeLink" href="/physics/people/faculty/fca.html">Fred Adams</a></h2>
    <div class="text-wrap">
      <p class="title">Professor</p>
      <p class="email"><a href="mailto:fca@umich.edu">fca@umich.edu</a></p>
      <p class="fields"><a class="field-tag" href="#a">Theoretical Cosmology and Astrophysics</a></p>
    </div>
  </div>
</div></div>
<div class="person-wrap"><div class="person">
  <a href="/physics/people/faculty/postdoc.html"></a>
  <div class="info">
    <h2 class="name"><a class="themeText" href="/physics/people/faculty/postdoc.html">Jane Postdoc</a></h2>
    <div class="text-wrap"><p class="title">Postdoctoral Research Fellow</p></div>
  </div>
</div></div>
"""


class TestLSAScrape:
    def _dept(self):
        return next(d for d in SCHOOL["departments"] if d["short"] == "PHYS")

    def test_parses_name_rank_email_keywords(self, monkeypatch):
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(LSA_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._dept())}
        assert "Fred Adams" in people
        adams = people["Fred Adams"]
        assert adams["email"] == "fca@umich.edu"
        assert "Theoretical Cosmology and Astrophysics" in (adams.get("keywords") or [])
        assert adams["url"].startswith("https://lsa.umich.edu/physics/people/faculty/")

    def test_ladder_filter_drops_postdoc(self, monkeypatch):
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(LSA_HTML, "html.parser"))
        names = {p["name"] for p in fg._scrape_directory(self._dept())}
        assert "Jane Postdoc" not in names


# ---- College of Engineering WordPress theme (*.engin.umich.edu): .faculty-row --
ENGIN_HTML = """
<div class="faculty-row">
  <div class="col"><img alt="Jeffrey Abell"/></div>
  <div class="col">
    <span class="faculty-name"><a href="https://me.engin.umich.edu/people/faculty/jeffrey-abell/">Jeffrey Abell</a></span>
    <span class="faculty-titles">Professor, Mechanical Engineering</span>
    <a class="faculty-email" href="mailto:jaabell@umich.edu">jaabell@umich.edu</a>
    <span class="faculty-interests">Research Interests: turbulence modeling, combustion, fluid mechanics</span>
  </div>
</div>
<div class="faculty-row">
  <div class="col">
    <span class="faculty-name"><a href="/x">Sam Staff</a></span>
    <span class="faculty-titles">Laboratory Manager</span>
  </div>
</div>
"""


class TestEnginScrape:
    def _dept(self):
        return next(d for d in SCHOOL["departments"] if d["short"] == "ME")

    def test_parses_name_rank_email_and_derives_keywords(self, monkeypatch):
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(ENGIN_HTML, "html.parser"))
        dept = self._dept()
        people = {p["name"]: p for p in fg._scrape_directory(dept)}
        assert "Jeffrey Abell" in people and "Sam Staff" not in people  # staff dropped
        abell = people["Jeffrey Abell"]
        assert abell["email"] == "jaabell@umich.edu"
        # keywords derive from the free-text interests block at normalize time.
        rec = fg._normalize(SCHOOL, dept, abell)
        assert any("turbulence" in k.lower() or "combustion" in k.lower()
                   for k in (rec.get("keywords") or []))


# ---- EECS shared "eecs_person" template (ece.engin.umich.edu), names "Last, First"
EECS_HTML = """
<div class="eecs_person_wrapper">
  <div class="eecs_person_copy">
    <p class="eecs_person_name">Afshari, Ehsan </p>
    <div><span class="person_title_section">Professor, EECS &#8211; Electrical and Computer Engineering</span></div>
    <span class="person_copy_section pcs_tall">Research Interests: high frequency circuits, bio-sensing</span>
    <span class="person_copy_section"><a class="person_email" href="mailto:afshari@umich.edu">afshari@umich.edu</a></span>
  </div>
</div>
<div class="eecs_person_wrapper">
  <div class="eecs_person_copy">
    <p class="eecs_person_name">Doe, John</p>
    <div><span class="person_title_section">Lecturer</span></div>
  </div>
</div>
"""


class TestEECSScrape:
    def _dept(self):
        return next(d for d in SCHOOL["departments"] if d["short"] == "ECE")

    def test_name_flip_rank_email_and_ladder_filter(self, monkeypatch):
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(EECS_HTML, "html.parser"))
        people = {p["name"]: p for p in fg._scrape_directory(self._dept())}
        # "Afshari, Ehsan" un-inverted to first-last; lecturer dropped by ladder.
        assert "Ehsan Afshari" in people
        assert "John Doe" not in people
        assert people["Ehsan Afshari"]["email"] == "afshari@umich.edu"
