"""A retired Jacobs profile route is only replaced for its confirmed owner."""
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.ucsd_faculty import SCHOOL

LEGACY = "http://jacobsschool.ucsd.edu/faculty/faculty_bios/findprofile.sfe?department=NANO&fmp_recid=396"
PROFILE = "https://jacobsschool.ucsd.edu/faculty/profile?id=396"


def test_nano_keeps_the_original_id_and_uses_the_personal_jacobs_profile(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "NANO")
    markup = f"""
    <table><tbody><tr><td><a href="{LEGACY}">Liu, Ping</a></td>
    <td><a href="mailto:pliu@ucsd.edu">piliu@ucsd.edu</a></td></tr>
    <tr><td><a href="{LEGACY}">Lane, Jane</a></td></tr>
    <tr><td><a href="/new-lab">Liu, Ping</a></td></tr></tbody></table>"""
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda *_a, **_kw: BeautifulSoup(markup, "html.parser"))
    people = faculty_graph._scrape_directory(dept)
    rows = [faculty_graph._normalize(SCHOOL, dept, person) for person in people]
    assert [p["url"] for p in rows] == [PROFILE, LEGACY, "https://nanoengineering.ucsd.edu/new-lab"]
    assert rows[0]["source_url"] == PROFILE
    assert rows[0]["id"] == "faculty-ucsd-nano-2097ee48"
    assert rows[0]["contact_email"] == "piliu@ucsd.edu"
