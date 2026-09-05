"""Offline tests for the Colgate directory selector family.

Colgate has no per-department roster: every person comes from ONE college-wide
Drupal View filtered by ``directory_units``, so a single selector set covers
the whole college — and a single selector drift takes the whole college with
it. That is exactly what happened. The View was re-themed onto the shared
``table-results-view`` component, the name link moved out of a ``class="h3"``
wrapper into ``h3.table-results-view__link``, ``.h3 a`` stopped matching, and
every row was dropped for want of a name. The collector reported
``{"fetched": 0, "status": "ok"}`` and, because a zero-emitting source was
attributed to its school, withheld the entire Colgate shard: 314 faculty
frozen at 2026-07-29.

There were no Colgate parser tests, which is why nothing caught it. These
fixtures are the live markup (verified against the real Biology unit) plus the
legacy shape, so neither template can regress the other unnoticed.
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors import faculty_graph as fg
from src.collectors.schools.colgate_faculty import _LADDER, _SELECTORS, SCHOOL


def _row(name: str, slug: str, rank: str, email: str | None) -> str:
    contact = (
        f'<td><span class="table-results-view__cell-label">Email</span>'
        f'<div><a href="mailto:{email}">{email}</a></div></td>'
        if email else '<td class="table-results-view__hidden-cell"><div></div></td>'
    )
    return (
        "<tr>"
        '<td><span class="table-results-view__cell-label">Name</span><div>'
        f'<h3 class="table-results-view__link">'
        f'<a class="cta cta--text" href="/about/directory/{slug}">{name}</a></h3>'
        f'<div class="directory__member-title">{rank}</div>'
        "</div></td>"
        f"{contact}"
        '<td><span class="table-results-view__cell-label">Role</span>'
        "<div>Faculty</div></td>"
        "</tr>"
    )


CURRENT_HTML = (
    '<table class="directory__results filter-results__table table"><tbody>'
    + _row("Ahmet Ay", "aay",
           "Professor of Biology and Mathematics; Chair, Department of Biology",
           None)
    + _row("Ken Belanger", "kbelanger",
           "Russell Colgate Distinguished University Professor of Biology",
           "kbelanger@colgate.edu")
    + _row("Priyanka Lamichhane", "plamichhane",
           "Visiting Assistant Professor of Biology", "plam@colgate.edu")
    + _row("Rita Ali", "rali", "Laboratory Instructor in Biology", None)
    + _row("Emeritus Person", "eperson",
           "Professor Emeritus of Biology", None)
    + "</tbody></table>"
)

# The pre-re-theme markup: name in a class="h3" wrapper, rank a bare text node.
LEGACY_HTML = (
    '<table class="directory__results"><tbody>'
    '<tr><td><div class="h3"><a href="/about/directory/aay">Ahmet Ay</a></div>'
    "Professor of Biology and Mathematics</td>"
    '<td><a href="mailto:aay@colgate.edu">aay@colgate.edu</a></td>'
    "<td>Faculty</td></tr>"
    "</tbody></table>"
)

_DIRECTORY_URL = SCHOOL["departments"][0]["scrape"]["url"]


def _parse(html: str) -> list[dict]:
    return fg._parse_cards(
        BeautifulSoup(html, "html.parser"),
        _SELECTORS,
        _DIRECTORY_URL,
        ladder_filter=_LADDER,
    )


def test_current_template_parses_faculty():
    """The regression: this shape used to yield ZERO people."""
    names = [p["name"] for p in _parse(CURRENT_HTML)]
    assert "Ahmet Ay" in names
    assert "Ken Belanger" in names


def test_rank_comes_from_its_own_element():
    ay = next(p for p in _parse(CURRENT_HTML) if p["name"] == "Ahmet Ay")
    assert ay["title"].startswith("Professor of Biology and Mathematics")
    # The role column's bare "Faculty" is not a rank and must not leak in.
    assert "Faculty" not in ay["title"]


def test_inline_email_is_captured_when_exposed():
    people = {p["name"]: p.get("email") for p in _parse(CURRENT_HTML)}
    assert people["Ken Belanger"] == "kbelanger@colgate.edu"
    # Colgate exposes an address for only part of the directory; a missing one
    # ships a lite record rather than a guess.
    assert people["Ahmet Ay"] is None


def test_ladder_gate_drops_emeriti_visiting_and_lab_instructors():
    names = [p["name"] for p in _parse(CURRENT_HTML)]
    assert "Emeritus Person" not in names
    assert "Priyanka Lamichhane" not in names  # visiting
    assert "Rita Ali" not in names             # no professor/lecturer rank


def test_legacy_template_still_parses():
    """Both name shapes are accepted, so restoring the old theme would not
    silently re-break the college."""
    people = _parse(LEGACY_HTML)
    assert [p["name"] for p in people] == ["Ahmet Ay"]
    assert people[0]["email"] == "aay@colgate.edu"


def test_profile_link_is_kept_as_the_record_url():
    ay = next(p for p in _parse(CURRENT_HTML) if p["name"] == "Ahmet Ay")
    assert ay["url"].endswith("/about/directory/aay")
