"""Collector for UC Berkeley Film & Media faculty.

Config-only department over ``src.collectors.ucb_common``: the Film & Media
directory (https://filmmedia.berkeley.edu/people/faculty) is a standard
"Open Berkeley" person grid (``div.node-openberkeley-person`` cards), so it
reuses ``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape +
profile-enrichment + normalize path — no bespoke parser needed.

Directory: https://filmmedia.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_filmmedia_faculty            # fetch & preview
    python -m src.collectors.ucb_filmmedia_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_filmmedia_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

FILMMEDIA_CONFIG = {
    "source": "ucb_filmmedia_faculty",
    "name": "Department of Film & Media",
    "short": "FILM",
    "url": "https://filmmedia.berkeley.edu/people/faculty",
    "base": "https://filmmedia.berkeley.edu",
    "majors": ["Film", "Media Studies", "Film and Media"],
    "keywords": ["film", "media studies"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Film & Media faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(FILMMEDIA_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(FILMMEDIA_CONFIG, "UC Berkeley Film & Media Faculty Collector")
