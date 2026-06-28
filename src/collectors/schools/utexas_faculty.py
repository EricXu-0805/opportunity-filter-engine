"""UT Austin faculty config (via the faculty_graph engine).

Scrape-first, like UW/GT/Stanford. UT Austin's departments run separate CMSes;
this covers the two whose directories are server-rendered Drupal "Views" grids:

  * **Computer Science** (``www.cs.utexas.edu/people``) — a rich grid that
    exposes each professor's research groups inline, so CS faculty land fully
    keyworded (UIUC-level richness).
  * **Electrical & Computer Engineering** (``ece.utexas.edu/people/faculty``) —
    a ``facentry`` grid with name + position (no inline research), so ECE
    faculty land as accurate major-scoped cold-email targets.

Held back: the Cockrell School engineering departments (ME, ChemE, AE, Civil,
BME) render their faculty via a JS WordPress block, and Physics/Chemistry/Math
404 on the obvious paths — all need the headless path or a confirmed URL before
shipping, rather than a guessed scrape.

Single source ("utexas_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

SCHOOL: dict = {
    "school_slug": "utexas",
    "source": "utexas_faculty",
    "organization": "The University of Texas at Austin",
    "location": "Austin, TX",
    "id_prefix": "utexas",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UT Austin) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Computer Engineering", "Data Science"],
            "directory_url": "https://www.cs.utexas.edu/people",
            "scrape": {
                "url": "https://www.cs.utexas.edu/people",
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-contact-faculty",
                    "research": ".views-field-field-research-groups",
                },
            },
        },
        {
            "short": "ECE",
            "name": "Chandra Family Department of Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering"],
            "directory_url": "https://ece.utexas.edu/people/faculty",
            "scrape": {
                "url": "https://ece.utexas.edu/people/faculty",
                "selectors": {
                    "card": ".facentry",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-faculty-position",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
