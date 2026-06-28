"""Collector for UC Berkeley Department of German faculty.

Config-only department over ``src.collectors.ucb_common``: the Department of German
directory (https://german.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://german.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_german_faculty            # fetch & preview
    python -m src.collectors.ucb_german_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_german_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

GERMAN_CONFIG = {
    "source": "ucb_german_faculty",
    "name": "Department of German",
    "short": "GERMAN",
    "url": "https://german.berkeley.edu/people/faculty",
    "base": "https://german.berkeley.edu",
    "majors": ['German', 'German Studies'],
    "keywords": ['german'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Department of German faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(GERMAN_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(GERMAN_CONFIG, "UC Berkeley Department of German Faculty Collector")
