"""Collector for UC Berkeley Architecture (College of Environmental Design) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_journalism_faculty / ucb_history_faculty.

The Architecture people page (ced.berkeley.edu/academics/architecture/people) is
a WordPress directory where each person is an `a[href=/people/<slug>]` wrapping a
`.people-listing` photo and a body with the name in a `div.font-bold` and the
title in the following div. The page mixes professors, lecturers, PhD students,
advisors, and staff, so the collector keeps only entries whose title names a
Professor or Lecturer (emeritus faculty are then dropped by the shared title
filter).

The listing has no email, so profiles are visited to recover the personal email
(first mailto:) and the curated "SPECIALIZATIONS" field — a short research-area
phrase laid out as a label column whose value lives in the sibling div. The
biography body is deliberately ignored (its long prose trips unrelated
KEYWORD_BANK terms, as seen with the School of Education). Records with no email
ship "lite" (contact_email=None, confidence_score=0.5).

Directory: https://ced.berkeley.edu/academics/architecture/people

Usage:
    python -m src.collectors.ucb_arch_faculty            # fetch & preview
    python -m src.collectors.ucb_arch_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_arch_faculty --save     # merge into processed data
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

ARCH_CONFIG = {
    "source": "ucb_arch_faculty",
    "name": "Architecture (College of Environmental Design)",
    "short": "ARCH",
    "url": "https://ced.berkeley.edu/academics/architecture/people",
    "base": "https://ced.berkeley.edu",
    "majors": ["Architecture", "Environmental Design"],
    "keywords": ["architecture"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_arch_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Architecture people page into [{name, url, title}].

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

    logger.info(f"  Found {len(faculty)} Architecture faculty")
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


def _enrich_arch_profiles(faculty: list[dict], config: dict) -> list[dict]:
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
    """Scrape Architecture faculty and return normalized opportunity records.

    The listing supplies name + link + title; with enrich=True (default) each
    profile is visited to recover the personal email and specializations.
    """
    soup = fetch_soup(ARCH_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_arch_faculty_list(soup, ARCH_CONFIG["base"]))
    if enrich:
        raw = _enrich_arch_profiles(raw, ARCH_CONFIG)
    normalized = [n for n in (normalize_faculty(p, ARCH_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Architecture faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(ARCH_CONFIG, "UC Berkeley Architecture Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
