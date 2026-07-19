"""Arizona State University faculty config (via the faculty_graph engine).

ASU is a single-platform school: every department directory on campus is a
client-side JS widget (the WordPress "pitchfork-people" plugin on the
engineering sites, the Drupal "clas-isearch" React widget on the CLAS sites)
that renders its roster from ONE authoritative backend — the ASU iSearch
directory API (``https://search.asu.edu/api/v1/webdir-profiles/faculty-staff/
filtered``, no auth). The names are NOT in the server HTML on any of these
pages, so the reliable path is the JSON API, not CSS scraping. All dept ids,
the record shape, and the faculty filter were live-verified 2026-07-19.

One shared ``json_dir`` field mapping serves every department — only the
``dept_ids`` query param changes. Record shape: each field is a ``{"raw": …}``
box, so dotted paths (``display_name.raw``, ``primary_title.raw``,
``email_address.raw``) read the value; ``size=1000`` returns the whole roster
in one page (the largest unit, SoMSS, is 276 rows → still one page).

Faculty filter (two gates, high precision):
* ``primary_empl_class.raw == "Faculty"`` — the authoritative faculty flag that
  drops the University Staff, Graduate Assistant/Associate, Post-Doctoral
  Scholars, and Academic-Professional rows the same feed carries (e.g. the CS
  unit's 235 records → 113 faculty).
* a title ``ladder_filter`` — keep professor/instructor/lecturer ranks (incl.
  the research-track Research/Regents/President's/Teaching professors, who run
  labs), drop Emeritus / Adjunct / Visiting and the part-time "Faculty
  Associate" instructional rows.

Keywords: ``expertise_areas.raw`` is a clean controlled-vocabulary LIST when
present (~40–65% of faculty) — folded straight into keyword chips via the
``[]`` fan-out. ``research_interests.raw`` is HTML prose (not clean keywords),
so it is deliberately NOT used. Faculty without an expertise list ship
name+title+email+department (OpenAlex/LLM enrichment backfills topics later).
Link: ``website.raw`` (a per-person homepage/lab site where the profile
declares one — always an absolute http(s) URL; verified 0 relative values);
absent, the record falls back to its department directory URL.

Several "departments" here are ASU *schools* that house multiple degree
programs under one iSearch unit id, and the API exposes no clean sub-filter to
split them (the human pages filter client-side by a hard-coded asurite
exclude-list we can't reconstruct). Rather than ship a mis-scoped slice, each
is modeled as its whole school with a multi-program ``majors`` list:
* SCAI (id 1661) = School of Computing & Augmented Intelligence — CS + Software
  Engineering + Industrial Engineering.
* SEMTE (id 1662) = School for Engineering of Matter, Transport & Energy —
  Aerospace/Mechanical + Chemical Engineering + Materials Science.
* SMS (id 1734) = School of Molecular Sciences — Chemistry + Biochemistry.
* SoMSS (id 2243) = School of Mathematical & Statistical Sciences — Mathematics
  + Statistics (ASU has no standalone Statistics department).

Single source ("asu_faculty"); department rides each record, ids namespaced by
department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# ---- shared ASU iSearch directory API mapping ------------------------------
_ISEARCH = ("https://search.asu.edu/api/v1/webdir-profiles/faculty-staff/"
            "filtered?dept_ids={ids}&size=1000&page=1")

# Keep ladder + teaching + research-track + instructor/lecturer ranks; drop the
# retired/visiting/adjunct and the part-time "Faculty Associate" rows. The
# empl_class gate already removes staff/students/postdocs, so this only prunes
# the non-PI faculty ranks the feed still tags "Faculty".
_LADDER = {"require": r"professor|instructor|lecturer",
           "drop": r"emerit|adjunct|visiting"}


def _dept(short: str, name: str, majors: list[str], dept_ids: str,
          directory_url: str) -> dict:
    """One ASU unit fetched from the shared iSearch API (dept_ids is the only
    per-department variable)."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": directory_url,
        "json_dir": {
            "url": _ISEARCH.format(ids=dept_ids),
            "records_key": "results",
            "name_fields": ["display_name.raw"],
            "title_field": "primary_title.raw",
            "email_field": "email_address.raw",
            "link_field": "website.raw",
            "status_field": "primary_empl_class.raw",
            "status_value": "Faculty",
            "research_field": ["expertise_areas.raw[]"],
            "ladder_filter": _LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "asu",
    "source": "asu_faculty",
    "organization": "Arizona State University",
    "location": "Tempe, AZ",
    "id_prefix": "asu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Arizona State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Ira A. Fulton Schools of Engineering --------------------------
        _dept("CS", "School of Computing and Augmented Intelligence",
              ["Computer Science", "Software Engineering",
               "Industrial Engineering", "Computer Engineering"],
              "1661",
              "https://faculty.engineering.asu.edu/directory/scai/computer-science-and-engineering/"),
        _dept("ECE", "School of Electrical, Computer and Energy Engineering",
              ["Electrical Engineering", "Computer Engineering",
               "Electrical Systems Engineering"],
              "1663",
              "https://faculty.engineering.asu.edu/directory/ecee/"),
        _dept("SEMTE", "School for Engineering of Matter, Transport and Energy",
              ["Mechanical Engineering", "Aerospace Engineering",
               "Chemical Engineering", "Materials Science and Engineering"],
              "1662",
              "https://faculty.engineering.asu.edu/directory/semte/aerospace-and-mechanical-engineering/"),
        _dept("BME", "School of Biological and Health Systems Engineering",
              ["Biomedical Engineering"],
              "1659",
              "https://faculty.engineering.asu.edu/directory/sbhse/"),
        # ---- The College of Liberal Arts and Sciences ----------------------
        _dept("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
              "1735",
              "https://physics.asu.edu/directory/faculty"),
        _dept("CHEM", "School of Molecular Sciences", ["Chemistry", "Biochemistry"],
              "1734",
              "https://sms.asu.edu/People/Faculty"),
        _dept("MATH", "School of Mathematical and Statistical Sciences",
              ["Mathematics", "Statistics", "Applied Mathematics"],
              "2243",
              "https://math.asu.edu/faculty/all"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
