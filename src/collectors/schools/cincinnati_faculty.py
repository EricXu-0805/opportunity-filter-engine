"""University of Cincinnati faculty config (via the faculty_graph engine).

Every department here rides ONE shared AEM "contact" people component — plain
server-rendered HTML, no WAF, no JS render needed (every page returns a clean
static 200 through the proxy). Two card *skins* of the same component exist and
one selector set covers both, live-verified 2026-07-20:

* **College of Engineering & Applied Science (CEAS, www.ceas.uc.edu).**
  CS / ECE / ME / Aerospace / BME / ChemE / Civil each render a person as
  ``div.contact-item`` with an ``h3.name`` (a trailing ``<span>,</span>`` the
  ``name_strip`` regex removes), an ``h4.title`` rank, and a ``p.email > a``
  plain ``mailto:`` (``@ucmail.uc.edu``). A SECOND skin — ``div.contact-card`` —
  holds only the Emeritus / Postdoc / Research-Associate / department-staff
  roster (doubled desktop+mobile copies), so the card selector is deliberately
  ``div.contact-item`` ONLY: it captures the entire ladder-faculty group and
  cleanly excludes the emeriti/postdoc/staff skin without the doubling.

* **College of Arts & Sciences (A&S, www.artsci.uc.edu).**
  Physics / Chemistry / Mathematical Sciences render the SAME ``div.contact-item``
  card, but the rank sits in a ``span.title`` (beside a sibling ``span.department``
  the selector avoids) and the ``h3.name`` carries no trailing comma. One
  ``h4.title, span.title`` selector covers both colleges.

Every card exposes the profile link as ``a.btn-red`` →
``researchdirectory.uc.edu/p/<username>`` (100% coverage on the kept set) and,
uniquely for this school, a real per-person ``mailto`` — so records land
name + title + email in one pass (~99% email coverage, no per-profile crawl).

Title gate (``field_filter``, require ``professor|lecturer``) — ESSENTIAL here:
the listings mix in graduate assistants, postdoctoral fellows, research
associates, department staff (grant/business/lab administrators, coordinators),
adjunct instructors, and — heavily on the A&S pages — dozens of grad students
(Physics 135 cards, Math 185 cards). A ``field_filter`` (not ``ladder_filter``)
is used so a title-LESS card can't fall through the engine's default-to-
"Professor": ``require_present`` reads the title element directly and drops the
card when it is absent — which matters because UC lists its EMERITI with a blank
title cell (ECE alone has ~19 title-less emeriti: Boolchand, Franco, Schlipf,
Wilsey …), and a bare ``ladder_filter`` would default those to "Professor" and
inject them. ``include`` then keeps only Professor / Lecturer ranks (ladder +
Educator-track + research + visiting + endowed-chair professors whose title
still carries the word "Professor"), and the engine's own ``_RETIRED_TITLE_RE``
drops the labelled emeriti ("Professor Emeritus"). "instructor" is intentionally
left OUT of the gate: UC's bare "Instructor - Adj" rows are part-time adjunct
teaching appointments, not research mentors, and excluding them matches the Math
kept count to its ~70-professor recon estimate.

A handful of genuinely active faculty are dropped by the gate because their
title cell carries only an endowed-chair name ("Bradley Jones Chair", "Brian H.
Rowe Endowed Chair" — Khare, Cohen in Aerospace) or a joint-appointment string
("Psychology-Mechanical Engineering-Electrical Engineering (jointly appointed)"
— Lorenz, Vanderelst) with no rank word. That is the accepted accuracy-over-
recall tradeoff: no non-ladder / wrong-primary-department rows leak in.

Single source ("cincinnati_faculty"); department rides each record, ids
namespaced by department short-code.

Live-verified 2026-07-20 (deep=True, listing scrape, kept-after-gate / email):
CS 41/41, ECE 30/30, ME 36/36, Aerospace 15/15, BME 49/46, ChemE 25/25,
Civil 27/27, Physics 30/30, Chemistry 31/31, Mathematical Sciences 72/72.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UC AEM "contact" people card. One selector set spans both college
# skins: CEAS keeps the rank in ``h4.title``, A&S in ``span.title`` (beside a
# ``span.department`` sibling the ``span.title`` selector avoids). The ``h3.name``
# on CEAS wraps a trailing ``<span>,</span>`` that ``name_strip`` removes (A&S
# names carry no comma, so the strip is a harmless no-op there). The card
# selector is ``div.contact-item`` ONLY — the ``div.contact-card`` skin holds
# just the emeriti / postdoc / research-associate / staff roster (doubled copies).
_SEL = {
    "card": "div.contact-item",
    "name": "h3.name",
    "name_strip": r"\s*,\s*$",
    "link": "a.btn-red[href*='researchdirectory.uc.edu/p/']",
    "title": "h4.title, span.title",
    "email": "p.email a[href^='mailto:']",
}

# Keep Professors (ladder + Educator-track + research + visiting + endowed-chair
# rows carrying "Professor") and Lecturers; drop grad students, postdocs,
# research associates, staff, adjunct instructors, and title-less cards. A
# field_filter (not ladder_filter) with require_present is REQUIRED so UC's
# title-less emeriti cards can't default to "Professor" and inject themselves;
# labelled emeriti are additionally dropped by the engine's retired-title gate.
_FIELD = {
    "selector": "h4.title, span.title",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UC contact-item people component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


_CEAS = "https://www.ceas.uc.edu/academics/departments"
_AS = "https://www.artsci.uc.edu/natural-sciences"

SCHOOL: dict = {
    "school_slug": "cincinnati",
    "source": "cincinnati_faculty",
    "organization": "University of Cincinnati",
    "location": "Cincinnati, OH",
    "id_prefix": "cincinnati",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Cincinnati) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering & Applied Science (CEAS) --------------
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Data Science", "Cybersecurity"],
              f"{_CEAS}/computer-science/computer-science-people.html"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              f"{_CEAS}/electrical-computer-engineering/people.html"),
        _dept("ME", "Department of Mechanical and Materials Engineering",
              ["Mechanical Engineering", "Materials Science and Engineering"],
              f"{_CEAS}/mechanical-materials-engineering/People/"
              "mechanical-engineering-faculty.html"),
        _dept("AERO", "Department of Aerospace Engineering and Engineering Mechanics",
              ["Aerospace Engineering", "Engineering Mechanics"],
              f"{_CEAS}/aerospace-engineering-mechanics/people.html"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              f"{_CEAS}/biomedical-engineering/people.html"),
        _dept("CHEME", "Department of Chemical and Environmental Engineering",
              ["Chemical Engineering", "Environmental Engineering"],
              f"{_CEAS}/chemical-environmental-engineering/people.html"),
        _dept("CIVIL",
              "Department of Civil and Architectural Engineering and Construction Management",
              ["Civil Engineering", "Architectural Engineering",
               "Construction Management", "Environmental Engineering"],
              f"{_CEAS}/civil-architectural-engineering-construction-management/people.html"),
        # ---- College of Arts & Sciences (A&S) -----------------------------
        _dept("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
              f"{_AS}/physics/faculty-staff.html"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              f"{_AS}/chemistry/faculty-and-staff-directory.html"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematics", "Applied Mathematics", "Statistics"],
              f"{_AS}/math/faculty-staff-students.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
