"""Collector for UC Berkeley Bioengineering (BioE) faculty research opportunities.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_cee_faculty / ucb_eecs_faculty (a
non-Open-Berkeley directory that needs a local parser but reuses fetching,
dedup, profile enrichment, normalization, and the merge path from ucb_common).

The BioE department site is a Beaver Builder grid: each faculty member is a
`div.fl-post-grid-post.persontype-faculty` card carrying name + profile link
(`h3.fl-post-title a`) + rank (`p.professor-title`). The only structured
research signal on the listing is a `research-area-<slug>` CSS class drawn from
a fixed 5-term vocabulary (like Berkeley EECS's umbrella tags), so the parser
maps those slugs to readable areas and BIOE_AREA_KEYWORDS turns each into
topical keywords via the shared area_keywords path. Email is not on the listing;
the shared per-profile enrichment hop recovers it (a mailto: link on each
profile). Profiles carry no labeled research section, so research comes solely
from the listing's area tags.

Records with no email found ship "lite" (contact_email=None,
confidence_score=0.5); the 4 faculty with no area tag fall back to the broad
department keyword. Emeritus faculty (persontype-emeritus) are skipped — they
are not viable undergrad-research mentors.

Directory: https://bioeng.berkeley.edu/people/
Each entry links to a profile at /person/<slug>.

Usage:
    python -m src.collectors.ucb_bioe_faculty            # fetch & preview
    python -m src.collectors.ucb_bioe_faculty --no-enrich  # skip email hop (fast)
    python -m src.collectors.ucb_bioe_faculty --save     # merge into processed data
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

# The listing encodes each professor's research area(s) as a `research-area-*`
# CSS class from this fixed 5-term vocabulary. Map the slugs to readable names.
SLUG_TO_AREA = {
    "biomems-nano": "BioMEMS & Nanotechnology",
    "cell-tissue": "Cell & Tissue Engineering",
    "compbio": "Computational Biology",
    "bioinstrumentation": "Bioinstrumentation & Imaging",
    "synbio": "Synthetic Biology",
}

# Readable area -> topical keywords (consumed via config["area_keywords"], the
# same mechanism Berkeley EECS uses). Keys are the readable area names
# lowercased — see ucb_common._normalize_area_tag.
BIOE_AREA_KEYWORDS = {
    "biomems & nanotechnology": ["nanotechnology", "biomedical",
                                 "microelectromechanical systems"],
    "cell & tissue engineering": ["tissue engineering", "biomaterials", "biomedical"],
    "computational biology": ["computational biology", "bioinformatics", "genomics"],
    "bioinstrumentation & imaging": ["medical imaging", "signal processing", "biomedical"],
    "synthetic biology": ["synthetic biology", "genomics", "metabolic engineering"],
}

BIOE_CONFIG = {
    "source": "ucb_bioe_faculty",
    "name": "Department of Bioengineering",
    "short": "BIOE",
    "url": "https://bioeng.berkeley.edu/people/",
    "base": "https://bioeng.berkeley.edu",
    "majors": ["Bioengineering", "Biomedical Engineering"],
    # Broad fallback used only when a card carries no research-area tag.
    "keywords": ["bioengineering"],
    "area_keywords": BIOE_AREA_KEYWORDS,
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    # No selectors: the listing parser below is bespoke, and leaving
    # research_interests unset means the email-enrichment hop won't overwrite
    # the research areas already captured from the listing.
    "selectors": {},
}


def _scrape_bioe_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the BioE directory into [{name, url, title, research_areas}].

    Berkeley-specific markup (verified against the live page): each faculty
    member is a `div.fl-post-grid-post.persontype-faculty` card with the name +
    profile link in `h3.fl-post-title a`, the rank in `p.professor-title`, and
    research area(s) encoded as `research-area-<slug>` classes on the card.
    Emeritus faculty are skipped. Email is not on the listing — the
    profile-enrichment hop recovers it.
    """
    faculty: list[dict] = []
    for card in soup.select("div.fl-post-grid-post.persontype-faculty"):
        classes = card.get("class", [])
        if "persontype-emeritus" in classes:
            continue

        name_el = card.select_one("h3.fl-post-title a")
        if not name_el:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        href = name_el.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}

        title_el = card.select_one("p.professor-title")
        if title_el:
            person["title"] = title_el.get_text(" ", strip=True)

        areas = [SLUG_TO_AREA[slug] for cls in classes
                 if cls.startswith("research-area-")
                 for slug in [cls.removeprefix("research-area-")]
                 if slug in SLUG_TO_AREA]
        if areas:
            person["research_areas"] = "; ".join(areas)

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} BIOE faculty")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape BioE faculty and return normalized opportunity records.

    The listing supplies name + link + title + research areas; with enrich=True
    (default) each profile page is visited to recover the contact email (a
    mailto: link the listing omits).
    """
    soup = fetch_soup(BIOE_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_bioe_faculty_list(soup, BIOE_CONFIG["base"]))
    if enrich:
        raw = enrich_faculty_from_profiles(raw, BIOE_CONFIG)
    normalized = [n for n in (normalize_faculty(p, BIOE_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} BIOE faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(BIOE_CONFIG, "UC Berkeley Bioengineering Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
