"""Iowa State University faculty config (via the faculty_graph engine).

Only the three department directories that server-render their roster over plain
HTTP are wired here; the other three core-STEM departments are JS-rendered and/or
WAF-walled and are deferred (see the dropped list in the onboarding notes):

* **ECE, Chemistry, Mechanical Engineering — dropped (needs render).** ECE and ME
  sit behind an F5 BIG-IP ASM WAF (default UA gets a 247-byte "Request Rejected"
  page) *and* inject their faculty cards client-side (the real page is an empty
  WordPress skeleton). Chemistry runs the same Drupal platform as CS/Physics but
  its people-directory view returns zero person rows in static HTML (AJAX-
  populated). All three need a headless render pass, out of scope for this HTTP
  onboarding.

Two markup families, both clean static 200s (default curl UA, no render, no WAF).
Live-verified 2026-07-19:

* **Computer Science + Physics & Astronomy — Drupal "isu-people-directory".**
  One ``article.node--type-people.isu-horizontal-card`` per person: the name is a
  profile-linked ``h3.people-teaser-name a`` (absolute cs/physastro.iastate.edu
  URL), the rank is the first ``<li>`` of ``ul.isu-people_position-list`` (later
  ``<li>``s are committee/leadership roles), and a plain ``mailto`` sits in
  ``.isu-people_email``. Both pages are a single ``<h2>Faculty</h2>`` section —
  no staff/emeritus rows — so the title gate is belt-and-suspenders here rather
  than load-bearing. It IS load-bearing on Math (below).

* **Mathematics — WordPress iastate22 "faculty-staff-card", paginated.**
  ``math.iastate.edu/profiles/`` lists the WHOLE department — ~183 people across
  19 pages: grad students (67), postdocs, advisory-council members, academic
  advisers, and admin staff alongside the actual faculty. One
  ``div.faculty-staff-card`` per person: name in ``h3.faculty-staff-card__content
  -name`` (plain text, the profile link is a separate ``a.iastate22-link-
  secondary``), rank in ``div.faculty-staff-feed-item__content-body``, mailto in
  ``.faculty-staff-card__content-contact``. Path pagination /profiles/page/N/
  (page 1 = base). The title gate does the heavy lifting: 183 cards → 52 ladder/
  teaching faculty + lecturers (grad students / postdocs / staff / advisers all
  dropped for lacking a professor/lecturer rank; emeriti/retired dropped by the
  engine's own retired-title guard).

Title gate: a ``field_filter`` (not ``ladder_filter``) reading the WHOLE rank
element and requiring ``professor|lecturer`` — because a department chair's card
leads with "Department Chair" and carries "Professor" only on a later line, which
a first-line ladder read would wrongly drop. ``require_present`` also drops the
handful of blank/absent rank fields (staff) before the engine's "Professor"
default could wave them through.

Single source ("iastate_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-19 (cards / kept-after-gate, pre-dedupe): CS 44/44,
Physics 27/27, Math 183/52.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Drupal "isu-people-directory" (Computer Science, Physics & Astronomy) ----
# The name anchor already carries the absolute profile URL, so link == name. The
# title selector lands the FIRST position <li> (the rank) for the record's
# display title; the gate below reads the whole list so a chair whose rank sits
# on a later line is still kept.
_ISU_SEL = {
    "card": "article.node--type-people.isu-horizontal-card",
    "name": "h3.people-teaser-name a",
    "link": "h3.people-teaser-name a",
    "title": "ul.isu-people_position-list li",
    "email": ".isu-people_email a",
}
# Gate on the ENTIRE position list (not just the first <li>): a department chair
# card leads with "Department Chair" and only names "Professor" further down, so a
# first-line read would drop a real full professor. require_present drops the
# rare rank-less card before the engine's default title kicks in.
_ISU_FIELD = {
    "selector": "ul.isu-people_position-list",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _isu(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared Drupal isu-people-directory component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ISU_SEL, "field_filter": _ISU_FIELD},
    }


# ---- WordPress iastate22 "faculty-staff-card" (Mathematics) --------------------
_MATH_SEL = {
    "card": "div.faculty-staff-card",
    "name": "h3.faculty-staff-card__content-name",
    "link": "a.iastate22-link-secondary",
    "title": "div.faculty-staff-feed-item__content-body",
    "email": ".faculty-staff-card__content-contact a[href^='mailto:']",
}
_MATH_FIELD = {
    "selector": "div.faculty-staff-feed-item__content-body",
    "require_present": True,
    "include": r"professor|lecturer",
}


SCHOOL: dict = {
    "school_slug": "iastate",
    "source": "iastate_faculty",
    "organization": "Iowa State University",
    "location": "Ames, IA",
    "id_prefix": "iastate",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Iowa State University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _isu("CS", "Department of Computer Science",
             ["Computer Science", "Software Engineering", "Data Science"],
             "https://www.cs.iastate.edu/people/faculty"),
        _isu("PHYS", "Department of Physics and Astronomy",
             ["Physics", "Astronomy"],
             "https://www.physastro.iastate.edu/people/faculty"),
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://math.iastate.edu/profiles/",
            "scrape": {
                "url": "https://math.iastate.edu/profiles/",
                "selectors": _MATH_SEL,
                "field_filter": _MATH_FIELD,
                # /profiles/ lists the whole department ~10/page; base = page 1.
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 20},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
