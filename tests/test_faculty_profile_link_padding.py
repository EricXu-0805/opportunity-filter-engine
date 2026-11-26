import pytest
from bs4 import BeautifulSoup

from backend.lib.public_projection import safe_public_http_url
from src.collectors import faculty_graph
from src.collectors.schools.miami_faculty import SCHOOL

NURSING = next(dept for dept in SCHOOL["departments"] if dept["short"] == "SONHS")
TONY = "https://people.miami.edu/profile/a1e7d2ef1ef8b9fd0c681b22e15044f7"


def test_padded_campus_link_survives_the_card_filter_and_keeps_the_original_person():
    page = BeautifulSoup(
        f'<article><a href="  {TONY}  ">Tony Umadhay</a><b>Professor</b></article>', "html.parser",
    )
    rows = faculty_graph._parse_cards(
        page, {"card": "article", "name": "a", "link": "a", "title": "b"},
        NURSING["directory_url"], link_filter=r"^https://people\.miami\.edu/profile/[a-f0-9]+$",
    )
    [person] = rows
    assert person["url"] == TONY
    row = faculty_graph._normalize(SCHOOL, NURSING, person)
    assert row["id"] == "faculty-miami-sonhs-3042ed43"
    assert safe_public_http_url(row["url"]) == row["source_url"] == TONY


def test_direct_feed_preserves_full_query_fragment_and_exact_reviewed_alias():
    url = "https://directory.example.edu/people?id=20#bio"
    dept = {**NURSING, "profile_id_names": {url: ("Tony Umadhay", "Lonar Anthony Umadhay")}}
    row = faculty_graph._normalize(SCHOOL, dept, faculty_graph.faculty("Tony Umadhay", url=f"\n  {url}\t"))
    assert row["id"] == "faculty-miami-sonhs-3042ed43"
    assert row["url"] == row["source_url"] == url


def test_only_outside_html_whitespace_is_removed():
    url = "https://people.miami.edu/profile/two words"
    row = faculty_graph._normalize(SCHOOL, NURSING, faculty_graph.faculty("Tony Umadhay", url=f"  {url} "))
    assert row["url"] == url
    assert safe_public_http_url(row["url"]) is None
    assert safe_public_http_url(f" {TONY} ") is None


@pytest.mark.parametrize("raw", ["", " \t\n"])
def test_no_personal_link_falls_back_to_directory_without_gaining_a_person_alias(raw):
    dept = {**NURSING, "profile_id_names": {NURSING["directory_url"]: ("Tony Umadhay", "Lonar Anthony Umadhay")}}
    row = faculty_graph._normalize(SCHOOL, dept, faculty_graph.faculty("Tony Umadhay", url=raw))
    assert row["url"] == NURSING["directory_url"]
    assert row["id"] != "faculty-miami-sonhs-3042ed43"
