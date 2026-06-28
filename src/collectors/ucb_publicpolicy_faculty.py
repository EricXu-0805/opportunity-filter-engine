"""Collector for UC Berkeley Goldman School of Public Policy faculty.

A department config + bespoke listing parser over ``src.collectors.ucb_common``.

The Goldman directory (https://gspp.berkeley.edu/research-and-impact/faculty) is
a newer theme — a grid of ``div.directory__list-person`` cards. Each card has the
clean name in an ``<h3>`` and the title in ``<p class="title">``; the profile
link wraps the card. The listing exposes no personal email (only a school comms
mailbox), and profiles are JS-rendered, so records ship "lite" (no email,
confidence 0.5) — the profile link is the cold-email entry point.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import clean_name, dedup_by_profile_url, fetch_soup, normalize_faculty

logger = logging.getLogger(__name__)

PUBLICPOLICY_CONFIG = {
    "source": "ucb_publicpolicy_faculty",
    "name": "Goldman School of Public Policy",
    "short": "GSPP",
    "url": "https://gspp.berkeley.edu/research-and-impact/faculty",
    "base": "https://gspp.berkeley.edu",
    "majors": ["Public Policy"],
    "keywords": ["public policy"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_gspp_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Goldman directory into [{name, url, title}].

    Each faculty member is a ``div.directory__list-person`` card: name in
    ``<h3>``, title in ``<p class="title">``, profile link on the wrapping ``<a>``.
    """
    faculty: list[dict] = []
    for card in soup.select("div.directory__list-person"):
        h3 = card.select_one("h3")
        link = card.select_one("a[href]")
        if not h3 or not link:
            continue
        name = clean_name(h3.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue
        person: dict = {"name": name, "url": urljoin(base, href)}
        title_el = card.select_one("p.title")
        if title_el:
            person["title"] = title_el.get_text(" ", strip=True)
        faculty.append(person)
    logger.info(f"  Found {len(faculty)} Goldman (GSPP) faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Goldman School faculty and return normalized opportunity records.

    ``enrich`` is accepted for interface parity but unused: the listing has no
    personal email and profiles are JS-rendered, so records ship "lite".
    """
    soup = fetch_soup(PUBLICPOLICY_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_gspp_faculty_list(soup, PUBLICPOLICY_CONFIG["base"]))
    normalized = [n for n in (normalize_faculty(p, PUBLICPOLICY_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Goldman (GSPP) faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(PUBLICPOLICY_CONFIG, "UC Berkeley Goldman Public Policy Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
