"""Case Western Reserve University faculty config (via the faculty_graph engine).

All six departments here are plain server-rendered HTML (no render mode, no WAF;
every recon fetch returned a clean static 200 through the proxy). Three distinct
markup families, live-verified 2026-07-19:

* **Case School of Engineering — one shared Drupal "media" directory.**
  CS, ECSE, EMAE, and BME all render each person as a Bootstrap media card:
  ``h3.media-heading > a`` (name, credentials-suffixed) + ``p.media-title``
  (rank + department) + a plain ``mailto:`` anchor. Two wrapper variants exist —
  the ``/faculty-and-staff`` pages wrap each card in ``li.biography`` (CS, EMAE)
  and the ``/about/our-team`` + ``/bme/people`` pages use ``li.media`` (ECSE,
  BME) — so the card selector matches either. Every card sits under a role
  heading (Chair / Faculty / Research Faculty / Emeritus / Staff); the ladder
  filter (require ``professor|lecturer``) keeps ladder + research + teaching
  professors and lecturers and drops the Staff bucket (managers, coordinators,
  AI scientists, assistants, research assistants), while the engine's own
  retired-title guard drops the Emeritus bucket.

* **Physics & Astronomy — a Bootstrap grid table.**
  ``physics.case.edu/directory/faculty/`` renders one ``div.directory-row`` per
  person with four ``.directory-data`` cells (Name link / Title / Email text /
  Phone text). A ``:not(.directory-header)`` on the card drops the column-label
  header row of each section; emails are plain text in the third cell
  (``_clean_email`` extracts them). Instructors are dropped by the ladder gate,
  emeriti by the retired-title guard.

* **Mathematics, Applied Mathematics & Statistics — a WordPress directory grid.**
  ``mathstats.case.edu/faculty-staff/`` renders one ``div.row.directory-space``
  per person; the info column (``div.col-xs-7``) holds the name link then the
  rank / email / phone as ``<br>``-separated plain text with no wrapping
  elements. The rank is pulled with ``title_re`` (so plain Instructors fail the
  ladder gate and drop) and the email is regex-extracted from the whole info
  cell. Lecturers and ladder faculty are kept.

Chemistry (chemistry.case.edu/people/faculty/) was DROPPED: it is a WPBakery
page with unclosed ``<p>`` markup where faculty render as a flat sequence of
centered paragraphs (name / title / email / interests) with no reliable
per-person card element — only 3 of 31 ``column-group`` divs segment cleanly and
emails are plain text (not mailto), so the card engine cannot parse it without a
bespoke sequential parser. Six clean departments beat five clean + one dirty.

Single source ("casewestern_faculty"); department rides each record, ids
namespaced by department short-code.

Live-verified counts (cards / kept-after-gate) recorded in the onboarding run.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Case School of Engineering: shared Drupal "media" card ----------------
# CS/EMAE wrap each person in li.biography; ECSE/BME in li.media — one card
# selector matches either. Name carries trailing credentials (", PhD") the
# engine strips; the title cell holds rank + department (endowed-chair titles
# still contain "Professor"), so the ladder gate reads it directly.
_ENG_SEL = {
    "card": "li.biography, li.media",
    "name": "h3.media-heading a",
    "link": "h3.media-heading a",
    "title": "p.media-title",
    "email": "a[href^='mailto:']",
}
# Keep ladder + research + teaching professors and lecturers; drop the Staff
# section (managers, coordinators, assistants, AI scientists, research
# assistants) whose titles carry neither word. Emeriti are dropped by the
# engine's own retired-title guard.
_ENG_LADDER = {"require": r"professor|lecturer"}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Case School of Engineering department on the shared media-card template."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "ladder_filter": _ENG_LADDER},
    }


# ---- Physics & Astronomy: Bootstrap grid table -----------------------------
# Each person is a div.directory-row with four positional .directory-data cells
# (Name link / Title / Email text / Phone text). The header row of each section
# carries .directory-header (label cells, no .directory-data) and is excluded.
_PHYS_SEL = {
    "card": "div.directory-row:not(.directory-header)",
    "name": "div.directory-data:nth-of-type(1)",
    "link": "div.directory-data:nth-of-type(1) a",
    "title": "div.directory-data:nth-of-type(2)",
    "email": "div.directory-data:nth-of-type(3)",
}

# ---- Math/AppliedMath/Statistics: WordPress directory grid ------------------
# Each person is a div.row.directory-space; the info column (div.col-xs-7) holds
# the name link then rank / email / phone as <br>-separated bare text. The rank
# has no element of its own, so title_re lifts it from the card text (a plain
# "Instructor" then fails the ladder gate); the email is regex-extracted from the
# whole info column by _clean_email.
_MATH_SEL = {
    "card": "div.row.directory-space",
    "name": "div.col-xs-7 a",
    "link": "div.col-xs-7 a",
    "email": "div.col-xs-7",
    "title_re": (
        r"((?:Adjunct |Visiting |Assistant |Associate |Research |Senior "
        r"|Full[- ]?[Tt]ime |Part[- ]?[Tt]ime |Clinical |Teaching |Distinguished "
        r"|Emeritus |Emerita )*(?:Professor|Lecturer|Instructor))"
    ),
}

# Ladder gate shared by Physics + Math: keep professors and lecturers, drop the
# instructors / staff. Emeriti are handled by the engine's retired-title guard.
_LADDER = {"require": r"professor|lecturer"}


SCHOOL: dict = {
    "school_slug": "casewestern",
    "source": "casewestern_faculty",
    "organization": "Case Western Reserve University",
    "location": "Cleveland, OH",
    "id_prefix": "casewestern",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Case Western Reserve University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Case School of Engineering (shared media-card template) --------
        _eng("CS", "Department of Computer and Data Sciences",
             ["Computer Science", "Data Science"],
             "https://engineering.case.edu/computer-and-data-sciences/faculty-and-staff"),
        _eng("ECSE", "Department of Electrical, Computer and Systems Engineering",
             ["Electrical Engineering", "Computer Engineering", "Systems Engineering"],
             "https://case.edu/engineering/electrical-computer-and-systems-engineering/about/our-team"),
        _eng("EMAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "https://engineering.case.edu/mechanical-and-aerospace-engineering/faculty-and-staff"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"],
             "https://case.edu/bme/people/primary-faculty"),
        # ---- College of Arts & Sciences: Physics ----------------------------
        {
            "short": "PHYS", "name": "Department of Physics",
            "majors": ["Physics", "Astronomy"],
            "directory_url": "https://physics.case.edu/directory/faculty/",
            "scrape": {
                "url": "https://physics.case.edu/directory/faculty/",
                "selectors": _PHYS_SEL,
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Arts & Sciences: Math / Applied Math / Statistics ---
        {
            "short": "MATH",
            "name": "Department of Mathematics, Applied Mathematics and Statistics",
            "majors": ["Mathematics", "Applied Mathematics", "Statistics"],
            "directory_url": "https://mathstats.case.edu/faculty-staff/",
            "scrape": {
                "url": "https://mathstats.case.edu/faculty-staff/",
                "selectors": _MATH_SEL,
                "ladder_filter": _LADDER,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
