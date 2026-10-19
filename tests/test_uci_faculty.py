"""UC Irvine's Engineering and Mathematics rosters moved; fixture replays of the new pages.

engineering.uci.edu left Drupal between the 2026-10-10 and 2026-10-17 refreshes.
The 2026-10-17 run got a 404 for every ``/dept/<short>/faculty-staff/faculty``
roster, so EECS, MAE, BME, CBE, CEE and MSE read zero rows and their rows were
last seen 2026-10-10. Each department now lists its faculty at
``/dept/<short>/people/faculty.php`` as hand-edited cards, and each person links
to ``/directory/<last>_<first>.php`` instead of ``/users/<slug>``.

math.uci.edu moved to WordPress. ``/people`` answered 404 on the 2026-08-22,
10-10 and 10-17 refreshes (no Mathematics row has been seen since 2026-08-15),
and the core faculty are a paged ``/role/core-faculty/`` archive that writes six
names without the middle initial or second surname their rows were stored under.

The page fixtures are cards copied from those pages on 2026-10-18, every
address replaced by a placeholder. No test here touches the network.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import uci_faculty
from tests.test_css_selector_strict import strict_error

FIXTURES = Path(__file__).parent / "fixtures" / "uci"
PAGES = {
    "https://engineering.uci.edu/dept/eecs/people/faculty.php": "eecs_faculty.html",
    "https://engineering.uci.edu/dept/cbe/people/faculty.php": "cbe_faculty.html",
    "https://engineering.uci.edu/dept/cee/people/faculty.php": "cee_faculty.html",
    "https://engineering.uci.edu/dept/mse/people/faculty.php": "mse_faculty.html",
    "https://math.uci.edu/role/core-faculty/": "math_core_faculty.html",
    "https://math.uci.edu/role/core-faculty/page/2/": "math_core_faculty_2.html",
}
UNITS = {"EECS", "CBE", "CEE", "MSE", "MATH"}
# The id and name of each stored row these tests look up, as
# data/processed/shards/uci.json held them after the 2026-10-17 refresh. A
# refresh writes today's name into every row it sees again, so the shard
# itself stops recording the spelling an id was minted from.
STORED = {r["id"]: r["pi_name"] for r in json.loads(
    (FIXTURES / "stored_faculty.json").read_text(encoding="utf-8"))}


def _soup(url, *args, **kwargs):
    name = PAGES.get(url)
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"),
                         "html.parser") if name else None


@pytest.fixture
def run(monkeypatch) -> tuple[dict[str, dict], dict]:
    monkeypatch.setattr(ucb_common, "fetch_soup", _soup)
    monkeypatch.setattr(faculty_graph.time, "sleep", lambda _s: None)
    school = {**uci_faculty.SCHOOL,
              "departments": [d for d in uci_faculty.SCHOOL["departments"]
                              if d["short"] in UNITS]}
    ledger: dict = {}
    records = faculty_graph.fetch_and_normalize(school, deep=True, unit_ledger=ledger)
    return {r["pi_name"]: r for r in records}, ledger


def _unit(records: dict[str, dict], short: str) -> set[str]:
    return {n for n, r in records.items() if r["id"].split("-")[2] == short.lower()}


def test_every_samueli_department_reads_its_people_page():
    urls = {d["short"]: d["scrape"]["url"] for d in uci_faculty.SCHOOL["departments"]
            if d["scrape"]["url"].startswith("https://engineering.uci.edu/")}
    assert urls == {s: f"https://engineering.uci.edu/dept/{s.lower()}/people/faculty.php"
                    for s in ("EECS", "MAE", "BME", "CBE", "CEE", "MSE")}


def test_the_new_selectors_are_strictly_valid():
    for short in ("EECS", "MATH"):
        sel = next(d for d in uci_faculty.SCHOOL["departments"]
                   if d["short"] == short)["scrape"]["selectors"]
        for key in ("card", "name", "link", "title", "email"):
            assert strict_error(sel[key]) is None, (short, key)


def test_eecs_keeps_its_professors_and_drops_teaching_and_adjunct_ranks(run):
    records, _ = run
    assert _unit(records, "EECS") == {"A. Lee Swindlehurst", "Dion Khodagholy"}
    lee = records["A. Lee Swindlehurst"]
    assert lee["url"] == "https://engineering.uci.edu/directory/swindlehurst_lee.php"
    assert lee["metadata"]["faculty_title"].startswith(
        "Nicolaos G. and Sue Curtis Alexopoulos Presidential Chair and")
    assert lee["keywords"][:2] == ["Signal processing", "estimation and detection theory"]
    assert lee["contact_email"] == "person1@uci.edu"


def test_the_rank_pattern_stays_fast_on_a_card_built_to_stall_it():
    """A long run of degrees after the name link, with no label after it, took
    8.5 s with a backtracking pattern; the rank pattern reads every card."""
    pattern = re.compile(uci_faculty._ENG["title_html_re"], re.I | re.S)
    card = '<a href="/directory/x.php">A</a>' + ", Ph.D" * 20000
    started = time.perf_counter()
    assert pattern.search(card) is None
    assert time.perf_counter() - started < 1.0


def test_a_degree_left_outside_the_name_link_stays_out_of_the_rank(run):
    records, _ = run
    assert records["Dion Khodagholy"]["metadata"]["faculty_title"] == (
        "Associate Professor, Henry Samueli Faculty Excellence; "
        "Electrical Engineering and Computer Science")


def test_a_name_in_a_paragraph_and_a_rank_outside_any_span_are_read(run):
    records, _ = run
    assert _unit(records, "CBE") == {"Szu-Wen Wang", "Plamen Atanassov", "Nancy Da Silva"}
    assert records["Plamen Atanassov"]["metadata"]["faculty_title"] == (
        "Chancellor’s Professor, Department of Chemical and Biomolecular Engineering")
    assert records["Nancy Da Silva"]["metadata"]["faculty_title"].startswith(
        "Professor of Department of Chemical and Biomolecular Engineering")
    otsuki = records["Yu Otsuki"]
    assert otsuki["metadata"]["faculty_title"] == (
        "Assistant Professor, Department of Civil & Environmental Engineering")
    assert otsuki["keywords"][0] == "Construction robotics"


def test_research_is_read_with_the_label_colon_outside_the_bold(run):
    records, _ = run
    assert records["Sunny Jiang"]["keywords"][0] == "Water pollution microbiology"


def test_a_mailto_that_links_another_address_gives_the_one_the_card_shows(run):
    """Daniel Mumm's card links egratton@ under the text mumm@, and Yu Otsuki's
    links ndphu@ under yu.otsuki@ (person16/person17 and person12/person13 here)."""
    records, _ = run
    assert records["Daniel Mumm"]["contact_email"] == "person17@uci.edu"
    assert records["Yu Otsuki"]["contact_email"] == "person13@uci.edu"


def test_materials_drops_its_emeriti_visitors_and_lecturers(run):
    records, _ = run
    assert _unit(records, "MSE") == {"Lorenzo Valdevit", "Diran Apelian",
                                     "Daniel Mumm", "Xiaoqing Pan"}
    assert "Distinguished Professor" in records["Xiaoqing Pan"]["metadata"]["faculty_title"]


def test_mathematics_walks_the_core_faculty_archive_past_teaching_ranks(run):
    records, _ = run
    assert _unit(records, "MATH") == {"Jun Allard", "Michael Cranston", "German Enciso",
                                      "Isaac Goldbring", "Zhiqin Lu"}
    assert records["Zhiqin Lu"]["metadata"]["faculty_title"] == "Department Chair & Professor"
    assert records["Isaac Goldbring"]["url"] == "https://math.uci.edu/person/goldbring-isaac/"


def test_every_unit_accounts_for_every_card(run):
    _, ledger = run
    counts = {u: {k: e["coverage"][k] for k in (
        "raw_roster_rows", "parsed_faculty_rows", "classified_nonfaculty_rows", "unparsed_rows")}
        for u, e in ledger.items()}
    assert counts == {
        "eecs": {"raw_roster_rows": 4, "parsed_faculty_rows": 2,
                 "classified_nonfaculty_rows": 2, "unparsed_rows": 0},
        "cbe": {"raw_roster_rows": 4, "parsed_faculty_rows": 3,
                "classified_nonfaculty_rows": 1, "unparsed_rows": 0},
        "cee": {"raw_roster_rows": 4, "parsed_faculty_rows": 3,
                "classified_nonfaculty_rows": 1, "unparsed_rows": 0},
        "mse": {"raw_roster_rows": 7, "parsed_faculty_rows": 4,
                "classified_nonfaculty_rows": 3, "unparsed_rows": 0},
        "math": {"raw_roster_rows": 7, "parsed_faculty_rows": 5,
                 "classified_nonfaculty_rows": 2, "unparsed_rows": 0},
    }


def test_the_moved_rows_keep_their_corpus_ids(run):
    """Ids hash the department and the name, so a moved row is updated in place.
    Where the new page writes a stored name another way, ``id_names`` maps it
    back, and the row takes the name the page writes now."""
    records, _ = run
    # Her row left the corpus on 2026-10-17, when CEE read nothing and the
    # Public Health row on her address absorbed it; this was its id until then.
    assert records["Sunny Jiang"]["id"] == "faculty-uci-cee-f207b79c"
    assert {n: r["id"] for n, r in records.items()
            if n != "Sunny Jiang" and r["id"] not in STORED} == {}
    renamed = {n: STORED[r["id"]] for n, r in records.items()
               if r["id"] in STORED and STORED[r["id"]] != n}
    assert renamed == {
        "Amir Aghakouchak": "Amir Aghakouchak, Ph.D., P.E.",
        "Michael Cranston": "Michael C. Cranston",
        "German Enciso": "German A. Enciso Ruiz",
        "Isaac Goldbring": "Isaac M. Goldbring",
    }


def test_rows_stored_under_an_older_spelling_keep_their_ids():
    """Each page wrote these names on 2026-10-17. The fresh row each minted was
    folded into the stored one, which kept its old name and a last sighting
    from July."""
    depts = {d["short"]: d for d in uci_faculty.SCHOOL["departments"]}
    seen = {}
    for short, name in (("ANTHRO", "António Tomás"), ("SOC", "Rocío Rosales"),
                        ("PHYS", "Pedro Ochoa-Ricoux")):
        rec = faculty_graph._normalize(uci_faculty.SCHOOL, depts[short],
                                       faculty_graph.faculty(name, title="Professor"))
        seen[name] = (STORED.get(rec["id"]), rec["pi_name"])
    assert seen == {
        "António Tomás": ("Ant&oacute;nio Tom&aacute;s", "António Tomás"),
        "Rocío Rosales": ("Roc&iacute;o Rosales", "Rocío Rosales"),
        "Pedro Ochoa-Ricoux": ("Juan Pedro Ochoa-Ricoux", "Pedro Ochoa-Ricoux"),
    }
