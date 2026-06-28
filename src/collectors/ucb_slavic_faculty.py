"""Collector for UC Berkeley Slavic Languages and Literatures faculty.

Config-only department over ``src.collectors.ucb_common``: the Slavic Languages and Literatures
directory (https://slavic.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://slavic.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_slavic_faculty            # fetch & preview
    python -m src.collectors.ucb_slavic_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_slavic_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

SLAVIC_CONFIG = {
    "source": "ucb_slavic_faculty",
    "name": "Slavic Languages and Literatures",
    "short": "SLAVIC",
    "url": "https://slavic.berkeley.edu/people/faculty",
    "base": "https://slavic.berkeley.edu",
    "majors": ['Slavic Languages and Literatures'],
    "keywords": ['slavic'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Slavic Languages and Literatures faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(SLAVIC_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(SLAVIC_CONFIG, "UC Berkeley Slavic Languages and Literatures Faculty Collector")
