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


@pytest.mark.parametrize("module, seeds, programs", [(colby, 8, 8), (haverford, 5, 9)])
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


def test_every_colby_seed_backs_a_program():
    # A seed no record is read from costs a render a week for nothing.
    source = colby.SCHOOL["sources"][0]
    assert set(source["seeds"]) == {spec["url"] for spec in source["programs"]}


def test_the_shard_runs_install_chromium_for_both_schools():
    from scripts.refresh_rotation import browser_schools

    assert {"colby", "haverford"} <= browser_schools()


# --- Colby faculty: the People Directory's own data, read through the render ---
#
# people_directory.html is the rendered directory with its #app[data-page]
# JSON cut to the four fields the config reads (all 1,177 people kept) and the
# 100-card DOM grid and page chrome dropped. stored_faculty.json holds the
# identity, contact and activity fields of the 238 colby_faculty rows of
# data/processed/shards/colby.json on 2026-10-17, the curated July harvest.

STORED = json.loads((FIXTURES / "colby" / "stored_faculty.json").read_text(encoding="utf-8"))


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
    stored = {r["id"]: r["pi_name"] for r in STORED}

    assert len(stored) == 238
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


@pytest.mark.parametrize("data_page", ['{"props": {}}', '{"props": {"people": null}}'])
def test_a_directory_page_without_its_people_reads_as_zero_rows(monkeypatch, data_page):
    # The page renders, but its JSON no longer holds the people list.
    from bs4 import BeautifulSoup

    from src.collectors.schools import colby_faculty

    page = BeautifulSoup(f"<div id='app' data-page='{data_page}'></div>", "html.parser")
    renders: list[str] = []
    monkeypatch.setattr(faculty_graph, "_render_soup",
                        lambda url, *a, **k: renders.append(url) or page)
    ledger: dict = {}

    assert colby_faculty.fetch_and_normalize(deep=True, unit_ledger=ledger) == []
    assert len(renders) == 1
    assert {u["parse_status"] for u in ledger.values()} == {"zero_rows"}


def test_a_render_json_dir_without_its_attribute_is_rejected():
    school = {"school_slug": "x", "source": "x_faculty", "organization": "X", "id_prefix": "x",
              "departments": [{"short": "A", "name": "A", "json_dir": {"url": "u", "render": True}}]}
    assert "A: json_dir render needs attr_json" in faculty_graph.validate(school)


# --- The next Colby refresh, replayed through refresh_all ---
#
# The stored rows were last seen on 2026-10-17, and the retirement pass keeps a
# row seen within its 14-day grace period, so the weekly Colby run that first
# retires anyone is 2026-11-07's.

GONE = {"Catherine Besteman", "Yuri Funahashi",            # now titled Emerita
        "Chaoran Wang", "Fang Wang", "Tiffany Miller"}     # no longer listed


def _refresh(monkeypatch, tmp_path, today, page):
    """refresh_all for the colby shard over the stored rows, with only the
    network replaced and the retirement pass run on ``today``."""
    import copy
    import functools

    import requests

    import src.collectors.refresh_all as refresh_all
    import src.normalizers.deactivate_stale_faculty as deactivate
    from src.collectors import ucb_common
    from src.collectors.schools import colby_faculty
    from tests.test_refresh_all import _stub_with_processed_file

    processed = _stub_with_processed_file(monkeypatch, tmp_path, copy.deepcopy(STORED))
    monkeypatch.setattr(refresh_all, "fetch_colby_faculty", colby_faculty.fetch_and_normalize)
    monkeypatch.setattr(refresh_all, "merge_colby_faculty", colby_faculty.merge_into_processed)
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", processed)
    monkeypatch.setattr(refresh_all, "deactivate_stale_faculty",
                        functools.partial(deactivate.deactivate_stale_faculty, today=today))
    monkeypatch.setattr(faculty_graph, "_render_soup", lambda *a, **k: page)

    def post(url, **_kwargs):
        raise requests.ConnectionError(url)

    monkeypatch.setattr(requests, "get", lambda url, **_kwargs: _Challenge())
    monkeypatch.setattr(requests, "post", post)
    summary = refresh_all.refresh_all(deep=True, schools={"colby"})
    return summary, json.loads(processed.read_text(encoding="utf-8"))


