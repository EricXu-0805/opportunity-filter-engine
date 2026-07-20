"""Drexel University faculty config (via the faculty_graph engine).

Drexel's department directories are almost all client-rendered (the College of
Engineering CS/ECE/MEM "people" pages are JS-only React apps that a stdlib
request lands empty), so this pass ships ONLY the one server-rendered source:
the College of Arts & Sciences (COAS) combined faculty directory. One page —
``drexel.edu/coas/faculty-research/faculty-directory/`` — lists every COAS
department's people in a single HTML ``<table>`` of ``tr.FacultyTableRow`` rows,
so Physics, Chemistry, and Mathematics are three ``link_filter`` slices of the
same fetch (plain HTTP 200, no WAF, no JS render).

Row markup (one ``tr.FacultyTableRow``):

* the row's class list carries a **track token** the department itself assigns —
  ``faculty`` (tenure-track / research ladder), ``teaching`` (teaching-track
  professors), ``emeriti``/``emeritus`` (retired), ``adjunct``, ``affiliated``,
  ``research``, ``visiting``, ``postdoc``, ``Courtesy`` (primary appointment in
  another department). The card selector keys off ``.faculty`` so the class IS
  the gate (same approach as Utah Math's ``tenure-line`` selector): teaching
  professors, emeriti, adjuncts, and — critically — cross-listed affiliates/
  courtesy appointees (whose "Professor" title would slip any title gate but
  whose home department is elsewhere) are all excluded by construction.
* the first ``<td>`` holds a ``.fcontact`` block: ``.fname h3 a`` is the name +
  profile link (``/coas/faculty-research/faculty-directory/<dept>/<slug>/`` — the
  ``<dept>`` segment is the per-department ``link_filter`` key), then the rank as
  bare text between ``<br>`` markup (no element of its own — extracted with
  ``title_html_re``, which strips tags + unescapes), then office, then a
  ``mailto`` — a real address on essentially every ladder row (high email yield).
* the third ``<td>`` is a semicolon/comma-delimited "Research & Teaching
  Interests" list in a ``span.no-bullets`` (the department ``<td>`` uses
  ``ul.no-bullets``, so ``span.no-bullets`` targets only the research cell) —
  every ladder row publishes one, so faculty land keyworded in a single pass
  (the engine's ``_clean_keywords`` splits the list and drops the occasional
  prose bio that a few cells carry instead of a clean list).

Title gate (``ladder_filter`` require ``professor|lecturer``): a safety net on
top of the ``.faculty`` class gate — every kept row's rank already contains
"Professor", and the engine's own ``_RETIRED_TITLE_RE`` drops any "Professor
Emeritus" the class token missed. Accuracy over recall: research-track lab PIs
who take undergraduates, not the teaching/emeriti/adjunct rows the directory
mixes in.

DROPPED — Computer Science, Electrical & Computer Engineering, Mechanical
Engineering & Mechanics: the College of Engineering "people" directories render
client-side (React); a stdlib fetch returns the app shell with zero cards, so
there is no server-rendered roster to scrape this pass.

Single source ("drexel_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-20 (``.faculty``-track rows kept after the ladder gate):
Physics 17, Chemistry 9, Mathematics 20 -> 46 total. Emails land on nearly every
record (the COAS directory publishes a plain ``mailto`` per ladder row).
"""

from __future__ import annotations

from .. import faculty_graph

# The shared COAS faculty-directory row. Card = the department-assigned
# ``.faculty`` track token (tenure/research ladder only); the per-department
# ``link_filter`` slices this one page by the profile-URL ``<dept>`` segment.
# The rank is bare text between the name div's ``</h3></div>`` and the next
# ``<br>`` — no element of its own, so ``title_html_re`` captures it (the engine
# strips tags + unescapes group 1). Email is the ``mailto`` in the ``.fcontact``
# block.
_SEL = {
    "card": "tr.FacultyTableRow.faculty",
    "name": ".fname h3 a",
    "link": ".fname h3 a",
    "title_html_re": r"</h3>\s*</div>\s*<br\s*/?>\s*(.*?)\s*<br",
    "research": "span.no-bullets",
    "email": "a[href^='mailto:']",
}
_LADDER = {"require": r"professor|lecturer"}
_URL = "https://drexel.edu/coas/faculty-research/faculty-directory/"


def _dept(short: str, name: str, majors: list[str], seg: str) -> dict:
    """A COAS department: one slice of the shared directory, keyed by the
    profile-URL ``<dept>`` segment (``physics`` / ``chemistry`` / ``mathematics``)."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": _URL,
        "scrape": {
            "url": _URL, "selectors": _SEL, "ladder_filter": _LADDER,
            "link_filter": rf"/faculty-directory/{seg}/",
        },
    }


SCHOOL: dict = {
    "school_slug": "drexel",
    "source": "drexel_faculty",
    "organization": "Drexel University",
    "location": "Philadelphia, PA",
    "id_prefix": "drexel",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Drexel University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _dept("PHYS", "Department of Physics",
              ["Physics", "Astrophysics"], "physics"),
        _dept("CHEM", "Department of Chemistry",
              ["Chemistry", "Biochemistry"], "chemistry"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"], "mathematics"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
