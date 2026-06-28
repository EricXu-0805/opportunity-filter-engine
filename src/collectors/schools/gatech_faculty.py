"""Georgia Tech faculty config (via the faculty_graph engine).

Scrape-first, like UW. Georgia Tech's schools each run their own CMS on different
URL conventions, so coverage grows department by department as each directory's
real URL + render path is confirmed. Accuracy over breadth: a department is only
included once its scrape is verified to terminate cleanly and yield real faculty
(not staff/affiliates).

Currently: the **College of Computing** — a paginated Drupal card grid
(``card-block``) covering the CS, Interactive Computing, and Computational
Science & Engineering schools, ~228 faculty across 19 pages followed via
``?page=N`` (verified to terminate, not wrap). Cards carry name + title (no
inline research/email), so faculty land as accurate major-scoped cold-email
targets.

Deferred (need verified directory URLs / accurate dept scoping before shipping):
ME (its faculty page over-lists ~280 incl. research staff), BME / CEE (Drupal
"Views" with a different name field), and ECE / Physics / Chemistry / Math
(directories 404 on the obvious paths or render via JS).

Single source ("gatech_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown" (per-prof openness).
"""

from __future__ import annotations

from .. import faculty_graph

SCHOOL: dict = {
    "school_slug": "gatech",
    "source": "gatech_faculty",
    "organization": "Georgia Institute of Technology",
    "location": "Atlanta, GA",
    "id_prefix": "gatech",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Georgia Tech) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "College of Computing",
            "majors": ["Computer Science", "Computer Engineering", "Computational Media", "Cybersecurity"],
            "directory_url": "https://www.cc.gatech.edu/people/faculty",
            "scrape": {
                "url": "https://www.cc.gatech.edu/people/faculty",
                "selectors": {
                    "card": ".card-block",
                    "name": ".card-block__title a",
                    "link": ".card-block__title a",
                    "title": ".card-block__subtitle",
                },
                "paginate": {"param": "page", "start": 1, "max": 22},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
