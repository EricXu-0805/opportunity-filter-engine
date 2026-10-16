"""Closed campus programs through renames and moves: one scenario matrix for
the campus_graph and ucb_campus merges.

The rule (M93, M98): a program whose last read page said applications are
closed stays closed and inactive until a run that actually reads its page
says otherwise, whichever row or key carries it.

Each scenario commits a corpus from a deep run, then plays scheduled days the
way refresh-data.yml does: assemble the work file from the committed shards,
refresh the half of the config that the day publishes (the school's own
shard on its day, national.json on Sunday), and split back that day's shard
only. After every day it checks the rule against the pages the scenario's
runs read, and the rows of the scenario's programs against the trace written
under the day.

- 43 move/rename scenarios: renamed, and moved either way with either file's
  day first, with the same or a new URL and the page open or closed before
  the edit, every run reading the page; renamed back (campus_graph) and moved
  back (ucb_campus) with the page open, coming back on a quick run; and, for
  campus_graph, renamed on a page its config shares with another program.
- 30 landing-day scenarios: a closed program renamed or moved with its URL,
  and the run on which its record could land reads nothing (a quick run, or a
  page that fails to load) or reads the page saying open, closed or nothing.
- 7 scenarios on the three paths M98 closes: a page shared with another
  program, a program renamed back, and one moved back.
- 3 scenarios where the closed row that holds the program is in the other
  file under a key that file no longer lists, before that file's day retires
  it: renamed and moved back in one edit, and renamed and moved on a shared
  page.
- 11 scenarios a closed row in the other file must not hold back: a program
  on a page it shares with a program still listed in the other file, new or
  back to its own retired row, arriving in the school's file or in
  national.json; a new program on the page of one retired in the other file
  and listed there again; and a program renamed and moved back whose landing
  run reads its page. A title alone never ties a record to a row in the
  other file: title matches are scoped to the record's source, which names
  its file.
- 4 scenarios on a merge given no list of the other file's keys, as a direct
  caller may: every closed row in the other file counts, so a new program
  beside a closed program still listed there, or retired there and listed
  there again, waits for a run that reads its page.

Main at c99142c2 passes the 73, 10 of the 11 and 1 of the 4 as written. The
other 14 fail there on the day that reads nothing: 10 listed the program,
ucb_campus held the new program beside the one listed again in the other
file, as it held any new record sharing the URL or title of a row retired
closed, in either file, and campus_graph listed the new program in the
other 3 of the 4, as its wait for a read skipped every record on a shared
page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from bs4 import BeautifulSoup

from scripts.shard_corpus import assemble, load_shards, split
from src.collectors import campus_graph as cg
from src.collectors import ucb_campus
from src.collectors import ucb_sources as reg

_TEXT = {"open": "Applications are now open!", "closed": "Applications are now closed.", "nothing": "Program page"}
# The pages the scenarios' programs live on. Every other page loads and states
# no status.
_PROGRAM_PAGES = frozenset({"summer", "summer-new", "hub"})
_PROGRAM_OF = {"old_key": "summer", "new_key": "summer", "moving": "summer", "first_key": "summer",
               "second_key": "summer", "alpha": "alpha", "alpha2": "alpha", "beta": "beta", "gamma": "gamma"}
_TITLE_OF = {"summer": "Summer Fellowship", "alpha": "Alpha Fellowship", "beta": "Beta Grant", "gamma": "Gamma Award"}
# national.json always holds other sources' rows, so Sunday always has a
# shard to write.
_NATIONAL_ROW = {"id": "nsf-reu-0001", "source": "nsf_reu", "source_type": "reu", "school": None,
                 "title": "Example REU Site", "url": "https://example.org/reu/", "metadata": {"is_active": True}}


@dataclass(frozen=True)
class Config:
    """The (key, page) of each program in the school's own bucket and in its
    open bucket, besides a kept program that holds the school's shard."""

    campus: tuple[tuple[str, str], ...] = ()
    open: tuple[tuple[str, str], ...] = ()

    def collected(self, national):
        return [*(self.campus if national is not True else ()), *(self.open if national is not False else ())]


@dataclass(frozen=True)
class Day:
    """One run: ``national`` None is the commit (both halves, one call),
    False the school's day, True Sunday. ``run`` is deep, quick, or fails
    (deep, with every program page failing to load). ``page`` is what the
    program pages say when they load, and ``expect`` the rows of the
    scenario's programs afterwards, as "key@file status state"."""

    config: Config
    national: bool | None
    run: str
    page: str
    expect: str


