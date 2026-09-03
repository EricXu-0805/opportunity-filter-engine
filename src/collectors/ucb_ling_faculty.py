"""Collector for UC Berkeley Linguistics faculty research opportunities.

A department config + bespoke parser over src.collectors.ucb_common.

The department moved host and template between 2026-07-21 and 2026-08-18:
``linguistics.berkeley.edu/faculty`` now 301s to
``lx.berkeley.edu/people/faculty``. Both are the same OpenBerkeley Drupal
build, and each faculty member is still a one-cell table carrying the rank,
an "Email:" address, the office, and a "Research and teaching:" description —
but the name heading is no longer the table's previous sibling. Each person is
now one ``div.panel-pane`` whose ``h2.pane-title`` holds the name (usually
linking to a personal site) and whose ``.pane-content`` holds the table.

The old parser required the heading to be the table's immediate previous
sibling, so after the move it matched nothing: the collector returned 0 with
status "ok" for four weeks, which withheld the ENTIRE UC Berkeley shard (53
other healthy departments, 3,106 records frozen at 2026-07-21) because the
release contract attributed a zero-emitting department to its school. The
parser therefore accepts BOTH shapes — the pane wrapper and the legacy
adjacent heading — so neither template regresses the other.

Faculty without a personal-site link (or with a non-informative one, e.g. the
bare "/" the current page carries for one appointment) get a synthetic anchor
URL (``/faculty#<name-slug>``) so each record stays unique through the
URL-based dedup. Records with no email ship "lite"; emeritus are on a
separate page.

Directory: https://lx.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_ling_faculty            # fetch & preview
    python -m src.collectors.ucb_ling_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    clean_name,
    dedup_by_profile_url,
    fetch_soup,
    normalize_faculty,
    stamp_bound_directory_contact,
    unique_bound_container_contact,
)

logger = logging.getLogger(__name__)

LING_CONFIG = {
    "source": "ucb_ling_faculty",
    "name": "Department of Linguistics",
    "short": "LING",
    "url": "https://lx.berkeley.edu/people/faculty",
    "base": "https://lx.berkeley.edu",
    "majors": ["Linguistics"],
    "keywords": ["linguistics"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# An href that carries no per-person information must not become the record
# URL: every such person would collapse onto the same URL and the URL-based
# dedup would keep exactly one of them.
_UNINFORMATIVE_HREFS = frozenset({"", "/", "#", "."})


def _person_heading(table) -> object | None:
    """The heading element naming the professor whose table this is.

    Two templates, both live-verified:

    * current (``lx.berkeley.edu``) — the table sits in a
      ``div.panel-pane`` whose ``h2.pane-title`` is the name. Only a pane
      holding exactly ONE table is accepted, so a future multi-person pane
      cannot bind one name to somebody else's row.
    * legacy (``linguistics.berkeley.edu``) — the heading is the table's
      immediate previous sibling.

    Returns None when neither shape applies, so an unrelated layout table is
    skipped rather than guessed at.
    """
    pane = table.find_parent("div", class_="panel-pane")
    if pane is not None and len(pane.select("table")) == 1:
        heading = pane.select_one("h2.pane-title")
        if heading is not None:
            return heading

    heading = table.previous_sibling
    while isinstance(heading, str) and not heading.strip():
        heading = heading.previous_sibling
    if getattr(heading, "name", None) in {"h2", "h3", "h4"}:
        return heading
    return None


def _scrape_ling_faculty_list(soup: BeautifulSoup, base: str, listing_url: str) -> list[dict]:
    """Parse the Linguistics page into [{name, url, title, email, research_areas}].

    Each faculty member is a small table (containing an "Email:" /
    "Research and teaching:" body) named by a heading — the containing pane's
    ``h2.pane-title`` on the current template, the table's previous sibling on
    the legacy one (see :func:`_person_heading`). The heading's link (a personal
    site) is used as the URL; faculty without an informative one get a synthetic
    ``/faculty#<slug>`` anchor so dedup keeps them distinct.
    """
    faculty: list[dict] = []
    for table in soup.select("table"):
        text = table.get_text(" ", strip=True)
        if "Email:" not in text and "Research" not in text:
            continue
        heading = _person_heading(table)
        if heading is None:
            continue
        name = clean_name(heading.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        link = heading.find("a", href=True)
        href = (link.get("href") or "").strip() if link else ""
        if href in _UNINFORMATIVE_HREFS:
            href = ""
        url = href or f"{listing_url}#{_slugify(name)}"
        person: dict = {"name": name, "url": url}

        title = text.split("Email:")[0].strip()
        if title:
            person["title"] = title

        email = unique_bound_container_contact(
            table,
            LING_CONFIG,
            nested_record_selector="table",
        )
        if email:
            stamp_bound_directory_contact(
                person,
                email,
                LING_CONFIG,
                source_soup=soup,
                requested_url=listing_url,
            )

        if "Research and teaching:" in text:
            research = text.split("Research and teaching:", 1)[1].strip()
            if research:
                person["research_areas"] = research[:600]

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} LING faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Linguistics faculty and return normalized opportunity records.

    Name + title + email + research all come from the faculty page, so the
    ``enrich`` flag is accepted (for the shared CLI) but there is no profile hop.
    """
    soup = fetch_soup(LING_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(
        _scrape_ling_faculty_list(soup, LING_CONFIG["base"], LING_CONFIG["url"])
    )
    normalized = [n for n in (normalize_faculty(p, LING_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} LING faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(LING_CONFIG, "UC Berkeley Linguistics Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
