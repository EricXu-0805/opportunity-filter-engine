"""Rensselaer Polytechnic Institute faculty config (via the faculty_graph engine).

Two server-rendered Drupal markup families, both fetched over plain HTTP (no WAF,
no JS render). Live-verified 2026-07-19.

* **Science + MANE — the ``profile-card`` component.** Five departments
  (Computer Science, Physics, Chemistry, Mathematical Sciences, and the
  Mechanical/Aerospace/Nuclear engineering directory) render each person as a
  ``div.profile-card.card`` grouped under sibling ``<h2>`` role headings —
  ``Faculty`` first, then ``Joint Appointment`` / ``Affiliated Faculty`` /
  ``Emeritus`` / ``Retired Faculty`` / ``Staff`` / ``Postdoctoral …``. A
  ``section_filter`` keyed on ``^faculty$`` keeps only the home-department
  ladder block, dropping the joint/affiliated cross-listings (which are the home
  faculty of another dept and would double-count), the emeriti/retired, the
  postdocs, and the staff (whose rank lives in a different sub-element and would
  otherwise fall through to the "Professor" default).

  The component has TWO variants for where the rank sits:
  - Science depts (CS/PHYS/CHEM/MATH) put the rank in ``.profile-card-text`` and
    carry no research line on the card (topics come from OpenAlex enrichment).
  - MANE puts the rank in ``.profile-card-title`` and the research areas in
    ``.profile-card-text`` — so MANE lands keyworded faculty in one pass.

* **ECSE — the older ``personbox`` component.** Electrical, Computer & Systems
  Engineering serves a dedicated faculty-only page (``div.personbox.views-row``):
  name in ``.field-title``, rank in ``.position``, research in ``.focus-area``.
  It is a single faculty roster (no emeritus/staff section on the page — those
  live on separate nav tabs), so no section_filter is needed; the title gate
  alone drops the lone non-faculty card (the RPI President's courtesy listing).

Title gate (``ladder_filter require: prof|lecturer``): keeps ladder + endowed +
practice professors and lecturers; drops the admin-only cards whose listing text
is a pure administrative role with no rank ("Associate Dean of Science…",
"Chief Scientist and Center Director", the university President). Emeriti/retired
are already excluded by the section_filter and the engine's own retired-title
guard. The gate is intentionally ``prof`` (not ``professor``) so an abbreviated
"Distinguished Prof. of Computer Science" endowed title still qualifies.

The listing cards expose no per-person email (they link out to faculty.rpi.edu
profile pages), so records land name+title(+research for MANE/ECSE) only.

Single source ("rpi_faculty"); department rides each record, ids namespaced by
department short-code. Live counts (cards in Faculty section / kept after gate):
CS 32/29, ECSE 37/36, PHYS 23/21, CHEM 19/19, MATH 22/21, MANE 56/56.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- profile-card component, science variant (rank in .profile-card-text) ---
_SEL_SCI = {
    "card": "div.profile-card.card",
    "name": ".profile-card-name a",
    "link": ".profile-card-name a",
    "title": ".profile-card-text",
}
# ---- profile-card component, MANE variant (rank in .title, research in .text)-
_SEL_ENG = {
    "card": "div.profile-card.card",
    "name": ".profile-card-name a",
    "link": ".profile-card-name a",
    "title": ".profile-card-title",
    "research": ".profile-card-text",
}
# ---- older personbox component (ECSE) ---------------------------------------
_SEL_ECSE = {
    "card": "div.personbox.views-row",
    "name": ".field-title",
    "link": "a",
    "title": ".position",
    "research": ".focus-area",
}

# Keep professors (ladder / endowed / distinguished / of-practice) and lecturers;
# drop admin-only listing rows (Dean/Director/President) that carry no rank word.
_LADDER = {"require": r"prof|lecturer"}
# Keep only the first "Faculty" heading's cards (drops Joint/Affiliated/Emeritus/
# Retired/Staff/Postdoc sections on the multi-section profile-card pages).
_FACULTY_SECTION = {"heading": "h2", "include": r"^faculty$"}


def _sci(short: str, name: str, majors: list[str], url: str) -> dict:
    """A science department on the profile-card component (rank in .card-text)."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL_SCI, "ladder_filter": _LADDER,
                   "section_filter": _FACULTY_SECTION},
    }


SCHOOL: dict = {
    "school_slug": "rpi",
    "source": "rpi_faculty",
    "organization": "Rensselaer Polytechnic Institute",
    "location": "Troy, NY",
    "id_prefix": "rpi",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Rensselaer Polytechnic Institute) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Science ----------------------------------------------
        _sci("CS", "Department of Computer Science",
             ["Computer Science"],
             "https://compsci.rpi.edu/people"),
        _sci("PHYS", "Department of Physics, Applied Physics, and Astronomy",
             ["Physics", "Applied Physics", "Astronomy"],
             "https://physics.rpi.edu/people"),
        _sci("CHEM", "Department of Chemistry and Chemical Biology",
             ["Chemistry", "Biochemistry and Biophysics"],
             "https://chemistry.rpi.edu/people"),
        _sci("MATH", "Department of Mathematical Sciences",
             ["Mathematics", "Applied Mathematics"],
             "https://math.rpi.edu/people"),
        # ---- School of Engineering: ECSE (older personbox page) -------------
        {
            "short": "ECSE",
            "name": "Department of Electrical, Computer, and Systems Engineering",
            "majors": ["Electrical Engineering", "Computer and Systems Engineering"],
            "directory_url": "https://ecse.rpi.edu/people",
            "scrape": {
                "url": "https://ecse.rpi.edu/people",
                "selectors": _SEL_ECSE,
                "ladder_filter": _LADDER,
            },
        },
        # ---- School of Engineering: MANE (profile-card, rank in .card-title)-
        {
            "short": "MANE",
            "name": "Department of Mechanical, Aerospace, and Nuclear Engineering",
            "majors": ["Mechanical Engineering", "Aeronautical Engineering",
                       "Nuclear Engineering"],
            "directory_url": "https://mane.rpi.edu/people",
            "scrape": {
                "url": "https://mane.rpi.edu/people",
                "selectors": _SEL_ENG,
                "ladder_filter": _LADDER,
                "section_filter": _FACULTY_SECTION,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
