from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.umd_faculty import SCHOOL


def test_math_directory_preserves_ids_and_reads_only_each_members_fields(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "MATH")
    page = """
    <div class="jl-width-expand"><h3 class="tm-title">Roe, Ada</h3>
      Associate Professor<br>4413 Kirwan Hall<br>
      <a href="https://example.edu/campus">Campus map</a>
      <a href="mailto:mailto:aroe@example.edu">aroe@example.edu</a>
      <a href="https://example.edu/ada">Website<br></a>
    </div>
    <div class="jl-width-expand"><h3 class="tm-title">Lee, Bo</h3>
      Teaching Professor<br>Kirwan Hall<br>
    </div>
    <div class="jl-width-expand"><h3 class="tm-title">Vale, Cal</h3>
      Professor Emeritus<br>Kirwan Hall<br>
    </div>
    <div class="jl-width-expand"><h3 class="tm-title">Moss, Dee</h3>
      Visiting Professor<br>Kirwan Hall<br>
    </div>"""
    legacy = """
    <div class="catItemView"><h3 class="catItemTitle">
      <a href="/people/faculty/item/1-aroe.html">Roe, Ada</a></h3>
      <span class="catItemExtraFieldsValue">Associate Professor</span>
    </div>"""

    def read(html):
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda *a, **kw: BeautifulSoup(html, "html.parser"))
        return {r["pi_name"]: r for p in faculty_graph._scrape_directory(dept)
                if (r := faculty_graph._normalize(SCHOOL, dept, p))}

    old = read(legacy)["Ada Roe"]
    current = read(page)
    assert set(current) == {"Ada Roe", "Bo Lee"}
    assert current["Ada Roe"]["id"] == old["id"]
    assert current["Ada Roe"]["metadata"]["faculty_title"] == "Associate Professor"
    assert current["Ada Roe"]["source_url"] == "https://example.edu/ada"
    assert current["Ada Roe"]["contact_email"] == "aroe@example.edu"
    assert current["Bo Lee"]["source_url"] == dept["directory_url"]
    assert current["Bo Lee"]["contact_email"] is None
