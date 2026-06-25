"""Collector for UC Berkeley Political Science faculty research opportunities.

A department config + bespoke listing parser over src.collectors.ucb_common.

The Political Science directory (polisci.berkeley.edu/people/faculty) is a
Drupal field-based listing: each faculty member is a `div.views-row` whose name
is in `div.field--name-realname a` (-> /people/person/<slug>) and whose rank is
in `div.field--name-field-user-title`. Profiles expose a mailto: email and
research interests in `div.field--name-field-research-interests` (plus
`field-academic-subfields`), recovered via the shared enrichment hop.

Records with no email ship "lite" (contact_email=None, confidence_score=0.5);
emeritus faculty are dropped by the shared title filter.

Directory: https://polisci.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_polisci_faculty            # fetch & preview
    python -m src.collectors.ucb_polisci_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_polisci_faculty --save     # merge into processed data
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

POLISCI_CONFIG = {
    "source": "ucb_polisci_faculty",
    "name": "Department of Political Science",
    "short": "POLISCI",
    "url": "https://polisci.berkeley.edu/people/faculty",
    "base": "https://polisci.berkeley.edu",
    "majors": ["Political Science", "Political Economy"],
    "keywords": ["political science"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        # Profile research signal: the field-research-interests block plus the
        # academic-subfields tags. .field__item keeps the labels out.
        "research_interests": [
            "div.field--name-field-research-interests .field__item",
            "div.field--name-field-academic-subfields .field__item",
        ],
    },
}


def _scrape_polisci_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Political Science directory into [{name, url, title}].

    Each faculty member is a `div.views-row` with the name + profile link in
    `div.field--name-realname a` (href /people/person/<slug>) and the rank in
    `div.field--name-field-user-title`.
    """
    faculty: list[dict] = []
    for row in soup.select("div.views-row"):
        name_el = row.select_one("div.field--name-realname a") or row.select_one("h2.field__item a")
        if not name_el or "/person/" not in name_el.get("href", ""):
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        href = name_el.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}
        title_el = row.select_one("div.field--name-field-user-title")
        if title_el and title_el.get_text(strip=True):
            person["title"] = title_el.get_text(" ", strip=True)
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} POLISCI faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Political Science faculty and return normalized opportunity records.

    The listing gives name + link + rank; with enrich=True (default) each
    profile is visited to recover the contact email and research interests.
    """
    soup = fetch_soup(POLISCI_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_polisci_faculty_list(soup, POLISCI_CONFIG["base"]))
    if enrich:
        raw = enrich_faculty_from_profiles(raw, POLISCI_CONFIG)
    normalized = [n for n in (normalize_faculty(p, POLISCI_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} POLISCI faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(POLISCI_CONFIG, "UC Berkeley Political Science Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
