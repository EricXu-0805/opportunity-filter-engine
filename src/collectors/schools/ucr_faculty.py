"""UC Riverside faculty config (via the faculty_graph engine).

UCR is a uniform platform: every department directory is a JS-SPA shell that
embeds an iframe from ``profiles.ucr.edu`` (the campus Interfolio-style profile
system). The real roster is one authoritative JSON endpoint —

    GET https://profiles.ucr.edu/api/profile?groupId=<GID>&affiliationFilter=All&...

— returning a flat array of faculty objects with ``name``, ``title``, ``email``
(100% populated on every group), and a clean controlled-vocabulary
``researchAreas`` string array. So the single path here is the generic
``json_dir`` source pointed at the profile API, one dept per faculty group id
(all field mappings identical; only the group id differs). Group ids + counts
live-verified 2026-07-19.

The feed carries no per-person profile URL (the SPA builds it client-side from
``netId``), which ``json_dir`` can't template — so records fall back to each
department's human directory URL (an accepted engine pattern), and joint
appointments de-dupe on the always-present email.

Each department is queried on its CORE / tenure-track faculty group (not the
broad "All Faculty" superset), so emeriti / adjunct / cooperating cross-lists
stay out; the engine's retired-title gate drops the lone emeritus that rides a
core group. Teaching-track (LPSOE) professors are kept — real faculty who
mentor undergrads (mirrors the ncsu lecturer precedent).

Deferred: Chemistry's broad ``groupId=99486`` "All Faculty" (48) folds in
cross-listed Atmospheric Science / MSE / Biochemistry / Bioengineering
appointments — the tenure-track subset ``114198`` (36) is used instead.
"""

from __future__ import annotations

from .. import faculty_graph

# The campus profile API. One flat JSON array per faculty group; the same field
# names on every group, so one shared mapping serves all departments.
_API = (
    "https://profiles.ucr.edu/api/profile?acctStruct=&groupId={gid}"
    "&researchArea=&affiliationFilter=All&excludeStudentEmployees=false"
    "&excludeSecondaryDepartmentEmployees=false&excludeAffiliates=false"
)

# Shared field mapping (name/title/email scalars; researchAreas is a clean
# controlled-vocab string array → keywords). No link field in the feed → each
# record falls back to its department directory_url.
_MAP = {
    "name_fields": ["name"],
    "title_field": "title",
    "email_field": "email",
    "research_field": "researchAreas[]",
}


def _dept(short: str, name: str, majors: list[str], directory: str, gid: int) -> dict:
    """A UCR department fetched from the profiles.ucr.edu group JSON feed."""
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": directory,
        "json_dir": {"url": _API.format(gid=gid), **_MAP},
    }


SCHOOL: dict = {
    "school_slug": "ucr",
    "source": "ucr_faculty",
    "organization": "University of California, Riverside",
    "location": "Riverside, CA",
    "id_prefix": "ucr",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of California, Riverside) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Marlan and Rosemary Bourns College of Engineering ------------
        _dept("CS", "Department of Computer Science & Engineering",
              ["Computer Science", "Computer Engineering"],
              "https://www1.cs.ucr.edu/people/faculty", 1787),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.ucr.edu/Tenure-Track-Faculty", 4108),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              "https://me.ucr.edu/about/faculty", 12716),
        _dept("BME", "Department of Bioengineering",
              ["Bioengineering", "Biomedical Engineering"],
              "https://bioeng.ucr.edu/about/faculty", 4462),
        # ---- College of Natural and Agricultural Sciences -----------------
        _dept("Physics", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"],
              "https://www.physics.ucr.edu/people/faculty", 15357),
        _dept("Chemistry", "Department of Chemistry", ["Chemistry"],
              "https://chem.ucr.edu/people/faculty", 114198),
        _dept("Statistics", "Department of Statistics", ["Statistics"],
              "https://statistics.ucr.edu/people/faculty", 110795),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
