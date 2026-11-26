from bs4 import BeautifulSoup

from src.collectors.faculty_graph import _parse_cards
from src.collectors.schools.northwestern_faculty import SCHOOL


def test_postdocs_and_alumni_are_not_faculty_even_when_a_card_omits_rank():
    def card(name, url, title=""):
        return (
            f'<div class="people-wrap"><h4><a href="{url}">{name}</a></h4>'
            f'<p itemprop="jobTitle">{title}</p></div>'
        )

    faculty = card("Current Faculty", "/directory/current/")
    mixed = card("Current Professor", "/directory/professor/", "Professor")
    source = "".join((
        "<h3>Core Faculty</h3>", faculty, mixed,
        "<h3>Postdocs</h3>", card("Samantha Wu", "/directory/samantha-wu/"),
        "<h3>Postdoctoral Alumni</h3>", card("Rocco Coppejans", "/directory/rocco-coppejans/"), mixed,
    ))
    config = next(dept["scrape"] for dept in SCHOOL["departments"] if dept["short"] == "CIERA")
    parsed = _parse_cards(BeautifulSoup(source, "html.parser"), config["selectors"], config["url"],
                          config["ladder_filter"], section_filter=config["section_filter"])
    assert [person["name"] for person in parsed] == ["Current Faculty", "Current Professor"]
