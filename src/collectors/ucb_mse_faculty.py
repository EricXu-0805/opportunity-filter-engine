"""Collector for UC Berkeley Materials Science & Engineering (MSE) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_bioe_faculty (a Beaver Builder grid, not an
Open-Berkeley Drupal directory).

The MSE faculty directory is a Beaver Builder grid where each faculty member is
a `div.fl-post-grid-post` of the `people_new` post type. There is no `h3`
link; the name and profile URL come from the card's
`<meta itemprop="mainEntityOfPage" content="<name>" itemid="<url>">`. A
`category-<role>` class tags the role, so the 14 `category-emeritus` cards are
skipped. The listing carries no rank or research text, and profiles expose the
email as plain text (no mailto) with no labeled research section — so records
are "lite": name + profile link + email (recovered by the shared profile hop's
page-wide scan) and the broad department keyword.

Records with no email found ship "lite" (contact_email=None,
confidence_score=0.5).

Directory: https://mse.berkeley.edu/people/faculty/
Each entry links to a profile at /people_new/<slug>/.

Usage:
    python -m src.collectors.ucb_mse_faculty            # fetch & preview
    python -m src.collectors.ucb_mse_faculty --no-enrich  # skip email hop (fast)
    python -m src.collectors.ucb_mse_faculty --save     # merge into processed data
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

MSE_CONFIG = {
    "source": "ucb_mse_faculty",
    "name": "Department of Materials Science & Engineering",
    "short": "MSE",
    "url": "https://mse.berkeley.edu/people/faculty/",
    "base": "https://mse.berkeley.edu",
    "majors": ["Materials Science & Engineering", "Materials Science and Engineering"],
    "keywords": ["materials science"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    # No selectors: bespoke listing parser below; the profile exposes its email
    # as plain text (no mailto/field), so the shared extractor's page-wide scan
    # recovers it.
    "selectors": {},
}


def _scrape_mse_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the MSE directory into [{name, url}].

    Each faculty member is a `div.fl-post-grid-post`; the name + profile URL are
    on its `<meta itemprop="mainEntityOfPage">` (there is no heading link).
    `category-emeritus` cards are skipped. Email/research are not on the listing.
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

    logger.info(f"  Found {len(faculty)} MSE faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape MSE faculty and return normalized opportunity records.

    The listing supplies name + link; with enrich=True (default) each profile
    page is visited to recover the contact email.
    """
    soup = fetch_soup(MSE_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_mse_faculty_list(soup, MSE_CONFIG["base"]))
    if enrich:
        raw = enrich_faculty_from_profiles(raw, MSE_CONFIG)
    normalized = [n for n in (normalize_faculty(p, MSE_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} MSE faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(MSE_CONFIG, "UC Berkeley Materials Science & Engineering Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
