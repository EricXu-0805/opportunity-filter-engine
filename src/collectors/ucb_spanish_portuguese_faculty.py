"""Collector for UC Berkeley Department of Spanish & Portuguese faculty.

Config-only department over ``src.collectors.ucb_common``: the Department of Spanish & Portuguese
directory (https://spanish-portuguese.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://spanish-portuguese.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_spanish_portuguese_faculty            # fetch & preview
    python -m src.collectors.ucb_spanish_portuguese_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_spanish_portuguese_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

SPANISH_PORTUGUESE_CONFIG = {
    "source": "ucb_spanish_portuguese_faculty",
    "name": "Department of Spanish & Portuguese",
    "short": "SPANPORT",
    "url": "https://spanish-portuguese.berkeley.edu/people/faculty",
    "base": "https://spanish-portuguese.berkeley.edu",
    "majors": ['Spanish', 'Portuguese'],
    "keywords": ['spanish', 'portuguese'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Department of Spanish & Portuguese faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(SPANISH_PORTUGUESE_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(SPANISH_PORTUGUESE_CONFIG, "UC Berkeley Department of Spanish & Portuguese Faculty Collector")
