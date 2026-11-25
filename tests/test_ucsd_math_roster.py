"""UCSD Mathematics publishes names and ranks in a six-column table."""

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.ucsd_faculty import SCHOOL


def test_math_uses_the_faculty_table_and_keeps_existing_ids(monkeypatch):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == "MATH")
    url = dept["directory_url"]
    html = """
    <a href="/people/emeriti">See Emeriti Faculty Directory</a>
    <table><thead><tr><th>First Name</th><th>Last Name</th><th>Office</th>
    <th>Email</th><th>Website</th><th>Title</th></tr></thead><tbody>
    <tr><td><a href="/node/123">Morris</a></td><td><a href="/node/123">Ang</a></td>
        <td>AP&amp;M</td><td>first@example.edu</td>
        <td><a href="https://example.com">Link</a></td><td>Assistant Professor</td></tr>
    <tr><td>Leesa</td><td>Anzaldo</td><td></td>
        <td><a href="mailto:second@example.edu">second@example.edu</a></td><td></td>
        <td>Assistant Teaching Professor (Lecturer PSOE)</td></tr>
    <tr><td>Michael</td><td>Holst</td><td></td><td>chair@example.edu</td><td></td>
        <td>Department Chair<br>Professor</td></tr>
    <tr><td>Example</td><td>Staff</td><td></td><td></td><td></td><td>Coordinator</td></tr>
    <tr><td>Example</td><td>Visitor</td><td></td><td></td><td></td><td>Visiting Professor</td></tr>
    <tr><td>Example</td><td>Retired</td><td></td><td></td><td></td><td>Professor Emeritus</td></tr>
    <tr><td>Example</td><td>Unknown</td><td></td><td></td><td></td><td></td></tr>
    </tbody></table>"""

    def fetch(link, **_kwargs):
        assert link == url
        return BeautifulSoup(html, "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    people = faculty_graph._scrape_directory(dept)
    rows = [faculty_graph._normalize(SCHOOL, dept, person) for person in people]
    assert [r["pi_name"] for r in rows] == ["Morris Ang", "Leesa Anzaldo", "Michael Holst"]
    assert [r["id"] for r in rows[:2]] == [
        "faculty-ucsd-math-0e70967c", "faculty-ucsd-math-e00befb6",
    ]
    assert rows[0]["url"] == "https://math.ucsd.edu/node/123"
    assert rows[1]["url"] == rows[2]["url"] == url
    assert [r["contact_email"] for r in rows[:2]] == ["first@example.edu", "second@example.edu"]
