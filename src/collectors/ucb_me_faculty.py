"""Collector for UC Berkeley Mechanical Engineering (ME) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_bioe_faculty (a Beaver Builder grid, not an
Open-Berkeley Drupal directory).

The ME faculty directory (`/faculty/`) is a Beaver Builder grid where each
faculty member is a `div.fl-post-grid-post` with the name + profile link in
`h3.fl-post-title a` (href `/people/<slug>/`). Unlike BioE it carries no rank
text or research-area classes on the listing (the title slot is JS-populated
and the by-research-area page is JS-filtered), so records are "lite": name +
profile link, with the contact email recovered from each profile's mailto via
the shared enrichment hop. Research falls back to the broad department keyword.

Records with no email found ship "lite" (contact_email=None,
confidence_score=0.5). Emeritus faculty are not listed on `/faculty/`, and the
shared title filter still drops any whose profile-derived title says so.

Directory: https://me.berkeley.edu/faculty/
Each entry links to a profile at /people/<slug>/.

Usage:
    python -m src.collectors.ucb_me_faculty            # fetch & preview
    python -m src.collectors.ucb_me_faculty --no-enrich  # skip email hop (fast)
    python -m src.collectors.ucb_me_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    clean_name,
    dedup_by_profile_url,
    enrich_faculty_from_profiles,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

ME_CONFIG = {
    "source": "ucb_me_faculty",
    "name": "Department of Mechanical Engineering",
    "short": "ME",
    "url": "https://me.berkeley.edu/faculty/",
    "base": "https://me.berkeley.edu",
    "majors": ["Mechanical Engineering"],
    "keywords": ["mechanical engineering"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    # No selectors: bespoke listing parser below; email comes from the profile
    # mailto via the shared enrichment hop.
    "selectors": {},
}


def _scrape_me_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the ME directory into [{name, url, title?}].

    Each faculty member is a `div.fl-post-grid-post` with name + profile link in
    `h3.fl-post-title a`. The `div.professor-title` slot is JS-populated (empty
    in the served HTML), so a title is attached only when present.
    """
    faculty: list[dict] = []
    for card in soup.select("div.fl-post-grid-post"):
        name_el = card.select_one("h3.fl-post-title a")
        if not name_el:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        href = name_el.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        title_el = card.select_one("div.professor-title")
        if title_el:
            title = title_el.get_text(" ", strip=True)
            if title:
                person["title"] = title

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} ME faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape ME faculty and return normalized opportunity records.

    The listing supplies name + link; with enrich=True (default) each profile
    page is visited to recover the contact email (a mailto: link).
    """
    soup = fetch_soup(ME_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_me_faculty_list(soup, ME_CONFIG["base"]))
    if enrich:
        raw = enrich_faculty_from_profiles(raw, ME_CONFIG)
    normalized = [n for n in (normalize_faculty(p, ME_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} ME faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(ME_CONFIG, "UC Berkeley Mechanical Engineering Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
