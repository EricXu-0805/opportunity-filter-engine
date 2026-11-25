"""NJIT's department directories mix professors, staff and titleless profiles."""

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.njit_faculty import SCHOOL


def _legacy_link(uid, name, title):
    return (
        f'<a class="column" href="//people.njit.edu/profile/{uid}">'
        f'<div class="faculty-staff-profile-card"><h1 class="name">{name}</h1>'
        f'<p class="title">{title}</p><p class="title">{title}</p></div></a>'
    )


def _current_link(uid, name, title):
    role = f'<li class="title">{title}</li>' if title else ""
    return (
        f'<ul class="people-list"><li class="person"><a href="https://people.njit.edu/profile/{uid}">'
        f'<div class="image-container"></div><div class="text-container">'
        f'<div class="name">{name}</div><ul class="title-container">{role}</ul>'
        '</div></a></li></ul>'
    )


def _roster(monkeypatch, links, unit="CS"):
    dept = next(d for d in SCHOOL["departments"] if d["short"] == unit)
    soup = BeautifulSoup("".join(links), "html.parser")
    monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                        lambda url, **kwargs: soup if url == dept["directory_url"] else None)
    people = faculty_graph._scrape_directory(dept)
    rows = [faculty_graph._normalize(SCHOOL, dept, person) for person in people]
    return [row for row in rows if row]


@pytest.mark.parametrize("link", [_legacy_link, _current_link])
def test_roster_template_preserves_profile_identity_and_filters_rank(monkeypatch, link):
    rows = _roster(monkeypatch, [
        link("borcea", "Borcea, Cristian", "Professor"),
        link("chair", "Green, Taylor", "Chair"),
        link("staff", "Hall, Robin", "Program Coordinator"),
        link("unranked", "Lee, Morgan", ""),
        link("retired", "Dale, Leslie", "Professor Emeritus"),
        '<a href="https://people.njit.edu/">Campus Directory</a>',
    ])
    assert [(row["id"], row["pi_name"], row["metadata"]["faculty_title"], row["url"])
            for row in rows] == [
        ("faculty-njit-cs-2a48f569", "Cristian Borcea", "Professor",
         "https://people.njit.edu/profile/borcea"),
    ]


@pytest.mark.parametrize(("unit", "uid", "listing_name", "previous_name", "title", "held_id"), [
    ("CHEM", "shakib", "Shakib, Farnaz", "Shakib, Farnaz Alipour", "Associate Professor",
     "faculty-njit-chem-cd6f856b"),
    ("HSS", "ys44", "Semizer, Yelda", "Semizer Kaplan, Yelda", "Assistant Professor",
     "faculty-njit-hss-abded0f8"),
])
def test_updated_display_name_keeps_existing_id(monkeypatch, unit, uid, listing_name,
                                               previous_name, title, held_id):
    old, = _roster(monkeypatch, [_legacy_link(uid, previous_name, title)], unit)
    current, = _roster(monkeypatch, [_current_link(uid, listing_name, title)], unit)
    assert current["id"] == old["id"] == held_id
    assert current["url"] == old["url"]
    assert current["pi_name"] == faculty_graph._flip_name(listing_name)
