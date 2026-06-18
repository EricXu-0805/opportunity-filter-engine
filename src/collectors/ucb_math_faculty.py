"""Collector for UC Berkeley Mathematics faculty research opportunities.

A thin department config over src.collectors.ucb_common — the same config-only
path as ucb_chem_faculty. Math runs the identical Open-Berkeley card variant as
Chemistry: each listing card is `div.node-openberkeley-person` with the name in
an `<h2>` and the profile href on a `/people/` link, and each profile exposes a
mailto: email (plus the same field) and a free-text research-interests block.

Behavior matches the shared path: scrape the listing for name + profile link +
title, dedup, then visit each profile to recover the contact email AND research
interests. Records with no email ship "lite" (contact_email=None,
confidence_score=0.5); records with no research section keep the broad
department keyword. Emeritus faculty are dropped by the shared title filter.

Note: Math profiles list the department front office (frontoffice@math.berkeley
.edu) as a second mailto; it's in ucb_common.NOISE_EMAILS so a professor whose
personal address is non-Berkeley doesn't resolve to it.

Directory: https://math.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_math_faculty            # fetch & preview
    python -m src.collectors.ucb_math_faculty --no-enrich  # skip profile hop (fast)
    python -m src.collectors.ucb_math_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

MATH_CONFIG = {
    "source": "ucb_math_faculty",
    "name": "Department of Mathematics",
    "short": "MATH",
    "url": "https://math.berkeley.edu/people/faculty",
    "base": "https://math.berkeley.edu",
    "majors": ["Mathematics", "Applied Mathematics", "Statistics"],
    "keywords": ["mathematics"],
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
    return ucb_common.fetch_and_normalize(MATH_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(MATH_CONFIG, "UC Berkeley Mathematics Faculty Collector")
