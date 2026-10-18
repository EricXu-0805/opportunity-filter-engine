"""Offline replay of the UT Dallas faculty selectors.

On the 2026-10-17 refresh twenty of the thirty UT Dallas departments returned no
rows. The refresh installed soupsieve 3.0.3, which rejects a multi-step path
inside ``:has()``, and two of our selectors had one: the ECE card
(``:has(> ul.wp-block-list a[…])``) and the not-yet-arrived gate on every
Profiles-plugin card (``:not(:has(.profile-name a…))``). Each rejected selector
raised inside the per-unit guard, so the unit logged a warning and kept nothing.

The fixtures are trimmed copies of the live pages fetched 2026-10-18. The ECE
pages are server-rendered, so their rows are the real markup (addresses
replaced by placeholders). The Profiles pages (physics, math, bbs) ship an empty
card template that the plugin fills from the Profiles API in the browser; those
fixtures keep the real page shell, headings and template, and add filled cards
cloned from that template for names and ranks already in the corpus, plus
placeholder people for a hire who has not started and for the emeritus and
in-memoriam grids.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import utdallas_faculty
from tests.test_css_selector_strict import strict_error

FIXTURES = Path(__file__).parent / "fixtures" / "utdallas"
PAGES = {
    "https://ece.utdallas.edu/people/tenure-system-faculty/": "ece_tenure_system.html",
    "https://ece.utdallas.edu/instructional-faculty/": "ece_instructional.html",
    "https://physics.utdallas.edu/faculty/": "physics.html",
    "https://math.utdallas.edu/people/faculty/": "math.html",
    "https://bbs.utdallas.edu/faculty/": "bbs.html",
}
DEPARTMENTS = {"ECE", "ECE2", "PHYS", "MATH", "PSY", "NSCI"}


def _soup(url: str):
    name = PAGES.get(url)
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"),
                         "html.parser") if name else None


def _render_soup(url, *args, expect_selector=None, **kwargs):
    """The render path's own readiness check: a page counts as rendered only
    when the card selector finds cards (a selector that raises is a failed
    render, as in ``faculty_graph._render_soup``)."""
    soup = _soup(url)
    try:
        return soup if soup is not None and (
            not expect_selector or soup.select(expect_selector)) else None
    except Exception:  # noqa: BLE001 — mirrors the render path's guard
        return None


@pytest.fixture
def people(monkeypatch) -> dict[str, list[dict]]:
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url, *a, **k: _soup(url))
    monkeypatch.setattr(faculty_graph, "_render_soup", _render_soup)
    monkeypatch.setattr(faculty_graph.time, "sleep", lambda _s: None)
    return {d["short"]: faculty_graph._scrape_directory(d)
            for d in utdallas_faculty.SCHOOL["departments"] if d["short"] in DEPARTMENTS}


def _names(rows: list[dict]) -> list[str]:
    return sorted(r["name"] for r in rows)


def test_the_replayed_departments_have_strictly_valid_card_selectors():
    cards = {d["short"]: d["scrape"]["selectors"]["card"]
             for d in utdallas_faculty.SCHOOL["departments"] if d["short"] in DEPARTMENTS}
    assert {short: strict_error(card) for short, card in cards.items()
            if strict_error(card)} == {}


def test_ece_reads_each_column_card_and_not_the_roster_wrapper(people):
    # The rows without a mailto: (a professor whose address is not listed yet)
    # are not cards, and neither is the wrapper column that holds every row.
    assert _names(people["ECE"]) == ["Bilal Akin", "Naofal Al-Dhahir", "Poras Balsara"]
    assert [r["email"] for r in people["ECE"]] == [
        "person1@utdallas.edu", "person2@utdallas.edu", "person3@utdallas.edu"]


def test_ece_skips_an_empty_leftover_mailto(people):
    rows = {r["name"]: r for r in people["ECE2"]}
    assert sorted(rows) == ["Amneh Akour", "Shaheen Ahmed"]
    assert rows["Shaheen Ahmed"]["email"] == "person4@utdallas.edu"


def test_physics_keeps_the_active_grids_and_drops_a_hire_not_yet_arrived(people):
    assert _names(people["PHYS"]) == [
        "Lunjin Chen", "Paul MacAlevey", "Phillip Anderson", "Yuri Gartstein"]
    assert {r["title"] for r in people["PHYS"]} == {
        "Professor", "Associate Professor", "Professor of Instruction"}


def test_math_reads_the_id_less_plugin_cards(people):
    assert _names(people["MATH"]) == ["Iris Alvarado", "Kelly Aman", "Mohammad Ahsan"]


def test_the_combined_bbs_page_splits_by_tag_class(people):
    assert _names(people["PSY"]) == ["Hervé Abdi", "Robert Ackerman"]
    assert _names(people["NSCI"]) == ["Andrew Eagle", "Gregory Dussor"]