def _directory_page(edit=None):
    """The fixture page, its people list passed through ``edit``."""
    from bs4 import BeautifulSoup

    page = BeautifulSoup((FIXTURES / "colby" / "people_directory.html").read_text(encoding="utf-8"),
                         "html.parser")
    if edit is not None:
        app = page.select_one("#app[data-page]")
        data = json.loads(app["data-page"])
        data["props"]["people"] = edit(data["props"]["people"])
        app["data-page"] = json.dumps(data)
    return page


def _relist_tate(department):
    def edit(people):
        for x in people:
            if x["post_title"] == "Winifred Tate":
                x["department"] = department
        return people
    return edit


@pytest.mark.parametrize("today, retired", [
    (datetime(2026, 10, 31).date(), set()),
    (datetime(2026, 11, 7).date(), GONE),
])
def test_the_colby_refresh_retires_the_people_the_directory_no_longer_lists(
        monkeypatch, tmp_path, today, retired):
    summary, corpus = _refresh(monkeypatch, tmp_path, today, _directory_page())

    ledger = summary["sources"]["colby_faculty"]["stale_unit_ledger"]
    assert len(ledger) == 34
    assert {e["completeness_status"] for e in ledger.values()} == {"complete"}
    # The page lists every person, staff included, so each department's
    # roster is all of them, read to the last row.
    assert {e["coverage"]["raw_roster_rows"] for e in ledger.values()} == {1177}
    # Together the 34 read 234 people for the 239 they hold active (Andie Wang
    # merged in), above the 90% the shared page needs.
    assert all(e["shared_roster"] == "https://www.colby.edu/people/people-directory/"
               and e["shared_roster_check"] == {
                   "units": 34, "incomplete_units": [], "observed_count": 234,
                   "baseline_active_count": 239, "withheld": None}
               for e in ledger.values())
    assert len(corpus) == 239
    inactive = [r for r in corpus if r["metadata"]["is_active"] is False]
    assert {r["pi_name"] for r in inactive} == retired
    assert all(r["metadata"]["deactivation_reason"] == "absent_from_directory_rescrape"
               and r["metadata"]["deactivated_at"] == today.isoformat() for r in inactive)
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == len(retired)
    # Andie Wang, new in East Asian Languages and Cultures, where Fang Wang
    # (the same title) is no longer listed: perhaps one person renamed.
    andie = next(r for r in corpus if r["pi_name"] == "Andie Wang")
    assert andie["id"] == "faculty-colby-ealc-7a1ebe0c"
    assert andie["metadata"]["is_active"] is True


def test_a_failed_render_retires_no_one(monkeypatch, tmp_path):
    # Zero rows in every department: the source reads as a suspicious zero,
    # so the retirement pass never weighs its ledger.
    summary, corpus = _refresh(monkeypatch, tmp_path, datetime(2026, 11, 7).date(), None)

    source = summary["sources"]["colby_faculty"]
    assert source["status"] == "suspicious_zero"
    ledger = source["stale_unit_ledger"]
    assert {(e["parse_status"], e["coverage"]["unparsed_rows"], e["shared_roster"])
            for e in ledger.values()} == {
        ("zero_rows", 0, "https://www.colby.edu/people/people-directory/")}
    assert not any(e["retirement_authorized"] for e in ledger.values())
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    assert all(r["metadata"]["is_active"] is True for r in corpus)
    assert {r["id"] for r in STORED} <= {r["id"] for r in corpus}


def _drop_department(name):
    return lambda people: [x for x in people if name not in str(x["department"])]


_ANTH_ROW = {"post_name": "", "business_title": "Professor of Anthropology",
             "department": "Anthropology"}


