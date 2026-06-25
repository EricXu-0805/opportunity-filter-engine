"""Collector for UC Berkeley Department of History faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_ieor_faculty / ucb_sph_faculty.

The History directory (https://history.berkeley.edu/people/faculty) is an Open
Berkeley landing page whose roster is a grid of "label" widgets: each faculty
member is a `div.openberkeley-widgets-label-inner` with the name + profile link
in `h2 > a` and a curated research field (e.g. "Early Modern Europe", "History
of Science", "East Asia") in the following `<p>`. Unlike a typical Berkeley
directory the listing thus already carries the research signal; profiles are
visited only to recover the email.

Cross-listed faculty live on area-studies subdomains (melc, sseas, cmes, ...),
so profile URLs span several hosts; on every host the professor's personal email
is the first `mailto:` and a department mailbox is the second (filtered via
NOISE_EMAILS, with the first-mailto rule as the real guard). Emeritus faculty
(flagged in the research field) are dropped. Records with no email found ship
"lite" but still carry the listing's research field (confidence_score=0.5).

Directory: https://history.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_history_faculty            # fetch & preview
    python -m src.collectors.ucb_history_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_history_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
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

# The research field marks cross-listed emeritus faculty, e.g.
# "Ethnic Studies (Emeritus)"; they are not viable cold-email targets.
_EMERITUS_RE = re.compile(r"\b(emeritus|emerita|emeriti)\b", re.IGNORECASE)

HISTORY_CONFIG = {
    "source": "ucb_history_faculty",
    "name": "History",
    "short": "HIST",
    "url": "https://history.berkeley.edu/people/faculty",
    "base": "https://history.berkeley.edu",
    "majors": ["History"],
    # Broad fallback for faculty whose curated field maps to no topical keyword.
    "keywords": ["history"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_history_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the History directory into [{name, url, research_areas}].

    Each faculty member is a `div.openberkeley-widgets-label-inner` with the name
    + profile link in `h2 > a` and the curated research field in the following
    `<p>`. Emeritus faculty (flagged in that field) are skipped. Email is not on
    the listing.
    """
    faculty: list[dict] = []
    for block in soup.select("div.openberkeley-widgets-label-inner"):
        link = block.select_one("h2 a[href]")
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        field_el = block.find("p")
        field = field_el.get_text(" ", strip=True) if field_el else ""
        if field and _EMERITUS_RE.search(field):
            continue  # cross-listed emeritus faculty

        person: dict = {"name": name, "url": urljoin(base, href)}
        if field:
            person["research_areas"] = field
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} History faculty")
    return faculty


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Return the professor's personal email: the first mailto: that is not a
    department mailbox (NOISE_EMAILS). The personal address is listed first on
    every History / area-studies profile."""
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if addr and addr not in NOISE_EMAILS:
            return addr
    return None


def _enrich_history_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the personal email (research already came from the
    listing). Respectful: a small delay between requests, the shared robust
    fetcher, and a graceful skip when a profile fails to fetch.
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
    """Scrape History faculty and return normalized opportunity records.

    The listing supplies name + link + research field; with enrich=True (default)
    each profile page is visited to recover the personal email.
    """
    soup = fetch_soup(HISTORY_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(
        _scrape_history_faculty_list(soup, HISTORY_CONFIG["base"])
    )
    if enrich:
        raw = _enrich_history_profiles(raw, HISTORY_CONFIG)
    normalized = [n for n in (normalize_faculty(p, HISTORY_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} History faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(HISTORY_CONFIG, "UC Berkeley History Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
