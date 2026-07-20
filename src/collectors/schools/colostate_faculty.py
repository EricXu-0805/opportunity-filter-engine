"""Colorado State University faculty config (via the faculty_graph engine).

Two server-rendered markup families, both plain static 200s to a bare request
(no WAF, no JS render). Live-verified 2026-07-19. Both are the campus WordPress
("Jupiter" theme) but ship two different directory widgets, so they need two
selector sets — a single ``.team-member-*`` set does NOT cover both, and the
``.team-member-name`` class is emitted 2-3x per person in each (a photo anchor,
a text anchor, and an inner span), so the card selector must key off the
per-person WRAPPER, never ``.team-member-name`` itself, or every professor
triples.

* **"sg-directory" list rows (Computer Science, Physics, Mathematics).**
  ``compsci`` / ``physics`` / ``mathematics``.colostate.edu render the Natural
  Sciences shared directory as one ``div.directory-default-row`` per person:
  a photo ``a.team-member-name``, a text ``a.team-member-name`` wrapping the
  ``span.team-member-name`` display name, a ``span.directory-list-title`` rank
  (prefixed with a stray "/ ", e.g. "/ Assistant Professor"), a clean
  ``mailto`` in ``.directory-list-contact-info``, and a free-text research ``<p>``
  (prose, not a clean tag list — topics come from downstream OpenAlex, not a
  ``research`` selector). These pages are FULL people directories: Physics alone
  lists 22 graduate research assistants, 12 graduate teaching assistants, 4
  graduate assistants, ~10 emeriti, postdocs, research associates and admin staff
  around only ~20 ladder faculty; CS and Math likewise mix instructors,
  coordinators, IT/admin staff and emeriti. A ``field_filter`` on
  ``span.directory-list-title`` (``require_present`` so a title-less card can't
  fall through to the engine's "Professor" default, ``include: professor|lecturer``,
  ``exclude: emerit``) is the load-bearing gate that keeps only ladder / teaching
  professors and drops every grad student, postdoc, staff and emeritus. A
  ``title_re`` then trims the kept rank back off the "/ " prefix and any trailing
  " - FC" / "(CCAF)" / "(Joint Appointment …)" / "/ she/they" suffix.

* **"mk-employee-item" cards (Chemistry, Statistics).**
  ``chem`` / ``statistics``.colostate.edu render the Jupiter employees widget:
  one ``div.mk-employee-item`` per person, name in ``span.team-member-name``,
  rank in ``span.team-member-position``, and a per-card ``mailto`` (every card
  publishes one — 100% email coverage). NOTE the ``.team-member-desc`` block is
  Office/Phone contact text, NOT research areas, so it is deliberately not scraped
  as research. Same title gate: these are full staff rosters (Chemistry mixes in
  a dozen ARC-facility scientists/managers, IT and accounting staff, and 12
  emeriti; Statistics mixes coordinators and 9 emeriti), so the
  ``field_filter`` on ``span.team-member-position`` keeps only professor/lecturer
  ranks (incl. teaching professors) and drops emeriti + non-faculty staff.

Engineering (ECE + Mechanical, on engr.colostate.edu) is intentionally NOT built
this pass: the whole engr.colostate.edu WordPress returns HTTP 500 (a site-wide
crash, likely transient) — re-probe later.

Single source ("colostate_faculty"); department rides each record, ids
namespaced by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- "sg-directory" list rows: Computer Science / Physics / Mathematics -----
# Card = the per-person row wrapper (never ``.team-member-name``, which repeats
# 3x/person). Name is the inner span; the profile link is the photo/text anchor
# to ``/person/?id=…`` (its ?id query IS the identity, so it is NOT stripped).
_DIR_SEL = {
    "card": "div.directory-default-row",
    "name": "span.team-member-name",
    "link": "a.team-member-name[href*='/person/']",
    "title": "span.directory-list-title",
    # Trim the kept rank off the stray "/ " prefix and any trailing
    # " - FC" / "(CCAF)" / "(Joint Appointment …)" / "/ she/they" / chair suffix.
    "title_re": (
        r"((?:University\s+)?(?:Distinguished\s+)?"
        r"(?:Assistant\s+|Associate\s+|Adjunct\s+|Research\s+|Visiting\s+"
        r"|Teaching\s+|Senior\s+)*(?:Professor|Lecturer))"
    ),
    "email": "div.directory-list-contact-info a[href^='mailto:']",
}
# Load-bearing gate: require the rank element (so a title-less staff row can't
# default to "Professor"), keep only professor/lecturer ranks, drop emeriti.
_DIR_FIELD = {
    "selector": "span.directory-list-title",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"emerit",
}

# ---- "mk-employee-item" cards: Chemistry / Statistics -----------------------
# ``.team-member-desc`` is Office/Phone contact text, NOT research — no research
# selector; topics come from downstream OpenAlex enrichment.
_EMP_SEL = {
    "card": "li.mk-employee-item",
    "name": "span.team-member-name",
    "link": "a.team-member-name[href*='/person/']",
    "title": "span.team-member-position",
    "email": "a[href^='mailto:']",
}
_EMP_FIELD = {
    "selector": "span.team-member-position",
    "require_present": True,
    "include": r"professor|lecturer",
    "exclude": r"emerit",
}


def _dir_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A CS/Physics/Math department on the sg-directory list-row widget."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _DIR_SEL, "field_filter": _DIR_FIELD},
    }


def _emp_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Chemistry/Statistics department on the mk-employee-item card widget."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _EMP_SEL, "field_filter": _EMP_FIELD},
    }


SCHOOL: dict = {
    "school_slug": "colostate",
    "source": "colostate_faculty",
    "organization": "Colorado State University",
    "location": "Fort Collins, CO",
    "id_prefix": "colostate",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Colorado State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        _dir_dept("CS", "Department of Computer Science",
                  ["Computer Science", "Data Science"],
                  "https://compsci.colostate.edu/people/"),
        _dir_dept("PHYS", "Department of Physics",
                  ["Physics", "Astrophysics"],
                  "https://www.physics.colostate.edu/about/people/"),
        _dir_dept("MATH", "Department of Mathematics",
                  ["Mathematics", "Applied Mathematics"],
                  "https://mathematics.colostate.edu/people/faculty/"),
        _emp_dept("CHEM", "Department of Chemistry",
                  ["Chemistry", "Biochemistry"],
                  "https://www.chem.colostate.edu/people/"),
        _emp_dept("STAT", "Department of Statistics",
                  ["Statistics", "Data Science"],
                  "https://statistics.colostate.edu/faculty-staff/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
