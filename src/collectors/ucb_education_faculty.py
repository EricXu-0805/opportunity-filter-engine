"""Collector for UC Berkeley School of Education (BSE, formerly GSE) faculty.

A department config + bespoke listing parser over src.collectors.ucb_common,
following the same pattern as ucb_history_faculty / ucb_english_faculty.

The Berkeley School of Education faculty page is an Open-Berkeley content page
whose roster is a grid of `div.fieldable-panels-pane` cards. Each card has the
profile link in its single `a[href]` (the photo link, to bse.berkeley.edu/<slug>)
and an image caption holding the name in a `<strong>` and the rank in an adjacent
`div.openberkeley-widgets-label-inner`. The listing carries no email or research,
so profiles are visited via the shared enrichment hop to recover the mailto:
email and the free-text biography (`field-name-body`) used as the research signal.

Emeritus faculty live on a separate page and are not in this roster; the shared
title filter drops any that slip in. Records with no email ship "lite"
(contact_email=None, confidence_score=0.5).

Directory: https://gse.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_education_faculty            # fetch & preview
    python -m src.collectors.ucb_education_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_education_faculty --save     # merge into processed data
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

# Each BSE topic tag renders as "<Cluster name> topic page"; the suffix is the
# link text and must be stripped to recover the cluster name.
_TOPIC_SUFFIX_RE = re.compile(r"\s*topic page\s*$", re.IGNORECASE)


def _personal_email(soup: BeautifulSoup, name: str) -> str | None:
    """Return the faculty member's own email.

    Some BSE profiles list only a scheduling assistant's address as the sole
    mailto: (structurally identical to a personal one), so we require the
    localpart to contain a name token — this rejects e.g. "annalisa.cf@..." on a
    "Travis Bristol" page (he then ships lite) while accepting "dor@",
    "freedman@", "delaneyj@", etc.
    """
    tokens = [t for t in re.split(r"[^a-z]+", name.lower()) if len(t) >= 3]
    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
        if not addr or addr in NOISE_EMAILS:
            continue
        local = re.sub(r"[^a-z0-9]", "", addr.split("@")[0])
        if any(tok in local for tok in tokens):
            return addr
    return None

EDUCATION_CONFIG = {
    "source": "ucb_education_faculty",
    "name": "School of Education",
    "short": "EDUC",
    "url": "https://gse.berkeley.edu/people/faculty",
    "base": "https://bse.berkeley.edu",
    "majors": ["Education"],
    "keywords": ["education"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        # Profiles expose the email via mailto: (tried first by the shared
        # extractor) — this field is a fallback if a future page adds it.
        "email_field": "div.field-name-field-openberkeley-person-email",
    },
    # BSE tags each faculty with one or more clusters/programs (a controlled
    # vocabulary) rather than free-text interests; mapping them explicitly beats
    # substring-matching the noisy biography prose (which trips ML/science terms).
    "area_keywords": {
        "learning sciences & human development":
            ["learning sciences", "cognition and development", "child development"],
        "policy, politics, & leadership":
            ["educational policy", "educational leadership"],
        "critical studies of race, class, & gender":
            ["critical pedagogy", "educational equity", "sociology of education"],
        "language, literacy, and culture":
            ["literacy", "language and literacy", "second language acquisition"],
        "social research methodologies":
            ["quantitative methods", "educational measurement"],
        "berkeley teacher education program": ["teacher education"],
        "leadership programs": ["educational leadership"],
        "leadership programs: teacher leadership":
            ["teacher education", "educational leadership"],
        "principal leadership institute": ["educational leadership"],
        "leaders for equity and democracy edd":
            ["educational leadership", "educational equity"],
    },
}


def _scrape_education_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the BSE faculty grid into [{name, url, title}].

    Each faculty member is a `div.fieldable-panels-pane` whose single `a[href]`
    is the profile link and whose caption holds the name in a `<strong>` and the
    rank in an adjacent `div.openberkeley-widgets-label-inner` (the label whose
    text is not the name). Email/research are not on the listing.
    """
    faculty: list[dict] = []
    for pane in soup.select("div.fieldable-panels-pane"):
        link = pane.select_one("a[href]")
        strong = pane.select_one("strong")
        if not link or not strong:
            continue
        name = clean_name(strong.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}
        for inner in pane.select("div.openberkeley-widgets-label-inner"):
            text = inner.get_text(" ", strip=True)
            if text and text != name and not inner.find("strong"):
                person["title"] = text
                break
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} Education faculty")
    return faculty


def _topics_from_profile(soup: BeautifulSoup) -> str:
    """Recover the BSE cluster/program tags as a "; "-joined string.

    Each tag is a link whose text is "<Cluster name> topic page"; the suffix is
    stripped. The "; " separator lets config["area_keywords"] map each tag. Empty
    when the profile carries no topics field.
    """
    field = soup.select_one("div.field-name-field-openberkeley-topics")
    if not field:
        return ""
    tags = []
    for a in field.select("a"):
        tag = _TOPIC_SUFFIX_RE.sub("", a.get_text(" ", strip=True)).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return "; ".join(tags)


def _enrich_education_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each profile for the mailto: email and the BSE cluster tags.

    Research comes from the controlled topic vocabulary (mapped via
    area_keywords), not the biography body — the long prose trips unrelated
    KEYWORD_BANK terms. Respectful: a small delay between requests, the shared
    robust fetcher, and a graceful skip when a profile fails to fetch.
    """
    total = len(faculty)
    found = with_topics = 0
    for i, person in enumerate(faculty):
        url = person.get("url")
        if not url:
            continue
        soup = fetch_soup(url)
        if soup:
            email = _personal_email(soup, person["name"])
            if email:
                person["email"] = email
                found += 1
            topics = _topics_from_profile(soup)
            if topics:
                person["research_areas"] = topics
                with_topics += 1
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(
        f"  Recovered {found}/{total} emails and {with_topics}/{total} topic "
        f"tag sets from profile pages"
    )
    return faculty


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Education faculty and return normalized opportunity records.

    The listing supplies name + link + title; with enrich=True (default) each
    profile is visited to recover the email and the BSE cluster tags.
    """
    soup = fetch_soup(EDUCATION_CONFIG["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(
        _scrape_education_faculty_list(soup, EDUCATION_CONFIG["base"])
    )
    if enrich:
        raw = _enrich_education_profiles(raw, EDUCATION_CONFIG)
    normalized = [n for n in (normalize_faculty(p, EDUCATION_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Education faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(EDUCATION_CONFIG, "UC Berkeley School of Education Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