def _source(build, base, name, emit, entries):
    return {"source_name": name, "source_type": "program", "emit": emit, "crawl": "static", "crawl_depth": 1,
            "update": "weekly", "seeds": [f"{base}/{name}/", *(f"{base}/{page}/" for _key, page in entries)],
            "programs": [build(key, _TITLE_OF.get(_PROGRAM_OF.get(key), "Kept Fellowship"), f"{base}/{page}/",
                               "Curated") for key, page in entries]}


def _loaded(url, word):
    soup = BeautifulSoup(f"<body><p>{_TEXT[word]}</p></body>", "html.parser")
    soup._ofe_fetch_metadata = {"requested_url": url, "final_url": url, "checked_at": datetime.now(UTC).isoformat()}
    return soup


def _serve(page):
    """The fetch for a day: a program page says ``page``, or fails to load
    when ``page`` is None."""
    def fetch(url, **_):
        if url.rstrip("/").rsplit("/", 1)[-1] not in _PROGRAM_PAGES:
            return _loaded(url, "nothing")
        return None if page is None else _loaded(url, page)
    return fetch


def _other_file(evidence):
    """The other file's keys as a merge argument; none from main's fetch,
    whose merge takes none, so the module runs on main's code too."""
    keys = evidence.get("other_file_program_keys")
    return {} if keys is None else {"other_file_program_keys": set(keys)}


class _CampusGraph:
    home = "example"

    def __init__(self, monkeypatch, processed):
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(cg, "PROCESSED_FILE", processed)

    def serve(self, page):
        self.monkeypatch.setattr(cg, "_fetch", _serve(page))

    def refresh(self, config, national, deep):
        base = "https://example.edu"
        school = {
            "school_slug": "example", "organization": "Example University", "location": "Example, EX",
            "emit": {"campus": ("example_programs", "example", "campus"), "open": ("example_external", None, "open")},
            "sources": [_source(cg.program, base, "example_programs", "campus", (("kept", "kept"), *config.campus)),
                        _source(cg.program, base, "example_external", "open", config.open)],
        }
        records, evidence = cg.fetch_and_normalize_with_evidence(school, deep=deep, national=national)
        listed, other = evidence["listed_program_keys"], _other_file(evidence)
        cg.merge_into_processed(
            records,
            complete_recursive_sources=set(evidence["complete_recursive_sources"]),
            condition_capture_updates=evidence["condition_capture_updates"],
            listed_program_keys=None if listed is None else set(listed),
            national=national,
            school_slug="example",
            **other,
        )


class _Ucb:
    home = "ucb"

    def __init__(self, monkeypatch, processed):
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(ucb_campus, "PROCESSED_FILE", processed)

    def serve(self, page):
        fetch = _serve(page)
        self.monkeypatch.setattr(ucb_campus, "_fetch", lambda url: fetch(url))

    def refresh(self, config, national, deep):
        base = "https://example.berkeley.edu"
        self.monkeypatch.setattr(reg, "UCB_SOURCES", [
            _source(reg._prog, base, "ucb_fixture_programs", reg.EMIT_CAMPUS, (("kept", "kept"), *config.campus)),
            _source(reg._prog, base, "ucb_fixture_external", reg.EMIT_OPEN, config.open),
        ])
        records, evidence = ucb_campus.fetch_and_normalize_with_evidence(deep=deep, national=national)
        listed, other = evidence["listed_program_keys"], _other_file(evidence)
        ucb_campus.merge_into_processed(
            records,
            complete_recursive_sources=set(evidence["complete_recursive_sources"]),
            listed_program_keys=None if listed is None else set(listed),
            national=national,
            **other,
        )


_ENGINES = {"cg": _CampusGraph, "ucb": _Ucb}


def _rows(shards):
    """The committed rows of the scenario's programs: (key, file, status,
    state, page), where state is listed, retired (no_longer_listed) or
    hidden (inactive because its page said closed)."""
    rows = []
    for row in load_shards(shards):
        metadata = row["metadata"]
        if metadata.get("collector_key") not in _PROGRAM_OF:
            continue
        state = ("listed" if metadata["is_active"] else
                 "retired" if metadata.get("deactivation_reason") == cg.NO_LONGER_LISTED else "hidden")
        rows.append((metadata["collector_key"], "home" if row["school"] else "national", metadata["status"],
                     state, row["url"].rstrip("/").rsplit("/", 1)[-1]))
    return rows


