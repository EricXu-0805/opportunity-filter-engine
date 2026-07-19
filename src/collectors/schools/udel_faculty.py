"""University of Delaware faculty config (via the faculty_graph engine).

Four distinct server-rendered markup families across the six STEM departments —
all plain-HTTP 200s, no WAF, no JS render needed. Live-verified 2026-07-19.

* **CIS — Divi column grid** (``www.cis.udel.edu/people/faculty/``).
  Each professor is a ``div.et_pb_column`` card carrying an
  ``a.entry-featured-image-url`` profile link, an ``h2`` name, and a stack of
  ``<p>`` lines (rank / office / phone / mailto). The card selector is scoped to
  columns that actually hold a faculty link (``:has(a.entry-featured-image-url)``)
  so the four layout columns without a person are skipped. First ``<p>`` is the
  rank; the ladder gate keeps professor/endowed-chair ranks and drops the
  Instructors, Associate Instructors, and the lone Senior Researcher.

* **ECE — Divi table, role-sectioned** (``www.ece.udel.edu/people/faculty/``).
  Five ``<table>``s under sibling ``h2`` headings — Primary / Emeritus / Joint /
  Affiliated / Secondary. Only the Primary table is home-department ladder
  faculty; Emeritus rows carry an EMPTY title cell (so the retired-title gate
  can't catch them) and Joint/Affiliated/Secondary carry their outside
  department or employer in the title cell — so a ``section_filter`` on the
  ``h2`` scopes to Primary, and the ladder gate then drops the one Instructor.
  Row = ``td.column-1`` (name+link) / ``td.column-2`` (rank) / ``td.column-4``
  (mailto).

* **Physics / Chemistry / Mathematics — central AEM "Our People"** (one shared
  template on ``www.udel.edu/academics/.../<dept>/our-people/``). Each person is
  a ``div.col-sm-12.col-md-8`` info column (the page's intro block is a
  ``col-sm-8`` column, excluded by the ``col-sm-12`` class) holding an
  ``a.matrixResultLink`` with the name in an ``h1`` and a
  ``.matrixResultTextContent`` block of ``<p><b>`` lines (rank(s) / Email /
  Phone / Office). These pages cross-list a few affiliated faculty whose profile
  lives in ANOTHER department (e.g. a Chemistry professor shown on the Physics
  page), so a ``link_filter`` keeps only own-department profile URLs. A card
  can lead with a non-rank role line ("Department Chair", "Conservation
  Scientist") above its professor rank, so the gate is a ``field_filter`` on the
  whole text block (keeps a card mentioning Professor/Lecturer/Instructor
  anywhere) rather than a title-only ladder — that keeps a professor whose first
  line is an administrative role while still dropping the pure-staff rows.
  The profile hrefs carry an ``/udel/en/`` AEM authoring prefix that 301-redirects
  to the canonical ``/academics/`` path (functional, just a redirect).

* **Mechanical Engineering — WordPress grid** (``me.udel.edu/people/faculty/``).
  Each primary-faculty person is a ``div.faculty-grid-item`` (name in the first
  ``<span>``, rank+office+phone mashed in the second, mailto last). The Adjunct /
  Joint / Secondary / Affiliated / Emeritus people are rendered AFTER these grid
  items in a different structure, so ``div.faculty-grid-item`` is already
  primary-faculty-only; ``title_strip_after`` trims the office/phone tail off the
  rank and the ladder gate drops any non-professor.

Single source ("udel_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-19 (cards seen / kept after gate): CIS 42/34, ECE 32/31
(Primary table), Physics 42/41, Chemistry 38/37, Mathematics 42/42, Mechanical
35/35 (pre-dedupe; the engine collapses any cross-listed duplicates).
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + endowed-chair professors; drop the Instructors, Associate
# Instructors, Senior Researchers, and any adjunct/emeritus/visiting the
# directories mix in. (Emeriti with a real title are also dropped by the
# engine's own retired-title guard.)
_LADDER = {"require": r"professor|chair", "drop": r"emerit|adjunct|visiting"}


# --- CIS: Divi column cards -------------------------------------------------
_CIS_SEL = {
    "card": "div.et_pb_column:has(a.entry-featured-image-url)",
    "name": "h2",
    "link": "a.entry-featured-image-url",
    "title": "p",  # first <p> in the card is the rank line
    "email": "a[href^='mailto:']",
}

# --- ECE: Divi table sliced to the Primary section --------------------------
_ECE_SEL = {
    "card": "table tr",
    "name": "td.column-1 a",
    "link": "td.column-1 a",
    "title": "td.column-2",
    "email": "td.column-4 a[href^='mailto:']",
}

# --- ME: WordPress grid items (primary faculty only) ------------------------
_ME_SEL = {
    "card": "div.faculty-grid-item",
    "name": "span:nth-of-type(1)",
    "link": "a[href*='/faculty/']",
    "title": "span:nth-of-type(2)",
    # Cut the office/phone tail off the rank: a room number, or a
    # "<building> Lab/Hall" office name (some cards omit the room number).
    "title_strip_after": r"\s+\d|\s+\w+\s+(?:Lab|Hall)\b",
    "email": "a[href^='mailto:']",
}

# --- Physics / Chemistry / Mathematics: central AEM "Our People" ------------
_AEM_SEL = {
    "card": "div.col-sm-12.col-md-8",
    "name": "h1",
    "link": "a.matrixResultLink",
    "title": ".matrixResultTextContent p:nth-of-type(1) b",
    "email": "a[href^='mailto:']",
}


def _aem(short: str, name: str, majors: list[str], dept_path: str) -> dict:
    """A CAS department on the shared central-udel.edu AEM "Our People" page.

    ``field_filter`` reads the whole text block and keeps only cards that mention
    a professor/lecturer/instructor rank anywhere (dropping pure-staff rows even
    when their first line is an administrative role); ``link_filter`` drops the
    affiliated faculty this page cross-lists from other departments.
    """
    url = (f"https://www.udel.edu/academics/colleges/cas/units/departments/"
           f"{dept_path}/our-people/")
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _AEM_SEL,
            "link_filter": rf"{dept_path}/our-people/",
            "field_filter": {
                "selector": ".matrixResultTextContent",
                "require_present": True,
                # "Chair" keeps endowed-chair professors whose only title line is
                # a named chair ("C. Eugene Bennett Chair of Chemistry").
                "include": r"Prof|Lecturer|Instructor|Chair",
            },
        },
    }


SCHOOL: dict = {
    "school_slug": "udel",
    "source": "udel_faculty",
    "organization": "University of Delaware",
    "location": "Newark, DE",
    "id_prefix": "udel",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Delaware) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences: Computer & Information Sciences ----
        {
            "short": "CIS", "name": "Department of Computer and Information Sciences",
            "majors": ["Computer Science", "Information Systems", "Data Science"],
            "directory_url": "https://www.cis.udel.edu/people/faculty/",
            "scrape": {
                "url": "https://www.cis.udel.edu/people/faculty/",
                "selectors": _CIS_SEL,
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Engineering ----------------------------------------
        {
            "short": "ECE", "name": "Department of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://www.ece.udel.edu/people/faculty/",
            "scrape": {
                "url": "https://www.ece.udel.edu/people/faculty/",
                "selectors": _ECE_SEL,
                "section_filter": {"heading": "h2", "include": r"^Primary$"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ME", "name": "Department of Mechanical Engineering",
            "majors": ["Mechanical Engineering"],
            "directory_url": "https://me.udel.edu/people/faculty/",
            "scrape": {
                "url": "https://me.udel.edu/people/faculty/",
                "selectors": _ME_SEL,
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Arts & Sciences: central AEM "Our People" ----------
        _aem("PHYS", "Department of Physics and Astronomy",
             ["Physics", "Astronomy", "Astrophysics"], "physics-astronomy"),
        _aem("CHEM", "Department of Chemistry and Biochemistry",
             ["Chemistry", "Biochemistry"], "chem-biochem"),
        _aem("MATH", "Department of Mathematical Sciences",
             ["Mathematics", "Applied Mathematics", "Statistics"],
             "mathematical-sciences"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
