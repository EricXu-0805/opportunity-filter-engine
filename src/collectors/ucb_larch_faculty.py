"""Collector for UC Berkeley Landscape Architecture & Environmental Planning (CED).

A department config + bespoke listing parser over src.collectors.ucb_common. The
Landscape Architecture & Environmental Planning (LAEP) people page lives on the
same College of Environmental Design WordPress theme as Architecture and City &
Regional Planning, so the parsing mirrors those collectors: each person is an
`a[href=/people/<slug>]` wrapping a `.people-listing` photo with the name in
`div.font-bold` and the title in the following div. The page mixes professors,
lecturers, PhD students, advisors, and staff, so only entries whose title names a
Professor or Lecturer are kept (emeritus faculty are then dropped by the shared
title filter).

Profiles are visited for the personal email (first mailto:) and the curated
"SPECIALIZATIONS" field (a two-column layout whose label column has its value in
the sibling div). The biography body is ignored (its prose trips unrelated
KEYWORD_BANK terms). Records with no email ship "lite".

Directory: https://ced.berkeley.edu/academics/landscape-architecture-environmental-planning/people

Usage:
    python -m src.collectors.ucb_larch_faculty            # fetch & preview
    python -m src.collectors.ucb_larch_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_larch_faculty --save     # merge into processed data
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

# The people page mixes roles; keep only ladder/teaching faculty. Emeritus
# entries match too but are dropped downstream by the shared title filter.
_FACULTY_TITLE_RE = re.compile(r"\b(professor|lecturer)\b", re.IGNORECASE)

LARCH_CONFIG = {
    "source": "ucb_larch_faculty",
    "name": "Landscape Architecture & Environmental Planning (College of Environmental Design)",
    "short": "LAEP",
    "url": "https://ced.berkeley.edu/academics/landscape-architecture-environmental-planning/people",
    "base": "https://ced.berkeley.edu",
    "majors": ["Landscape Architecture", "Environmental Planning",
               "Landscape Architecture & Environmental Planning"],
    "keywords": ["landscape architecture"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_larch_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the LAEP people page into [{name, url, title}].

    Each person is an `a[href*='/people/']` wrapping a `.people-listing` photo;
    the name is in `div.font-bold` and the title in the following div. Only
    entries whose title names a Professor or Lecturer are kept (PhD students,
    advisors, and staff are skipped). Email/research are not on the listing.
    """
    faculty: list[dict] = []
    for a in soup.select("a[href*='/people/']"):
        if not a.select_one(".people-listing"):
            continue
        name_el = a.select_one("div.font-bold")
        href = a.get("href", "")
        if not name_el or not href:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        title_el = name_el.find_next_sibling()
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if not _FACULTY_TITLE_RE.search(title):
            continue  # PhD student / advisor / staff

        person: dict = {"name": name, "url": urljoin(base, href), "title": title}
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} LAEP faculty")
    return faculty


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Return the first mailto: that is not a shared/admin mailbox."""
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if addr and addr not in NOISE_EMAILS:
            return addr
    return None


def _specializations_from_profile(soup: BeautifulSoup) -> str:
    """Return the curated "SPECIALIZATIONS" research phrase.

    The profile is a two-column layout: the heading sits in a label column whose
    value is the sibling div. Returns "" when the section is absent.
    """
    for heading in soup.find_all(re.compile(r"^h[2-5]$")):
        if "specialization" not in heading.get_text(" ", strip=True).lower():
            continue
        label_col = heading.find_parent("div")
        value_col = label_col.find_next_sibling() if label_col else None
        if value_col is not None:
            return value_col.get_text(" ", strip=True)
        break
    return ""


def _enrich_larch_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the personal email and the SPECIALIZATIONS field.

    Respectful: a small delay between requests, the shared robust fetcher, and a
    graceful skip when a profile fails to fetch.
    """
    total = len(faculty)
    found = with_spec = 0
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
            spec = _specializations_from_profile(soup)
            if spec:
                person["research_areas"] = spec[:600]
                with_spec += 1
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(
        f"  Recovered {found}/{total} emails and {with_spec}/{total} "
        f"specialization fields from profile pages"
    )
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape LAEP faculty and return normalized opportunity records.

    The listing supplies name + link + title; with enrich=True (default) each
    profile is visited to recover the personal email and specializations.
    """
    soup = fetch_soup(LARCH_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_larch_faculty_list(soup, LARCH_CONFIG["base"]))
    if enrich:
        raw = _enrich_larch_profiles(raw, LARCH_CONFIG)
    normalized = [n for n in (normalize_faculty(p, LARCH_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} LAEP faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(LARCH_CONFIG, "UC Berkeley Landscape Architecture & Environmental Planning Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
