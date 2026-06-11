"""Collector for UC Berkeley Statistics faculty research opportunities.

A thin department config over src.collectors.ucb_common, which holds the shared
Open-Berkeley scraping / email-enrichment / normalization logic. Statistics was
the first department on this path; Chemistry and others follow by config.

Behavior: scrape the listing for name + profile link + title, dedup people who
appear in multiple sections, then visit each profile page to recover the
contact email (the listing does not expose it). Records with no email found
ship "lite" (contact_email=None, confidence_score=0.5).

Directory: https://statistics.berkeley.edu/people/faculty

Usage:
    python -m src.collectors.ucb_stat_faculty            # fetch & preview
    python -m src.collectors.ucb_stat_faculty --no-enrich  # skip email hop (fast)
    python -m src.collectors.ucb_stat_faculty --save     # merge into processed data
"""

from __future__ import annotations

from . import ucb_common

STAT_CONFIG = {
    "source": "ucb_stat_faculty",
    "name": "Department of Statistics",
    "short": "STAT",
    "url": "https://statistics.berkeley.edu/people/faculty",
    "base": "https://statistics.berkeley.edu",
    "majors": ["Statistics", "Data Science", "Applied Mathematics"],
    "keywords": ["statistics"],
    "selectors": {
        "card": "article.node--type-faculty",
        "name": "h3 a",                              # name text (also the link)
        "link": "h3 a",                              # profile href
        "title": "div.field--name-field-job-title",
        # Profile-page email field (no mailto: link on STAT profiles).
        "email_field": "div.field--name-field-email",
    },
}


def fetch_and_normalize(enrich: bool = True) -> list[dict]:
    return ucb_common.fetch_and_normalize(STAT_CONFIG, enrich=enrich)


if __name__ == "__main__":
    ucb_common.run_cli(STAT_CONFIG, "UC Berkeley Statistics Faculty Collector")
