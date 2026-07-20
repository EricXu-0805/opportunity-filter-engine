"""Clemson University faculty config (via the faculty_graph engine).

Three server-rendered markup families, every page a plain static 200 to a bare
request (no WAF, no JS render). Live-verified 2026-07-20.

* **CECAS "person-card" grid — School of Computing.**
  ``div.person-card`` cards on www.clemson.edu/cecas/departments/computing.
  Name in ``h3.person-name`` (no profile link — the card exposes only a mailto,
  so the record's url falls back to the directory), rank in the first
  ``p.about > strong``, address in a ``p.about a[href^=mailto:]``. The page mixes
  15 staff cards, postdocs and administrators alongside ladder faculty; the
  ``field_filter`` (require ``professor|lecturer`` on the rank ``<strong>``, which
  every card carries) drops the non-faculty and keeps every professor / lecturer
  rank (incl. professor-of-practice / research / principal-lecturer).

* **CECAS "cell large-3" grid — ECE and Mechanical Engineering.**
  ``div.cell.large-3`` cards on the ece / me department sites. Name in an
  ``h3 > a`` that links the person's profile page, rank in ``p.about > strong``
  (rendered ALL-CAPS), address in a ``p.about a[href^=mailto:]``. Both pages list
  every rank under one flat grid (ECE: Faculty + Joint Faculty + Research Faculty
  + Professor of Practice; ME: Primary Faculty + Lecturer + Professor of Practice
  + a Staff block of 18 coordinators/managers). The same ``field_filter`` keeps
  only professor/lecturer ranks — dropping ME's entire staff block and ECE's lone
  non-ranked department-chair/research-associate cards — so no non-faculty leak in.

* **College of Science LiveWhale table — Physics & Astronomy, Chemistry, and
  Mathematical & Statistical Sciences.**
  www.clemson.edu/science/…/about/people.html renders one big ``<table>`` whose
  every person is a ``<tr>`` of: a category cell (``td`` #1 — "faculty",
  "graduatestudents", "postdocs", "adjunct", "staff", "emeritifaculty",
  "inmemoriam", …), a name cell (``td`` #2, an ``a[href*=/profiles/]`` in
  "Last, First" order — ``name_flip`` un-inverts it), a rank cell (``td`` #3), and
  an email cell (``td`` #4, a plain ``mailto``). These directories are dominated
  by graduate students (Physics 86, Math 126) plus postdocs, adjuncts, emeriti and
  staff, so a title gate alone is not enough — the ``field_filter`` pins the
  category cell to exactly ``faculty`` (``^faculty$`` — the combined dual-tags
  "faculty postdocs"/"faculty adjunct"/"faculty emeritifaculty" are correctly
  excluded), and a ``ladder_filter`` require ``professor|lecturer`` drops the few
  non-ranked administrators (dept-chair/associate-dean) left in that category.
  Emeriti that slip the category are additionally dropped by the engine's retired
  gate. Every kept row exposes a real ``mailto`` → 100% email on the listing.

Single source ("clemson_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-20 (cards → kept-after-gate): COMP 75/58, ECE 60/58,
ME 66/48, PHYS 180/33, CHEM 80/45, MATH 261/93 → 335 total, 100% emailed on the
listing (every kept card/row carries a plain clemson.edu mailto).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- CECAS "person-card" grid (School of Computing) ------------------------
# div.person-card: name h3.person-name (no profile link — mailto only), rank in
# the first p.about<strong>, email a plain mailto. field_filter (not ladder) so a
# title-less card can't default to "Professor": require_present reads the rank
# <strong> directly (every card has one) and include keeps only professor/lecturer.
_CARD_SEL = {
    "card": "div.person-card",
    "name": "h3.person-name",
    "title": "p.about strong",
    "email": 'p.about a[href^="mailto:"]',
}

# ---- CECAS "cell large-3" grid (ECE, Mechanical Engineering) ---------------
# div.cell.large-3: name h3>a (profile link), rank p.about<strong> (ALL CAPS),
# email a plain mailto. Same professor/lecturer field gate isolates ladder faculty
# from the staff / non-ranked cards these flat grids mix in.
_GRID_SEL = {
    "card": "div.cell.large-3",
    "name": "h3",
    "link": "h3 a",
    "title": "p.about strong",
    "email": 'p.about a[href^="mailto:"]',
}

# Shared CECAS rank gate: require a Professor/Lecturer rank word on the card's
# rank <strong>; require_present drops a card that has no rank element at all
# (staff cards carry a staff-title strong, so they're dropped by the include miss).
_CECAS_FIELD = {
    "selector": "p.about strong",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- College of Science LiveWhale table (Physics, Chemistry, MathStat) -----
# One <table>; each person a <tr>. td#1 = category tag, td#2 = name link
# ("Last, First" → name_flip), td#3 = rank, td#4 = mailto. field_filter pins the
# category cell to exactly "faculty" (drops grad students / postdocs / adjuncts /
# emeriti / staff and the dual-tag combos); ladder_filter then drops the rare
# non-ranked administrator left in the faculty category.
_TABLE_SEL = {
    "card": "tr:has(a[href*='/profiles/'])",
    "name": "td a[href*='/profiles/']",
    "link": "td a[href*='/profiles/']",
    "title": "td:nth-of-type(3)",
    "email": 'td a[href^="mailto:"]',
}
_TABLE_FIELD = {
    "selector": "td:nth-of-type(1)",
    "require_present": True,
    "include": r"^faculty$",
}
_TABLE_LADDER = {"require": r"professor|lecturer"}


def _computing(short: str, name: str, majors: list[str], url: str) -> dict:
    """School of Computing on the CECAS person-card grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CARD_SEL, "field_filter": _CECAS_FIELD},
    }


def _grid(short: str, name: str, majors: list[str], url: str) -> dict:
    """ECE / ME on the CECAS cell-large-3 grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _GRID_SEL, "field_filter": _CECAS_FIELD},
    }


def _science(short: str, name: str, majors: list[str], url: str) -> dict:
    """A College of Science department on the shared LiveWhale people table."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _TABLE_SEL, "name_flip": True,
                   "field_filter": _TABLE_FIELD, "ladder_filter": _TABLE_LADDER},
    }


SCHOOL: dict = {
    "school_slug": "clemson",
    "source": "clemson_faculty",
    "organization": "Clemson University",
    "location": "Clemson, SC",
    "id_prefix": "clemson",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Clemson University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering, Computing and Applied Sciences -------
        _computing("COMP", "School of Computing",
                   ["Computer Science", "Computer Information Systems",
                    "Data Science"],
                   "https://www.clemson.edu/cecas/departments/computing/people/index.html"),
        _grid("ECE", "Holcombe Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://www.clemson.edu/cecas/departments/ece/people/index.html"),
        _grid("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              "https://www.clemson.edu/cecas/departments/me/people/index.html"),
        # ---- College of Science -------------------------------------------
        _science("PHYS", "Department of Physics and Astronomy",
                 ["Physics", "Astronomy", "Astrophysics"],
                 "https://www.clemson.edu/science/academics/departments/physics/about/people.html"),
        _science("CHEM", "Department of Chemistry",
                 ["Chemistry", "Biochemistry"],
                 "https://www.clemson.edu/science/academics/departments/chemistry/about/people.html"),
        _science("MATH", "School of Mathematical and Statistical Sciences",
                 ["Mathematical Sciences", "Statistics", "Applied Mathematics"],
                 "https://www.clemson.edu/science/academics/departments/mathstat/about/people.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
