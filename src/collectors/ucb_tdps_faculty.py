"""Collector for UC Berkeley Theater, Dance & Performance Studies faculty.

Config-only department over ``src.collectors.ucb_common``: the Theater, Dance & Performance Studies
directory (https://tdps.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://tdps.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_tdps_faculty            # fetch & preview
    python -m src.collectors.ucb_tdps_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_tdps_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

TDPS_CONFIG = {
    "source": "ucb_tdps_faculty",
    "name": "Theater, Dance & Performance Studies",
    "short": "TDPS",
    "url": "https://tdps.berkeley.edu/people/faculty",
    "base": "https://tdps.berkeley.edu",
    "majors": ['Theater and Performance Studies', 'Dance'],
    "keywords": ['theater', 'performance studies', 'dance'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Theater, Dance & Performance Studies faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(TDPS_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(TDPS_CONFIG, "UC Berkeley Theater, Dance & Performance Studies Faculty Collector")
