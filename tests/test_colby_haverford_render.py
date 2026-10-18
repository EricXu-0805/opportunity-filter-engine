"""Colby and Haverford pages are read through the headless render, from fixtures.

Every Colby and Haverford page answers a plain GET with HTTP 403 and
``cf-mitigated: challenge``, so the static crawl read none of them: on
2026-10-17 campus_graph:colby loaded 0 of its 2 seeds, and neither school's
program records had been checked against their pages since 2026-07-23. The
headless render returns the real pages.

The fixtures are the rendered pages, fetched 2026-10-17, with scripts,
styles, images and attributes other than id/class/href stripped (the records
built from them match the records built from the full pages). No test here
touches the network.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.collectors import campus_graph, faculty_graph
from src.collectors.import_document import parse_import_html
from src.collectors.schools import colby, haverford

FIXTURES = Path(__file__).parent / "fixtures"
_COLBY_RES = "https://www.colby.edu/academics/research"
_AFA = "https://afa.colby.edu/academics/scholar-programs"
RENDERED = {
    f"{_COLBY_RES}/": "colby/research_hub.html",
    f"{_COLBY_RES}/colby-undergraduate-summer-research-retreat/": "colby/cusrr.html",
    f"{_COLBY_RES}/colby-achievement-program-in-the-sciences/": "colby/caps.html",
    "https://www.colby.edu/academics/departments-and-programs/independent-major/senior-scholars/":
        "colby/senior_scholars.html",
    f"{_COLBY_RES}/colby-liberal-arts-symposium/": "colby/clas.html",
    f"{_AFA}/bunche-scholars/": "colby/bunche_scholars.html",
    f"{_AFA}/presidential-scholars/": "colby/presidential_scholars.html",
    f"{_AFA}/pulver-science-scholars/": "colby/pulver_science_scholars.html",
    "https://davisconnects.colby.edu/": "colby/davisconnects.html",
    "https://www.haverford.edu/integrated-natural-sciences-center": "haverford/kinsc.html",
    "https://www.haverford.edu/peace-and-global-citizenship": "haverford/cpgc.html",
    "https://www.haverford.edu/hcah": "haverford/hcah.html",
    "https://www.haverford.edu/provost": "haverford/provost.html",
    "https://www.haverford.edu/tri-co-philly-program": "haverford/philly.html",
}
# Where the old addresses land in a browser; the crawl counts a redirect to
# another page as a failed page.
REDIRECTS = {
    "https://www.colby.edu/research/": f"{_COLBY_RES}/",
    "https://www.haverford.edu/kinsc": "https://www.haverford.edu/integrated-natural-sciences-center",
    "https://www.haverford.edu/cpgc": "https://www.haverford.edu/peace-and-global-citizenship",
    "https://www.haverford.edu/philly-program": "https://www.haverford.edu/tri-co-philly-program",
}


class _Challenge:
    """What a plain GET of every one of these pages returned."""

    status_code = 403
    headers = {"cf-mitigated": "challenge"}

    def raise_for_status(self):
        import requests

        raise requests.HTTPError("403 Client Error: Forbidden")


@pytest.fixture
def pages(monkeypatch):
    import requests

    gets: list[str] = []
    renders: list[str] = []

    def get(url, **_kwargs):
        gets.append(url)
        return _Challenge()

    def render(url, *_args, bounded=False, **_kwargs):
        renders.append(url)
        final = REDIRECTS.get(url, url)
        if final not in RENDERED:
            return None
        soup = parse_import_html((FIXTURES / RENDERED[final]).read_bytes())
        soup._ofe_fetch_metadata = {"requested_url": url, "final_url": final,
                                    "checked_at": datetime.now(UTC).isoformat()}
        return soup

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(faculty_graph, "_render_soup", render)
    return gets, renders


@pytest.mark.parametrize("module, seeds, programs", [(colby, 9, 8), (haverford, 5, 9)])
def test_every_program_page_is_read_through_the_render(pages, module, seeds, programs):
    gets, renders = pages
    records, evidence = campus_graph.fetch_and_normalize_with_evidence(module.SCHOOL, deep=True)

    assert gets == []
    assert len(renders) == seeds
    assert evidence["seed_pages_loaded"] == evidence["seed_pages_expected"] == seeds
    assert evidence["crawl_errors"] == []
    assert len(records) == programs
    assert all(r["metadata"]["seed_page_verified"] is True and r["metadata"]["last_verified"]
               for r in records)
    # Nothing on these pages reads as open or closed; a render must not invent either.
    assert {r["metadata"]["status"] for r in records} == {"unknown"}
    assert all(r["metadata"]["is_active"] is True for r in records)


@pytest.mark.parametrize("module", [colby, haverford])
def test_the_static_path_reads_none_of_these_pages(pages, module):
    gets, renders = pages
    school = {**module.SCHOOL,
              "sources": [{**s, "render": False} for s in module.SCHOOL["sources"]]}

    records, evidence = campus_graph.fetch_and_normalize_with_evidence(school, deep=True)

    assert renders == []
    assert evidence["seed_pages_loaded"] == 0
    assert evidence["seed_pages_failed"] == len(gets)
    assert not any(r["metadata"]["seed_page_verified"] for r in records)


def test_program_records_quote_their_own_page(pages):
    records, _ = campus_graph.fetch_and_normalize_with_evidence(colby.SCHOOL, deep=True)
    caps = next(r for r in records if r["metadata"]["collector_key"] == "colby_caps")
    curated, page = caps["description"].split("\n\nFrom the program page: ")
    assert curated.startswith("An early-research summer bridge program")
    assert page.startswith("CAPS Program CAPS Program A summer bridge program for incoming "
                           "Colby students")

    records, _ = campus_graph.fetch_and_normalize_with_evidence(haverford.SCHOOL, deep=True)
    philly = next(r for r in records if r["metadata"]["collector_key"] == "haverford_tri_co_philly")
    assert philly["url"] == "https://www.haverford.edu/tri-co-philly-program"
    assert "From the program page: Tri-Co Philly Program" in philly["description"]


@pytest.mark.parametrize("old", sorted(REDIRECTS))
def test_an_address_that_redirects_counts_as_a_failed_page(pages, old):
    # Why the seeds point at where the old addresses now land.
    school = {**haverford.SCHOOL, "school_slug": "probe",
              "sources": [{**haverford.SCHOOL["sources"][0], "seeds": [old], "programs": []}]}
    _records, evidence = campus_graph.fetch_and_normalize_with_evidence(school, deep=True)
    assert evidence["seed_pages_loaded"] == 0
    assert all(old not in s for src in (colby.SCHOOL, haverford.SCHOOL)
               for s in src["sources"][0]["seeds"])


def test_the_shard_runs_install_chromium_for_both_schools():
    from scripts.refresh_rotation import browser_schools

    assert {"colby", "haverford"} <= browser_schools()


# --- Colby faculty: the People Directory's own data, read through the render ---
#
# people_directory.html is the rendered directory with its #app[data-page]
# JSON cut to the four fields the config reads (all 1,177 people kept) and the
# 100-card DOM grid and page chrome dropped.

SHARD = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "colby.json"


@pytest.fixture
def directory(monkeypatch):
    import requests
    from bs4 import BeautifulSoup

    from src.collectors.schools import colby_faculty

    renders: list[str] = []
    page = (FIXTURES / "colby" / "people_directory.html").read_text(encoding="utf-8")

    def render(url, *_args, **_kwargs):
        renders.append(url)
        return BeautifulSoup(page, "html.parser")

    def get(url, **_kwargs):
        return _Challenge()

    monkeypatch.setattr(faculty_graph, "_render_soup", render)
    monkeypatch.setattr(requests, "get", get)
    return colby_faculty, renders


def _by_name(records):
    return {r["pi_name"]: r for r in records}


def test_colby_faculty_are_read_from_one_render_of_the_directory(directory):
    colby_faculty, renders = directory
    records = colby_faculty.fetch_and_normalize(deep=True)

    assert renders == ["https://www.colby.edu/people/people-directory/"]
    assert len(records) == 234
    by_name = _by_name(records)
    barner = by_name["Allison Barner"]
    assert barner["id"] == "faculty-colby-biol-3aa85328"
    assert barner["metadata"]["faculty_title"] == "Clare Booth Luce Assistant Professor of Biology"
    assert barner["url"] == "https://www.colby.edu/people/people-directory/allison-barner/"
    assert barner["department"] == "Department of Biology"
    # The directory publishes no address for anyone.
    assert not any(r.get("contact_email") for r in records)
    # Titles as the page states them today.
    assert by_name["John Turner"]["metadata"]["faculty_title"] == (
        "Dean of Faculty 2025 - ; Professor of History")
    assert by_name["Andie Wang"]["department"] == "Department of East Asian Languages and Cultures"


def test_colby_keeps_its_ladder_gate_and_home_departments(directory):
    colby_faculty, _ = directory
    by_name = _by_name(colby_faculty.fetch_and_normalize(deep=True))

    for gone in ("Catherine Besteman",  # "..., Emerita"
                 "Keer Wang",           # Visiting Assistant Professor of Music
                 "Lisa Miller",         # Senior Lab Instructor in Chemistry
                 "RJ Miller",           # Applied Music Instructor in Drum Set
                 "David Greene"):       # President; listed under "Colby College"
        assert gone not in by_name
    # A multi-department field files the person under the first one, past a
    # leading "Colby College" or "Center for Arts and Humanities".
    assert by_name["Tahiya Chowdhury"]["department"] == "Department of Computer Science"
    assert by_name["Laura Sachiko Fugikawa"]["department"] == (
        "Women's, Gender, and Sexuality Studies Program")
    assert by_name["Denise Bruesewitz"]["department"] == "Environmental Studies Program"
    assert by_name["Dean Allbritton"]["department"] == "Department of Spanish"
    # A typographic apostrophe from the page keeps the id the harvest minted.
    assert by_name["Kerill O'Neill"]["id"] == "faculty-colby-clas-9e88cc51"


def test_colby_rows_stored_before_the_render_keep_their_ids(directory):
    colby_faculty, _ = directory
    produced = {r["id"] for r in colby_faculty.fetch_and_normalize(deep=True)}
    stored = {r["id"]: r["pi_name"] for r in json.loads(SHARD.read_text(encoding="utf-8"))
              if r["source"] == "colby_faculty"
              and r["metadata"]["first_seen_at"] < "2026-10-18"}

    assert {stored[i] for i in set(stored) - produced} == {
        "Catherine Besteman", "Yuri Funahashi",            # now titled Emerita
        "Chaoran Wang", "Fang Wang", "Tiffany Miller",     # no longer listed
    }


def test_colby_static_fetch_reads_no_faculty(directory, monkeypatch):
    colby_faculty, renders = directory
    school = {**colby_faculty.SCHOOL, "departments": [
        {**d, "json_dir": {**d["json_dir"], "render": False}}
        for d in colby_faculty.SCHOOL["departments"]]}

    assert faculty_graph.fetch_and_normalize(school, deep=True) == []
    assert renders == []


def test_a_failed_colby_render_is_tried_once_and_reads_as_zero_rows(monkeypatch):
    from src.collectors.schools import colby_faculty

    renders: list[str] = []
    monkeypatch.setattr(faculty_graph, "_render_soup",
                        lambda url, *a, **k: renders.append(url))
    ledger: dict = {}

    assert colby_faculty.fetch_and_normalize(deep=True, unit_ledger=ledger) == []
    assert len(renders) == 1
    assert {u["parse_status"] for u in ledger.values()} == {"zero_rows"}
    assert len(ledger) == len(colby_faculty.SCHOOL["departments"])


def test_a_render_json_dir_without_its_attribute_is_rejected():
    school = {"school_slug": "x", "source": "x_faculty", "organization": "X", "id_prefix": "x",
              "departments": [{"short": "A", "name": "A", "json_dir": {"url": "u", "render": True}}]}
    assert "A: json_dir render needs attr_json" in faculty_graph.validate(school)
