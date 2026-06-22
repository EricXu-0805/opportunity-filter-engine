"""Collector for UC Berkeley Molecular & Cell Biology (MCB) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common.

MCB splits its faculty data across two pages, which this collector joins by name:
  * "Faculty Research Descriptions" (`/faculty/`) — the richest research listing
    of any Berkeley department: each faculty member is a `<p>` with the name +
    profile link (`<a><strong>Name</strong></a>` -> /faculty/<div>/<slug>), the
    rank/division in a second `<strong>`, and a free-text research description.
  * Directory (`/people/faculty`) — a Name/Phone/Email/Office table (Faculty,
    Lecturers, Emeriti sections) that carries each professor's `mailto:` email.

The research page has no emails (and profiles publish only the department
chair's shared `mcbchair@berkeley.edu`), while the directory has no research —
so name, title and research come from the research page and the email is joined
from the directory by a (first, last) name key. Records with no matched email
ship "lite"; emeritus are dropped by the shared title filter.

Usage:
    python -m src.collectors.ucb_mcb_faculty            # fetch & preview
    python -m src.collectors.ucb_mcb_faculty --no-enrich  # skip the email join
    python -m src.collectors.ucb_mcb_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
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

# Person profile links are /faculty/<division>/<slug>; the bare /faculty/<div>
# links (e.g. /faculty/bbs) are research-division nav, not people.
_PERSON_HREF_RE = re.compile(r"/faculty/[A-Za-z]+/[A-Za-z]")

# The directory table page (name + phone + email + office).
_DIRECTORY_URL = "https://mcb.berkeley.edu/people/faculty"


def _name_key(name: str) -> tuple[str, ...]:
    """(first, last) lower-cased key for joining the two pages, tolerant of
    middle initials that differ between them (e.g. 'Jennifer A. Doudna')."""
    toks = clean_name(name).lower().replace(".", "").split()
    return (toks[0], toks[-1]) if len(toks) >= 2 else tuple(toks)


def _scrape_directory_emails(soup: BeautifulSoup) -> dict[tuple[str, ...], str]:
    """Map each faculty member's (first, last) name key -> email from the
    directory table. Skips the Emeriti section's table and shared/admin
    mailboxes."""
    emails: dict[tuple[str, ...], str] = {}
    for table in soup.select("table"):
        heading = table.find_previous(["h2", "h3", "h4"])
        if heading and "emeriti" in heading.get_text(" ", strip=True).lower():
            continue
        for row in table.select("tr"):
            name_link = row.find("a", href=True)
            mail = row.select_one("a[href^='mailto:']")
            if not name_link or not mail:
                continue
            email = mail.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
            if email and email not in NOISE_EMAILS:
                emails.setdefault(_name_key(name_link.get_text(" ", strip=True)), email)
    return emails

MCB_CONFIG = {
    "source": "ucb_mcb_faculty",
    "name": "Department of Molecular & Cell Biology",
    "short": "MCB",
    "url": "https://mcb.berkeley.edu/faculty/",
    "base": "https://mcb.berkeley.edu",
    "majors": ["Molecular & Cell Biology", "Molecular and Cell Biology"],
    "keywords": ["molecular biology"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_mcb_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the MCB directory into [{name, url, title, research_areas}].

    Each faculty member is a `<p>` with the name + profile link in
    `<a><strong>Name</strong></a>` (href /faculty/<div>/<slug>), the rank in a
    second `<strong>`, and the research description as the `<p>`'s direct text
    nodes. Emeritus faculty (title says so) are left to the shared title filter.
    """
    faculty: list[dict] = []
    for p in soup.find_all("p"):
        link = p.find("a", href=_PERSON_HREF_RE)
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        # First <strong> is the name (inside the <a>); the second is the rank.
        strongs = p.find_all("strong")
        if len(strongs) > 1:
            title = strongs[1].get_text(" ", strip=True)
            if title:
                person["title"] = title

        # Research description: the <p>'s direct text nodes (the name lives in
        # the <a> and the title in a <strong>, so neither is included here).
        research = " ".join(s.strip() for s in p.find_all(string=True, recursive=False)
                            if s.strip())
        if research:
            person["research_areas"] = research[:600]

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} MCB faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape MCB faculty and return normalized opportunity records.

    Name + title + research come from the research-descriptions page; with
    enrich=True (default) the directory page is also fetched and each email is
    joined by (first, last) name key. No per-profile hop is made.
    """
    soup = fetch_soup(MCB_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_mcb_faculty_list(soup, MCB_CONFIG["base"]))

    if enrich:
        dir_soup = fetch_soup(_DIRECTORY_URL)
        if dir_soup:
            emails = _scrape_directory_emails(dir_soup)
            matched = 0
            for person in raw:
                email = emails.get(_name_key(person["name"]))
                if email:
                    person["email"] = email
                    matched += 1
            logger.info(f"  Joined {matched}/{len(raw)} emails from the directory")

    normalized = [n for n in (normalize_faculty(p, MCB_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} MCB faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(MCB_CONFIG, "UC Berkeley Molecular & Cell Biology Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
