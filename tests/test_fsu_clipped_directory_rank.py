import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.fsu_faculty import SCHOOL

COMM = next(unit for unit in SCHOOL["departments"] if unit["short"] == "COMM")
PROFILE = "https://directory.cci.fsu.edu/jessica-wendorf-muhamad/"
RAW = "Director of Undergraduate Studies | Director PEAKS Research Laboratory | Associate Profess"
FULL = RAW + "or"


def page(markup):
    return BeautifulSoup(markup, "html.parser")


def rows(monkeypatch, raw, biography, *, resolved_url=PROFILE, profile_name="Jessica Wendorf Muhamad"):
    calls = []

    def read(address):
        calls.append(address)
        if biography is None:
            return None
        result = page(f'<h1 class="entry-title">{profile_name}</h1><div class="fsu-hero-title-tag">{biography}</div>')
        result._ofe_final_url = resolved_url
        return result

    monkeypatch.setattr(ucb_common, "fetch_soup", read)
    roster = page(
        f'<div class="panel-profile faculty comm"><div class="panel-profile-body">'
        f'<a href="{PROFILE} "><h4>Wendorf Muhamad, Jessica</h4></a><p class="job-title">{raw}</p></div></div>'
    )
    cfg = COMM["scrape"]
    people = faculty_graph._parse_cards(roster, cfg["selectors"], cfg["url"], cfg["ladder_filter"], cfg["name_flip"])
    return [faculty_graph._normalize(SCHOOL, COMM, person) for person in people], calls


def test_clipped_directory_rank_is_read_from_the_named_biography(monkeypatch):
    results, calls = rows(monkeypatch, RAW, FULL)
    [person] = results
    assert calls == [PROFILE]
    assert person["id"] == "faculty-fsu-comm-e3519c6b"
    assert person["url"] == person["source_url"] == PROFILE
    assert person["metadata"]["faculty_title"] == FULL


@pytest.mark.parametrize("raw", ["Assistant Professor", "Director of Undergraduate Studies"])
def test_an_untruncated_card_uses_its_own_rank(monkeypatch, raw):
    people, calls = rows(monkeypatch, raw, None)
    assert calls == []
    assert bool(people) == (raw == "Assistant Professor")


@pytest.mark.parametrize("biography,name,final", [
    (None, "Jessica Wendorf Muhamad", PROFILE),
    (FULL, "Another Person", PROFILE),
    (FULL, "Jessica Wendorf Muhamad", "https://elsewhere.example/profile"),
    ("Professor Emerita", "Jessica Wendorf Muhamad", PROFILE),
])
def test_unavailable_changed_or_different_biography_does_not_claim_an_active_rank(monkeypatch, biography, name, final):
    people, calls = rows(monkeypatch, RAW, biography, resolved_url=final, profile_name=name)
    assert not people and calls == [PROFILE]