def _assert_the_rule(rows, config, readings, label):
    """No program is listed while the last run that read its page found it
    closed, under whichever key or file, and none is listed twice."""
    pages = {_PROGRAM_OF[key]: page for key, page in config.collected(None)}
    for program in {_PROGRAM_OF[key] for key, *_ in rows}:
        listed = [row for row in rows if _PROGRAM_OF[row[0]] == program and row[3] == "listed"]
        assert len(listed) <= 1, f"{label}: {program} listed twice: {listed}"
        if readings.get((program, pages.get(program))) == "closed":
            assert not listed, f"{label}: {program} listed though its page last read closed: {listed}"
        for key, _file, status, _state, page in listed:
            assert status != "closed" and readings.get((program, page)) != "closed", (
                f"{label}: {program} listed as {key} on a page last read closed")


def _play(monkeypatch, tmp_path, engine_name, days):
    processed, shards = tmp_path / "opportunities.json", tmp_path / "shards"
    engine = _ENGINES[engine_name](monkeypatch, processed)
    readings = {}
    for number, day in enumerate(days):
        engine.serve(None if day.run == "fails" else day.page)
        if day.national is None:
            processed.write_text(json.dumps([_NATIONAL_ROW]), encoding="utf-8")
            engine.refresh(day.config, None, deep=True)
            split(processed, shards)
        else:
            assemble(processed, shards, force=True, allow_empty=True)
            engine.refresh(day.config, day.national, deep=day.run != "quick")
            split(processed, shards, only_shards={"national" if day.national else engine.home})
        if day.run == "deep":
            for key, page in day.config.collected(day.national):
                readings[(_PROGRAM_OF[key], page)] = day.page
        rows = _rows(shards)
        label = f"day {number} ({day.run}, page {day.page})"
        _assert_the_rule(rows, day.config, readings, label)
        assert sorted(f"{key}@{file} {status} {state}" for key, file, status, state, _page in rows) == sorted(
            filter(None, day.expect.split(", "))), label


def _shown(word):
    return "hidden" if word == "closed" else "listed"


def _day_of(file):
    """The national flag of the day that publishes ``file``."""
    return file == "national"


# --- 43 move/rename scenarios ------------------------------------------------

def _renamed(engine, url, before):
    old = Config(campus=(("old_key", "summer"),))
    new = Config(campus=(("new_key", "summer" if url == "same_url" else "summer-new"),))
    days = [Day(old, None, "deep", before, f"old_key@home {before} {_shown(before)}"),
            Day(new, False, "deep", before, f"old_key@home {before} retired, new_key@home {before} {_shown(before)}")]
    if before == "closed":
        days.append(Day(new, False, "deep", "open", "old_key@home closed retired, new_key@home open listed"))
    return pytest.param(engine, days, id=f"{engine}-renamed-{url}-page_{before}")


def _moved(engine, direction, url, before, order):
    old, new = ("home", "national") if direction == "into_open" else ("national", "home")
    page = "summer" if url == "same_url" else "summer-new"

    def config(file, entry):
        return Config(campus=(entry,)) if file == "home" else Config(open=(entry,))

    before_config, after = config(old, ("moving", "summer")), config(new, ("moving", page))
    landed = f"moving@{old} {before} retired, moving@{new} {before} {_shown(before)}"
    days = [Day(before_config, None, "deep", before, f"moving@{old} {before} {_shown(before)}")]
    if order == "old_file_day_first":
        days += [Day(after, _day_of(old), "deep", before, f"moving@{old} {before} retired"),
                 Day(after, _day_of(new), "deep", before, landed)]
    else:
        # The moved record is held while the old row is listed, dropped as
        # the closed old row's near-duplicate while it shares that row's
        # page, and lands at once on a new page.
        if before == "open":
            first, retired = f"moving@{old} open listed", f"moving@{old} open retired"
        elif url == "same_url":
            first, retired = f"moving@{old} closed hidden", f"moving@{old} closed retired"
        else:
            first = f"moving@{old} closed hidden, moving@{new} closed hidden"
            retired = f"moving@{old} closed retired, moving@{new} closed hidden"
        days += [Day(after, _day_of(new), "deep", before, first),
                 Day(after, _day_of(old), "deep", before, retired),
                 Day(after, _day_of(new), "deep", before, landed)]
    if before == "closed":
        days.append(Day(after, _day_of(new), "deep", "open", f"moving@{old} closed retired, moving@{new} open listed"))
    return pytest.param(engine, days, id=f"{engine}-moved_{direction}-{url}-page_{before}-{order}")


