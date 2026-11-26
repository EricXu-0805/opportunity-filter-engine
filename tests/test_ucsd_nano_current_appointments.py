"""The shared CNE roster can establish a NANO appointment only through the department roster and the named faculty biography."""
import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.ucsd_faculty import SCHOOL

NANO = next(dept for dept in SCHOOL["departments"] if dept["short"] == "NANO")
GRID = NANO["scrape"]["extra_urls"][0]["url"]
PERSON = "https://jacobsschool.ucsd.edu/faculty/profile?id=527"
OID = "faculty-ucsd-nano-8a42e65d"


def grid(name="Zeinab Jahed", url=PERSON, title="Associate Professor"):
    return (f'<div class="faculty-information"><h4><a href="{url}">{name}</a></h4>'
            f'<h5>{title}</h5></div><div class="faculty-information">'
            '<h4><a href="/another-person">Another Person</a></h4><h5>Professor</h5></div>')


def biography(name="Zeinab  Jahed", title="Associate Professor, NENG"):
    return f'<h3 class="faculty_profile_name"><strong>{name}</strong></h3><p>{title}</p>'


def collect(monkeypatch, roster, named_page, *, also_on_legacy=False):
    other = '<tr><td><a href="/ken">Vecchio, Ken</a></td></tr>'
    duplicate = f'<tr><td><a href="{PERSON}">Jahed, Zeinab</a></td></tr>' if also_on_legacy else ""
    pages = {NANO["directory_url"]: f'<table><tbody>{other}{duplicate}</tbody></table>',
             GRID: roster, PERSON: named_page}

    def fetch(url, **kwargs):
        raw = pages[url]
        return BeautifulSoup(raw, "html.parser") if raw else None

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    ledger = {}
    rows = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [NANO]}, deep=True, unit_ledger=ledger)
    assert sum(row["id"] == "faculty-ucsd-nano-467aa36b" for row in rows) == 1
    return [row for row in rows if row["id"] == OID], ledger["nano"]


def test_verified_current_appointment_preserves_both_sources_and_stable_id(monkeypatch):
    for title in ("Associate Professor", "Professor"):
        (row,), _ = collect(monkeypatch, grid(title=title), biography(title=title + ", NENG"))
        assert row["source_url"] == GRID and row["url"] == PERSON
        assert row["pi_name"] == "Zeinab Jahed" and row["metadata"]["faculty_title"] == title
        assert row["metadata"]["verification_scope"] == "directory"
    rows, _ = collect(monkeypatch, grid(), biography(), also_on_legacy=True)
    assert len(rows) == 1 and rows[0]["url"] == PERSON
    assert rows[0]["source_url"] == GRID and rows[0]["metadata"]["faculty_title"] == "Associate Professor"


@pytest.mark.parametrize(("listing", "personal"), [
    (grid(), biography(title="Associate Professor, CHE")),
    (grid(), biography(title="Associate Professor, Chemical and Nano Engineering")),
    (grid(), biography(name="Another Person")),
    (grid(), biography(title="Adjunct Professor, NENG")),
    (grid(), biography(title="Associate Professor, NENG<br>Professor Emeritus, NENG")),
    (grid(name="Another Person"), biography()),
    (grid(url=PERSON + "0"), biography()),
    (grid(title="Adjunct Professor"), biography()),
])
def test_other_appointments_and_changed_identity_do_not_enter_nano(monkeypatch, listing, personal):
    rows, _ = collect(monkeypatch, listing, personal)
    assert rows == []


@pytest.mark.parametrize(("listing", "personal"), [(None, biography()), (grid(), None)])
def test_failed_read_withholds_retirement_and_retry_recovers(monkeypatch, listing, personal):
    rows, observation = collect(monkeypatch, listing, personal)
    assert not rows and observation["coverage"]["partial_render_rows"] >= 1
    (recovered,), _ = collect(monkeypatch, grid(), biography())
    assert recovered["id"] == OID
