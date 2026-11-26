from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.umd_faculty import SCHOOL


def test_physics_current_profiles_and_abbreviated_rank_keep_the_member_id(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "PHYS")

    def read(html):
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda *a, **kw: BeautifulSoup(html, "html.parser"))
        return {r["pi_name"]: r for p in faculty_graph._scrape_directory(dept)
                if (r := faculty_graph._normalize(SCHOOL, dept, p))}

    def card(name, group, rank, slug, layout="jl-width-expand"):
        return f"""<div class="{layout}">
          <h3 class="tm-title"><a href="/directory/faculty/{group}/{slug}.html">{name}</a></h3>
          {rank}<br><a href="mailto:mailto:{slug}@example.edu"></a>
          <a href="https://example.edu/physics-lab">Website</a>
        </div>"""

    old = read("""
    <div class="itemContainer"><h4 class="catItemTitle">
        <a href="/people/faculty/current/item/123-aroe.html">Roe, Ada</a></h4>
        <div class="catItemExtraFields">Title Associate Professor E-mail
          <a href="mailto:aroe@example.edu">aroe@example.edu</a></div>
    </div>""")
    new = read(card("Roe, Ada", "current", "Associate Professor", "aroe")
               + card("Lee, Bo", "current", "Assoc Prof &amp; Assoc Dean", "blee", "el-item jl-panel")
               + card("Vale, Cal", "emeritus", "Professor Emeritus", "cvale")
               + card("Wood, Dee", "research-professors", "Research Professor", "dwood")
               + card("Lane, Eve", "adjunct", "Professor", "elane"))
    assert set(new) == {"Ada Roe", "Bo Lee"}
    assert new["Ada Roe"]["id"] == old["Ada Roe"]["id"]
    assert new["Ada Roe"]["source_url"].endswith("/directory/faculty/current/aroe.html")
    assert new["Ada Roe"]["contact_email"] == "aroe@example.edu"
    assert new["Bo Lee"]["metadata"]["faculty_title"] == "Assoc Prof & Assoc Dean"