def _renamed_back():
    first, second = Config(campus=(("first_key", "summer"),)), Config(campus=(("second_key", "summer"),))
    return pytest.param("cg", [
        Day(first, None, "deep", "open", "first_key@home open listed"),
        Day(second, False, "deep", "open", "first_key@home open retired, second_key@home open listed"),
        Day(first, False, "quick", "open", "first_key@home open listed, second_key@home open retired"),
    ], id="cg-renamed_back-page_open-quick_run")


def _moved_back():
    """Held while its row in the other file is listed, as any moved record."""
    home, away = Config(campus=(("moving", "summer"),)), Config(open=(("moving", "summer"),))
    return pytest.param("ucb", [
        Day(home, None, "deep", "open", "moving@home open listed"),
        Day(away, False, "deep", "open", "moving@home open retired"),
        Day(away, True, "deep", "open", "moving@home open retired, moving@national open listed"),
        Day(home, False, "quick", "open", "moving@home open retired, moving@national open listed"),
        Day(home, True, "quick", "open", "moving@home open retired, moving@national open retired"),
        Day(home, False, "quick", "open", "moving@home open listed, moving@national open retired"),
    ], id="ucb-moved_back-page_open-quick_run")


def _renamed_on_a_shared_page():
    before = Config(campus=(("alpha", "hub"), ("beta", "hub")))
    after = Config(campus=(("alpha2", "hub"), ("beta", "hub")))
    return pytest.param("cg", [
        Day(before, None, "deep", "closed", "alpha@home closed hidden, beta@home closed hidden"),
        Day(after, False, "deep", "closed", "alpha@home closed retired, alpha2@home closed hidden, beta@home closed hidden"),
        Day(after, False, "deep", "open", "alpha@home closed retired, alpha2@home open listed, beta@home open listed"),
    ], id="cg-renamed_on_a_shared_page-page_closed")


MOVES_AND_RENAMES = [
    *(_renamed(engine, url, before) for engine in _ENGINES for url in ("same_url", "new_url")
      for before in ("open", "closed")),
    *(_moved(engine, direction, url, before, order) for engine in _ENGINES
      for direction in ("into_open", "out_of_open") for url in ("same_url", "new_url")
      for before in ("open", "closed") for order in ("old_file_day_first", "new_file_day_first")),
    _renamed_back(),
    _moved_back(),
    _renamed_on_a_shared_page(),
]


@pytest.mark.parametrize(("engine", "days"), MOVES_AND_RENAMES)
def test_a_moved_or_renamed_program_follows_its_page(monkeypatch, tmp_path, engine, days):
    _play(monkeypatch, tmp_path, engine, days)


# --- 30 landing-day scenarios ------------------------------------------------

_LANDINGS = {
    "quick_run": ("quick", "closed", ""),
    "page_fails": ("fails", "closed", ""),
    "reads_open": ("deep", "open", "open listed"),
    "reads_closed": ("deep", "closed", "closed hidden"),
    "reads_nothing": ("deep", "nothing", "unknown listed"),
}


def _landing(engine, edit, landing):
    run, page, lands = _LANDINGS[landing]
    if edit == "renamed":
        before, after = Config(campus=(("old_key", "summer"),)), Config(campus=(("new_key", "summer"),))
        old, new, day = "old_key@home", "new_key@home", False
        days = [Day(before, None, "deep", "closed", f"{old} closed hidden")]
    else:
        home, national = Config(campus=(("moving", "summer"),)), Config(open=(("moving", "summer"),))
        before, after = (home, national) if edit == "moved_into_open" else (national, home)
        old_file, new_file = ("home", "national") if edit == "moved_into_open" else ("national", "home")
        old, new, day = f"moving@{old_file}", f"moving@{new_file}", _day_of(new_file)
        days = [Day(before, None, "deep", "closed", f"{old} closed hidden"),
                Day(after, _day_of(old_file), "deep", "closed", f"{old} closed retired")]
    days += [Day(after, day, run, page, f"{old} closed retired" + (f", {new} {lands}" if lands else "")),
             Day(after, day, "deep", "open", f"{old} closed retired, {new} open listed")]
    return pytest.param(engine, days, id=f"{engine}-{edit}-{landing}")


