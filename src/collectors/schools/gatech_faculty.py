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

Also shipped, each via its department's faculty-only filter URL (verified to
yield real ladder faculty, not staff/affiliates):

  * **Chemistry & Biochemistry** — the "Academic Faculty / Tenure-Track" page
    (``div.person`` cards, name in ``h3``); Emeriti/Instructional/Research/
    Adjunct live on sibling pages, so this is ladder-clean.
  * **Mathematics** — the ``field_job_type_tid=11`` (Faculty) table.
  * **Materials Science & Engineering** — the ``1FTE`` (FTE Faculty) Views grid,
    with public emails inline.

Deferred (need slug-derived names / pagination / accurate scoping before
shipping): ME and BME (faculty pages over-list incl. research staff with no
clean rank selector), ECE / CEE / ChBE (their card's name link reads "Learn
more about …" — a slug-name pass is needed), and Physics (JS-rendered).

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
        {
            "short": "CHEM",
            "name": "School of Chemistry and Biochemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://chemistry.gatech.edu/faculty/academic-faculty-PI",
            "scrape": {
                "url": "https://chemistry.gatech.edu/faculty/academic-faculty-PI",
                "selectors": {"card": "div.person", "name": "h3",
                              "link": "a[href*='/people/']"},
            },
        },
        {
            "short": "MATH",
            "name": "School of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics"],
            "directory_url": "https://math.gatech.edu/people?field_job_type_tid=11",
            "scrape": {
                "url": "https://math.gatech.edu/people?field_job_type_tid=11",
                "selectors": {"card": "tr", "name": "td a", "link": "td a"},
            },
        },
        {
            "short": "MSE",
            "name": "School of Materials Science and Engineering",
            "majors": ["Materials Science and Engineering", "Materials Science"],
            "directory_url": "https://www.mse.gatech.edu/people?field_personnel_group_value_1=1FTE",
            "scrape": {
                "url": "https://www.mse.gatech.edu/people?field_personnel_group_value_1=1FTE",
                "selectors": {"card": ".views-row", "name": "a[href*='/people/']",
                              "link": "a[href*='/people/']", "email": "a[href^='mailto:']"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
