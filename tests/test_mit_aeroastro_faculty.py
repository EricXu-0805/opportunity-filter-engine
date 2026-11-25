"""Replay the AeroAstro WordPress roster card from November 2026."""

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.mit_faculty import SCHOOL

AA = next(unit for unit in SCHOOL["departments"] if unit["short"] == "AA")
DIRECTORY = AA["directory_url"]


def _card(name, rank, href=None):
    heading = f'<a href="{href}">{name}</a>' if href else name
    position = f"<p><em>{rank}</em></p>" if rank else ""
    return (
        '<div class="wp-block-group cp-post-box-link">'
        '<div class="wp-block-column"><figure><a href="/events/">'
        '<img alt=""></a></figure></div>'
        f'<div class="wp-block-column"><h2 class="wp-block-heading">{heading}</h2>'
        f'{position}<p><strong>Research Areas:</strong> Space Sciences</p></div></div>'
    )


def _read(monkeypatch, body):
    def fetch(url, **kwargs):
        assert url == DIRECTORY
        return ucb_common._mark_fetched_soup_observation(
            BeautifulSoup(f"<main>{body}</main>", "html.parser"), requested_url=url, final_url=url)

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", False)
    ledger = {}
    rows = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [AA]},
                                             deep=True, unit_ledger=ledger)
    return {row["pi_name"]: row for row in rows}, ledger["aa"]


def test_roster_rank_is_separate_from_research_and_unlinked_people_are_retained(monkeypatch):
    rows, unit = _read(monkeypatch, _card("Hamsa Balakrishnan", "Professor", "/people/hamsa-balakrishnan/")
                       + _card("Ada Quill", "", "/people/ada-quill/")
                       + _card("Tina Dale", "Professor of the Practice")
                       + _card("Bea Finch", "Professor, Post Tenure")
                       + _card("Ian Roe", "Professor Emeritus")
                       + _card("Lee Stone", "Interim Associate Department Head")
                       + _card("Jules Black", "", "https://another.example/people/jules/")
                       + _card("Ira Ash", "Finance Manager", "/people/ira-ash/")
                       + '<div class="cp-post-box-link"><h2 class="wp-block-heading">'
                         '<a href="/people/cy/">Cy Poe</a></h2></div>'
                       + '<h2><a href="/seminar/">Distinguished Professor Lecture</a></h2>')

    assert set(rows) == {"Hamsa Balakrishnan", "Ada Quill", "Tina Dale"}
    assert rows["Hamsa Balakrishnan"]["id"] == "faculty-mit-aa-0147440c"
    assert rows["Hamsa Balakrishnan"]["metadata"]["faculty_title"] == "Professor"
    assert rows["Hamsa Balakrishnan"]["url"] == "https://aeroastro.mit.edu/people/hamsa-balakrishnan/"
    assert rows["Ada Quill"]["metadata"]["faculty_title"] == ""
    assert rows["Ada Quill"]["url"] == "https://aeroastro.mit.edu/people/ada-quill/"
    assert rows["Ada Quill"]["keywords"] == ["Space Sciences"]
    assert rows["Tina Dale"]["url"] == DIRECTORY
    assert unit["coverage"]["raw_roster_rows"] == 9
    assert unit["coverage"]["parsed_faculty_rows"] == 3


def test_wrong_heading_link_cannot_drop_a_different_person_and_accepts_a_later_correction(monkeypatch):
    wardle = "/people/brian-l-wardle/"
    rows, _ = _read(monkeypatch, _card("Moe Z. Win", "Professor", wardle)
                    + _card("Brian L. Wardle", "Professor", wardle))
    assert rows["Moe Z. Win"]["url"] == DIRECTORY
    assert rows["Brian L. Wardle"]["url"] == "https://aeroastro.mit.edu" + wardle

    rows, _ = _read(monkeypatch, _card("Moe Z. Win", "Professor", "/people/moe-z-win/"))
    assert rows["Moe Z. Win"]["url"] == "https://aeroastro.mit.edu/people/moe-z-win/"