LANDING_DAYS = [_landing(engine, edit, landing) for engine in _ENGINES
                for edit in ("renamed", "moved_into_open", "moved_out_of_open") for landing in _LANDINGS]


@pytest.mark.parametrize(("engine", "days"), LANDING_DAYS)
def test_the_day_a_closed_program_could_land_lists_it_only_from_a_read(monkeypatch, tmp_path, engine, days):
    _play(monkeypatch, tmp_path, engine, days)


# --- 7 scenarios on the paths M98 closes ---------------------------------------

def _shared_page_moved_into_open(order):
    """A record on a page its config shares with another program skips the
    near-duplicate filter, so the closed row in the old file held nothing
    back, and the moved record landed listed on a run that read nothing."""
    before = Config(campus=(("alpha", "hub"), ("beta", "hub")))
    after = Config(campus=(("beta", "hub"),), open=(("alpha", "hub"),))
    closed = "alpha@home closed hidden, beta@home closed hidden"
    retired = "alpha@home closed retired, beta@home closed hidden"
    days = [Day(before, None, "deep", "closed", closed)]
    if order == "new_file_day_first":
        days += [Day(after, True, "quick", "closed", closed), Day(after, False, "deep", "closed", retired)]
    else:
        days += [Day(after, False, "deep", "closed", retired), Day(after, True, "fails", "closed", retired)]
    days.append(Day(after, True, "deep", "open", f"{retired}, alpha@national open listed"))
    run = "quick_run" if order == "new_file_day_first" else "page_fails"
    return pytest.param("cg", days, id=f"cg-shared_page-moved_into_open-{order}-{run}")


def _shared_page_renamed_back():
    first = Config(campus=(("alpha", "hub"), ("beta", "hub")))
    second = Config(campus=(("alpha2", "hub"), ("beta", "hub")))
    return pytest.param("cg", [
        Day(first, None, "deep", "open", "alpha@home open listed, beta@home open listed"),
        Day(second, False, "deep", "open", "alpha@home open retired, alpha2@home open listed, beta@home open listed"),
        Day(second, False, "deep", "closed", "alpha@home open retired, alpha2@home closed hidden, beta@home closed hidden"),
        Day(first, False, "quick", "closed", "alpha@home open retired, alpha2@home closed retired, beta@home closed hidden"),
        Day(first, False, "deep", "open", "alpha@home open listed, alpha2@home closed retired, beta@home open listed"),
    ], id="cg-shared_page-renamed_back-quick_run")


def _shared_page_moved_back():
    """The other program on the page keeps its own last reading: Sunday read
    the page for the moved program only."""
    home = Config(campus=(("alpha", "hub"), ("beta", "hub")))
    away = Config(campus=(("beta", "hub"),), open=(("alpha", "hub"),))
    return pytest.param("cg", [
        Day(home, None, "deep", "open", "alpha@home open listed, beta@home open listed"),
        Day(away, False, "deep", "open", "alpha@home open retired, beta@home open listed"),
        Day(away, True, "deep", "open", "alpha@home open retired, alpha@national open listed, beta@home open listed"),
        Day(away, True, "deep", "closed", "alpha@home open retired, alpha@national closed hidden, beta@home open listed"),
        Day(home, False, "quick", "closed", "alpha@home open retired, alpha@national closed hidden, beta@home open listed"),
        Day(home, True, "deep", "closed", "alpha@home open retired, alpha@national closed retired, beta@home open listed"),
        Day(home, False, "deep", "open", "alpha@home open listed, alpha@national closed retired, beta@home open listed"),
    ], id="cg-shared_page-moved_back-home_file_day_first-quick_run")


def _renamed_back_on_sunday(engine, run):
    first, second = Config(open=(("first_key", "summer"),)), Config(open=(("second_key", "summer"),))
    return pytest.param(engine, [
        Day(first, None, "deep", "open", "first_key@national open listed"),
        Day(second, True, "deep", "open", "first_key@national open retired, second_key@national open listed"),
        Day(second, True, "deep", "closed", "first_key@national open retired, second_key@national closed hidden"),
        Day(first, True, run, "closed", "first_key@national open retired, second_key@national closed retired"),
        Day(first, True, "deep", "open", "first_key@national open listed, second_key@national closed retired"),
    ], id=f"{engine}-renamed_back_in_national_json-{'page_fails' if run == 'fails' else 'quick_run'}")


