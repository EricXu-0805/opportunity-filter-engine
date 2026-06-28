"""Collector for UC Berkeley Department of French faculty.

Config-only department over ``src.collectors.ucb_common``: the Department of French
directory (https://french.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://french.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_french_faculty            # fetch & preview
    python -m src.collectors.ucb_french_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_french_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

FRENCH_CONFIG = {
    "source": "ucb_french_faculty",
    "name": "Department of French",
    "short": "FRENCH",
    "url": "https://french.berkeley.edu/people/faculty",
    "base": "https://french.berkeley.edu",
    "majors": ['French'],
    "keywords": ['french'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Department of French faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(FRENCH_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(FRENCH_CONFIG, "UC Berkeley Department of French Faculty Collector")
