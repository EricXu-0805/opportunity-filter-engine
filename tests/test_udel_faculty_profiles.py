from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.udel_faculty import SCHOOL


def test_health_directory_keeps_people_and_uses_their_own_profile():
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "HBNS")
    url = dept["directory_url"]
    path = "/academics/colleges/chs/departments/hbns/faculty/"

    def card(name, title, links):
        return f"""
        <div class="media"><h4 class="media-heading">{name}</h4>
          <span class="media-title">{title}</span>
          <div class="media-email"><a href="mailto:example@udel.edu">Email</a></div>
          <div class="media-content">{links}</div></div>"""

    links = (f'<a href="{path}">Directory</a><a href="{path}aaron-cv.pdf">CV</a>'
             f'<a href="{path}aaron-boulton/">Full Profile &gt;</a>')
    other_unit = '<a href="/academics/colleges/chs/departments/pt/faculty/">Physical Therapy</a>'
    soup = BeautifulSoup(card("Aaron Boulton", "Assistant Professor", links)
                         + card("Morgan Jones", "Lecturer", other_unit)
                         + card("Alex Jones", "Program Coordinator", links), "html.parser")
    cfg = dept["scrape"]
    people = faculty_graph._parse_cards(soup, cfg["selectors"], url, cfg["ladder_filter"])
    rows = [faculty_graph._normalize(SCHOOL, dept, person) for person in people]
    assert [(r["pi_name"], r["url"]) for r in rows] == [
        ("Aaron Boulton", url + "aaron-boulton/"),
        ("Morgan Jones", url),
    ]
    assert rows[0]["id"] == "faculty-udel-hbns-38f2fcab"
