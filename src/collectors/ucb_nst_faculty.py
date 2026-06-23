"""Collector for UC Berkeley Nutritional Sciences & Toxicology (NST) faculty.

A thin department config over src.collectors.ucb_common — the same config-only
path as ucb_chem_faculty. NST (Metabolic Biology & Nutrition) uses the
Open-Berkeley card variant, with one difference: the name sits in an `<h3>`
(not the `<h2>` Chemistry uses). Each profile exposes a mailto: email (plus the
email field) and a free-text `field-openberkeley-person-resint` research block.

Behavior matches the shared path: scrape the listing for name + profile link +
title, dedup, then visit each profile to recover the contact email AND research
interests. Records with no email ship "lite" (contact_email=None,
confidence_score=0.5); records with no research keep the broad department
keyword. Emeritus faculty are dropped by the shared title filter.

Directory: https://nst.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_nst_faculty            # fetch & preview
    python -m src.collectors.ucb_nst_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_nst_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

NST_CONFIG = {
    "source": "ucb_nst_faculty",
    "name": "Department of Nutritional Sciences & Toxicology",
    "short": "NST",
    "url": "https://nst.berkeley.edu/people/faculty",
    "base": "https://nst.berkeley.edu",
    "majors": ["Nutritional Sciences", "Nutritional Science & Toxicology",
               "Molecular Toxicology", "Metabolic Biology"],
    "keywords": ["nutrition"],
    "work_auth_notes": "External campus (UC Berkeley) — work "
                       "authorization depends on the arrangement",
    "selectors": {
        "card": "div.node-openberkeley-person",
        "name": "h3",                                          # name text (NST uses h3)
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
    return ucb_common.fetch_and_normalize(NST_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(NST_CONFIG, "UC Berkeley Nutritional Sciences & Toxicology Faculty Collector")
