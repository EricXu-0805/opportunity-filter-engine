"""University of Central Florida faculty config (via the faculty_graph engine).

Two server-rendered markup families cover the six STEM departments — no WAF, no
JS render (every recon fetch returns a clean static 200 to a plain request).
Live-verified 2026-07-19.

* **College of Engineering & Computer Science — Elementor "filterable gallery".**
  ``www.cs.ucf.edu`` / ``www.ece.ucf.edu`` / ``mae.ucf.edu`` all run the same
  WordPress + Essential-Addons filterable gallery: one person is a
  ``div.eael-filterable-gallery-item-wrap`` whose category is a body class
  (``eael-cf-faculty`` vs ``eael-cf-affiliated`` / ``eael-cf-emeritus`` /
  ``eael-cf-staff``). Name sits in ``.fg-item-title`` (an ``<h1>`` on ECE, an
  ``<h2>`` on CS/MAE — so the selector is class-only), the profile link in the
  card's ``/person/<slug>/`` anchor, and rank + email in a single
  ``.fg-item-content > p`` ("Associate Lecturer<br>name@ucf.edu"). ``email`` and
  ``title`` therefore point at the same ``<p>``: ``title_strip_after`` cuts the
  address off the rank, and ``_clean_email`` extracts it (CS/ECE publish it as a
  ``mailto:`` anchor, MAE as plain text — both land via the ``<p>`` text).

  - **CS / ECE** carry a clean ``eael-cf-faculty`` category, so the card selector
    is ``[class*='eael-cf-faculty']`` — it also catches a trailing-dash
    data-entry variant (``eael-cf-faculty-`` on the last-added professors,
    including CS's department chair Damla Turgut) while still excluding the
    ``affiliated`` / ``emeritus`` / ``staff`` buckets. ECE's "UCF President"
    entry (President Cartwright, listed with no professor rank) is dropped by the
    ladder gate.
  - **MAE** has no ``faculty`` category — its cards are tagged by sub-discipline
    (``aerospace`` / ``mechanical`` / ``biomedical``) plus an untagged bucket
    that mixes ~9 real professors with lab managers, program coordinators, and an
    administrative assistant. So MAE selects ALL wraps and leans on the ladder
    gate (drops the coordinators/manager/assistant) + the engine's retired-title
    gate (drops the emeriti); one cross-listed College-of-Medicine surgery
    professor (a biomedical affiliate) rides along.

* **College of Sciences — the shared "Colleges" people theme.**
  ``sciences.ucf.edu/<dept>/people/`` renders one person as
  ``a.person-link`` wrapping ``h3.person-name`` + ``.person-job-title`` (no
  per-card email — topic keywords come from downstream OpenAlex enrichment).
  Physics and Chemistry group people into ``<section class="ucf-section-*">``
  blocks (faculty / research-personnel / emeritus / staff / adjunct / courtesy /
  joint), so the card selector scopes to ``section.ucf-section-faculty`` to keep
  home-department ladder faculty and exclude the courtesy/joint/staff sections;
  the ladder gate then drops the instrument specialists / instrumentation staff
  the Chemistry faculty section mixes in. Math renders its people flat (no
  section wrapper), so it selects ``a.person-link`` directly and the ladder gate
  drops the STEM/teaching postdocs, the lone adjunct, and an office assistant.

Title gate (ladder ``require: professor|lecturer|instructor``): keeps ladder,
teaching, research, and endowed-chair professors plus lecturers and instructors,
and drops titleless/role-only staff, postdocs, coordinators, advisors, and
administrators. Emeriti are dropped by the engine's own ``_RETIRED_TITLE_RE``.

Single source ("ucf_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-19 (kept after title + retired gate / email coverage):
CS 67/67 email, ECE 55/55 email, MAE 68/67 email, Physics 60 (no card email),
Chemistry 44 (no card email), Math 48 (no card email).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- CECS Elementor filterable gallery -------------------------------------
# Rank + email share one <p>; title_strip_after cuts the address off the rank,
# and the email selector re-reads the same <p> (_clean_email pulls the address —
# a mailto anchor on CS/ECE, plain text on MAE).
_ELEM_SEL = {
    "name": ".fg-item-title",
    "link": "a[href*='/person/']",
    "title": ".fg-item-content p",
    "title_strip_after": r"\s+[\w.+-]+@",
    "email": ".fg-item-content p",
}

# ---- College of Sciences shared "Colleges" people theme --------------------
_COS_SEL = {
    "name": ".person-name",
    "link": ":self",
    "title": ".person-job-title",
}

# Keep professor / lecturer / instructor ranks; drop role-only staff, postdocs,
# coordinators, advisors, and administrators. (Emeriti drop via the engine's
# retired-title gate.)
_LADDER = {"require": r"professor|lecturer|instructor"}


def _elem_dept(short: str, name: str, majors: list[str], url: str, card: str) -> dict:
    """A CECS department on the shared Elementor filterable gallery."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": card, **_ELEM_SEL},
            "ladder_filter": _LADDER,
        },
    }


def _cos_dept(short: str, name: str, majors: list[str], url: str, card: str) -> dict:
    """A College of Sciences department on the shared "Colleges" people theme."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": card, **_COS_SEL},
            "ladder_filter": _LADDER,
        },
    }


# CS/ECE = the clean faculty category (+ trailing-dash variant); MAE = all wraps.
_CECS_FACULTY_CARD = ".eael-filterable-gallery-item-wrap[class*='eael-cf-faculty']"
_MAE_CARD = ".eael-filterable-gallery-item-wrap"
# Physics/Chemistry = home-department faculty section; Math renders people flat.
_COS_FACULTY_CARD = "section.ucf-section-faculty a.person-link"
_COS_FLAT_CARD = "a.person-link"


SCHOOL: dict = {
    "school_slug": "ucf",
    "source": "ucf_faculty",
    "organization": "University of Central Florida",
    "location": "Orlando, FL",
    "id_prefix": "ucf",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Central Florida) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering & Computer Science ---------------------
        _elem_dept("CS", "Department of Computer Science",
                   ["Computer Science", "Data Science"],
                   "https://www.cs.ucf.edu/faculty-directory/",
                   _CECS_FACULTY_CARD),
        _elem_dept("ECE", "Department of Electrical and Computer Engineering",
                   ["Electrical Engineering", "Computer Engineering",
                    "Photonic Science and Engineering"],
                   "https://www.ece.ucf.edu/faculty-directory/",
                   _CECS_FACULTY_CARD),
        _elem_dept("MAE", "Department of Mechanical and Aerospace Engineering",
                   ["Mechanical Engineering", "Aerospace Engineering",
                    "Biomedical Engineering"],
                   "https://mae.ucf.edu/faculty-directory/",
                   _MAE_CARD),
        # ---- College of Sciences -------------------------------------------
        _cos_dept("PHYS", "Department of Physics", ["Physics", "Astronomy"],
                  "https://sciences.ucf.edu/physics/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("CHEM", "Department of Chemistry",
                  ["Chemistry", "Biochemistry"],
                  "https://sciences.ucf.edu/chemistry/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("MATH", "Department of Mathematics", ["Mathematics"],
                  "https://sciences.ucf.edu/math/people/",
                  _COS_FLAT_CARD),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
