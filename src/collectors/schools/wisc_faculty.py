"""UW-Madison faculty config (via the faculty_graph engine).

Scrape-first, like the other peer schools. UW-Madison's departments run
different CMSes; this covers each via the cleanest source it exposes:

  * **Computer Science** (``www.cs.wisc.edu/people/faculty-2/``) — a
    ``faculty-member-content`` grid with name + public mailto inline.
  * **ECE / Mechanical / Biomedical Engineering** — the College of Engineering's
    shared ``directory.engr.wisc.edu/<dept>/`` lists faculty and staff together
    in ``div.profileDisplay`` cards; a ``link_filter`` keeps only the ``/Faculty/``
    profile links (the staff carry ``/Staff/``), with public emails inline.
  * **Mathematics** — a WordPress ``uw_staff`` post type filtered to the
    Professor / Associate / Assistant ``uw_staff_type`` terms (name un-inverted
    from "Last, First").
  * **Physics / Statistics** — the same ``faculty-member-content`` theme on a
    single page. Physics' ``/people/faculty/`` is faculty-only (Chair + the
    Department & Affiliated Faculty), so a flat card scrape lands all of it.
    Statistics lists Faculty, Teaching Faculty, Affiliate, and Emeritus on one
    page with no per-card class or rank that separates them (an Affiliate carries
    a real "Professor, <other dept>" title), so a ``section_filter`` keeps only
    the cards under the ``Faculty`` heading; names un-inverted from "Last, First".

Deferred: Chemistry (an AWS load-balancer bot-challenge returns an empty body) —
needs the headless path.

Single source ("wisc_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph


# College of Engineering shared directory: faculty and staff share the page, so
# keep only the /Faculty/ profile links; the profileSubText cell is contact info
# (not research), so these land as emailed name+title cold-email targets.
def _engr(short: str, name: str, majors: list[str], code: str) -> dict:
    url = f"https://directory.engr.wisc.edu/{code}/"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "link_filter": r"/Faculty/",
                       "selectors": {"card": "div.profileDisplay",
                                     "name": "h3.display a.display",
                                     "link": "h3.display a.display",
                                     "title": "p.title",
                                     "email": "a[href^='mailto:']"}}}


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
        _engr("ECE", "Department of Electrical & Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"], "ece"),
        _engr("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"], "me"),
        _engr("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"], "bme"),
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics"],
            "directory_url": "https://www.math.wisc.edu/people/",
            "api": {"type": "wp", "base": "https://www.math.wisc.edu",
                    "post_type": "uw_staff",
                    "category_include": {"uw_staff_type": [20, 21, 22]},
                    "name_flip": True},
        },
        {
            "short": "PHYS",
            "name": "Department of Physics",
            "majors": ["Physics", "Applied Physics", "Astrophysics"],
            "directory_url": "https://www.physics.wisc.edu/people/faculty/",
            "scrape": {
                "url": "https://www.physics.wisc.edu/people/faculty/",
                "selectors": {"card": ".faculty-member-content",
                              "name": "h3 a", "link": "h3 a"},
            },
        },
        {
            "short": "STAT",
            "name": "Department of Statistics",
            "majors": ["Statistics", "Data Science"],
            "directory_url": "https://stat.wisc.edu/people/",
            "scrape": {
                "url": "https://stat.wisc.edu/people/",
                "name_flip": True,
                "section_filter": {"include": r"^faculty$"},
                "selectors": {"card": ".faculty-member-content",
                              "name": "h3 a", "link": "h3 a"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
