"""Collector for UC Berkeley Economics faculty research opportunities.

A department config + bespoke parser over src.collectors.ucb_common.

The Economics directory (econ.berkeley.edu/faculty) is a Drupal teaser listing,
not an Open-Berkeley card grid: each faculty member is a
`div.views-row > div.profile.teaser` with the name in `div.display-name a`
(formatted "Last, First" — reformatted here to "First Last"), the rank in
`div.display-position`, and a `/profile/<slug>` link. The profile is a
field-labeled page where values sit in `.field_value` elements preceded by a
label ("Email:", "Fields:", "Research:"). This collector reads the mailto:
email and joins the "Fields" + "Research" values for keywords.

Records with no email ship "lite" (contact_email=None, confidence_score=0.5);
emeritus faculty are dropped by the shared title filter.

Directory: https://www.econ.berkeley.edu/faculty

Usage:
    python -m src.collectors.ucb_econ_faculty            # fetch & preview
    python -m src.collectors.ucb_econ_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_econ_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    clean_name,
    dedup_by_profile_url,
    extract_email_from_profile,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

PROFILE_DELAY = ucb_common.PROFILE_DELAY

ECON_CONFIG = {
    "source": "ucb_econ_faculty",
    "name": "Department of Economics",
    "short": "ECON",
    "url": "https://www.econ.berkeley.edu/faculty",
    "base": "https://www.econ.berkeley.edu",
    "majors": ["Economics"],
    "keywords": ["economics"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _reformat_name(name: str) -> str:
    """Econ lists names as "Last, First" — reorder to "First Last"."""
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return clean_name(name)


def _scrape_econ_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Economics teaser listing into [{name, url, title}].

    Each faculty member is a `div.profile.teaser` with the name in
    `div.display-name a` ("Last, First") and the rank in `div.display-position`.
    """
    faculty: list[dict] = []
    for teaser in soup.select("div.profile.teaser"):
        name_el = teaser.select_one("div.display-name a")
        if not name_el:
            continue
        name = _reformat_name(name_el.get_text(" ", strip=True))
        href = name_el.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}
        pos = teaser.select_one("div.display-position")
        if pos and pos.get_text(strip=True):
            person["title"] = pos.get_text(" ", strip=True)
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} ECON faculty")
    return faculty


def _research_from_profile(soup: BeautifulSoup) -> str:
    """Join the profile's "Fields" + "Research" field values.

    Each value sits in a `.field_value` preceded by a label element; we keep the
    values whose label starts with "Fields" or "Research".
    """
    parts: list[str] = []
    for value in soup.select(".field_value"):
        label_el = value.find_previous(class_=re.compile("label", re.IGNORECASE))
        label = label_el.get_text(" ", strip=True) if label_el else ""
        if re.match(r"(Fields|Research)", label, re.IGNORECASE):
            text = value.get_text(" ", strip=True)
            if text:
                parts.append(text)
    return "; ".join(dict.fromkeys(parts))


def _enrich_econ_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the mailto: email and the Fields/Research values."""
    import time
    total = len(faculty)
    found = with_research = 0
    for i, person in enumerate(faculty):
        url = person.get("url")
        if not url:
            continue
        soup = fetch_soup(url)
        if soup:
            email = extract_email_from_profile(soup, config)
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
    """Scrape Economics faculty and return normalized opportunity records.

    The listing gives name + link + rank; with enrich=True (default) each
    profile is visited to recover the contact email and Fields/Research values.
    """
    soup = fetch_soup(ECON_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_econ_faculty_list(soup, ECON_CONFIG["base"]))
    if enrich:
        raw = _enrich_econ_profiles(raw, ECON_CONFIG)
    normalized = [n for n in (normalize_faculty(p, ECON_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} ECON faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(ECON_CONFIG, "UC Berkeley Economics Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
