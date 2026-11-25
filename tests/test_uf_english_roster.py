"""Check exact IDs, specialties, profile links and rank-neutral copy for UF English."""

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.uf_faculty import SCHOOL


def test_english_roster_keeps_names_and_specialties_separate(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "ENG")
    html = """
      <main><h1>Alphabetical Listing of Faculty</h1>
      <div class="faculty-listing-item">
        <a class="faculty-listing-img" href="/uwem-akpan/"><img alt="Faculty"></a>
        <div class="faculty-listing-bio"><p><strong>Uwem Akpan</strong></p>
          <p>Creative Writing (Fiction)</p><a href="/uwem-akpan/">See Bio</a></div>
      </div>
      <div class="faculty-listing-item">
        <a class="faculty-listing-img" href="/apollo-amoko/"><img alt=""></a>
        <div class="faculty-listing-bio"><p><strong>Apollo Amoko</strong></p>
          <p>Critical Theory</p><a href="/apollo-amoko/">See Bio</a></div>
      </div></main>
      <footer><a href="/staff-listing/">Staff</a><a href="/emeriti/">Emeritus faculty</a></footer>
    """

    def fetch(url, **_kwargs):
        assert url == dept["directory_url"]
        return BeautifulSoup(html, "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    specs = faculty_graph._scrape_directory(dept)
    assert [s["research_areas"] for s in specs] == ["Creative Writing (Fiction)", "Critical Theory"]
    rows = [faculty_graph._normalize(SCHOOL, dept, s) for s in specs]
    assert [(r["id"], r["url"]) for r in rows] == [
        ("faculty-uf-eng-0150a165", "https://english.ufl.edu/uwem-akpan/"),
        ("faculty-uf-eng-565b1bf2", "https://english.ufl.edu/apollo-amoko/"),
    ]
    assert all(not r["metadata"]["faculty_title"] for r in rows)
