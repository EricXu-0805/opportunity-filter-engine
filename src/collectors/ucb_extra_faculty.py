"""Collector for UC Berkeley departments not yet covered by a dedicated module.

Fills the L&S humanities/area-studies + Rausser gaps the per-department audit
found: Italian Studies, African American Studies, Agricultural & Resource
Economics (Rausser), South & Southeast Asian Studies, Ethnic Studies, Gender &
Women's Studies, Art Practice, East Asian Languages & Cultures, and Demography.
All are Open-Berkeley Drupal sites, so the faculty *profile* pages are uniform
(``field-openberkeley-person-*`` fields); only the *listing* markup varies,
handled by two modes:

Still uncovered (need the render engine, not urllib): School of Optometry
(JS-rendered roster), School of Information (403s urllib), Near Eastern Studies
(domain retired). Tracked for a later render-based pass.

- ``card``  : standard ``div.node-openberkeley-person`` teaser cards (name in an
              ``h2``/``h3``, rank in the person-title field), like the English
              collector. Paginated over ``?page=N``.
- ``links`` : listings that render profile links without the node card wrapper —
              harvest every ``/people/<slug>`` person link (link text = name),
              then recover rank/email/research via the shared profile hop.

Both feed ``enrich_faculty_from_profiles`` (email + biography from each profile)
and ``normalize_faculty``. One source ("ucb_extra_faculty"); each record's
department rides its per-dept config. Records with no email ship "lite".

Usage:
    python -m src.collectors.ucb_extra_faculty            # fetch & preview
    python -m src.collectors.ucb_extra_faculty --no-enrich
    python -m src.collectors.ucb_extra_faculty --save
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from . import ucb_common
from .ucb_common import (
    _is_person_name,
    clean_name,
    dedup_by_profile_url,
    enrich_faculty_from_profiles,
    fetch_soup,
    normalize_faculty,
    scrape_open_berkeley_faculty,
)

logger = logging.getLogger(__name__)

_SOURCE = "ucb_extra_faculty"
_WORK_AUTH = ("External campus (UC Berkeley) — work authorization depends on the "
              "arrangement")
_MAX_PAGES = 12

# Open-Berkeley profile fields are uniform across departments; the listing card
# selectors only matter in ``card`` mode.
_OB_SELECTORS = {
    "card": "div.node-openberkeley-person",
    "name": "h2, h3",
    "link": "a[href*='/people/']",
    "title": "div.field-name-field-openberkeley-person-title",
    "email_field": "div.field-name-field-openberkeley-person-email",
    "research_interests": [
        "div.field-name-field-openberkeley-person-research-interests .field-item",
        "div.field-name-field-resint .field-item",
        "div.field-name-body .field-item",
    ],
}

# A person profile: /people/<slug> or /faculty/<slug> where the slug carries a
# hyphen (first-last). Non-person hubs like /faculty/administration have no
# hyphen and never match; hyphenated section pages (/faculty/graduate-students)
# do match here but are dropped by the link-text section filter below.
_PERSON_HREF_RE = re.compile(r"/(?:people|faculty)/[a-z][a-z0-9]+-[a-z0-9-]+$")

# Link text that is a section/role label, not a person. In ``links`` mode the
# listing mixes person links with navigation ("Professors Emeriti", "Graduate
# Students", "The People of SSEAS"); reject any link text containing one of
# these tokens — no real surname is "Scholars" or "Emeriti".
_SECTION_WORDS = {
    "the", "people", "of", "faculty", "staff", "student", "students", "scholar",
    "scholars", "emeriti", "emeritus", "emerita", "professor", "professors",
    "lecturer", "lecturers", "affiliated", "affiliate", "affiliates", "visiting",
    "graduate", "undergraduate", "postdoctoral", "postdoc", "postdocs",
    "researcher", "researchers", "alumni", "department", "core", "senate",
    "adjunct", "fellow", "fellows", "directory", "overview", "home", "ladder",
    "memorial", "lecture", "lectureship", "prize", "award", "fund", "endowed",
    "chair", "obituary", "positions", "join", "contact", "administration",
    "administrative", "associated", "instructors", "instructor",
    "gsi", "gsis", "ta", "tas", "emeriti/ae",
}


def _looks_like_section(name: str) -> bool:
    """True if any token in the link text is a section/role label."""
    return any(tok.lower().strip(".,") in _SECTION_WORDS for tok in name.split())


def _cfg(short, name, url, base, majors, keywords, mode="card"):
    return {
        "source": _SOURCE, "short": short, "name": name, "url": url, "base": base,
        "majors": majors, "keywords": keywords, "mode": mode,
        "work_auth_notes": _WORK_AUTH, "selectors": dict(_OB_SELECTORS),
    }


# Each department is exposed as a module-level ``*_CONFIG`` dict (all carry the
# same ``source == "ucb_extra_faculty"``) so the filesystem wiring guard
# (tests/test_collector_wiring.py::_configs_in_module) discovers this module's
# source exactly as it does single-department modules' ENGLISH_CONFIG.
ITAL_CONFIG = _cfg(
    "ITAL", "Department of Italian Studies", "https://italian.berkeley.edu/people/faculty",
    "https://italian.berkeley.edu", ["Italian", "Italian Studies"], ["italian studies"])
AFRICAM_CONFIG = _cfg(
    "AFRICAM", "Department of African American Studies",
    "https://africam.berkeley.edu/people/faculty", "https://africam.berkeley.edu",
    ["African American Studies", "African Diaspora Studies"], ["african american studies"])
ARE_CONFIG = _cfg(
    "ARE", "Department of Agricultural & Resource Economics",
    "https://are.berkeley.edu/people/faculty", "https://are.berkeley.edu",
    ["Agricultural & Resource Economics", "Environmental Economics", "Economics"],
    ["agricultural economics", "resource economics"])
SSEAS_CONFIG = _cfg(
    "SSEAS", "Department of South & Southeast Asian Studies",
    "https://sseas.berkeley.edu/faculty", "https://sseas.berkeley.edu",
    ["South & Southeast Asian Studies"], ["south asian studies", "southeast asian studies"],
    mode="links")
ETHSTD_CONFIG = _cfg(
    "ETHSTD", "Department of Ethnic Studies",
    "https://ethnicstudies.berkeley.edu/people/faculty/", "https://ethnicstudies.berkeley.edu",
    ["Ethnic Studies", "Asian American Studies", "Chicano Studies", "Native American Studies"],
    ["ethnic studies"], mode="links")
GWS_CONFIG = _cfg(
    "GWS", "Department of Gender & Women's Studies",
    "https://gws.berkeley.edu/people/faculty", "https://gws.berkeley.edu",
    ["Gender & Women's Studies"], ["gender studies", "women's studies"], mode="links")
ARTPRAC_CONFIG = _cfg(
    "ARTPRAC", "Department of Art Practice",
    "https://art.berkeley.edu/people/faculty/", "https://art.berkeley.edu",
    ["Art Practice", "Studio Art"], ["art practice"], mode="links")
EALC_CONFIG = _cfg(
    "EALC", "Department of East Asian Languages & Cultures",
    "https://ealc.berkeley.edu/faculty", "https://ealc.berkeley.edu",
    ["East Asian Languages & Cultures", "Chinese", "Japanese", "Korean"],
    ["east asian studies", "chinese", "japanese", "korean"], mode="links")
DEMOG_CONFIG = _cfg(
    "DEMOG", "Department of Demography",
    "https://www.demog.berkeley.edu/faculty/", "https://www.demog.berkeley.edu",
    ["Demography", "Population Studies"], ["demography", "population studies"], mode="links")

CONFIGS = [
    ITAL_CONFIG, AFRICAM_CONFIG, ARE_CONFIG, SSEAS_CONFIG, ETHSTD_CONFIG,
    GWS_CONFIG, ARTPRAC_CONFIG, EALC_CONFIG, DEMOG_CONFIG,
]


def _scrape_card(config: dict) -> list[dict]:
    """Paginated Open-Berkeley teaser-card listing."""
    faculty: list[dict] = []
    for page in range(_MAX_PAGES):
        soup = fetch_soup(f"{config['url']}?page={page}")
        if not soup:
            break
        cards = scrape_open_berkeley_faculty(soup, config)
        if not cards and page > 0:
            break
        faculty.extend(cards)
    return faculty


def _scrape_links(config: dict) -> list[dict]:
    """Harvest every /people/<slug> person link (text = name) from the listing."""
    soup = fetch_soup(config["url"])
    if not soup:
        return []
    seen: set[str] = set()
    faculty: list[dict] = []
    for a in soup.select("a[href]"):
        href = a.get("href", "").split("?")[0].split("#")[0]
        if not _PERSON_HREF_RE.search(href):
            continue
        name = clean_name(a.get_text(" ", strip=True))
        if not name or not _is_person_name(name) or _looks_like_section(name):
            continue
        if href in seen:
            continue
        seen.add(href)
        faculty.append({"name": name, "url": urljoin(config["base"], href)})
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape every configured department and return normalized records."""
    out: list[dict] = []
    for config in CONFIGS:
        raw = _scrape_card(config) if config["mode"] == "card" else _scrape_links(config)
        raw = dedup_by_profile_url(raw)
        logger.info(f"  {config['short']}: {len(raw)} faculty (listing)")
        if not raw:
            continue
        if enrich:
            raw = enrich_faculty_from_profiles(raw, config)
        out.extend(n for n in (normalize_faculty(p, config) for p in raw) if n)
    logger.info(f"Normalized {len(out)} UCB extra-department faculty opportunities")
    return out


def merge_into_processed(new_opps: list[dict]):
    return ucb_common.merge_into_processed(new_opps)


if __name__ == "__main__":
    ucb_common.run_cli(CONFIGS[0], "UC Berkeley Extra Departments Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
