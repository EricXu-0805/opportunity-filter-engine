"""Collector for UC Berkeley Sociology faculty research opportunities.

A department config + bespoke table parser over src.collectors.ucb_common.

The Sociology directory (sociology.berkeley.edu/people/faculty) is a single
Name/Contact/Special Interests table where each row carries the name + rank
(`td.views-field-name`: an `<a>` to /faculty/<slug> plus a `<div>` rank), the
email (`td.views-field-mail`), and the research interests
(`td.views-field-field-special`) — all inline, so no profile hop is needed.

Records with no email ship "lite" (contact_email=None, confidence_score=0.5);
emeritus faculty are dropped by the shared title filter.

Directory: https://sociology.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_soc_faculty            # fetch & preview
    python -m src.collectors.ucb_soc_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    EMAIL_RE,
    NOISE_EMAILS,
    clean_name,
    dedup_by_profile_url,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

SOC_CONFIG = {
    "source": "ucb_soc_faculty",
    "name": "Department of Sociology",
    "short": "SOC",
    "url": "https://sociology.berkeley.edu/people/faculty",
    "base": "https://sociology.berkeley.edu",
    "majors": ["Sociology"],
    "keywords": ["sociology"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_soc_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Sociology table into [{name, url, title, email, research_areas}].

    Each row's `td.views-field-name` holds the name `<a>` (-> /faculty/<slug>)
    and a `<div>` rank; `td.views-field-mail` holds the email; and
    `td.views-field-field-special` holds the research interests.
    """
    table = soup.select_one("table")
    if not table:
        return []
    faculty: list[dict] = []
    for row in table.select("tbody tr"):
        name_cell = row.select_one("td.views-field-name")
        name_link = name_cell.select_one("a[href]") if name_cell else None
        if not name_link:
            continue
        name = clean_name(name_link.get_text(" ", strip=True))
        href = name_link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        rank = name_cell.select_one("div")
        if rank and rank.get_text(strip=True):
            person["title"] = rank.get_text(" ", strip=True)

        mail_cell = row.select_one("td.views-field-mail, td[class*='views-field-mail']")
        if mail_cell:
            match = EMAIL_RE.search(mail_cell.get_text(" ", strip=True))
            if match and match.group(0).lower() not in NOISE_EMAILS:
                person["email"] = match.group(0).lower()

        research_cell = row.select_one("td.views-field-field-special")
        if research_cell and research_cell.get_text(strip=True):
            person["research_areas"] = research_cell.get_text(" ", strip=True)[:600]

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} SOC faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Sociology faculty and return normalized opportunity records.

    Name + title + email + research all come from the directory table, so the
    ``enrich`` flag is accepted (for the shared CLI) but there is no profile hop.
    """
    soup = fetch_soup(SOC_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_soc_faculty_list(soup, SOC_CONFIG["base"]))
    normalized = [n for n in (normalize_faculty(p, SOC_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} SOC faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(SOC_CONFIG, "UC Berkeley Sociology Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
