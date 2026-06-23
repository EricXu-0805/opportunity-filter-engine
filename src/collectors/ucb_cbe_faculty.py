"""Collector for UC Berkeley Chemical & Biomolecular Engineering (CBE) faculty.

A thin department config over src.collectors.ucb_common — the same config-only
path as ucb_chem_faculty. CBE is listed on the College of Chemistry site and
uses the identical Open-Berkeley card variant as Chemistry: each listing card is
`div.node-openberkeley-person` with the name in an `<h2>` and the profile href
on a `/people/` link, and each profile exposes a mailto: email (plus the email
field) and a free-text `field-openberkeley-person-resint` research block.

Behavior matches the shared path: scrape the listing for name + profile link +
title, dedup, then visit each profile to recover the contact email AND research
interests. Records with no email ship "lite" (contact_email=None,
confidence_score=0.5); records with no research section keep the broad
department keyword. Emeritus faculty are dropped by the shared title filter.

Directory: https://chemistry.berkeley.edu/faculty/cbe

Usage:
    python -m src.collectors.ucb_cbe_faculty            # fetch & preview
    python -m src.collectors.ucb_cbe_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_cbe_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

CBE_CONFIG = {
    "source": "ucb_cbe_faculty",
    "name": "Department of Chemical & Biomolecular Engineering",
    "short": "CBE",
    "url": "https://chemistry.berkeley.edu/faculty/cbe",
    "base": "https://chemistry.berkeley.edu",
    "majors": ["Chemical Engineering", "Chemical & Biomolecular Engineering",
               "Biomolecular Engineering"],
    "keywords": ["chemical engineering"],
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
    return ucb_common.fetch_and_normalize(CBE_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(CBE_CONFIG, "UC Berkeley Chemical & Biomolecular Engineering Faculty Collector")
