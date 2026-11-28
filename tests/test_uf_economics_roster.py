"""UF Economics moved to the CLAS team-grid cards; the roster must still be read."""

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.uf_faculty import SCHOOL

_PAGE = """
<main><div class="ufclas-team-grid"><div class="ufclas-team-grid__container">
  <article class="ufclas-team-grid__item">
    <div class="ufclas-team-grid__image">
      <a href="https://people.clas.example.edu/avery-sample/" aria-label="View bio for Avery Sample">
        <img class="ufclas-team-grid__photo" alt="Headshot"></a></div>
    <div class="ufclas-team-grid__content">
      <h3 class="ufclas-team-grid__name">Avery Sample</h3>
      <p class="ufclas-team-grid__position">Assistant Professor</p>
      <p class="ufclas-team-grid__email"><a href="mailto:asample@example.edu">asample@example.edu</a></p>
      <p class="ufclas-team-grid__bio"><a href="https://people.clas.example.edu/avery-sample/">Profile</a></p>
    </div></article>
  <article class="ufclas-team-grid__item">
    <div class="ufclas-team-grid__image">
      <a href="https://people.clas.example.edu/blake-example/"><img class="ufclas-team-grid__photo" alt="Headshot"></a></div>
    <div class="ufclas-team-grid__content">
      <h3 class="ufclas-team-grid__name">Blake Example</h3>
      <p class="ufclas-team-grid__position">Professor - Labor Economics, Public Finance</p>
      <p class="ufclas-team-grid__email"><a href="mailto:bexample@example.edu">bexample@example.edu</a></p>
    </div></article>
  <article class="ufclas-team-grid__item">
    <div class="ufclas-team-grid__image">
      <a href="https://people.clas.example.edu/casey-retired/"><img class="ufclas-team-grid__photo" alt="Headshot"></a></div>
    <div class="ufclas-team-grid__content">
      <h3 class="ufclas-team-grid__name">Casey Retired</h3>
      <p class="ufclas-team-grid__position">Emeritus Professor</p>
      <p class="ufclas-team-grid__email"><a href="mailto:cretired@example.edu">cretired@example.edu</a></p>
    </div></article>
  <article class="ufclas-team-grid__item">
    <div class="ufclas-team-grid__image">
      <a href="https://people.clas.example.edu/devon-visitor/"><img class="ufclas-team-grid__photo" alt="Headshot"></a></div>
    <div class="ufclas-team-grid__content">
      <h3 class="ufclas-team-grid__name">Devon Visitor</h3>
      <p class="ufclas-team-grid__position">Visiting Assistant Professor</p>
      <p class="ufclas-team-grid__email"><a href="mailto:dvisitor@example.edu">dvisitor@example.edu</a></p>
    </div></article>
</div></div></main>
"""


def _specs(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "ECO")

    def fetch(url, **_kwargs):
        assert url == dept["directory_url"]
        return BeautifulSoup(_PAGE, "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    return dept, faculty_graph._scrape_directory(dept)


def test_team_grid_cards_are_read_and_the_ladder_still_applies(monkeypatch):
    _dept, specs = _specs(monkeypatch)
    assert [(s["name"], s["email"], s["url"]) for s in specs] == [
        ("Avery Sample", "asample@example.edu", "https://people.clas.example.edu/avery-sample/"),
        ("Blake Example", "bexample@example.edu", "https://people.clas.example.edu/blake-example/"),
    ]


def test_areas_after_the_rank_are_research_areas_not_part_of_the_title(monkeypatch):
    dept, specs = _specs(monkeypatch)
    rows = [faculty_graph._normalize(SCHOOL, dept, s) for s in specs]
    assert [r["metadata"]["faculty_title"] for r in rows] == ["Assistant Professor", "Professor"]
    assert [s["research_areas"] for s in specs] == ["", "Labor Economics, Public Finance"]
