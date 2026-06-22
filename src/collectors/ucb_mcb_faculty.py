"""Collector for UC Berkeley Molecular & Cell Biology (MCB) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common.

MCB's "Faculty Research Descriptions" page (`/faculty/`) is the richest listing
of any Berkeley department: each faculty member is a `<p>` block holding the
name + profile link (`<a><strong>Name</strong></a>` -> /faculty/<div>/<slug>),
the rank/division in a second `<strong>`, and a free-text research description.
So name, title AND research all come from the listing — no profile hop is
needed (and would not help: MCB profiles publish only the department chair's
shared address, `mcbchair@berkeley.edu`, never the individual's). Records are
therefore "lite" (contact_email=None, confidence_score=0.5) but carry topical
keywords from the research description. Emeritus faculty are interspersed in the
alphabetical list with an "Emeritus" title and dropped by the shared title
filter.

Directory: https://mcb.berkeley.edu/faculty/
Each entry links to a profile at /faculty/<division>/<slug>.

Usage:
    python -m src.collectors.ucb_mcb_faculty            # fetch & preview
    python -m src.collectors.ucb_mcb_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import clean_name, dedup_by_profile_url, fetch_soup, normalize_faculty

logger = logging.getLogger(__name__)

# Person profile links are /faculty/<division>/<slug>; the bare /faculty/<div>
# links (e.g. /faculty/bbs) are research-division nav, not people.
_PERSON_HREF_RE = re.compile(r"/faculty/[A-Za-z]+/[A-Za-z]")

MCB_CONFIG = {
    "source": "ucb_mcb_faculty",
    "name": "Department of Molecular & Cell Biology",
    "short": "MCB",
    "url": "https://mcb.berkeley.edu/faculty/",
    "base": "https://mcb.berkeley.edu",
    "majors": ["Molecular & Cell Biology", "Molecular and Cell Biology"],
    "keywords": ["molecular biology"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
}


def _scrape_mcb_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the MCB directory into [{name, url, title, research_areas}].

    Each faculty member is a `<p>` with the name + profile link in
    `<a><strong>Name</strong></a>` (href /faculty/<div>/<slug>), the rank in a
    second `<strong>`, and the research description as the `<p>`'s direct text
    nodes. Emeritus faculty (title says so) are left to the shared title filter.
    """
    faculty: list[dict] = []
    for p in soup.find_all("p"):
        link = p.find("a", href=_PERSON_HREF_RE)
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        # First <strong> is the name (inside the <a>); the second is the rank.
        strongs = p.find_all("strong")
        if len(strongs) > 1:
            title = strongs[1].get_text(" ", strip=True)
            if title:
                person["title"] = title

        # Research description: the <p>'s direct text nodes (the name lives in
        # the <a> and the title in a <strong>, so neither is included here).
        research = " ".join(s.strip() for s in p.find_all(string=True, recursive=False)
                            if s.strip())
        if research:
            person["research_areas"] = research[:600]

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} MCB faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape MCB faculty and return normalized opportunity records.

    Listing-only: name + title + research all come from the directory, and MCB
    profiles expose no individual email, so the ``enrich`` flag is accepted (for
    the shared CLI) but there is no profile hop.
    """
    soup = fetch_soup(MCB_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_mcb_faculty_list(soup, MCB_CONFIG["base"]))
    normalized = [n for n in (normalize_faculty(p, MCB_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} MCB faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(MCB_CONFIG, "UC Berkeley Molecular & Cell Biology Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
