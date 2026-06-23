"""Collector for UC Berkeley Plant & Microbial Biology (PMB) faculty.

A department config + bespoke paginated-table parser over src.collectors.ucb_common.

PMB's `/people/faculty` is an Open-Berkeley views-table (Name / Job title /
Role), paginated across several pages and mixing Staff, Graduate Group members,
Emeriti, and Faculty. We page through it and keep only rows whose Role contains
"Faculty" (excluding Emeriti). Each kept row gives a name + /people/<slug>
profile link; the profile (an Open-Berkeley person page) is then visited via the
shared enrichment hop to recover the mailto: email and the free-text research
interests (`resint`). Records with no email ship "lite".

Directory: https://pmb.berkeley.edu/people/faculty  (paginated ?page=N)

Usage:
    python -m src.collectors.ucb_pmb_faculty            # fetch & preview
    python -m src.collectors.ucb_pmb_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_pmb_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
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

# Stop paging after this many pages (safety bound; the directory is ~5 pages).
_MAX_PAGES = 15
_FACULTY_ROLE_RE = re.compile(r"\bFaculty\b")

PMB_CONFIG = {
    "source": "ucb_pmb_faculty",
    "name": "Department of Plant & Microbial Biology",
    "short": "PMB",
    "url": "https://pmb.berkeley.edu/people/faculty",
    "base": "https://pmb.berkeley.edu",
    "majors": ["Plant Biology", "Microbiology", "Plant & Microbial Biology"],
    "keywords": ["plant biology"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        # Profile (Open-Berkeley person page) email + research fields.
        "email_field": "div.field-name-field-openberkeley-person-email",
        "research_interests": [
            "div.field-name-field-openberkeley-person-resint .field-item",
        ],
    },
}


def _scrape_table_page(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse one views-table page, keeping only Role-contains-"Faculty" rows
    (Emeriti excluded). Returns [{name, url}]."""
    table = soup.select_one("table")
    if not table:
        return []
    out: list[dict] = []
    for row in table.select("tbody tr"):
        role_cell = row.select_one("td.views-field-field-openberkeley-person-type")
        role = role_cell.get_text(" ", strip=True) if role_cell else ""
        if not _FACULTY_ROLE_RE.search(role) or "Emeriti" in role:
            continue
        link = row.select_one("td.views-field-title a[href], a[href]")
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue
        out.append({"name": name, "url": urljoin(base, href)})
    return out


def _scrape_pmb_faculty() -> list[dict]:
    """Page through the directory, collecting Faculty-role rows from each page
    until a page yields none (or the safety bound is hit)."""
    faculty: list[dict] = []
    for page in range(_MAX_PAGES):
        url = f"{PMB_CONFIG['url']}?page={page}"
        soup = fetch_soup(url)
        if not soup:
            break
        rows = _scrape_table_page(soup, PMB_CONFIG["base"])
        if not rows and page > 0:
            break  # past the last populated page
        faculty.extend(rows)
        logger.info(f"  page {page}: {len(rows)} faculty")
    logger.info(f"  {len(faculty)} PMB faculty across pages")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape PMB faculty (paginated, role-filtered) and return normalized records.

    The listing gives name + profile link; with enrich=True (default) each
    profile is visited to recover the contact email and research interests.
    """
    raw = dedup_by_profile_url(_scrape_pmb_faculty())
    if not raw:
        return []
    if enrich:
        raw = enrich_faculty_from_profiles(raw, PMB_CONFIG)
    normalized = [n for n in (normalize_faculty(p, PMB_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} PMB faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(PMB_CONFIG, "UC Berkeley Plant & Microbial Biology Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
