"""Collector for UC Berkeley Astronomy faculty research opportunities.

A thin department config over src.collectors.ucb_common — the same config-only
path as ucb_chem_faculty. Astronomy uses the identical Open-Berkeley card
variant: each listing card is `div.node-openberkeley-person` with the name in
an `<h2>` and the profile href on a `/people/` link, and each profile exposes a
mailto: email (plus the email field) and a free-text
`field-openberkeley-person-resint` research block.

Behavior matches the shared path: scrape the listing for name + profile link +
title, dedup, then visit each profile to recover the contact email AND research
interests. Records with no email ship "lite" (contact_email=None,
confidence_score=0.5); records with no research keep the broad department
keyword. Emeritus faculty are dropped by the shared title filter.

Directory: https://astro.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_astro_faculty            # fetch & preview
    python -m src.collectors.ucb_astro_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_astro_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

ASTRO_CONFIG = {
    "source": "ucb_astro_faculty",
    "name": "Department of Astronomy",
    "short": "ASTRO",
    "url": "https://astro.berkeley.edu/people/faculty",
    "base": "https://astro.berkeley.edu",
    "majors": ["Astrophysics", "Astronomy", "Physics"],
    "keywords": ["astronomy"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        "card": "div.node-openberkeley-person",
        "name": "h2",                                          # name text
        "link": "a[href*='/people/']",                         # profile href
        "title": "div.field-name-field-openberkeley-person-title",
        # Profiles carry both a mailto: link (tried first) and this field.
        "email_field": "div.field-name-field-openberkeley-person-email",
        # Free-text research block; .field-item drops the "Research interests:" label.
        "research_interests": [
            "div.field-name-field-openberkeley-person-resint .field-item",
        ],
    },
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    return ucb_common.fetch_and_normalize(ASTRO_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(ASTRO_CONFIG, "UC Berkeley Astronomy Faculty Collector")
