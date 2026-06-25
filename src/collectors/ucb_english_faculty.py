"""Collector for UC Berkeley Department of English faculty.

A department config + paginated listing loop over src.collectors.ucb_common,
following the same pagination pattern as ucb_espm_faculty but over Open-Berkeley
person *teaser cards* (not a views-table).

English's `/people/faculty` is a standard Open-Berkeley directory rendered as
`div.node-openberkeley-person` teaser cards (name in `h2 > a`, rank in the
`field-openberkeley-person-title` field), paginated ~10 per page over several
`?page=N` pages. Each profile is an Open-Berkeley person page exposing a mailto:
email (plus the email field) and a free-text biography (`field-name-body`) that
describes the scholar's areas — used here as the research signal in place of the
`resint` field most science departments carry.

Behavior matches the shared path: page through the listing for name + profile
link + title, dedup, then visit each profile via the shared enrichment hop to
recover the email and the biography. Records with no email ship "lite"
(contact_email=None, confidence_score=0.5); emeritus faculty are dropped by the
shared title filter.

Directory: https://english.berkeley.edu/people/faculty  (paginated ?page=N)

Usage:
    python -m src.collectors.ucb_english_faculty            # fetch & preview
    python -m src.collectors.ucb_english_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_english_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging

from . import ucb_common
from .ucb_common import (
    dedup_by_profile_url,
    enrich_faculty_from_profiles,
    fetch_soup,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 12  # safety bound; the directory is ~6 pages

ENGLISH_CONFIG = {
    "source": "ucb_english_faculty",
    "name": "Department of English",
    "short": "ENGL",
    "url": "https://english.berkeley.edu/people/faculty",
    "base": "https://english.berkeley.edu",
    "majors": ["English", "English Literature"],
    "keywords": ["english literature"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        "card": "div.node-openberkeley-person",
        "name": "h2",
        "link": "a[href*='/people/']",
        "title": "div.field-name-field-openberkeley-person-title",
        # Profiles carry both a mailto: link (tried first) and this field.
        "email_field": "div.field-name-field-openberkeley-person-email",
        # English has no resint field; the biography body is the research signal.
        # .field-item drops the "Biography:" label.
        "research_interests": ["div.field-name-body .field-item"],
    },
}


def _scrape_english_faculty() -> list[dict]:
    """Page through the teaser-card directory, collecting name + profile link +
    title until a page yields no cards (or the safety bound is hit)."""
    faculty: list[dict] = []
    for page in range(_MAX_PAGES):
        soup = fetch_soup(f"{ENGLISH_CONFIG['url']}?page={page}")
        if not soup:
            break
        cards = scrape_open_berkeley_faculty(soup, ENGLISH_CONFIG)
        if not cards and page > 0:
            break
        faculty.extend(cards)
        logger.info(f"  page {page}: {len(cards)} faculty")
    logger.info(f"  {len(faculty)} English faculty across pages")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape English faculty (paginated teaser cards) and return normalized records.

    The listing gives name + profile link + title; with enrich=True (default)
    each profile is visited to recover the email and biography.
    """
    raw = dedup_by_profile_url(_scrape_english_faculty())
    if not raw:
        return []
    if enrich:
        raw = enrich_faculty_from_profiles(raw, ENGLISH_CONFIG)
    normalized = [n for n in (normalize_faculty(p, ENGLISH_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} English faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(ENGLISH_CONFIG, "UC Berkeley English Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
