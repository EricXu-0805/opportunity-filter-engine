"""Collector for UC Berkeley Environmental Science, Policy & Management (ESPM).

A department config + bespoke paginated-table parser over src.collectors.ucb_common,
following the same pattern as ucb_pmb_faculty.

ESPM's `/people/faculty` (ourenvironment.berkeley.edu) is an Open-Berkeley
views-table (Name / Title / Role), paginated across many pages and mixing
Graduate Students, Postdocs, Emeriti, and Faculty. We page through it and keep
only rows whose Role contains "Faculty" (Emeriti excluded). Each kept row gives
a name + /people/<slug> profile link; the profile (an Open-Berkeley person page)
is then visited via the shared enrichment hop to recover the mailto: email and
the free-text research interests (`resint`). Records with no email ship "lite".

Directory: https://ourenvironment.berkeley.edu/people/faculty  (paginated ?page=N)

Usage:
    python -m src.collectors.ucb_espm_faculty            # fetch & preview
    python -m src.collectors.ucb_espm_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_espm_faculty --save     # merge into processed data
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

_MAX_PAGES = 25  # safety bound; the directory is ~21 pages
_FACULTY_ROLE_RE = re.compile(r"\bFaculty\b")

ESPM_CONFIG = {
    "source": "ucb_espm_faculty",
    "name": "Department of Environmental Science, Policy & Management",
    "short": "ESPM",
    "url": "https://ourenvironment.berkeley.edu/people/faculty",
    "base": "https://ourenvironment.berkeley.edu",
    "majors": ["Environmental Sciences", "Society & Environment",
               "Conservation & Resource Studies", "Molecular Environmental Biology"],
    "keywords": ["environmental science"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
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


def _table_row_count(soup: BeautifulSoup) -> int:
    table = soup.select_one("table")
    return len(table.select("tbody tr")) if table else 0


def _scrape_espm_faculty() -> list[dict]:
    """Page through the directory, collecting Faculty-role rows until a page
    has no table rows at all (or the safety bound is hit).

    The end-of-pager test must count TABLE rows, not kept faculty rows: the
    directory sorts all roles together, so a middle page can be 20 rows of
    Graduate Students/Postdocs with zero Faculty rows (live page 10, 2026-07 —
    breaking there lost pages 11-21, 29 of 68 faculty)."""
    faculty: list[dict] = []
    for page in range(_MAX_PAGES):
        soup = fetch_soup(f"{ESPM_CONFIG['url']}?page={page}")
        if not soup:
            break
        rows = _scrape_table_page(soup, ESPM_CONFIG["base"])
        if not _table_row_count(soup) and page > 0:
            break
        faculty.extend(rows)
        logger.info(f"  page {page}: {len(rows)} faculty")
    logger.info(f"  {len(faculty)} ESPM faculty across pages")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape ESPM faculty (paginated, role-filtered) and return normalized records.

    The listing gives name + profile link; with enrich=True (default) each
    profile is visited to recover the contact email and research interests.
    """
    raw = dedup_by_profile_url(_scrape_espm_faculty())
    if not raw:
        return []
    if enrich:
        raw = enrich_faculty_from_profiles(raw, ESPM_CONFIG)
    normalized = [n for n in (normalize_faculty(p, ESPM_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} ESPM faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(ESPM_CONFIG, "UC Berkeley ESPM Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