def _renamed_and_moved_back():
    """Renamed and moved in one edit, then back: the record is its first
    key's retired row, and the closed row that holds it carries the other
    key in the other file, retired there first."""
    home, away = Config(campus=(("first_key", "summer"),)), Config(open=(("second_key", "summer"),))
    return pytest.param("ucb", [
        Day(home, None, "deep", "open", "first_key@home open listed"),
        Day(away, False, "deep", "open", "first_key@home open retired"),
        Day(away, True, "deep", "open", "first_key@home open retired, second_key@national open listed"),
        Day(away, True, "deep", "closed", "first_key@home open retired, second_key@national closed hidden"),
        Day(home, True, "deep", "closed", "first_key@home open retired, second_key@national closed retired"),
        Day(home, False, "quick", "closed", "first_key@home open retired, second_key@national closed retired"),
        Day(home, False, "deep", "open", "first_key@home open listed, second_key@national closed retired"),
    ], id="ucb-renamed_and_moved_back-away_file_day_first-quick_run")


M98_PATHS = [
    _shared_page_moved_into_open("new_file_day_first"),
    _shared_page_moved_into_open("old_file_day_first"),
    _shared_page_renamed_back(),
    _shared_page_moved_back(),
    _renamed_back_on_sunday("cg", "fails"),
    _renamed_back_on_sunday("ucb", "quick"),
    _renamed_and_moved_back(),
]


@pytest.mark.parametrize(("engine", "days"), M98_PATHS)
def test_a_closed_program_on_m98s_paths_waits_for_a_run_that_reads_its_page(monkeypatch, tmp_path, engine, days):
    _play(monkeypatch, tmp_path, engine, days)


# --- 3 scenarios with the closed row in the other file under an unlisted key --

def _renamed_and_moved_back_home_file_day_first(engine, run):
    """The closed row in the other file, not yet retired there, carries
    another key, so it held nothing back."""
    home, away = Config(campus=(("first_key", "summer"),)), Config(open=(("second_key", "summer"),))
    return pytest.param(engine, [
        Day(home, None, "deep", "open", "first_key@home open listed"),
        Day(away, False, "deep", "open", "first_key@home open retired"),
        Day(away, True, "deep", "open", "first_key@home open retired, second_key@national open listed"),
        Day(away, True, "deep", "closed", "first_key@home open retired, second_key@national closed hidden"),
        Day(home, False, run, "closed", "first_key@home open retired, second_key@national closed hidden"),
        Day(home, True, "deep", "closed", "first_key@home open retired, second_key@national closed retired"),
        Day(home, False, "deep", "open", "first_key@home open listed, second_key@national closed retired"),
    ], id=f"{engine}-renamed_and_moved_back-home_file_day_first-{'page_fails' if run == 'fails' else 'quick_run'}")


def _shared_page_renamed_and_moved_into_open():
    before = Config(campus=(("alpha", "hub"), ("beta", "hub")))
    after = Config(campus=(("beta", "hub"),), open=(("alpha2", "hub"),))
    return pytest.param("cg", [
        Day(before, None, "deep", "closed", "alpha@home closed hidden, beta@home closed hidden"),
        Day(after, True, "quick", "closed", "alpha@home closed hidden, beta@home closed hidden"),
        Day(after, False, "deep", "closed", "alpha@home closed retired, beta@home closed hidden"),
        Day(after, True, "deep", "open", "alpha@home closed retired, alpha2@national open listed, beta@home closed hidden"),
    ], id="cg-shared_page-renamed_and_moved_into_open-new_file_day_first-quick_run")


OTHER_FILE_UNDER_ANOTHER_KEY = [
    _renamed_and_moved_back_home_file_day_first("cg", "quick"),
    _renamed_and_moved_back_home_file_day_first("ucb", "fails"),
    _shared_page_renamed_and_moved_into_open(),
]


@pytest.mark.parametrize(("engine", "days"), OTHER_FILE_UNDER_ANOTHER_KEY)
def test_a_closed_row_in_the_other_file_holds_its_program_under_a_key_that_file_dropped(
        monkeypatch, tmp_path, engine, days):
    _play(monkeypatch, tmp_path, engine, days)


