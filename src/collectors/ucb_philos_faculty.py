"""Collector for UC Berkeley Department of Philosophy faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_history_faculty / ucb_sph_faculty.

The Philosophy directory (https://philosophy.berkeley.edu/people/faculty) is a
custom Rails theme: each faculty member is a `div.PersonListing` whose
`div.PersonDescription > p` opens with the name + profile link in `a > b`
(href `/people/detail/<id>`), followed by the rank and a free-text biography
that describes the person's areas of research. The listing thus already carries
both the title and the research signal; profiles are visited only to recover the
email (the personal address is the first `mailto:`; the department mailbox
`phildept@berkeley.edu` is the second and is filtered via NOISE_EMAILS).

Emeritus faculty (flagged in the rank) are dropped. Records with no email found
ship "lite" but still carry the listing biography (confidence_score=0.5).

Directory: https://philosophy.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_philos_faculty            # fetch & preview
    python -m src.collectors.ucb_philos_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_philos_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    NOISE_EMAILS,
    PROFILE_DELAY,
    clean_name,
    dedup_by_profile_url,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

PHILOS_CONFIG = {
    "source": "ucb_philos_faculty",
    "name": "Philosophy",
    "short": "PHIL",
    "url": "https://philosophy.berkeley.edu/people/faculty",
    "base": "https://philosophy.berkeley.edu",
    "majors": ["Philosophy"],
    # Broad fallback for faculty whose biography maps to no topical keyword.
    "keywords": ["philosophy"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_philos_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Philosophy directory into [{name, url, title, research_areas}].

    Each faculty member is a `div.PersonListing` whose `div.PersonDescription p`
    opens with the name + profile link in `a > b`, then the rank, then a
    biography. The rank is the text between the name and the first "(" (the
    degree parenthetical); the remaining text (rank + degree + bio) is kept as
    the research signal. Email is not on the listing.
    """
    faculty: list[dict] = []
    for block in soup.select("div.PersonListing"):
        para = block.select_one("div.PersonDescription p")
        if not para:
            continue
        link = para.select_one("a[href]")
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        full = para.get_text(" ", strip=True)
        rest = full[len(link.get_text(" ", strip=True)):].strip()

        person: dict = {"name": name, "url": urljoin(base, href)}
        title = rest.split("(")[0].strip()
        if title:
            person["title"] = title
        if rest:
            person["research_areas"] = rest[:600]
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} Philosophy faculty")
    return faculty


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Return the professor's personal email: the first mailto: that is not the
    department mailbox (NOISE_EMAILS)."""
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if addr and addr not in NOISE_EMAILS:
            return addr
    return None


def _enrich_philos_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the personal email (research came from the listing).

    Respectful: a small delay between requests, the shared robust fetcher, and a
    graceful skip when a profile fails to fetch.
    """
    total = len(faculty)
    found = 0
    for i, person in enumerate(faculty):
        url = person.get("url")
        if not url:
            continue
        soup = fetch_soup(url)
        if soup:
            email = _email_from_profile(soup)
            if email:
                person["email"] = email
                found += 1
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(f"  Recovered {found}/{total} emails from profile pages")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Philosophy faculty and return normalized opportunity records.

    The listing supplies name + link + title + biography; with enrich=True
    (default) each profile page is visited to recover the personal email.
    """
    soup = fetch_soup(PHILOS_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(
        _scrape_philos_faculty_list(soup, PHILOS_CONFIG["base"])
    )
    if enrich:
        raw = _enrich_philos_profiles(raw, PHILOS_CONFIG)
    normalized = [n for n in (normalize_faculty(p, PHILOS_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Philosophy faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(PHILOS_CONFIG, "UC Berkeley Philosophy Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
