"""Collector for UC Berkeley Geography faculty research opportunities.

A department config + bespoke parser over src.collectors.ucb_common.

The Geography faculty page (geography.berkeley.edu/people/faculty) renders each
faculty member as a two-column table: a photo cell and a content cell holding
an `<h3><a>` name (-> /<profile-slug>), a `<p>` with the rank / office / a
mailto: email, and an `<em>` with research interests — all inline, so no profile
hop is needed. The page is organized under section headings (Regular Faculty,
etc.); emeritus faculty are dropped by the shared title filter.

Records with no email ship "lite" (contact_email=None, confidence_score=0.5).

Directory: https://geography.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_geog_faculty            # fetch & preview
    python -m src.collectors.ucb_geog_faculty --save     # merge into processed data
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

_RANK_RE = re.compile(
    r"((?:Assistant |Associate |Adjunct |Visiting )?Professor(?: Emerit\w+)?|Lecturer|Researcher)",
    re.IGNORECASE,
)

GEOG_CONFIG = {
    "source": "ucb_geog_faculty",
    "name": "Department of Geography",
    "short": "GEOG",
    "url": "https://geography.berkeley.edu/people/faculty",
    "base": "https://geography.berkeley.edu",
    "majors": ["Geography"],
    "keywords": ["geography"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_geog_faculty_list(soup: BeautifulSoup) -> list[dict]:
    """Parse the Geography page into [{name, url, title, email, research_areas}].

    Each faculty member is a `<table>` whose content cell holds an `<h3><a>`
    name (+ profile link), a `<p>` with the rank / office / mailto: email, and
    an `<em>` with research interests.
    """
    faculty: list[dict] = []
    for table in soup.select("table"):
        name_link = table.select_one("h3 a[href]")
        if not name_link:
            continue
        name = clean_name(name_link.get_text(" ", strip=True))
        href = name_link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": href}

        text = table.get_text(" ", strip=True)
        rank = _RANK_RE.search(text)
        if rank:
            person["title"] = rank.group(1)

        email = unique_bound_container_contact(
            table,
            GEOG_CONFIG,
            nested_record_selector="table",
        )
        if email:
            stamp_bound_directory_contact(
                person,
                email,
                GEOG_CONFIG,
                source_soup=soup,
                requested_url=GEOG_CONFIG["url"],
            )

        research = table.select_one("em")
        if research and research.get_text(strip=True):
            person["research_areas"] = research.get_text(" ", strip=True)[:600]

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} GEOG faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Geography faculty and return normalized opportunity records.

    Name + title + email + research all come from the faculty page, so the
    ``enrich`` flag is accepted (for the shared CLI) but there is no profile hop.
    """
    soup = fetch_soup(GEOG_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_geog_faculty_list(soup))
    normalized = [n for n in (normalize_faculty(p, GEOG_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} GEOG faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(GEOG_CONFIG, "UC Berkeley Geography Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
