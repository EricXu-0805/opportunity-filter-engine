"""Collector for UC Berkeley Chemistry faculty research opportunities.

A thin department config over src.collectors.ucb_common (same path as
ucb_stat_faculty). Chemistry is on a different Open-Berkeley card variant than
Statistics: each listing card is `div.node-openberkeley-person` with the name
in an `<h2>` and the profile href on the wrapping `<a>` (so `name` and `link`
are different selectors). Profile pages expose the email as a mailto: link and
research interests in a free-text `field-openberkeley-person-resint` block.

Behavior matches the shared path: scrape the listing for name + profile link +
title, dedup people appearing in multiple sections, then visit each profile to
recover the contact email AND research interests. Records with no email ship
"lite" (contact_email=None, confidence_score=0.5); records with no research
section keep the broad department keyword.

Directory: https://chemistry.berkeley.edu/faculty/chem

Usage:
    python -m src.collectors.ucb_chem_faculty            # fetch & preview
    python -m src.collectors.ucb_chem_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_chem_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

CHEM_CONFIG = {
    "source": "ucb_chem_faculty",
    "name": "Department of Chemistry",
    "short": "CHEM",
    "url": "https://chemistry.berkeley.edu/faculty/chem",
    "base": "https://chemistry.berkeley.edu",
    "majors": ["Chemistry", "Chemical Biology", "Biochemistry"],
    "keywords": ["chemistry"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        "card": "div.node-openberkeley-person",
        "name": "h2",                                          # name text
        "link": "a[href*='/people/']",                         # profile href
        "title": "div.field-name-field-openberkeley-person-title",
        # Profiles carry both a mailto: link (tried first) and this field.
        "email_field": "div.field-name-field-openberkeley-person-email",
        # Free-text research block; .field-item drops the "Research:" label.
        "research_interests": [
            "div.field-name-field-openberkeley-person-resint .field-item",
        ],
    },
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    return ucb_common.fetch_and_normalize(CHEM_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(CHEM_CONFIG, "UC Berkeley Chemistry Faculty Collector")
