"""Worcester Polytechnic Institute faculty config (via the faculty_graph engine).

All ten departments share ONE component: WPI's campus Drupal "directory widget".
Every ``/academics/departments/<slug>/faculty-staff`` page renders each person as
an ``article.dw_wrapper`` — a single selector set covers the whole school. Every
page is plain server-rendered HTML through the proxy (no WAF, no JS render);
live-verified 2026-07-20.

Per card:

* ``a.dw__name_link`` — the display name (clean "First Last") wrapping the profile
  link (faculty → ``/people/faculty/<slug>``, staff → ``/people/staff/<slug>``,
  relative to www.wpi.edu);
* ``div.dw__title`` — the rank as leading text followed by a
  ``a.dw__title_link`` that repeats the home department (so ``get_text`` yields
  "rank + department", exactly like Case Western's ``p.media-title``); the gate
  reads this directly;
* ``a.dw__email_link[href^='mailto:']`` — a PLAIN mailto on every card
  (~100% coverage on the listing; no per-profile crawl needed).

Note the WPI edge emits UNQUOTED href attributes (``href=/people/faculty/x``,
``href=mailto:x``) — bs4/lxml parse these fine. A short/stripped ~115KB response
is an intermittent light-cache variant; a re-fetch returns the full page (every
recon fetch here landed the full page, 250-450KB).

Title gate (``field_filter``, require ``professor|lecturer|instructor``): the
faculty-staff pages mix in department staff (administrative associates, lab
managers, operations/grant/program managers, technicians) and title-less
administrators (interim deans, a president, a vice provost) — the require gate
drops every one because none carry a rank word, while keeping ladder /
teaching / research / affiliate / adjunct professors, lecturers, and WPI's
full-time Instructors and Senior Instructors. ``field_filter`` (not
``ladder_filter``) with ``require_present`` reads ``div.dw__title`` directly so a
title-less staff card can't fall through the engine's default-to-"Professor".
The ``exclude`` drops Mathematical Sciences' two "Instructor's Associate" support
roles that would otherwise ride the ``instructor`` alternation on a substring
match. Emeriti (none currently listed on these pages) would drop via the
engine's own retired-title guard.

Single source ("wpi_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-20 (cards → kept-after-gate, email%): CS 49→44 100%,
ECE 31→25 100%, ME 45→35 100%, BME 46→40 100%, Physics 31→25 100%,
Chemistry 30→24 100%, ChemE 24→19 100%, Robotics 26→21 100%, DataSci 26→24 100%,
Math 61→53 100% → 310 faculty, email on ~100% (plain mailto on every card).
"""

from __future__ import annotations

from .. import faculty_graph

# The shared WPI campus Drupal "directory widget" — identical markup on every
# department's /faculty-staff page. Card is ``article.dw_wrapper``; the name link
# doubles as the profile link; ``div.dw__title`` holds the rank followed by a
# department link (so its text is "rank + department", read directly by the gate);
# the email is a plain mailto on every card.
_SEL = {
    "card": "article.dw_wrapper",
    "name": "a.dw__name_link",
    "link": "a.dw__name_link",
    "title": "div.dw__title",
    "email": "a.dw__email_link[href^='mailto:']",
}

# Keep professors (ladder + teaching + research + affiliate + adjunct), lecturers,
# and WPI's full-time Instructors / Senior Instructors; drop the admin/lab/ops
# staff and title-less administrators the faculty-staff pages mix in. field_filter
# (not ladder_filter) so a title-less staff card can't default to "Professor":
# require_present reads div.dw__title directly and drops the card when absent,
# include then keeps only rank-bearing titles. exclude removes Math's two
# "Instructor's Associate" support roles caught by the ``instructor`` substring.
_FIELD = {
    "selector": "div.dw__title",
    "require_present": True,
    "include": r"professor|lecturer|instructor",
    "exclude": r"instructor.s\s+associate",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A WPI department on the shared directory-widget template."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


_BASE = "https://www.wpi.edu/academics/departments"

SCHOOL: dict = {
    "school_slug": "wpi",
    "source": "wpi_faculty",
    "organization": "Worcester Polytechnic Institute",
    "location": "Worcester, MA",
    "id_prefix": "wpi",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Worcester Polytechnic Institute) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        _dept("CS", "Department of Computer Science",
              ["Computer Science"],
              f"{_BASE}/computer-science/faculty-staff"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical and Computer Engineering", "Electrical Engineering",
               "Computer Engineering"],
              f"{_BASE}/electrical-computer-engineering/faculty-staff"),
        _dept("ME", "Department of Mechanical and Materials Engineering",
              ["Mechanical Engineering", "Aerospace Engineering",
               "Materials Science and Engineering"],
              f"{_BASE}/mechanical-engineering/faculty-staff"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              f"{_BASE}/biomedical-engineering/faculty-staff"),
        _dept("PHYS", "Department of Physics",
              ["Physics", "Applied Physics"],
              f"{_BASE}/physics/faculty-staff"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              f"{_BASE}/chemistry-biochemistry/faculty-staff"),
        _dept("CHE", "Department of Chemical Engineering",
              ["Chemical Engineering"],
              f"{_BASE}/chemical-engineering/faculty-staff"),
        _dept("RBE", "Robotics Engineering Department",
              ["Robotics Engineering"],
              f"{_BASE}/robotics-engineering/faculty-staff"),
        _dept("DS", "Data Science Program",
              ["Data Science"],
              f"{_BASE}/data-science/faculty-staff"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematical Sciences", "Actuarial Mathematics",
               "Applied Mathematics", "Statistics"],
              f"{_BASE}/mathematical-sciences/faculty-staff"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
