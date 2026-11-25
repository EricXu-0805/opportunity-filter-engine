"""Accountancy uses a different name heading from the other business rosters."""

from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.clemson_faculty import SCHOOL


def test_accountancy_reads_both_headings_and_keeps_each_contact_with_its_rank(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "ACCT")
    html = """
        <div class="columns"><img alt="Faculty photo"></div>
        <div class="columns"><p class="cu-oversize"><a href="/profiles/ada">Ada Vale</a></p>
            <p><strong>Senior Lecturer</strong><br>Office 10<br>
            <a href="#" title="Email Ada Vale">ada@example.edu</a></p></div>
        <div class="columns"><h4><a href="/profiles/ben">Ben Hall</a></h4>
            <p><strong>Associate Professor</strong><br>
            <a href="mailto:ben@example.edu">Email</a></p></div>
        <div class="columns"><p class="cu-oversize"><a href="/profiles/jo">Jo West</a></p>
            <p><strong>Administrative Coordinator</strong></p></div>
        <div class="columns"><p class="cu-oversize"><a href="/seminars">Seminar Series</a></p>
            <p><strong>Visiting Professor Seminar</strong></p></div>
    """
    monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                        lambda url, **kwargs: BeautifulSoup(html, "html.parser"))
    people = faculty_graph._scrape_directory(dept)
    assert [(p["name"], p["title"], p["url"], p["email"]) for p in people] == [
        ("Ada Vale", "Senior Lecturer", "https://www.clemson.edu/profiles/ada", "ada@example.edu"),
        ("Ben Hall", "Associate Professor", "https://www.clemson.edu/profiles/ben", "ben@example.edu"),
    ]
