"""Collector for UC Berkeley Linguistics faculty research opportunities.

A department config + bespoke parser over src.collectors.ucb_common.

The Linguistics faculty page (linguistics.berkeley.edu/faculty) renders each
faculty member as a small one-cell table preceded by an `<h2>` name heading
(which often links to the professor's personal site). The table text carries
the rank, an "Email:" address, the office, and a "Research and teaching:"
description — all inline, so no profile hop is needed.

Faculty without a personal-site link get a synthetic anchor URL
(`/faculty#<name-slug>`) so each record stays unique through the URL-based
dedup. Records with no email ship "lite"; emeritus are on a separate page.

Directory: https://linguistics.berkeley.edu/faculty

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
    "url": "https://linguistics.berkeley.edu/faculty",
    "base": "https://linguistics.berkeley.edu",
    "majors": ["Linguistics"],
    "keywords": ["linguistics"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _scrape_ling_faculty_list(soup: BeautifulSoup, base: str, listing_url: str) -> list[dict]:
    """Parse the Linguistics page into [{name, url, title, email, research_areas}].

    Each faculty member is a small table (containing an "Email:" /
    "Research and teaching:" body) preceded by an `<h2>` name heading. The
    heading's link (a personal site) is used as the URL; faculty without one get
    a synthetic `/faculty#<slug>` anchor so dedup keeps them distinct.
    """
    faculty: list[dict] = []
    for table in soup.select("table"):
        text = table.get_text(" ", strip=True)
        if "Email:" not in text and "Research" not in text:
            continue
        # The real template places each person's heading immediately before
        # their one-cell table. Skip formatting whitespace only; any intervening
        # element means this table is not that professor's explicit container.
        heading = table.previous_sibling
        while isinstance(heading, str) and not heading.strip():
            heading = heading.previous_sibling
        if getattr(heading, "name", None) not in {"h2", "h3", "h4"}:
            continue
        name = clean_name(heading.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        link = heading.find("a", href=True)
        url = link.get("href") if link else f"{listing_url}#{_slugify(name)}"
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
