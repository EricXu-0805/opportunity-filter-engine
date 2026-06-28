"""Collector for UC Berkeley Department of Scandinavian faculty.

Config-only department over ``src.collectors.ucb_common``: the Department of Scandinavian
directory (https://scandinavian.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://scandinavian.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_scandinavian_faculty            # fetch & preview
    python -m src.collectors.ucb_scandinavian_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_scandinavian_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

SCANDINAVIAN_CONFIG = {
    "source": "ucb_scandinavian_faculty",
    "name": "Department of Scandinavian",
    "short": "SCAND",
    "url": "https://scandinavian.berkeley.edu/people/faculty",
    "base": "https://scandinavian.berkeley.edu",
    "majors": ['Scandinavian'],
    "keywords": ['scandinavian'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Department of Scandinavian faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(SCANDINAVIAN_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(SCANDINAVIAN_CONFIG, "UC Berkeley Department of Scandinavian Faculty Collector")
