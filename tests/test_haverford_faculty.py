"""Two Haverford academic directories use distinct URLs but the same person cards."""

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools import haverford_faculty


@pytest.mark.parametrize(
    ("short", "directory", "name", "slug", "title", "expected_id"),
    [
        ("POLS", "https://www.haverford.edu/political-science/faculty",
         "Steve McGovern", "smcgover", "Professor of Political Science",
         "faculty-haverford-pols-d539e435"),
        ("FREN", "https://www.haverford.edu/french-francophone-studies/faculty-staff",
         "Koffi Anyinefa", "kanyinef", "Professor of French and Francophone Studies",
         "faculty-haverford-fren-9869b546"),
    ],
)
def test_configured_directory_keeps_person_link_and_id_after_failed_render(
    monkeypatch, short, directory, name, slug, title, expected_id
):
    department = next(d for d in haverford_faculty.SCHOOL["departments"] if d["short"] == short)
    school = dict(haverford_faculty.SCHOOL, departments=[department])
    people = ((name, slug, title), ("Jeffrey Lamken", "jlamken", "Visiting Professor"),
              ("Robert Mortimer", "rmortime", "Professor Emeritus"),
              ("Karla Alfaro-Urias", "kalfarou", "Academic Department Coordinator"))
    cards = "".join(
        f'<div class="faculty-staff-row"><div class="profile_link-full-name">'
        f'<a href="/users/{person_slug}">{person}</a></div><div class="italic">{role}</div></div>'
        for person, person_slug, role in people
    )
    available = True

    def render(url, **kwargs):
        assert url == directory
        return BeautifulSoup(cards, "html.parser") if available else None

    monkeypatch.setattr(faculty_graph, "_render_soup", render)
    for available in (True, False, True):
        ledger = {}
        records = faculty_graph.fetch_and_normalize(school, deep=True, unit_ledger=ledger)
        assert ledger[short.lower()]["observed_count"] == int(available)
        if available:
            assert [(r["id"], r["url"]) for r in records] == [
                (expected_id, f"https://www.haverford.edu/users/{slug}")
            ]
        else:
            assert not records
            assert not ledger[short.lower()]["retirement_authorized"]
