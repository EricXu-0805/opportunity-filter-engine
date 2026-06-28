"""Stanford University faculty config (via the faculty_graph engine).

Scrape-first, like UW/GT. Stanford's School of Engineering departments share a
Drupal "stanford-person" node template, so one selector set (``.node
.stanford-person.node-title`` → ``h3 a``) cleanly lists each department's faculty
as one card per person. The card carries only the name + profile link (the job
title and contact live on a separate node variant / the profile page), so these
land as accurate department/major-scoped cold-email targets.

Covers the five engineering departments confirmed to render this template
server-side. Held back pending verified directory URLs / render paths: Computer
Science and Math (their listings are auth-walled or 404 on the obvious paths),
EE (mostly a nav shell), and Physics/Chemistry/Statistics (a different Drupal
"Views" structure — a follow-up once their row selector is pinned down).

Single source ("stanford_faculty"); department rides each record's
``department``, ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Stanford School of Engineering "stanford-person" directory selectors.
_SU_PERSON = {
    "card": ".node.stanford-person.node-title",
    "name": "h3 a",
    "link": "h3 a",
}


def _su(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, "selectors": _SU_PERSON}}


SCHOOL: dict = {
    "school_slug": "stanford",
    "source": "stanford_faculty",
    "organization": "Stanford University",
    "location": "Stanford, CA",
    "id_prefix": "stanford",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Stanford University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _su("ME", "Department of Mechanical Engineering",
            ["Mechanical Engineering"], "https://me.stanford.edu/people/faculty"),
        _su("BIOE", "Department of Bioengineering",
            ["Bioengineering"], "https://bioengineering.stanford.edu/people/faculty"),
        _su("AA", "Department of Aeronautics & Astronautics",
            ["Aeronautics & Astronautics", "Aerospace Engineering"], "https://aa.stanford.edu/people/faculty"),
        _su("MSE", "Department of Materials Science & Engineering",
            ["Materials Science & Engineering"], "https://mse.stanford.edu/people/faculty"),
        _su("CHEME", "Department of Chemical Engineering",
            ["Chemical Engineering"], "https://cheme.stanford.edu/people/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
