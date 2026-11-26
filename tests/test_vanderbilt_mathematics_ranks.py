import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools import vanderbilt_faculty


def read_card(content, department="MATH"):
    dept = next(d for d in vanderbilt_faculty.SCHOOL["departments"] if d["short"] == department)
    profile = "https://as.vanderbilt.edu/math/bio/krzysztof-kapulkin"
    html = f'''<table class="table-striped"><tr><td class="biolink">
    <strong><a href="{profile}">Chris Kapulkin</a></strong><br>{content}
    </td><td><a href="mailto:kapulkin@vanderbilt.edu">Email</a></td></tr></table>'''
    people = faculty_graph._parse_cards(BeautifulSoup(html, "html.parser"), dept["scrape"]["selectors"],
                                        dept["directory_url"])
    return faculty_graph._normalize(vanderbilt_faculty.SCHOOL, dept, people[0])


def test_personal_rank_records_source_and_keeps_published_alias():
    row = read_card("<p>Professor of Mathematics</p><p>Dual Appointment: Computer Science</p>")
    assert row["id"] == "faculty-vanderbilt-math-1d5fbacf"
    assert row["pi_name"] == "Chris Kapulkin"
    assert row["metadata"]["faculty_title"] == "Professor of Mathematics · Dual Appointment: Computer Science"
    receipt = row["metadata"]["faculty_title_observation"]
    assert receipt == {
        "name": row["pi_name"], "title": row["metadata"]["faculty_title"], "profile": row["url"],
        "source": "https://as.vanderbilt.edu/math/faculty/", "checked_on": row["metadata"]["last_seen_at"][:10],
    }


@pytest.mark.parametrize("roles", [
    "<p>Research Professor<br>Professor Emeritus</p>",
    "<p>Professor <em>Emeritus</em></p><p>Distinguished Research Professor</p>",
    "<p>Professor Emeritus and Research Professor</p>",
    "<p>On leave this fall</p>",
    "",
])
def test_mixed_or_missing_rank_keeps_person_without_claiming_a_single_appointment(roles):
    row = read_card(roles)
    assert row["metadata"]["is_active"] and not row["metadata"]["faculty_title"]
    assert "faculty_title_observation" not in row["metadata"]


def test_exclusively_retired_faculty_and_unrelated_school_table():
    assert read_card("<p>Professor <em>Emeritus</em></p>") is None
    row = read_card("<p>Professor of Mathematics</p>", department="CHEM")
    assert not row["metadata"]["faculty_title"] and "faculty_title_observation" not in row["metadata"]
