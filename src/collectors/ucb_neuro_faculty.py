"""Collector for UC Berkeley Helen Wills Neuroscience Institute faculty.

A department config + single-page table parser over src.collectors.ucb_common.

Unlike most UCB departments, the Helen Wills directory at
``neuroscience.berkeley.edu/faculty/`` is a single Open-Berkeley *views-table*
that already carries every field inline — no per-profile enrichment hop needed:

    <td class="views-field-title"><a href="/people/slug">Name</a></td>
    <td class="views-field-field-openberkeley-person-dept">Neuroscience</td>
    <td class="views-field-field-openberkeley-person-resint">research interests</td>
    <td class="views-field-field-openberkeley-person-email"><a href="mailto:…">…</a></td>

Helen Wills is an *institute*, so most of its members are jointly appointed in
MCB, Psychology, Integrative Biology, Bioengineering, etc. — departments this
project already scrapes. Those joint appointments would collide on the strict
ucb_* data-quality gate (no two ucb_* records may share an email or pi_name), so
this collector relies on ``ucb_common.merge_into_processed`` →
``drop_joint_appointment_duplicates``: when refresh_all merges the home
departments first, a neuroscience row duplicating one of them is dropped, and
only the genuinely neuroscience-primary faculty (~15+) are added net-new.

Records whose row carries no mailto ship "lite" (contact_email=None).

Directory: https://neuroscience.berkeley.edu/faculty/

Usage:
    python -m src.collectors.ucb_neuro_faculty            # fetch & preview
    python -m src.collectors.ucb_neuro_faculty --save     # merge into processed data
"""

from __future__ import annotations

import logging
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

NEURO_CONFIG = {
    "source": "ucb_neuro_faculty",
    "name": "Helen Wills Neuroscience Institute",
    "short": "NEURO",
    "url": "https://neuroscience.berkeley.edu/faculty/",
    "base": "https://neuroscience.berkeley.edu",
    "majors": ["Neuroscience", "Cognitive Science", "Molecular & Cell Biology"],
    "keywords": ["neuroscience"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
}


def _scrape_table(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the single views-table, pulling name + profile link, research
    interests, and the inline mailto email straight from each row."""
    out: list[dict] = []
    for row in soup.select("table tbody tr"):
        link = row.select_one("td.views-field-title a[href]") or row.select_one("td.views-field-title a, a[href]")
        if not link:
            continue
        name = clean_name(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or len(name) < 3 or not href:
            continue
        resint_cell = row.select_one("td.views-field-field-openberkeley-person-resint")
        research = resint_cell.get_text(" ", strip=True) if resint_cell else ""
        mail = row.select_one("td.views-field-field-openberkeley-person-email a[href^='mailto:']")
        email = mail.get("href", "")[len("mailto:"):].strip() if mail else ""
        out.append({
            "name": name,
            "url": urljoin(base, href),
            "email": email,
            "research_areas": research,
        })
    return out


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape the Helen Wills faculty table and return normalized records.

    The table is self-contained (name + email + research interests inline), so
    ``enrich`` is accepted for CLI symmetry with the other UCB collectors but no
    per-profile hop is performed. Joint-appointment overlap with the home
    departments is resolved at merge time by drop_joint_appointment_duplicates.
    """
    soup = fetch_soup(NEURO_CONFIG["url"])
    if not soup:
        logger.warning("Helen Wills: directory fetch failed")
        return []
    raw = dedup_by_profile_url(_scrape_table(soup, NEURO_CONFIG["base"]))
    if not raw:
        return []
    normalized = [n for n in (normalize_faculty(p, NEURO_CONFIG) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} Helen Wills neuroscience faculty opportunities")
    return normalized


if __name__ == "__main__":
    ucb_common.run_cli(NEURO_CONFIG, "UC Berkeley Helen Wills Neuroscience Faculty Collector",
                       fetch=lambda enrich: fetch_and_normalize(enrich))
