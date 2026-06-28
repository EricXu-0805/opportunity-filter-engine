"""Collector for UC Berkeley Department of Rhetoric faculty.

Config-only department over ``src.collectors.ucb_common``: the Department of Rhetoric
directory (https://rhetoric.berkeley.edu/people/all-faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://rhetoric.berkeley.edu/people/all-faculty

Usage:
    python -m src.collectors.ucb_rhetoric_faculty            # fetch & preview
    python -m src.collectors.ucb_rhetoric_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_rhetoric_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

RHETORIC_CONFIG = {
    "source": "ucb_rhetoric_faculty",
    "name": "Department of Rhetoric",
    "short": "RHET",
    "url": "https://rhetoric.berkeley.edu/people/all-faculty",
    "base": "https://rhetoric.berkeley.edu",
    "majors": ['Rhetoric'],
    "keywords": ['rhetoric'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Department of Rhetoric faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(RHETORIC_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(RHETORIC_CONFIG, "UC Berkeley Department of Rhetoric Faculty Collector")