# --- 11 scenarios a closed row in the other file must not hold back -----------

def _new_on_a_page_shared_across_files():
    """A new program on a page its config shares with a program in the other
    file, whose closure is that program's own reading."""
    before, after = Config(open=(("alpha", "hub"),)), Config(campus=(("gamma", "hub"),), open=(("alpha", "hub"),))
    return pytest.param("cg", [
        Day(before, None, "deep", "closed", "alpha@national closed hidden"),
        Day(after, False, "quick", "closed", "alpha@national closed hidden, gamma@home unknown listed"),
    ], id="cg-new_program_on_a_page_shared_with_a_closed_program_in_the_other_file-quick_run")


def _back_on_a_page_shared_across_files(engine, run):
    """ucb_campus keeps one of two programs on a page in one run, so the
    other file's program arrives on its own day."""
    gamma, alpha = Config(campus=(("gamma", "hub"),)), Config(open=(("alpha", "hub"),))
    both = Config(campus=(("gamma", "hub"),), open=(("alpha", "hub"),))
    return pytest.param(engine, [
        Day(gamma, None, "deep", "open", "gamma@home open listed"),
        Day(alpha, False, "deep", "open", "gamma@home open retired"),
        Day(alpha, True, "deep", "closed", "alpha@national closed hidden, gamma@home open retired"),
        Day(both, False, run, "closed", "alpha@national closed hidden, gamma@home open listed"),
    ], id=f"{engine}-program_back_on_a_page_shared_with_a_closed_program_in_the_other_file-"
          f"{'page_fails' if run == 'fails' else 'quick_run'}")


def _new_in_national_json_on_a_page_shared_with_a_closed_program_in_the_school_file():
    """The first scenario mirrored: the new program arrives on Sunday."""
    before, after = Config(campus=(("alpha", "hub"),)), Config(campus=(("alpha", "hub"),), open=(("gamma", "hub"),))
    return pytest.param("cg", [
        Day(before, None, "deep", "closed", "alpha@home closed hidden"),
        Day(after, True, "quick", "closed", "alpha@home closed hidden, gamma@national unknown listed"),
    ], id="cg-new_program_in_national_json_on_a_page_shared_with_a_closed_program_in_the_school_file-quick_run")


def _back_in_national_json_on_a_page_shared_with_a_closed_program_in_the_school_file():
    """The second scenario mirrored, for ucb_campus."""
    gamma, alpha = Config(open=(("gamma", "hub"),)), Config(campus=(("alpha", "hub"),))
    both = Config(campus=(("alpha", "hub"),), open=(("gamma", "hub"),))
    return pytest.param("ucb", [
        Day(gamma, None, "deep", "open", "gamma@national open listed"),
        Day(alpha, True, "deep", "open", "gamma@national open retired"),
        Day(alpha, False, "deep", "closed", "alpha@home closed hidden, gamma@national open retired"),
        Day(both, True, "fails", "closed", "alpha@home closed hidden, gamma@national open listed"),
    ], id="ucb-program_back_in_national_json_on_a_page_shared_with_a_closed_program_in_the_school_file-page_fails")


def _new_on_a_page_shared_with_a_program_listed_again_in_the_other_file(engine, run):
    """A closed program dropped from the other file, its row retired there,
    then listed there again beside a new program on its page: that file
    lists the row's key, so the row holds nothing back."""
    alpha, both = Config(open=(("alpha", "hub"),)), Config(campus=(("gamma", "hub"),), open=(("alpha", "hub"),))
    return pytest.param(engine, [
        Day(alpha, None, "deep", "closed", "alpha@national closed hidden"),
        Day(Config(), True, "deep", "closed", "alpha@national closed retired"),
        Day(both, False, run, "closed", "alpha@national closed retired, gamma@home unknown listed"),
    ], id=f"{engine}-new_program_on_a_page_shared_with_a_closed_program_listed_again_in_the_other_file-"
          f"{'page_fails' if run == 'fails' else 'quick_run'}")


