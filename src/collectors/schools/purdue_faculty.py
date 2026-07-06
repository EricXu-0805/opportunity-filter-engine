"""Purdue University faculty config (via the faculty_graph engine).

Purdue's directories are server-rendered, so they scrape with a plain request
(no headless browser). Computer Science exposes a ``.people-item`` grid with the
name + rank on the listing (~120 ladder professors across the West Lafayette and
Indianapolis campuses); the public email lives on each person's profile page
(``.bio-email``), recovered by the gated per-profile enrichment pass. More Purdue
departments (Engineering, Sciences) can be added as their markup is identified.

Single source ("purdue_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit"}


SCHOOL: dict = {
    "school_slug": "purdue",
    "source": "purdue_faculty",
    "organization": "Purdue University",
    "location": "West Lafayette, IN",
    "id_prefix": "purdue",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Purdue University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Data Science"],
            "directory_url": "https://www.cs.purdue.edu/people/faculty/index.html",
            "scrape": {
                "url": "https://www.cs.purdue.edu/people/faculty/index.html",
                "selectors": {
                    "card": ".people-item",
                    "name": ".people-name a",
                    "link": ".people-name a",
                    "title": ".people-title",
                },
                "ladder_filter": _LADDER,
                # Email is not on the listing; the profile page carries it in
                # ``.bio-email``. Gated per-profile pass (OFE_ENRICH_PROFILES);
                # plain fetch (Purdue profiles are server-rendered too).
                "profile_enrich": {
                    "email_selector": ".bio-email a[href^='mailto:']",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
