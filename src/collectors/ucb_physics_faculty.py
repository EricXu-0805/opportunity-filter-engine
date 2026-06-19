"""Collector for UC Berkeley Physics faculty research opportunities.

A department config + bespoke multi-page scrape over src.collectors.ucb_common.

Physics renders faculty in the same Open-Berkeley card variant as Chemistry
(`div.node-openberkeley-person`), but the flat `/people/faculty` listing is
paginated across ~26 pages and mixes in grad students and postdocs. The clean
source is the per-research-area pages under `/research-faculty/<area>`, which
list each area's faculty as cards. We iterate the eight area pages, keep only
`/people/faculty/` cards, and tag each professor with the area(s) they appear
under — giving research keywords for free (mapped via PHYS_AREA_KEYWORDS, the
shared area_keywords path) and naturally restricting to faculty. A professor in
multiple areas is merged into one record carrying all of them.

Email is recovered by the shared per-profile hop (mailto: / email field).
Physics lists `physics_admin@berkeley.edu` as a second mailto on every profile;
it's in ucb_common.NOISE_EMAILS so a professor with a non-Berkeley personal
address doesn't resolve to it. Emeritus faculty are dropped by the shared title
filter. Records with no email ship "lite" (confidence_score=0.5).

Usage:
    python -m src.collectors.ucb_physics_faculty            # fetch & preview
    python -m src.collectors.ucb_physics_faculty --no-enrich  # skip email hop (fast)
    python -m src.collectors.ucb_physics_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import time

from . import ucb_common
from .ucb_common import (
    PROFILE_DELAY,
    dedup_by_profile_url,
    enrich_faculty_from_profiles,
    fetch_soup,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)

logger = logging.getLogger(__name__)

# Research-area pages under /research-faculty/<slug>. The value is the readable
# area name attached to each professor as research_areas (keys for the keyword
# map below are these names lowercased — see ucb_common._normalize_area_tag).
PHYS_AREAS = {
    "astrophysics": "Astrophysics",
    "atomic-molecular-optical-physics": "Atomic, Molecular & Optical Physics",
    "biophysics": "Biophysics",
    "condensed-matter": "Condensed Matter Physics",
    "nuclear-physics": "Nuclear Physics",
    "particle-physics": "Particle Physics",
    "plasma-nonlinear-dynamics": "Plasma & Nonlinear Dynamics",
    "quantum-physics": "Quantum Information Science",
}

PHYS_AREA_KEYWORDS = {
    "astrophysics": ["astrophysics", "cosmology"],
    "atomic, molecular & optical physics": ["atomic physics", "optics",
                                            "quantum optics"],
    "biophysics": ["biophysics", "biological physics"],
    "condensed matter physics": ["condensed matter", "materials science"],
    "nuclear physics": ["nuclear physics"],
    "particle physics": ["particle physics", "high energy physics"],
    "plasma & nonlinear dynamics": ["plasma physics", "nonlinear dynamics"],
    "quantum information science": ["quantum", "quantum information"],
}

PHYS_CONFIG = {
    "source": "ucb_physics_faculty",
    "name": "Department of Physics",
    "short": "PHYS",
    "url": "https://physics.berkeley.edu/research-faculty",
    "base": "https://physics.berkeley.edu",
    "majors": ["Physics", "Engineering Physics", "Astrophysics"],
    "keywords": ["physics"],
    "area_keywords": PHYS_AREA_KEYWORDS,
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        "card": "div.node-openberkeley-person",
        "name": "h2",
        "link": "a[href*='/people/']",
        "title": "div.field-name-field-openberkeley-person-title",
        # Profiles carry a mailto: link (tried first) and this field. Research
        # interests are intentionally NOT configured: the per-area tags are the
        # research signal, and leaving this unset stops the email hop from
        # overwriting them.
        "email_field": "div.field-name-field-openberkeley-person-email",
    },
}


def _scrape_physics_faculty() -> list[dict]:
    """Scrape the eight research-area pages into one faculty list.

    Keeps only `/people/faculty/` cards (the area pages also list some staff),
    tags each professor with the readable area name, and merges a professor who
    appears under multiple areas into a single record carrying all of them.
    """
    by_url: dict[str, dict] = {}
    for slug, area in PHYS_AREAS.items():
        soup = fetch_soup(f"{PHYS_CONFIG['base']}/research-faculty/{slug}")
        if not soup:
            continue
        cards = [p for p in scrape_open_berkeley_faculty(soup, PHYS_CONFIG)
                 if "/people/faculty/" in p["url"]]
        for person in cards:
            existing = by_url.get(person["url"])
            if existing:
                areas = existing.get("research_areas", "")
                if area not in areas:
                    existing["research_areas"] = f"{areas}; {area}" if areas else area
            else:
                person["research_areas"] = area
                by_url[person["url"]] = person
        logger.info(f"  {slug}: {len(cards)} faculty")
        time.sleep(PROFILE_DELAY)
    logger.info(f"  {len(by_url)} unique PHYS faculty across areas")
    return list(by_url.values())


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Physics faculty (by area) and return normalized records.

    Area pages supply name + link + title + research area(s); with enrich=True
    (default) each profile page is visited to recover the contact email.
    """
    raw = dedup_by_profile_url(_scrape_physics_faculty())
    if not raw:
        return []
    if enrich:
        raw = enrich_faculty_from_profiles(raw, PHYS_CONFIG)
    normalized = [n for n in (normalize_faculty(p, PHYS_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} PHYS faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(PHYS_CONFIG, "UC Berkeley Physics Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
