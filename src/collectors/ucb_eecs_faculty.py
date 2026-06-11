"""Collector for UC Berkeley EECS faculty research opportunities.

A department config + bespoke card parser over src.collectors.ucb_common.
The EECS directory is not an Open-Berkeley Drupal site (unlike Statistics),
so the listing parser is local; fetching, keyword/skill inference,
normalization, and the merge path (including the cross-UCB joint-appointment
dedup) all come from ucb_common.

Unlike the Open-Berkeley departments there is no per-profile enrichment hop:
Berkeley's EECS directory lists each faculty member's email AND
research-interest tags inline, so a single page fetch yields everything.

Directory page (current EECS faculty, names + email + research areas inline):
    https://www2.eecs.berkeley.edu/Faculty/Lists/faculty.html
Each entry links to a profile at /Faculty/Homepages/<lastname>.html .

Usage:
    python -m src.collectors.ucb_eecs_faculty            # fetch & preview
    python -m src.collectors.ucb_eecs_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import NOISE_EMAILS, clean_name, fetch_soup, normalize_faculty

logger = logging.getLogger(__name__)

# The directory tags each professor with curated umbrella research areas from
# a fixed ~22-tag vocabulary. Substring-matching those tags against the
# generic KEYWORD_BANK recovered only 10 distinct keywords and left ~30% of
# records on the bare department fallback, so each tag maps explicitly to the
# topical keywords its area covers. Keys are the tag names lowercased with the
# trailing "(ACRONYM)" stripped (see ucb_common._normalize_area_tag).
EECS_AREA_KEYWORDS = {
    "artificial intelligence": ["artificial intelligence", "machine learning"],
    "biosystems & computational biology": ["computational biology", "bioinformatics"],
    "computer architecture & engineering": ["computer architecture", "parallel computing"],
    "control, intelligent systems, and robotics": ["robotics", "control systems",
                                                   "autonomous systems"],
    "cyber-physical systems and design automation": ["cyber-physical systems",
                                                     "embedded systems",
                                                     "design automation"],
    "database management systems": ["databases", "data management"],
    "design, modeling and analysis": ["systems modeling", "simulation"],
    "education": ["computer science education"],
    "graphics": ["computer graphics"],
    "human-computer interaction": ["human-computer interaction"],
    "information, data, network, and communication sciences": ["information theory",
                                                               "communications",
                                                               "networking"],
    "integrated circuits": ["integrated circuits", "circuits"],
    "micro/nano electro mechanical systems": ["microelectromechanical systems",
                                              "nanotechnology"],
    "operating systems & networking": ["operating systems", "networking",
                                       "distributed systems"],
    "physical electronics": ["nanotechnology", "photonics", "materials science"],
    "power and energy": ["power systems", "renewable energy"],
    "programming systems": ["programming languages", "compilers"],
    "scientific computing": ["scientific computing", "high performance computing"],
    "security": ["security", "cybersecurity"],
    "signal processing": ["signal processing"],
    "theory": ["algorithms", "theoretical computer science"],
}

EECS_CONFIG = {
    "source": "ucb_eecs_faculty",
    "name": "Electrical Engineering and Computer Sciences",
    "short": "EECS",
    "url": "https://www2.eecs.berkeley.edu/Faculty/Lists/faculty.html",
    "base": "https://www2.eecs.berkeley.edu",
    "majors": ["EECS", "Electrical Engineering", "Computer Science",
               "Computer Engineering"],
    # Broad field used only as the honest fallback when a professor lists no
    # parseable research areas (never injected on top of real ones).
    "keywords": ["electrical engineering and computer sciences"],
    "area_keywords": EECS_AREA_KEYWORDS,
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
}


def _scrape_eecs_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the EECS directory into [{name, url, email, title, research_areas}].

    Berkeley-specific markup (verified against the live page): each faculty
    member is a `div.cc-image-list__item__content` containing an `h3 > a`
    (name + profile link), a `<p>` whose first `<strong>` is the rank, an
    inline email address, and one or more `a[href*='/Research/Areas/']` tags.
    """
    faculty: list[dict] = []
    for block in soup.select("div.cc-image-list__item__content"):
        name_el = block.select_one("h3 a[href*='/Faculty/Homepages/']")
        if not name_el:
            continue
        name = clean_name(name_el.get_text(strip=True))
        if not name or len(name) < 3:
            continue

        person: dict = {"name": name, "url": urljoin(base, name_el.get("href", ""))}

        p = block.find("p")
        p_text = p.get_text(" ", strip=True) if p else ""

        # Title: first <strong> that isn't a "Label:" header (e.g. "Professor").
        if p:
            for strong in p.find_all("strong"):
                t = strong.get_text(strip=True)
                if t and not t.endswith(":"):
                    person["title"] = t
                    break

        # Email: inline in the <p>; keep only Berkeley addresses.
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", p_text)
        berkeley = [e for e in emails
                    if e.lower().endswith("berkeley.edu")
                    and e.lower() not in NOISE_EMAILS]
        if berkeley:
            person["email"] = berkeley[0]

        # Research areas: the linked topic tags.
        areas = [a.get_text(strip=True)
                 for a in (p.select("a[href*='/Research/Areas/']") if p else [])]
        if areas:
            person["research_areas"] = "; ".join(areas)

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} EECS faculty")
    return faculty


def fetch_and_normalize() -> list[dict]:
    """Scrape EECS faculty and return normalized opportunity records."""
    soup = fetch_soup(EECS_CONFIG["url"])
    if not soup:
        return []
    raw = _scrape_eecs_faculty_list(soup, EECS_CONFIG["base"])
    normalized = [n for n in (normalize_faculty(p, EECS_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} EECS faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(EECS_CONFIG, "UC Berkeley EECS Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize())
