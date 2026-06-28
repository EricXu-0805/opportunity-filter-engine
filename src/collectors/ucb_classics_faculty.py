"""Collector for UC Berkeley Ancient Greek and Roman Studies (Classics) faculty.

A department config + bespoke listing parser over ``src.collectors.ucb_common``,
following the same pattern as ucb_history_faculty.

The directory (https://dagrs.berkeley.edu/people/faculty) is a newer Bootstrap
theme — a grid of ``div.views-row`` cards rather than the Open-Berkeley person
nodes. Each card carries a profile link (``/people/<slug>``) and, helpfully, the
professor's email inline, so no profile hop is needed. The visible name runs the
first and last name together without a space, so the clean name is recovered
from the URL slug instead (``susanna-elm`` -> ``Susanna Elm``).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import NOISE_EMAILS, dedup_by_profile_url, fetch_soup, normalize_faculty

logger = logging.getLogger(__name__)

CLASSICS_CONFIG = {
    "source": "ucb_classics_faculty",
    "name": "Ancient Greek and Roman Studies",
    "short": "AGRS",
    "url": "https://dagrs.berkeley.edu/people/faculty",
    "base": "https://dagrs.berkeley.edu",
    "majors": ["Ancient Greek and Roman Studies", "Classics", "Classical Languages"],
    "keywords": ["classics", "ancient history"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.edu", re.IGNORECASE)
# Slug tokens kept uppercase (initials) vs lowercased connective particles.
_PARTICLES = {"de", "del", "della", "van", "von", "der", "di", "la", "le"}


def _name_from_slug(slug: str) -> str:
    words = []
    for w in slug.split("-"):
        if not w:
            continue
        if len(w) <= 2 and w not in _PARTICLES:
            words.append(w.upper())          # initials: r, f -> R, F
        elif w in _PARTICLES:
            words.append(w)
        else:
            words.append(w.capitalize())
    return " ".join(words)


def _scrape_classics_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the DAGRS directory into [{name, url, email}].

    Each faculty member is a ``div.views-row`` with a ``/people/<slug>`` profile
    link and an inline ``@…edu`` email. The clean name comes from the slug.
    """
    faculty: list[dict] = []
    seen: set[str] = set()
    for row in soup.select("div.views-row"):
        link = row.select_one("a[href*='/people/']")
        if not link:
            continue
        href = link.get("href", "")
        slug = href.rstrip("/").split("/")[-1]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        name = _name_from_slug(slug)
        if not name or len(name) < 3:
            continue
        person: dict = {"name": name, "url": urljoin(base, href)}
        m = _EMAIL_RE.search(row.get_text(" ", strip=True))
        if m and m.group(0).lower() not in NOISE_EMAILS:
            person["email"] = m.group(0).lower()
        faculty.append(person)
    logger.info(f"  Found {len(faculty)} AGRS (Classics) faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape AGRS/Classics faculty and return normalized opportunity records.

    The listing already carries name + profile link + email, so ``enrich`` is
    accepted for interface parity but no profile hop is required.
    """
    soup = fetch_soup(CLASSICS_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_classics_faculty_list(soup, CLASSICS_CONFIG["base"]))
    normalized = [n for n in (normalize_faculty(p, CLASSICS_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} AGRS (Classics) faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(CLASSICS_CONFIG, "UC Berkeley Classics (AGRS) Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
