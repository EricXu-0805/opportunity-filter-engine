from copy import deepcopy

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.ucsd_faculty import SCHOOL


def test_physics_faculty_cards_keep_person_links_and_profile_facts(monkeypatch):
    dept = deepcopy(next(item for item in SCHOOL["departments"] if item["short"] == "PHYS"))
    dept["scrape"]["profile_enrich"]["throttle"] = 0
    url = dept["directory_url"]
    card = """
        <div class="col-sm-3 mb-4"><div class="pe-5">
          <a href="/people/profile/{num}"><img alt=""></a>
          <a href="/people/profile/{num}"><h4>{name}</h4></a>
          <h5 class="mt-2">{appointment}</h5>
        </div></div>"""
    roster = '<div class="profiles_container"><div class="row">' + "".join(
        card.format(num=i, name=name, appointment=rank) for i, (name, rank) in enumerate([
            ("Monica Allen", "Assistant Professor"), ("Daniel Dubin", "Professor Emeritus"),
            ("Marcelo Rozenberg", "Adjunct Professor"), ("Visiting Faculty", "Visiting Professor"),
            ("Oleg Shpyrko", "Department Chair"), ("Other Chair", "Department Chair"),
        ])
    ) + "</div></div>"
    profile = """
        <main><h1>Monica Allen</h1><div class="profile_container"><div class="row">
          <div class="col-sm-3"><h4>Email</h4><p>monica@example.edu</p></div>
          <div class="col-sm-9"><h3>Assistant Professor</h3>
            <h4>Research Statement</h4><p>Optical measurements of solids.</p>
            <h4>Teaching</h4><p>Unrelated course</p>
          </div></div></div></main><footer>office@example.edu</footer>"""
    source = "https://physics.ucsd.edu/people/profile/0"
    chair_url = "https://physics.ucsd.edu/people/profile/4"
    unknown = "https://physics.ucsd.edu/people/profile/5"
    chair_profile = profile.replace("Monica Allen", "Oleg Shpyrko").replace(
        "<h3>Assistant Professor</h3>", "<h3>Department Chair</h3><h3>Professor</h3>"
    )
    seen = []

    def fetch(href, **_kwargs):
        seen.append(href)
        return BeautifulSoup({url: roster, source: profile, chair_url: chair_profile, unknown: "<h3>Department Chair</h3>"}[href], "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    people = faculty_graph._scrape_directory(dept)
    assert [p["name"] for p in people] == ["Monica Allen", "Oleg Shpyrko"]
    assert people[1]["title"] == "Professor"
    row = faculty_graph._normalize(SCHOOL, dept, people[0])
    assert row["url"] == source
    assert row["metadata"]["faculty_title"] == "Assistant Professor"
    assert row["contact_email"] == "monica@example.edu"
    assert row["metadata"]["research_areas_raw"] == "Optical measurements of solids."
    assert seen == [url, source, chair_url, unknown]
