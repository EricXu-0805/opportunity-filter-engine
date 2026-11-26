from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.uf_faculty import SCHOOL

PHY = next(d for d in SCHOOL["departments"] if d["short"] == "PHY")


def card(name, rank, slug):
    bio = f'<p class="ufclas-team-grid__bio"><a href="/directory/{slug}/">See Bio</a></p>' if slug else ""
    return f'''<article class="ufclas-team-grid__item"><div class="ufclas-team-grid__content">
        <h3 class="ufclas-team-grid__name">{name}</h3>
        <p class="ufclas-team-grid__position">{rank}</p>
        <p class="ufclas-team-grid__phone"><a href="tel:0000">Phone</a></p>{bio}
        </div></article>'''


def collect(monkeypatch, html):
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *a, **kw: BeautifulSoup(html, "html.parser"))
    ledger = {}
    rows = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [PHY]}, deep=True, unit_ledger=ledger)
    return rows, ledger["phy"]


def test_current_faculty_section_uses_personal_bios_and_retains_reviewed_ids(monkeypatch):
    html = ("<main><h2>Faculty</h2>"
            + card("Jeff Andrews", "Assistant Professor", "jeff-andrews")
            + card("Clifford M. Will", "Distinguished Professor", "clifford-m-will")
            + card("Edwin Pedrozo-Peñafiel", "Assistant Professor", "edwin-pedrozo-penafiel")
            + card("Taylor Example", "Research Professor", "taylor-example")
            + "<h2>Affiliate Faculty</h2>" + card("Jordan Example", "Professor", "jordan-example")
            + "<h2>Emeritus Faculty</h2>" + card("Alex Example", "Professor Emeritus", "alex-example") + "</main>")
    rows, unit = collect(monkeypatch, html)
    assert [(r["pi_name"], r["id"]) for r in rows] == [
        ("Jeff Andrews", "faculty-uf-phy-51d99691"),
        ("Clifford M. Will", "faculty-uf-phy-37f35608"),
        ("Edwin Pedrozo-Peñafiel", "faculty-uf-phy-6e4e3e7c"),
    ]
    for r in rows:
        stamp = r["metadata"]["faculty_title_observation"]
        assert stamp["source"] == PHY["directory_url"]
        assert stamp["name"] == r["pi_name"] and stamp["profile"] == r["url"] == r["source_url"]
    assert unit["observed_count"] == 3


def test_uncertain_profile_or_title_cannot_reassign_a_saved_identity(monkeypatch):
    html = ("<h2>Faculty</h2>" + card("Jeff Andrews", "Professor", "")
            + card("Jeff Andrews", "Associate Professor", "unreviewed-site")
            + card("Casey Example", "Assistant Professor", "jeff-andrews")
            + card("Sudi Chen", "", "sudi-chen")
            + card("Jordan Example", "Lecturer", "jordan-example"))
    rows, unit = collect(monkeypatch, html)
    assert [r["pi_name"] for r in rows] == ["Jordan Example"]
    assert unit["coverage"]["partial_render_rows"] == 4
    assert unit["completeness_status"] != "complete"
