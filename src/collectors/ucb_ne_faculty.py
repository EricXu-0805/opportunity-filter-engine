"""Collector for UC Berkeley Nuclear Engineering (NE) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_mse_faculty (a Beaver Builder grid where the
name + profile URL come from each card's `<meta itemprop="mainEntityOfPage">`).

Listing-only by design — NE is the one Berkeley department whose profile pages
expose NOTHING per-professor: the only email on every profile is the shared
"Student Services" footer address (a page-wide scan would wrongly assign it to
everyone), and the "Research Areas" block is a site-wide nav overlay, not a
per-faculty section. So there is no profile-enrichment hop: records carry name
+ profile link + the broad department keyword, and ship "lite"
(contact_email=None, confidence_score=0.5). The 8 `category-emeritus` cards are
skipped.

Directory: https://nuc.berkeley.edu/faculty/
Each entry links to a profile at /people/<slug>/.

Usage:
    python -m src.collectors.ucb_ne_faculty            # fetch & preview
    python -m src.collectors.ucb_ne_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import clean_name, dedup_by_profile_url, fetch_soup, normalize_faculty

logger = logging.getLogger(__name__)

NE_CONFIG = {
    "source": "ucb_ne_faculty",
    "name": "Department of Nuclear Engineering",
    "short": "NE",
    "url": "https://nuc.berkeley.edu/faculty/",
    "base": "https://nuc.berkeley.edu",
    "majors": ["Nuclear Engineering"],
    "keywords": ["nuclear engineering"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_ne_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the NE directory into [{name, url}].

    Each faculty member is a `div.fl-post-grid-post`; the name + profile URL are
    on its `<meta itemprop="mainEntityOfPage">` (there is no heading link).
    `category-emeritus` cards are skipped.
    """
    faculty: list[dict] = []
    for card in soup.select("div.fl-post-grid-post"):
        if "category-emeritus" in card.get("class", []):
            continue
        meta = card.find("meta", itemprop="mainEntityOfPage")
        if not meta:
            continue
        name = clean_name(meta.get("content", "") or "")
        url = meta.get("itemid", "")
        if not name or len(name) < 3 or not url:
            continue
        faculty.append({"name": name, "url": urljoin(base, url)})

    logger.info(f"  Found {len(faculty)} NE faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape NE faculty and return normalized opportunity records.

    Listing-only: NE profiles expose no per-professor email or research, so the
    ``enrich`` flag is accepted (for the shared CLI) but there is no profile
    hop. Every record is lite (name + profile link + broad keyword).
    """
    soup = fetch_soup(NE_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_ne_faculty_list(soup, NE_CONFIG["base"]))
    normalized = [n for n in (normalize_faculty(p, NE_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} NE faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(NE_CONFIG, "UC Berkeley Nuclear Engineering Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
