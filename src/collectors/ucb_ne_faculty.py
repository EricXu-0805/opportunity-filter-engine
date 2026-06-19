"""Collector for UC Berkeley Nuclear Engineering (NE) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_mse_faculty (a Beaver Builder grid where the
name + profile URL come from each card's `<meta itemprop="mainEntityOfPage">`).

NE profiles need a bespoke enrichment hop for two reasons:
  * Email is obfuscated with SQUARE brackets, e.g. `abergel[at]berkeley.edu`
    (the shared page-wide scan would otherwise grab the shared Student Services
    footer address, jpyon1@berkeley.edu, which appears on every profile). So
    email is read from a mailto: link or de-obfuscated from an `[at]`/`[dot]`
    token only — never a literal page-wide scan.
  * Research lives in a Beaver Builder "Research Interests" accordion (same
    pattern as BioE), recovered from that item's content panel.

The 8 `category-emeritus` cards are skipped. Records with no email found ship
"lite" (contact_email=None, confidence_score=0.5); those with no research keep
the broad department keyword.

Directory: https://nuc.berkeley.edu/faculty/
Each entry links to a profile at /people/<slug>/.

Usage:
    python -m src.collectors.ucb_ne_faculty            # fetch & preview
    python -m src.collectors.ucb_ne_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_ne_faculty --save     # merge into processed data
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
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

# NE obfuscates emails with square brackets, e.g. "abergel[at]berkeley.edu" or
# "bethany[at]nuc.berkeley.edu". Match only `[at]` tokens so the literal-@
# footer/admin address on every profile is never picked up.
_OBFUSCATED_EMAIL_RE = re.compile(
    r"[\w.+-]+\s*\[\s*at\s*\]\s*[\w.\[\]-]+", re.IGNORECASE
)


def _deobfuscate_email(token: str) -> str:
    addr = re.sub(r"\s*\[\s*at\s*\]\s*", "@", token, flags=re.IGNORECASE)
    addr = re.sub(r"\s*\[\s*dot\s*\]\s*", ".", addr, flags=re.IGNORECASE)
    return addr.strip().lower()


NE_CONFIG = {
    "source": "ucb_ne_faculty",
    "name": "Department of Nuclear Engineering",
    "short": "NE",
    "url": "https://nuc.berkeley.edu/faculty/",
    "base": "https://nuc.berkeley.edu",
    "majors": ["Nuclear Engineering"],
    "keywords": ["nuclear engineering"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_ne_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the NE directory into [{name, url}].

    Each faculty member is a `div.fl-post-grid-post`; the name + profile URL are
    on its `<meta itemprop="mainEntityOfPage">` (there is no heading link).
    `category-emeritus` cards are skipped.
    """
    faculty: list[dict] = []
    for card in soup.select("div.fl-post-grid-post"):
        if "category-emeritus" in card.get("class", []):
            continue
        meta = card.find("meta", itemprop="mainEntityOfPage")
        if not meta:
            continue
        name = clean_name(meta.get("content", "") or "")
        url = meta.get("itemid", "")
        if not name or len(name) < 3 or not url:
            continue
        faculty.append({"name": name, "url": urljoin(base, url)})

    logger.info(f"  Found {len(faculty)} NE faculty")
    return faculty


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Recover a faculty email: a mailto: link first, then the `[at]`-obfuscated
    address. Never a literal page-wide scan (that would grab the shared footer
    Student Services address). Skips shared/admin mailboxes.
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


def _research_from_profile(soup: BeautifulSoup) -> str:
    """Pull the lab description from the "Research Interests" accordion.

    NE renders a Beaver Builder accordion whose button label is "Research
    Interests"; the prose is in that item's `.fl-accordion-content`. Returns ""
    when no such accordion is present.
    """
    for button in soup.select("a.fl-accordion-button-label, .fl-accordion-button"):
        if re.search(r"Research Interests", button.get_text(" ", strip=True), re.IGNORECASE):
            item = button.find_parent(class_=re.compile("fl-accordion-item"))
            content = item.select_one(".fl-accordion-content") if item else None
            if content:
                return content.get_text(" ", strip=True)
            break
    return ""


def _enrich_ne_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the contact email ([at]-obfuscated) and research."""
    total = len(faculty)
    found = with_research = 0
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
            research = _research_from_profile(soup)
            if research:
                person["research_areas"] = research[:600]
                with_research += 1
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(
        f"  Recovered {found}/{total} emails and {with_research}/{total} "
        f"research sections from profile pages"
    )
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape NE faculty and return normalized opportunity records.

    The listing supplies name + link; with enrich=True (default) each profile
    page is visited to recover the contact email and research interests.
    """
    soup = fetch_soup(NE_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_ne_faculty_list(soup, NE_CONFIG["base"]))
    if enrich:
        raw = _enrich_ne_profiles(raw, NE_CONFIG)
    normalized = [n for n in (normalize_faculty(p, NE_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} NE faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(NE_CONFIG, "UC Berkeley Nuclear Engineering Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
