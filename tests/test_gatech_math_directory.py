"""Georgia Tech's faculty filter renders a card per person and used to use a table."""

from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.gatech_faculty import SCHOOL

MATH = next(unit for unit in SCHOOL["departments"] if unit["short"] == "MATH")
DIRECTORY = MATH["directory_url"]


def _collect(html):
    soup = BeautifulSoup(html, "html.parser")
    soup._ofe_requested_url = soup._ofe_final_url = DIRECTORY
    soup._ofe_observed_at = "2026-11-26T12:00:00+00:00"
    people = faculty_graph._parse_cards(soup, MATH["scrape"]["selectors"], DIRECTORY)
    return [faculty_graph._normalize(SCHOOL, MATH, person) for person in people]


def _card(name, slug, title, email):
    return (
        f'<div class="profile-card"><div class="profile-name"><a href="/people/{slug}">{name}</a></div>'
        f'<div class="profile-title">{title}</div><div class="profile-email">{email}</div></div>'
    )


def test_filtered_profiles_keep_the_stated_ranks_and_only_their_own_campus_contacts():
    records = _collect(
        _card("Example Faculty", "example", "Professor and Hubbard Chair", "faculty.person@gatech.edu")
        + _card("Example Scientist", "scientist", "Principal Research Scientist",
                'different@gatech.edu <a href="mailto:other@gatech.edu">contact</a>')
        + '<footer>footer.person@gatech.edu</footer>'
    )
    professor, scientist = records
    assert professor["metadata"]["faculty_title"] == "Professor and Hubbard Chair"
    assert professor["metadata"]["identity_bound"] is True
    assert professor["url"] == "https://math.gatech.edu/people/example"
    assert professor["contact_email"] == "faculty.person@gatech.edu"
    assert scientist["metadata"]["faculty_title"] == "Principal Research Scientist"
    assert not scientist["contact_email"]


def test_joint_professors_old_math_id_follows_only_their_original_profile():
    original, unrelated = _collect(
        _card("Dmitrii  Ostrovskii", "dmitrii-ostrovskii", "Assistant Professor", "example@gatech.edu")
        + _card("Dmitrii Ostrovskii", "another-person", "Lecturer", "another@gatech.edu")
    )
    assert original["pi_name"] == "Dmitrii Ostrovskii"
    assert original["id"] == "faculty-gatech-math-c60ef761"
    assert unrelated["id"] != original["id"]


def test_old_table_still_finds_people_and_ignores_headers_and_unrelated_navigation():
    [person] = _collect(
        '<table><tr><th>Faculty</th></tr><tr><td><a href="/people/legacy">Legacy Person</a></td>'
        '</tr></table><nav><table><tr><td><a href="/about">About Us</a></td></tr></table></nav>'
    )
    assert person["pi_name"] == "Legacy Person"
    assert person["url"] == "https://math.gatech.edu/people/legacy"
    assert not person["contact_email"]
    assert not person["metadata"].get("faculty_title")
