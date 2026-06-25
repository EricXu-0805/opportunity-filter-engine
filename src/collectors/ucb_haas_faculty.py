"""Collector for UC Berkeley Haas School of Business faculty.

A department config + bespoke paginated listing parser over
src.collectors.ucb_common.

The Haas faculty directory (haas.berkeley.edu/faculty) is a WordPress
`faculty_bio` archive of `.faculty-info-block` cards, paginated 35 per page over
`/faculty/page/N/`. Each card sits inside an `<a>` to the profile and holds the
name in `h2.title`, the rank in a `<strong>`, and the academic area(s) (Finance,
Marketing, ...) as the trailing text — a curated research signal right on the
listing.

Two scope decisions specific to Haas:
- The archive mixes ~340 entries, mostly "Professional Faculty" / "Continuing
  Professional Faculty" / lecturers (practitioners). For a research-matching
  tool we keep only ladder/teaching faculty — titles containing the word
  "Professor" (this excludes "Professional Faculty" and "Lecturer"); emeritus
  faculty are then dropped by the shared title filter.
- Haas does not publish faculty emails anywhere (no mailto on the profiles), so
  every record ships "lite" (contact_email=None, confidence_score=0.5) but
  carries area-derived keywords. The area maps to keywords via area_keywords
  (config-local), so no generic business words pollute the shared KEYWORD_BANK.

Directory: https://haas.berkeley.edu/faculty/  (paginated /faculty/page/N/)

Usage:
    python -m src.collectors.ucb_haas_faculty            # fetch & preview
    python -m src.collectors.ucb_haas_faculty --save     # merge into processed data
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
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 14  # safety bound; the archive is ~10 pages
# Keep ladder/teaching faculty only; "Professional Faculty" and "Lecturer" do
# not contain the word "professor", so this excludes them.
_FACULTY_TITLE_RE = re.compile(r"\bprofessor\b", re.IGNORECASE)

HAAS_CONFIG = {
    "source": "ucb_haas_faculty",
    "name": "Haas School of Business",
    "short": "HAAS",
    "url": "https://haas.berkeley.edu/faculty/",
    "base": "https://haas.berkeley.edu",
    "majors": ["Business Administration", "Business"],
    "keywords": ["business"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
    # The listing tags each professor with one or more academic areas (a
    # controlled vocabulary). Mapping them explicitly keeps generic business
    # words ("finance", "management") out of the shared KEYWORD_BANK.
    "area_keywords": {
        "management of organizations": ["organizational behavior", "management"],
        "finance": ["finance", "corporate finance"],
        "economic analysis & policy": ["economics", "business economics"],
        "marketing": ["marketing", "consumer behavior"],
        "business & public policy": ["business and public policy"],
        "accounting": ["accounting", "financial reporting"],
        "real estate": ["real estate"],
        "operations & it management": ["operations management", "information systems"],
        "entrepreneurship & innovation": ["entrepreneurship", "innovation"],
        "innovation & design": ["innovation", "design thinking"],
        "energy institute": ["energy economics"],
        "fintech": ["fintech"],
        "business & social impact": ["social impact"],
        "responsible business": ["corporate social responsibility"],
        "graduate program in health management": ["health management"],
        "center for financial reporting & management": ["financial reporting"],
        "garwood center for corporate innovation": ["corporate innovation"],
        "center for social sector leadership": ["nonprofit management"],
        "sustainability": ["sustainability"],
    },
}


def _scrape_haas_page(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse one archive page into [{name, url, title, research_areas}].

    Each person is a `.faculty-info-block` inside a profile `<a>`; the name is in
    `h2`, the rank in a `<strong>`, and the academic area(s) the trailing text.
    Only titles naming a Professor are kept (professional faculty / lecturers /
    staff are skipped). Areas are "; "-joined so area_keywords can map each.
    """
    out: list[dict] = []
    for block in soup.select(".faculty-info-block"):
        anchor = block.find_parent("a") or block.find("a")
        name_el = block.select_one("h2")
        if not anchor or not name_el:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        href = anchor.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        para = block.select_one(".block-content p")
        strong = para.select_one("strong") if para else None
        title = strong.get_text(" ", strip=True) if strong else ""
        if not _FACULTY_TITLE_RE.search(title):
            continue  # professional faculty / lecturer / staff

        person: dict = {"name": name, "url": urljoin(base, href), "title": title}
        parts = list(para.stripped_strings) if para else []
        if len(parts) > 1:
            # The area line follows the rank; split multi-area " | " into ";"
            # so area_keywords maps each one.
            person["research_areas"] = parts[-1].replace("|", ";")
        out.append(person)
    return out


def _scrape_haas_faculty() -> list[dict]:
    """Page through the archive, collecting professor cards until a page yields
    none (or the safety bound is hit)."""
    faculty: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        url = HAAS_CONFIG["url"] if page == 1 else f"{HAAS_CONFIG['url']}page/{page}/"
        soup = fetch_soup(url)
        if not soup:
            break
        rows = _scrape_haas_page(soup, HAAS_CONFIG["base"])
        if not rows and page > 1:
            break
        faculty.extend(rows)
        logger.info(f"  page {page}: {len(rows)} professors")
    logger.info(f"  {len(faculty)} Haas professors across pages")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Haas ladder/teaching faculty and return normalized records.

    The listing carries name + title + academic area; Haas publishes no emails,
    so every record ships "lite". `enrich` is accepted for CLI parity but unused.
    """
    raw = dedup_by_profile_url(_scrape_haas_faculty())
    if not raw:
        return []
    normalized = [n for n in (normalize_faculty(p, HAAS_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Haas faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(HAAS_CONFIG, "UC Berkeley Haas Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
