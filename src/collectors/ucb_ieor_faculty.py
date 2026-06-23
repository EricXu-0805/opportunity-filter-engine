"""Collector for UC Berkeley Industrial Engineering & Operations Research (IEOR).

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_cee_faculty / ucb_eecs_faculty.

The IEOR department site is a Beaver Builder "callout" grid: each faculty member
is a `div.fl-callout` whose `h2.fl-callout-title a` is the name + profile link
(`/people/<slug>/`) and whose `div.fl-callout-text` holds the rank. The listing
exposes neither email nor research interests.

Enrichment quirk — why a bespoke profile hop instead of the shared one: every
IEOR profile page renders the same footer/admin addresses (e.g.
ieor-student-services@berkeley.edu) in its markup, so the shared
extract_email_from_profile's page-wide scan would attach a wrong address to any
professor who lists none. A real faculty email here appears only as a mailto:
link or an "(at)"-obfuscated address, so this collector reads email from those
ONLY. Research interests live in a Beaver Builder "Research" accordion present
on every profile (with the older `div.group-faculty-research` field as a
fallback). Records with no email found ship "lite" (contact_email=None,
confidence_score=0.5, broad department keyword).

Directory: https://ieor.berkeley.edu/people/faculty/

Usage:
    python -m src.collectors.ucb_ieor_faculty            # fetch & preview
    python -m src.collectors.ucb_ieor_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_ieor_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    EMAIL_RE,
    NOISE_EMAILS,
    PROFILE_DELAY,
    clean_name,
    dedup_by_profile_url,
    extract_research_interests,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

# IEOR obfuscates faculty emails against scrapers, e.g. "ilan(at)berkeley.edu"
# or "candiyano (at) berkeley.edu". Match only tokens containing "(at)" so the
# literal footer/admin addresses on every page are never mistaken for a
# professor's contact.
_OBFUSCATED_EMAIL_RE = re.compile(
    r"[\w.+-]+\s*\(\s*at\s*\)\s*[\w.+\-()\s]+?\.[a-z]{2,}", re.IGNORECASE
)


def _deobfuscate_email(token: str) -> str:
    addr = re.sub(r"\s*\(\s*at\s*\)\s*", "@", token, flags=re.IGNORECASE)
    addr = re.sub(r"\s*\(\s*dot\s*\)\s*", ".", addr, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", addr).lower()


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Recover a faculty email: a mailto: link first, then the (at)-obfuscated
    address IEOR publishes in its "E-mail:" line. Skips shared/admin mailboxes.
    """
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if addr and addr not in NOISE_EMAILS:
            return addr
    for token in _OBFUSCATED_EMAIL_RE.findall(soup.get_text(" ", strip=True)):
        addr = _deobfuscate_email(token)
        if EMAIL_RE.fullmatch(addr) and addr not in NOISE_EMAILS:
            return addr
    return None

IEOR_CONFIG = {
    "source": "ucb_ieor_faculty",
    "name": "Industrial Engineering & Operations Research",
    "short": "IEOR",
    "url": "https://ieor.berkeley.edu/people/faculty/",
    "base": "https://ieor.berkeley.edu",
    "majors": ["Industrial Engineering", "Operations Research",
               "Industrial Engineering & Operations Research"],
    # Broad fallback: IEOR's research signal is sparse, so most records use it.
    "keywords": ["operations research"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    # Fallback research field (older profiles); the "Research" accordion below
    # is the primary, present-on-every-profile source.
    "selectors": {
        "research_interests": ["div.group-faculty-research"],
    },
}


def _research_from_profile(soup: BeautifulSoup, config: dict) -> str:
    """Recover research interests from the profile.

    Every IEOR profile carries a Beaver Builder "Research" accordion (distinct
    from the "Publications" one); its content panel is the primary source. Falls
    back to the older `div.group-faculty-research` field. A leading
    "Research Areas:" label, when present, is stripped.
    """
    for button in soup.select("a.fl-accordion-button-label, .fl-accordion-button"):
        label = button.get_text(" ", strip=True)
        if re.search(r"\bResearch\b", label, re.IGNORECASE) and "Publication" not in label:
            item = button.find_parent(class_=re.compile("fl-accordion-item"))
            content = item.select_one(".fl-accordion-content") if item else None
            if content:
                text = content.get_text(" ", strip=True)
                return re.sub(r"^\s*Research Areas?\s*:?\s*", "", text, flags=re.IGNORECASE)
            break
    return extract_research_interests(soup, config)


def _scrape_ieor_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the IEOR directory into [{name, url, title}].

    Each faculty member is a `div.fl-callout` with the name + profile link in
    `h2.fl-callout-title a[href*='/people/']` and the rank on the first line of
    `div.fl-callout-text`. Callouts without a /people/ link (section blurbs) are
    skipped by the selector. Email/research are not on the listing.
    """
    faculty: list[dict] = []
    for card in soup.select("div.fl-callout"):
        name_el = card.select_one("h2.fl-callout-title a[href*='/people/']")
        if not name_el:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        href = name_el.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        text_el = card.select_one("div.fl-callout-text")
        if text_el:
            # Rank is the first line; later lines are advising roles ("Head MEng
            # Advisor") we don't want in the title.
            first_line = text_el.get_text("\n", strip=True).split("\n")[0].strip()
            if first_line:
                person["title"] = first_line

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} IEOR faculty")
    return faculty


def _enrich_ieor_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for a mailto: email and the research field.

    Mailto-only by design (see module docstring): the page-wide email scan the
    shared enricher falls back to would pick up IEOR's footer/admin addresses.
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
            interests = _research_from_profile(soup, config)
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
    """Scrape IEOR faculty and return normalized opportunity records.

    The listing supplies name + link + title; with enrich=True (default) each
    profile page is visited to recover a mailto: email and research interests.
    """
    soup = fetch_soup(IEOR_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_ieor_faculty_list(soup, IEOR_CONFIG["base"]))
    if enrich:
        raw = _enrich_ieor_profiles(raw, IEOR_CONFIG)
    normalized = [n for n in (normalize_faculty(p, IEOR_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} IEOR faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(IEOR_CONFIG, "UC Berkeley IEOR Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
