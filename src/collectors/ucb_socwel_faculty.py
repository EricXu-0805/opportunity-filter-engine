"""Collector for UC Berkeley School of Social Welfare faculty.

A thin department config over src.collectors.ucb_common — the same config-only
path as ucb_chem_faculty / ucb_nst_faculty. Berkeley Social Welfare uses the
Open-Berkeley card variant with the name in an `<h3>` (like NST), a title field,
and a `/people/<slug>` profile link. Each profile exposes a mailto: email (plus
the email field) and a free-text `field-openberkeley-person-resint` research
block.

Behavior matches the shared path: scrape the listing for name + profile link +
title, dedup, then visit each profile to recover the contact email AND research
interests. Records with no email ship "lite" (contact_email=None,
confidence_score=0.5); records with no research keep the broad department
keyword. The directory mixes in ~20 emeritus faculty, dropped by the shared
title filter.

Directory: https://socialwelfare.berkeley.edu/faculty

Usage:
    python -m src.collectors.ucb_socwel_faculty            # fetch & preview
    python -m src.collectors.ucb_socwel_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_socwel_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

SOCWEL_CONFIG = {
    "source": "ucb_socwel_faculty",
    "name": "School of Social Welfare",
    "short": "SOCWEL",
    "url": "https://socialwelfare.berkeley.edu/faculty",
    "base": "https://socialwelfare.berkeley.edu",
    "majors": ["Social Welfare", "Social Work"],
    "keywords": ["social welfare"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        "card": "div.node-openberkeley-person",
        "name": "h3",                                          # name text (uses h3, like NST)
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
    return ucb_common.fetch_and_normalize(SOCWEL_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(SOCWEL_CONFIG, "UC Berkeley School of Social Welfare Faculty Collector")
