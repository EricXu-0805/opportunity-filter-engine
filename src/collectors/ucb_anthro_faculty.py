"""Collector for UC Berkeley Anthropology faculty research opportunities.

A department config + bespoke parser over src.collectors.ucb_common.

The Anthropology directory splits faculty across two alphabetical landing pages
(A-J: /people/faculty-j, K-Z: /faculty-k-z). Each faculty member is a
`div.field-name-field-basic-text-text` block: a name `<a>` linking to a profile
(/<name-slug>), the rank, comma-separated subfield areas, an office, and an
"EMAIL:" address — all inline, so no profile hop is needed.

Records with no email ship "lite"; emeritus faculty are on separate pages.

Directories:
    https://anthropology.berkeley.edu/people/faculty-j   (A-J)
    https://anthropology.berkeley.edu/faculty-k-z        (K-Z)

Usage:
    python -m src.collectors.ucb_anthro_faculty            # fetch & preview
    python -m src.collectors.ucb_anthro_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    EMAIL_RE,
    NOISE_EMAILS,
    clean_name,
    dedup_by_profile_url,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

_RANK_RE = re.compile(
    r"((?:Assistant |Associate |Adjunct |Visiting )?Professor(?: Emerit\w+)?|Lecturer|Researcher)",
    re.IGNORECASE,
)
# Profile links are a bare /<name-slug> on the same host.
_PROFILE_HREF_RE = re.compile(r"/[a-z]+-[a-z-]+$")

ANTHRO_CONFIG = {
    "source": "ucb_anthro_faculty",
    "name": "Department of Anthropology",
    "short": "ANTHRO",
    "url": "https://anthropology.berkeley.edu/people/faculty-j",
    "base": "https://anthropology.berkeley.edu",
    "majors": ["Anthropology"],
    "keywords": ["anthropology"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}

# Both alphabetical halves of the faculty directory.
_FACULTY_URLS = [
    "https://anthropology.berkeley.edu/people/faculty-j",
    "https://anthropology.berkeley.edu/faculty-k-z",
]


def _scrape_anthro_page(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse one Anthropology landing page into [{name, url, title, email, research_areas}].

    Each faculty member is a `div.field-name-field-basic-text-text` block whose
    name `<a>` links to a `/<name-slug>` profile; the block text carries the
    rank, subfield areas (before "OFFICE:"), and an "EMAIL:" address.
    """
    faculty: list[dict] = []
    for block in soup.select("div.field-name-field-basic-text-text"):
        name_link = block.find("a", href=_PROFILE_HREF_RE)
        if not name_link:
            continue
        name = clean_name(name_link.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        text = block.get_text(" ", strip=True)
        person: dict = {"name": name, "url": urljoin(base, name_link.get("href", ""))}

        rank = _RANK_RE.search(text)
        if rank:
            person["title"] = rank.group(1)

        match = EMAIL_RE.search(text)
        if match and match.group(0).lower() not in NOISE_EMAILS:
            person["email"] = match.group(0).lower()

        # Research: subfield areas sit before "OFFICE:"/"EMAIL:"; strip the name
        # and rank that precede them.
        pre = re.split(r"OFFICE:|EMAIL:", text)[0].replace(name, "", 1)
        if rank:
            pre = pre.replace(rank.group(1), "", 1)
        pre = re.sub(r"^[\s,;|\xa0]+", "", pre).strip(" ,;|\xa0")
        if pre and len(pre) > 4:
            person["research_areas"] = pre[:300]

        faculty.append(person)
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape both Anthropology faculty pages and return normalized records.

    Name + title + email + research come from the listing pages, so the
    ``enrich`` flag is accepted (for the shared CLI) but there is no profile hop.
    """
    raw: list[dict] = []
    for url in _FACULTY_URLS:
        soup = fetch_soup(url)
        if not soup:
            continue
        page = _scrape_anthro_page(soup, ANTHRO_CONFIG["base"])
        logger.info(f"  {url.rsplit('/', 1)[-1]}: {len(page)} faculty")
        raw.extend(page)
    raw = dedup_by_profile_url(raw)
    normalized = [n for n in (normalize_faculty(p, ANTHRO_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} ANTHRO faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(ANTHRO_CONFIG, "UC Berkeley Anthropology Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
