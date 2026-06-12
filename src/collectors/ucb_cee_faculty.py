"""Collector for UC Berkeley Civil and Environmental Engineering faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_eecs_faculty (a non-Open-Berkeley directory
that needs a local parser but reuses fetching, dedup, normalization, and the
merge path from ucb_common).

CEE is a hybrid: the faculty listing is a 3-column grid where each professor is
a `span.views-field-field-faculty-info` carrying name + profile link + rank AND
inline "Research Interests:" text — but NOT the email. So the listing parser
captures the research interests directly, and the shared per-profile enrichment
hop is used only to recover the contact email (a mailto: link on each profile).

Because the listing already supplies research_areas, CEE_CONFIG sets no
`research_interests` profile selectors — enrich therefore never overwrites the
listing-derived interests. Records with no email found ship "lite"
(contact_email=None, confidence_score=0.5).

CEE research interests are domain-specific (e.g. "earthquake ground motions")
and rarely match the shared KEYWORD_BANK, so most records carry the broad
department keyword; the full interest text is preserved in the description and
metadata.research_areas_raw for matching/display.

Directory: https://ce.berkeley.edu/people/faculty
Each entry links to a profile at /people/faculty/<slug>.

Usage:
    python -m src.collectors.ucb_cee_faculty            # fetch & preview
    python -m src.collectors.ucb_cee_faculty --no-enrich  # skip email hop (fast)
    python -m src.collectors.ucb_cee_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    clean_name,
    dedup_by_profile_url,
    enrich_faculty_from_profiles,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

CEE_CONFIG = {
    "source": "ucb_cee_faculty",
    "name": "Civil and Environmental Engineering",
    "short": "CEE",
    "url": "https://ce.berkeley.edu/people/faculty",
    "base": "https://ce.berkeley.edu",
    "majors": ["Civil Engineering", "Environmental Engineering",
               "Civil & Environmental Engineering"],
    # Broad fallback used only when a professor lists no parseable interests.
    "keywords": ["civil and environmental engineering"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    # No selectors: the listing parser below is bespoke, and leaving
    # research_interests unset means the email-enrichment hop won't overwrite
    # the research interests already captured from the listing.
    "selectors": {},
}


def _scrape_cee_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the CEE directory into [{name, url, title, research_areas}].

    Berkeley-specific markup (verified against the live page): a 3-column grid
    where each faculty member is a `span.views-field-field-faculty-info`
    containing a `span.h4 > a[href*='/people/']` (name + profile link), one or
    more `span.bold` (the first non-label one is the rank; a later
    "Research Interests:" label precedes the interest text in its parent block).
    Email is not on the listing — the profile-enrichment hop recovers it.
    """
    faculty: list[dict] = []
    for card in soup.select("span.views-field-field-faculty-info"):
        name_el = card.select_one("span.h4 a[href*='/people/']")
        if not name_el:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        person: dict = {"name": name, "url": urljoin(base, name_el.get("href", ""))}

        # Title: the first <span class="bold"> that isn't a "Label:" header.
        for bold in card.select("span.bold"):
            t = bold.get_text(strip=True)
            if t and not t.endswith(":"):
                person["title"] = t
                break

        # Research interests: text following the "Research Interests:" label,
        # which lives in the same parent block as the label span.
        for bold in card.select("span.bold"):
            if bold.get_text(strip=True).lower().startswith("research interest"):
                full = bold.parent.get_text(" ", strip=True)
                interests = full.split(":", 1)[1].strip() if ":" in full else ""
                if interests:
                    person["research_areas"] = interests
                break

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} CEE faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape CEE faculty and return normalized opportunity records.

    The listing supplies name + link + title + research interests; with
    enrich=True (default) each profile page is visited to recover the contact
    email (a mailto: link the listing omits).
    """
    soup = fetch_soup(CEE_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_cee_faculty_list(soup, CEE_CONFIG["base"]))
    if enrich:
        raw = enrich_faculty_from_profiles(raw, CEE_CONFIG)
    normalized = [n for n in (normalize_faculty(p, CEE_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} CEE faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(CEE_CONFIG, "UC Berkeley CEE Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
