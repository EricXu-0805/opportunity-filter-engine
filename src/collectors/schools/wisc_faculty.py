"""UW-Madison faculty config (via the faculty_graph engine).

Scrape-first, like the other peer schools. UW-Madison's departments run
different CMSes on inconsistent URL paths; this covers the one whose directory is
a cleanly server-rendered WordPress grid:

  * **Computer Science** (``www.cs.wisc.edu/people/faculty-2/``) — a
    ``faculty-member-content`` grid with name + a public mailto inline, so CS
    faculty land as accurate, emailed cold-email targets.

Deferred until their real directory URL / render path is confirmed: ECE, ME,
BME, Physics, Chemistry, Math, Statistics (404 on the obvious paths, rate-limit,
or a different structure) — a guessed scrape would risk a wrong count, so they
wait.

Single source ("wisc_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

SCHOOL: dict = {
    "school_slug": "wisc",
    "source": "wisc_faculty",
    "organization": "University of Wisconsin-Madison",
    "location": "Madison, WI",
    "id_prefix": "wisc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UW-Madison) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "Department of Computer Sciences",
            "majors": ["Computer Science", "Data Science"],
            "directory_url": "https://www.cs.wisc.edu/people/faculty-2/",
            "scrape": {
                "url": "https://www.cs.wisc.edu/people/faculty-2/",
                "selectors": {
                    "card": ".faculty-member-content",
                    "name": ".faculty-name a",
                    "link": ".faculty-name a",
                    "email": "a[href^='mailto:']",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
