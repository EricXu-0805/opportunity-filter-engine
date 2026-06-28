"""University of Washington faculty config (via the faculty_graph engine).

Unlike Michigan (whose directories are Cloudflare-walled, so it ships a curated
hand-verified set), UW's department directories are server-rendered and
scrapable, so this config is scrape-first: each department carries a ``scrape``
block (directory URL + CSS selectors) and deep mode lands real, current faculty
live. No curated seed list to hand-maintain.

Two directory shapes on campus:
  * **ECE** uses the College-of-Engineering ``stafftemplate`` card, which exposes
    research interests + a mailto inline — so its faculty land fully keyworded
    in one pass (UIUC-level richness).
  * **The College of Arts & Sciences departments** (Physics, Chemistry,
    Mathematics) use a shared Drupal "Views" directory that lists
    name + job title + email but not research areas, so those faculty land as
    keyword-light cold-email targets (department majors drive matching;
    per-profile research enrichment is a follow-up, the same path UIUC took).

Departments behind a JS facultyfinder app (most of the College of Engineering)
or a client-rendered list (the Allen School) are intentionally omitted — a
stdlib scraper lands zero there; they need the headless-browser path.

Single source ("uw_faculty") across departments (the UIUC model); the
department rides each record's ``department`` field, ids namespaced by
department short-code. Audience "unknown" — cross-school openness is per-prof.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Drupal "Views" directory selectors (UW College of Arts & Sciences).
_CAS_SELECTORS = {
    "card": "div.views-row",
    "name": ".views-field-title a",
    "link": ".views-field-title a",
    "title": ".views-field-field-job-title .field-content",
    "email": ".views-field-field-email a",
}


def _cas(short: str, name: str, majors: list[str], url: str) -> dict:
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _CAS_SELECTORS},
    }


SCHOOL: dict = {
    "school_slug": "uw",
    "source": "uw_faculty",
    "organization": "University of Washington",
    "location": "Seattle, WA",
    "id_prefix": "uw",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Washington) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "ECE",
            "name": "Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering"],
            "directory_url": "https://www.ece.uw.edu/faculty/",
            "scrape": {
                "url": "https://www.ece.uw.edu/faculty/",
                "selectors": {
                    "card": ".stafftemplate--entry",
                    "name": ".stafftemplate--name a",
                    "link": ".stafftemplate--name a",
                    "title": ".stafftemplate--title",
                    "research": ".stafftemplate--interests",
                    "email": ".stafftemplate--email a",
                },
            },
        },
        _cas("PHYS", "Department of Physics",
             ["Physics", "Applied Physics", "Astrophysics"],
             "https://phys.washington.edu/people/faculty"),
        _cas("CHEM", "Department of Chemistry",
             ["Chemistry", "Biochemistry"],
             "https://chem.washington.edu/people/faculty"),
        _cas("MATH", "Department of Mathematics",
             ["Mathematics", "Applied Mathematics"],
             "https://math.washington.edu/people/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