def _renamed_and_moved_back_read_on_landing(engine, word):
    """The run that lands the program reads its page, which says what holds."""
    home, away = Config(campus=(("first_key", "summer"),)), Config(open=(("second_key", "summer"),))
    return pytest.param(engine, [
        Day(home, None, "deep", "open", "first_key@home open listed"),
        Day(away, False, "deep", "open", "first_key@home open retired"),
        Day(away, True, "deep", "closed", "first_key@home open retired, second_key@national closed hidden"),
        Day(home, False, "deep", word, f"first_key@home {word} {_shown(word)}, second_key@national closed hidden"),
    ], id=f"{engine}-renamed_and_moved_back-home_file_day_first-reads_{word}")


NOT_HELD = [
    _new_on_a_page_shared_across_files(),
    _back_on_a_page_shared_across_files("cg", "quick"),
    _back_on_a_page_shared_across_files("ucb", "fails"),
    _new_in_national_json_on_a_page_shared_with_a_closed_program_in_the_school_file(),
    _back_in_national_json_on_a_page_shared_with_a_closed_program_in_the_school_file(),
    _new_on_a_page_shared_with_a_program_listed_again_in_the_other_file("cg", "quick"),
    _new_on_a_page_shared_with_a_program_listed_again_in_the_other_file("ucb", "fails"),
    *(_renamed_and_moved_back_read_on_landing(engine, word) for engine in _ENGINES for word in ("open", "closed")),
]


@pytest.mark.parametrize(("engine", "days"), NOT_HELD)
def test_a_closed_row_in_the_other_file_holds_back_no_other_program_and_no_read_record(
        monkeypatch, tmp_path, engine, days):
    _play(monkeypatch, tmp_path, engine, days)


# --- 4 scenarios on a merge given no list of the other file's keys ------------

def _beside_a_closed_program_still_listed_in_the_other_file(run):
    """The first NOT_HELD scenario, which a merge told that file's keys
    lists on the day that reads nothing."""
    before, after = Config(open=(("alpha", "hub"),)), Config(campus=(("gamma", "hub"),), open=(("alpha", "hub"),))
    return pytest.param("cg", [
        Day(before, None, "deep", "closed", "alpha@national closed hidden"),
        Day(after, False, run, "closed", "alpha@national closed hidden"),
        Day(after, False, "deep", "open", "alpha@national closed hidden, gamma@home open listed"),
    ], id=f"cg-new_program_beside_a_closed_program_still_listed_in_the_other_file-"
          f"{'page_fails' if run == 'fails' else 'quick_run'}")


def _beside_a_closed_program_listed_again_in_the_other_file(engine, run):
    """The NOT_HELD scenario with the closed program retired in the other
    file and listed there again."""
    alpha, both = Config(open=(("alpha", "hub"),)), Config(campus=(("gamma", "hub"),), open=(("alpha", "hub"),))
    return pytest.param(engine, [
        Day(alpha, None, "deep", "closed", "alpha@national closed hidden"),
        Day(Config(), True, "deep", "closed", "alpha@national closed retired"),
        Day(both, False, run, "closed", "alpha@national closed retired"),
        Day(both, False, "deep", "open", "alpha@national closed retired, gamma@home open listed"),
    ], id=f"{engine}-new_program_beside_a_closed_program_listed_again_in_the_other_file-"
          f"{'page_fails' if run == 'fails' else 'quick_run'}")


WITHOUT_THE_OTHER_FILES_KEYS = [
    _beside_a_closed_program_still_listed_in_the_other_file("quick"),
    _beside_a_closed_program_still_listed_in_the_other_file("fails"),
    _beside_a_closed_program_listed_again_in_the_other_file("cg", "quick"),
    _beside_a_closed_program_listed_again_in_the_other_file("ucb", "fails"),
]


@pytest.mark.parametrize(("engine", "days"), WITHOUT_THE_OTHER_FILES_KEYS)
def test_a_merge_not_given_the_other_files_keys_counts_every_closed_row_there(monkeypatch, tmp_path, engine, days):
    monkeypatch.setitem(globals(), "_other_file", lambda evidence: {})
    _play(monkeypatch, tmp_path, engine, days)


def test_the_groups_hold_43_30_7_3_11_and_4_scenarios():
    assert (len(MOVES_AND_RENAMES), len(LANDING_DAYS), len(M98_PATHS), len(OTHER_FILE_UNDER_ANOTHER_KEY),
            len(NOT_HELD), len(WITHOUT_THE_OTHER_FILES_KEYS)) == (43, 30, 7, 3, 11, 4)
