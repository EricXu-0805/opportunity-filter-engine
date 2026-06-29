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

Plus **ECE** and **CEE**, each via its Faculty filter URL — their card name link
reads "Learn more about <Name>", recovered with a ``name_strip`` regex.

Deferred: ME and BME (faculty pages over-list incl. research staff with no clean
rank selector), ChBE (its name link is an empty image link with the named link
second — needs an nth-link selector), and Physics (JS-rendered).

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
        {
            "short": "ECE",
            "name": "School of Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://ece.gatech.edu/directory?field_person_groups_target_id=2323",
            "scrape": {
                "url": "https://ece.gatech.edu/directory?field_person_groups_target_id=2323",
                "selectors": {"card": ".views-row", "name": "a[href^='/directory/']",
                              "link": "a[href^='/directory/']",
                              "name_strip": r"^Learn more about\s+"},
                "ladder_filter": {"drop": r"emerit|adjunct|affiliat|of the practice"
                                          r"|academic professional|research (scientist|engineer)"},
                "paginate": {"param": "page", "start": 1, "max": 8},
            },
        },
        {
            "short": "CEE",
            "name": "School of Civil & Environmental Engineering",
            "majors": ["Civil Engineering", "Environmental Engineering"],
            "directory_url": "https://ce.gatech.edu/people?field_person_faculty_type_target_id=58",
            "scrape": {
                "url": "https://ce.gatech.edu/people?field_person_faculty_type_target_id=58",
                "selectors": {"card": ".views-row", "name": "a[href*='/directory/person/']",
                              "link": "a[href*='/directory/person/']",
                              "name_strip": r"^Learn more about\s+"},
                "ladder_filter": {"drop": r"emerit|adjunct|affiliat|of the practice"
                                          r"|academic professional|research (scientist|engineer)"},
                "paginate": {"param": "page", "start": 1, "max": 8},
            },
        },
        {
            "short": "CHBE",
            "name": "School of Chemical & Biomolecular Engineering",
            "majors": ["Chemical Engineering", "Biomolecular Engineering"],
            "directory_url": "https://chbe.gatech.edu/directory1?field_person_category_target_id=1",
            "scrape": {
                "url": "https://chbe.gatech.edu/directory1?field_person_category_target_id=1",
                "selectors": {"card": ".views-row", "name": "a.dir_link",
                              "link": "a.dir_link",
                              "title": ".field--name-field-person-job-title-s-"},
                "ladder_filter": {"drop": r"emerit|adjunct|affiliat|of the practice"
                                          r"|academic professional"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
