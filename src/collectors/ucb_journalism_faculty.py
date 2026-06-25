"""Collector for UC Berkeley Graduate School of Journalism faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_history_faculty.

The Journalism faculty page (journalism.berkeley.edu/faculty) is a WordPress
directory of `div.faculty-profile` media blocks. Each block carries everything
this collector needs on the listing itself — no profile hop:
    - name + profile link in `h4.media-heading a` (href /person/<slug>/)
    - role in `p.title span.faculty` ("Faculty" / "Emeritus") and the rank in
      `span.chair`
    - the personal email in `p.contact-me a[href^=mailto:]`

Research interests are NOT on the listing, and the profile biographies are long
prose that trips unrelated KEYWORD_BANK terms (the same problem seen with the
School of Education), so this collector does NOT scrape bios. Keywords come from
the (short, curated) title — a named chair like "Distinguished Chair in
Investigative Journalism" yields a topical keyword; a plain "Professor" falls
back to the broad department keyword. Emeritus faculty are dropped.

Directory: https://journalism.berkeley.edu/faculty/

Usage:
    python -m src.collectors.ucb_journalism_faculty            # fetch & preview
    python -m src.collectors.ucb_journalism_faculty --save     # merge into processed data
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

# Titles carry transient parentheticals, e.g. "Professor (On sabbatical Fall
# 2026)"; strip them so the rank is stable across scrapes.
_TITLE_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_EMERITUS_RE = re.compile(r"\b(emeritus|emerita|emeriti)\b", re.IGNORECASE)

JOURNALISM_CONFIG = {
    "source": "ucb_journalism_faculty",
    "name": "Graduate School of Journalism",
    "short": "JOUR",
    "url": "https://journalism.berkeley.edu/faculty/",
    "base": "https://journalism.berkeley.edu",
    "majors": ["Journalism"],
    "keywords": ["journalism"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_journalism_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Journalism directory into [{name, url, title, email}].

    Each faculty member is a `div.faculty-profile` block; emeritus faculty
    (flagged in the role label or rank) are skipped. The personal email is read
    from the `p.contact-me` mailto:.
    """
    faculty: list[dict] = []
    for block in soup.select("div.faculty-profile"):
        link = block.select_one("h4.media-heading a[href*='/person/']")
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        role_el = block.select_one("p.title span.faculty")
        role = role_el.get_text(" ", strip=True) if role_el else ""
        chair_el = block.select_one("p.title span.chair")
        if chair_el:
            title = chair_el.get_text(" ", strip=True)
        else:
            title_el = block.select_one("p.title")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if role:
                title = re.sub(rf"^\s*{re.escape(role)}\s*[–-]?\s*", "", title).strip()
        title = _TITLE_PAREN_RE.sub("", title).strip()

        if _EMERITUS_RE.search(f"{role} {title}"):
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}
        if title:
            person["title"] = title

        mail = block.select_one("p.contact-me a[href^='mailto:']")
        if mail:
            email = mail.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
            if email and email not in NOISE_EMAILS:
                person["email"] = email

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} Journalism faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Journalism faculty and return normalized opportunity records.

    The listing carries name + link + title + email, so there is no profile hop;
    `enrich` is accepted for CLI parity but unused.
    """
    soup = fetch_soup(JOURNALISM_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(
        _scrape_journalism_faculty_list(soup, JOURNALISM_CONFIG["base"])
    )
    normalized = [n for n in (normalize_faculty(p, JOURNALISM_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Journalism faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(JOURNALISM_CONFIG, "UC Berkeley Journalism Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