@pytest.mark.parametrize("edit, incomplete", [
    # A row that is not a person object, a person row with an empty name,
    # an empty object: a row nobody can read could be any department's.
    pytest.param(lambda people: [*people, "Catherine Besteman"], 34, id="not-an-object"),
    pytest.param(lambda people: [*people, {**_ANTH_ROW, "post_title": ""}], 34, id="empty-name"),
    pytest.param(lambda people: [*people, {}], 34, id="empty-object"),
    # One department with no one listed; the list cut to its first half,
    # which leaves two departments with no one.
    pytest.param(_drop_department("Anthropology"), 1, id="department-empty"),
    pytest.param(lambda people: people[:len(people) // 2], 2, id="first-half"),
])
def test_a_directory_not_read_whole_retires_no_one(monkeypatch, tmp_path, edit, incomplete):
    # The 34 departments read one page, so each one's roster only shows the
    # rows the page gave it. Unless every department read the page whole, none
    # of them retires anyone, and every unit's ledger says why.
    summary, corpus = _refresh(monkeypatch, tmp_path, datetime(2026, 11, 7).date(),
                               _directory_page(edit))

    ledger = summary["sources"]["colby_faculty"]["stale_unit_ledger"]
    assert len(ledger) == 34
    assert not any(e["retirement_authorized"] for e in ledger.values())
    checks = [e["shared_roster_check"] for e in ledger.values()]
    assert {c["withheld"] for c in checks} == {"shared_roster_unit_incomplete"}
    assert {c["units"] for c in checks} == {34}
    assert sum(e["completeness_status"] != "complete" for e in ledger.values()) == 34
    assert sum(e["failure_reason"] != "shared_roster_unit_incomplete"
               for e in ledger.values()) == incomplete
    stale = summary["sources"]["deactivate_stale_faculty"]
    assert stale["newly_deactivated"] == 0
    assert all(r["metadata"]["is_active"] is True for r in corpus)
    assert {r["id"] for r in STORED} <= {r["id"] for r in corpus}


def test_a_page_that_lists_too_few_people_retires_no_one(monkeypatch, tmp_path, caplog):
    # Every department still has someone, but together they read 144 people,
    # fewer than 90% of the 239 they hold active.
    def thin(people):
        # Every second professor is left off, but never a department's first.
        firsts: set = set()
        kept = []
        for i, x in enumerate(people):
            professor = "Professor" in x["business_title"]
            if professor and x["department"] in firsts and i % 2:
                continue
            if professor:
                firsts.add(x["department"])
            kept.append(x)
        return kept

    summary, corpus = _refresh(monkeypatch, tmp_path, datetime(2026, 11, 7).date(),
                               _directory_page(thin))

    ledger = summary["sources"]["colby_faculty"]["stale_unit_ledger"]
    assert summary["sources"]["deactivate_stale_faculty"]["newly_deactivated"] == 0
    assert all(r["metadata"]["is_active"] is True for r in corpus)
    assert not any(e["retirement_authorized"] for e in ledger.values())
    check = next(iter(ledger.values()))["shared_roster_check"]
    assert check["incomplete_units"] == []
    assert (check["observed_count"], check["baseline_active_count"]) == (144, 239)
    assert {e["shared_roster_check"]["withheld"] for e in ledger.values()} == {"shared_roster_short"}
    assert {e["failure_reason"] for e in ledger.values()} == {"shared_roster_short"}
    assert "34 unit(s) reading https://www.colby.edu/people/people-directory/ retire " \
           "nobody (shared_roster_short)" in caplog.text


@pytest.mark.parametrize("department", [None, "", "Colby College"])
def test_a_professor_still_listed_under_no_department_is_kept(monkeypatch, tmp_path, department):
    # Winifred Tate is still listed as Professor of Anthropology, but the page
    # no longer gives her a department any unit reads: no unit observes her,
    # yet she is not gone. The five the page lost still retire.
    summary, corpus = _refresh(monkeypatch, tmp_path, datetime(2026, 11, 7).date(),
                               _directory_page(_relist_tate(department)))

    tate = next(r for r in corpus if r["id"] == "faculty-colby-anth-1338c178")
    assert tate["metadata"]["is_active"] is True
    assert {r["pi_name"] for r in corpus if r["metadata"]["is_active"] is False} == GONE
    stale = summary["sources"]["deactivate_stale_faculty"]
    assert stale["records_preserved_still_listed"] == 1
