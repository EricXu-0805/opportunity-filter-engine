"""Collector for UC Berkeley Integrative Biology (IB) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common.

IB's `/people/faculty` page is a set of Name/Phone/Email/Office tables grouped
under "Faculty", "Lecturers", and "Emeriti" headings. The Faculty table carries
each professor's name, rank, and mailto: email inline — so name, title AND
email all come from the listing with no profile hop. Only the "Faculty" table
is scraped (Lecturers and Emeriti are skipped).

Research is NOT taken: IB's directory detail page only links out to a separate
per-faculty page for the research description (two hops away), so research
enrichment is deferred. Records therefore carry the broad department keyword but
do include the contact email (confidence_score=0.7 when present).

Directory: https://ib.berkeley.edu/people/faculty
Each row links to a contact card at /people/directory/detail/<id>/.

Usage:
    python -m src.collectors.ucb_ib_faculty            # fetch & preview
    python -m src.collectors.ucb_ib_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    NOISE_EMAILS,
    clean_name,
    dedup_by_profile_url,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

IB_CONFIG = {
    "source": "ucb_ib_faculty",
    "name": "Department of Integrative Biology",
    "short": "IB",
    "url": "https://ib.berkeley.edu/people/faculty",
    "base": "https://ib.berkeley.edu",
    "majors": ["Integrative Biology", "Biology"],
    "keywords": ["integrative biology"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_ib_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the IB "Faculty" table into [{name, url, title, email}].

    The page has Name/Phone/Email/Office tables under "Faculty", "Lecturers",
    and "Emeriti" headings; only the "Faculty" table is read. Each row's name
    cell is `<a><strong>Name</strong></a><br/>Title` and the email cell holds a
    mailto: link.
    """
    faculty_table = None
    for table in soup.select("table"):
        heading = table.find_previous(["h2", "h3", "h4"])
        if heading and heading.get_text(" ", strip=True).strip().lower() == "faculty":
            faculty_table = table
            break
    if faculty_table is None:
        logger.warning("IB: no 'Faculty' table found")
        return []

    faculty: list[dict] = []
    for row in faculty_table.select("tr"):
        name_link = row.find("a", href=True)
        if not name_link or not name_link.find("strong"):
            continue
        name = clean_name(name_link.get_text(" ", strip=True))
        href = name_link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        # Title: the name cell's text after the <a> (rank follows a <br/>).
        name_cell = name_link.find_parent("td")
        if name_cell:
            cell_text = name_cell.get_text(" ", strip=True)
            title = cell_text.replace(name_link.get_text(" ", strip=True), "", 1).strip(" ,")
            if title:
                person["title"] = title

        # Email: the row's mailto: cell (skip shared/admin mailboxes).
        mail = row.select_one("a[href^='mailto:']")
        if mail:
            email = mail.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
            if email and email not in NOISE_EMAILS:
                person["email"] = email

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} IB faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape IB faculty and return normalized opportunity records.

    Name + title + email all come from the "Faculty" table, so the ``enrich``
    flag is accepted (for the shared CLI) but there is no profile hop.
    """
    soup = fetch_soup(IB_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_ib_faculty_list(soup, IB_CONFIG["base"]))
    normalized = [n for n in (normalize_faculty(p, IB_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} IB faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(IB_CONFIG, "UC Berkeley Integrative Biology Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
