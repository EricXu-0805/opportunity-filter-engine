"""Collector for UC Berkeley Department of Music faculty.

Config-only department over ``src.collectors.ucb_common``: the Department of Music
directory (https://music.berkeley.edu/people/faculty) is a standard "Open Berkeley" person grid
(``div.node-openberkeley-person`` cards), so it reuses
``ucb_common.OPENBERKELEY_PERSON_SELECTORS`` and the shared scrape + profile-
enrichment + normalize path — no bespoke parser needed. Each profile is visited
to recover the contact email and research interests the listing omits.

Directory: https://music.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_music_faculty            # fetch & preview
    python -m src.collectors.ucb_music_faculty --no-enrich  # skip profile hop
    python -m src.collectors.ucb_music_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common
from .ucb_common import OPENBERKELEY_PERSON_SELECTORS

MUSIC_CONFIG = {
    "source": "ucb_music_faculty",
    "name": "Department of Music",
    "short": "MUSIC",
    "url": "https://music.berkeley.edu/people/faculty",
    "base": "https://music.berkeley.edu",
    "majors": ['Music'],
    "keywords": ['music'],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": OPENBERKELEY_PERSON_SELECTORS,
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    """Scrape Department of Music faculty and return normalized opportunity records."""
    return ucb_common.fetch_and_normalize(MUSIC_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(MUSIC_CONFIG, "UC Berkeley Department of Music Faculty Collector")
