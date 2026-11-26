from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.umd_faculty import SCHOOL


def test_clark_reads_a_concurrent_research_appointment_but_not_an_emeritus_title_alone():
    dept = next(unit for unit in SCHOOL["departments"] if unit["short"] == "AE")
    cfg = dept["scrape"]

    def card(name, ranks):
        headings = "".join(f"<h3>{rank}</h3>" for rank in ranks)
        return (
            f'<div class="faculty_row"><div class="field-directory-name-title-wrapper">'
            f'<a href="/clark/faculty/{name}">{name}, Ada</a><div class="title-wrapper">{headings}</div></div></div>'
        )

    html = "".join([
        card("Celi", ["Professor Emeritus, Research Professor"]),
        card("Patel", ["Associate Professor Emeritus"]),
        card("Roe", ["Professor Emeritus", "Former Research Professor"]),
        card("Park", ["Adjunct Professor", "Professor Emeritus, Research Professor"]),
    ])
    rows = faculty_graph._parse_cards(
        BeautifulSoup(html, "html.parser"), cfg["selectors"], cfg["url"],
        ladder_filter=cfg["ladder_filter"], name_flip=True,
    )
    assert [(row["name"], row["title"]) for row in rows] == [("Ada Celi", "Research Professor")]
