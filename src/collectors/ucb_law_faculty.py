"""Collector for UC Berkeley Law (Berkeley Law) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common.

The Berkeley Law faculty directory
(law.berkeley.edu/our-faculty/faculty-profiles/) is a WordPress archive where
each person is an `li.preview` carrying:
    - data-pname        the name
    - data-category     space-separated taxonomy codes: faculty_type-<id> (role)
                        and faculty_expertise-<id> (research area)
    - an `<a>` to the profile, followed by the rank text after the name

The page's filter `<select>` maps each faculty_expertise-<id> to a human label
(e.g. "Constitutional Law", "Intellectual Property"), so the research areas come
straight off the listing — that map is built from the same page at scrape time.
The directory mixes adjuncts, lecturers, clinical faculty, emeriti, fellows, and
ladder professors; only entries tagged faculty_type-253 ("Professor"), and not
faculty_type-249 ("Emeritus"), are kept.

Profiles are visited only to recover the personal email (first mailto:). The
50-term expertise vocabulary maps to keywords via config-local area_keywords, so
no legal terms pollute the shared KEYWORD_BANK.

Directory: https://www.law.berkeley.edu/our-faculty/faculty-profiles/

Usage:
    python -m src.collectors.ucb_law_faculty            # fetch & preview
    python -m src.collectors.ucb_law_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_law_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import ucb_common
from .ucb_common import (
    NOISE_EMAILS,
    PROFILE_DELAY,
    clean_name,
    dedup_by_profile_url,
    fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

_PROFESSOR_TYPE = "faculty_type-253"
_EMERITUS_TYPE = "faculty_type-249"
_EXPERTISE_RE = re.compile(r"faculty_expertise-(\d+)")

LAW_CONFIG = {
    "source": "ucb_law_faculty",
    "name": "Berkeley Law",
    "short": "LAW",
    "url": "https://www.law.berkeley.edu/our-faculty/faculty-profiles/",
    "base": "https://www.law.berkeley.edu",
    "majors": ["Law", "Jurisprudence and Social Policy"],
    "keywords": ["law"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {},
    # The listing tags each professor with one or more expertise areas (a
    # controlled vocabulary). Mapping them explicitly keeps the legal terms out
    # of the shared KEYWORD_BANK. Keys are the lowercased expertise labels.
    "area_keywords": {
        "administrative law": ["administrative law"],
        "antitrust": ["antitrust"],
        "arbitration and mediation": ["arbitration", "dispute resolution"],
        "artificial intelligence": ["artificial intelligence"],
        "banking and financial regulation": ["financial regulation"],
        "bankruptcy": ["bankruptcy"],
        "business associations": ["corporate law"],
        "business law": ["business law"],
        "capital punishment": ["capital punishment"],
        "civil procedure and litigation": ["civil procedure"],
        "civil rights and civil liberties": ["civil rights"],
        "constitutional law": ["constitutional law"],
        "consumer law and protection": ["consumer law"],
        "contract and commercial law": ["contract law"],
        "corporate finance and securities regulation":
            ["corporate finance", "securities regulation"],
        "criminal law, criminal procedure, and criminal justice":
            ["criminal law", "criminal justice"],
        "critical legal theory": ["critical legal theory"],
        "education law": ["education law"],
        "election law": ["election law"],
        "employment and labor law": ["labor law", "employment law"],
        "environmental, natural resources, and energy law":
            ["environmental law", "energy law"],
        "evidence": ["evidence law"],
        "family law, childrens' rights, and reproductive rights": ["family law"],
        "gender and sexuality": ["gender and sexuality"],
        "health law and policy": ["health law"],
        "human rights": ["human rights"],
        "immigration": ["immigration law"],
        "indian nations and indigenous peoples": ["indigenous peoples law"],
        "insurance law": ["insurance law"],
        "intellectual property: copyright, patents, trademarks":
            ["intellectual property"],
        "international and comparative law":
            ["international law", "comparative law"],
        "international business transactions and trade regulation":
            ["international trade law"],
        "jurisprudence": ["jurisprudence"],
        "juvenile justice": ["juvenile justice"],
        "law and economics": ["law and economics"],
        "law and science": ["law and science"],
        "law and social entrepreneurship": ["social entrepreneurship"],
        "law and society": ["law and society"],
        "law and technology": ["law and technology"],
        "legal ethics": ["legal ethics"],
        "legal history": ["legal history"],
        "legislation": ["legislation"],
        "national security": ["national security law"],
        "privacy and cybersecurity": ["privacy law", "cybersecurity"],
        "property": ["property law"],
        "racial and social justice": ["racial justice"],
        "securities law": ["securities law"],
        "state and local government": ["state and local government law"],
        "tax law and policy": ["tax law"],
        "torts and personal injury": ["torts"],
    },
}


def _build_expertise_map(soup: BeautifulSoup) -> dict[str, str]:
    """Map faculty_expertise-<id> -> human label from the filter <select>."""
    out: dict[str, str] = {}
    for option in soup.select("select[name='category'] option"):
        m = re.match(r"faculty_expertise-(\d+)", option.get("value", ""))
        if m:
            out[m.group(1)] = option.get_text(strip=True)
    return out


def _scrape_law_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the Berkeley Law directory into [{name, url, title, research_areas}].

    Each person is an `li.preview`; only those tagged faculty_type-253
    ("Professor") and not faculty_type-249 ("Emeritus") are kept. The research
    areas come from the faculty_expertise-<id> codes resolved against the page's
    filter map.
    """
    expertise_map = _build_expertise_map(soup)
    faculty: list[dict] = []
    for li in soup.select("li.preview"):
        category = li.get("data-category", "")
        types = set(re.findall(r"faculty_type-\d+", category))
        if _PROFESSOR_TYPE not in types or _EMERITUS_TYPE in types:
            continue

        name = clean_name(li.get("data-pname", ""))
        link = li.select_one("a[href]")
        if not name or len(name) < 3 or not link:
            continue
        href = link.get("href", "")
        if not href:
            continue

        # The rank is the text after the name (", Herma Hill Kay ... Professor").
        title = li.get_text(" ", strip=True).replace(name, "", 1).lstrip(" ,").strip()

        person: dict = {"name": name, "url": urljoin(base, href)}
        if title:
            person["title"] = title
        areas = [expertise_map[e] for e in _EXPERTISE_RE.findall(category)
                 if e in expertise_map]
        if areas:
            person["research_areas"] = "; ".join(areas)
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} Berkeley Law faculty")
    return faculty


def _email_from_profile(soup: BeautifulSoup) -> str | None:
    """Return the first mailto: that is not a shared/admin mailbox."""
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if addr and addr not in NOISE_EMAILS:
            return addr
    return None


def _enrich_law_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the personal email (research came from the listing).

    Respectful: a small delay between requests, the shared robust fetcher, and a
    graceful skip when a profile fails to fetch.
    """
    total = len(faculty)
    found = 0
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
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(f"  Recovered {found}/{total} emails from profile pages")
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Berkeley Law faculty and return normalized opportunity records.

    The listing supplies name + link + title + expertise areas; with enrich=True
    (default) each profile is visited to recover the personal email.
    """
    soup = fetch_soup(LAW_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(_scrape_law_faculty_list(soup, LAW_CONFIG["base"]))
    if enrich:
        raw = _enrich_law_profiles(raw, LAW_CONFIG)
    normalized = [n for n in (normalize_faculty(p, LAW_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Berkeley Law faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(LAW_CONFIG, "UC Berkeley Law Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
