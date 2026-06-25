"""Collector for UC Berkeley School of Public Health (SPH) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_ieor_faculty / ucb_cee_faculty.

The SPH faculty directory (https://publichealth.berkeley.edu/faculty) is a
server-rendered UIkit grid: each faculty member is an `a.uk-link-toggle` whose
href is the profile URL (`/people/<slug>`), with the name in a
`span.bph-text-serif` and the rank/department in a `span.uk-text-small`. The
listing exposes neither email nor research interests.

Enrichment: each profile page carries the professor's personal email as the
first `mailto:` link (the school-wide `publichealth@berkeley.edu` contact mailbox
appears as a second mailto and is filtered via NOISE_EMAILS), and lists research
interests under a "Research Interests" heading followed by a `<ul>`. Records with
no email found ship "lite" (contact_email=None, confidence_score=0.5).

Directory: https://publichealth.berkeley.edu/faculty

Usage:
    python -m src.collectors.ucb_sph_faculty            # fetch & preview
    python -m src.collectors.ucb_sph_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_sph_faculty --save     # merge into processed data
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

SPH_CONFIG = {
    "source": "ucb_sph_faculty",
    "name": "Public Health",
    "short": "SPH",
    "url": "https://publichealth.berkeley.edu/faculty",
    "base": "https://publichealth.berkeley.edu",
    "majors": ["Public Health", "Epidemiology", "Biostatistics",
               "Environmental Health Sciences", "Health Policy"],
    # Broad fallback for records with no recoverable research signal.
    "keywords": ["public health"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_sph_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the SPH directory into [{name, url, title}].

    Each faculty member is an `a.uk-link-toggle[href*='/people/']` with the name
    in `span.bph-text-serif` and the rank/department in `span.uk-text-small`.
    Email/research are not on the listing.
    """
    faculty: list[dict] = []
    for a in soup.select("a.uk-link-toggle[href*='/people/']"):
        href = a.get("href", "")
        name_el = a.select_one("span.bph-text-serif")
        if not name_el or not href:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        title_el = a.select_one("span.uk-text-small")
        if title_el:
            title = title_el.get_text(" ", strip=True)
            if title:
                person["title"] = title

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} SPH faculty")
    return faculty


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Return the professor's personal email: the first mailto: that is not the
    school-wide contact mailbox (NOISE_EMAILS)."""
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if addr and addr not in NOISE_EMAILS:
            return addr
    return None


def _research_from_profile(soup: BeautifulSoup) -> str:
    """Return research interests from the "Research Interests" section.

    The heading is an <h2>/<h3> whose text is "Research Interests"; the content
    is the immediately following list (`<ul>`) of interest items, joined into a
    comma-separated string. Returns "" when the section is absent.
    """
    for heading in soup.find_all(re.compile(r"^h[2-4]$")):
        if heading.get_text(" ", strip=True).lower() != "research interests":
            continue
        node = heading.find_next_sibling()
        while node is not None and not node.get_text(strip=True):
            node = node.find_next_sibling()
        if node is None:
            return ""
        # The list markup is malformed (the <li>s nest), so li.get_text() bleeds
        # every following item into the first. Take only each <li>'s own direct
        # text nodes to recover one interest per item.
        items = []
        for li in node.select("li"):
            own = " ".join(
                s.strip() for s in li.find_all(string=True, recursive=False)
                if s.strip()
            )
            if own:
                items.append(own)
        if items:
            return ", ".join(items)
        return node.get_text(" ", strip=True)
    return ""


def _enrich_sph_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the personal email and research interests.

    Respectful: a small delay between requests, the shared robust fetcher, and a
    graceful skip when a profile fails to fetch.
    """
    total = len(faculty)
    found = with_interests = 0
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
            interests = _research_from_profile(soup)
            if interests:
                person["research_areas"] = interests[:600]
                with_interests += 1
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(
        f"  Recovered {found}/{total} emails and {with_interests}/{total} "
        f"research-interest sections from profile pages"
    )
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape SPH faculty and return normalized opportunity records.

    The listing supplies name + link + title; with enrich=True (default) each
    profile page is visited to recover the personal email and research interests.
    """
    soup = fetch_soup(SPH_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_sph_faculty_list(soup, SPH_CONFIG["base"]))
    if enrich:
        raw = _enrich_sph_profiles(raw, SPH_CONFIG)
    normalized = [n for n in (normalize_faculty(p, SPH_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} SPH faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(SPH_CONFIG, "UC Berkeley Public Health Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
