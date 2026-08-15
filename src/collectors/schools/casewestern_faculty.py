"""Case Western Reserve University faculty config (via the faculty_graph engine).

Full-coverage build (live-verified 2026-07-24): every department of the four
colleges the frontend catalog knows — Case School of Engineering (all eight
departments), the College of Arts and Sciences (every department with a
directory), the Weatherhead School of Management (all six departments), and the
Frances Payne Bolton School of Nursing — plus the School of Medicine's
Department of Neurosciences, which is the teaching faculty behind the College's
Neuroscience major. Seven markup families, all majority-emailed:

* **Case Drupal "media" card** (``_eng``) — the shared case.edu / engineering
  .case.edu template: ``h3.media-heading > a`` (name, credentials-suffixed) +
  ``p.media-title`` (rank + department) + a ``mailto:`` anchor, wrapped in
  either ``li.biography`` (the ``/faculty-and-staff`` pages) or ``li.media``
  (the ``/about/our-team`` and case.edu pages), so one card selector matches
  both. Carries all eight engineering departments, Music, Cognitive Science,
  Neurosciences, and Weatherhead.

* **Weatherhead** (``_wsom``) — one school-wide directory of ~180 cards, not
  per-department rosters (each department's own page features only its chair).
  The rank line names the home department ("Associate Professor, Department of
  Economics, Weatherhead School of Management"), so a ``field_filter`` over
  ``p.media-title`` splits the shared page into the six real departments; the
  seventh entry sweeps up the deans'-office and Doctor-of-Management adjuncts
  whose line carries no department, excluding the six matched above.

* **Arts & Sciences directory grid** (``_grid``) — the WordPress theme shared by
  most A&S department sites: one ``div.directory-row`` per person with four
  positional ``.directory-data`` cells (Name link / Title / Email text / Phone).
  ``:not(.directory-header)`` drops each section's column-label row; emails are
  plain text (``_clean_email`` extracts them). Carries twelve departments.

* **Mathematics, Applied Mathematics & Statistics** (``_MATH_SEL``) — an older
  WordPress grid: ``div.row.directory-space`` per person, with the rank / email
  / phone as ``<br>``-separated bare text inside ``div.col-xs-7``. ``title_re``
  lifts the rank (plain Instructors then fail the ladder gate) and the email is
  regex-extracted from the whole info cell.

* **WPBakery column pseudo-table** (``_col``) — Political Science and Classics
  render each person as a row of ``div.wpb_column`` cells (Name link / Title /
  Email / Phone) with no per-person class. Political Science's rows are the
  inner ``div.vc_row.vc_inner``; Classics' are the direct ``div.vc_row``
  children of ``.entry-content`` (a descendant selector would also match the
  wrappers and re-emit the first person of each block).

* **HTML table** — History (Name / Title / Specialization / Email, with the
  specialization cell wired as ``research`` for free keywords) and Nursing (an
  A–Z table whose name cell is inverted, hence ``name_flip``). Both pages carry
  several tables — staff and emeriti included — which the ladder gate and the
  engine's retired-title guard drop.

* **Headless render** — Chemistry only. ``chemistry.case.edu/people/faculty/``
  is served with unclosed ``<p>`` markup that html.parser collapses into a
  single row (this is why Chemistry was dropped in the previous build); a
  browser's error-recovering parser rebuilds the real grid, so
  ``scrape["render"] = True`` recovers 24 faculty at 83% email. Biology's
  WPBakery page needs no render but does need a ``field_filter`` requiring a
  ``mailto:``, since its person rows share a class with the layout wrappers.

Every roster is gated to ladder + research + teaching faculty by the shared
``require: professor|lecturer`` filter, which drops the staff sections
(managers, coordinators, assistants, lab techs) and plain Instructors; emeriti
are dropped by the engine's own retired-title guard.

DROPPED / phase-2:
* **Astronomy** — no separate directory (``astronomy.case.edu`` does not
  resolve); CWRU's astronomers are listed in Physics, which carries the
  Astronomy major.
* **Weatherhead per-department rosters** — ``/about/departments/<dept>`` pages
  render only the department chair (1–2 cards), so the school-wide directory is
  the only complete source; see ``_wsom`` above.
* **Schools of Medicine, Law, Dental Medicine, and the Mandel School of Applied
  Social Sciences** — real directories exist, but none of these colleges is in
  the frontend catalog for this school, so their records would land under a
  college the matcher cannot map. Deliberately deferred, not blocked.

Single source ("casewestern_faculty"); department rides each record, ids
namespaced by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + research + teaching professors and lecturers; drop the staff
# buckets (managers, coordinators, assistants, lab technicians) and plain
# Instructors, whose titles carry neither word. Emeriti are dropped downstream
# by the engine's retired-title guard.
_LADDER = {"require": r"professor|lecturer"}

# A rank with no element of its own, lifted out of the card's running text.
# Shared by the two families whose markup keeps the rank as bare prose.
_RANK_RE = (
    r"((?:Adjunct |Visiting |Assistant |Associate |Research |Senior "
    r"|Full[- ]?[Tt]ime |Part[- ]?[Tt]ime |Clinical |Teaching |Distinguished "
    r"|Emeritus |Emerita )*(?:Professor|Lecturer|Instructor))"
)

# ---- Case Drupal "media" card ----------------------------------------------
# The name carries trailing credentials (", PhD") the engine strips; the title
# cell holds rank + department (endowed-chair titles still contain "Professor"),
# so the ladder gate reads it directly.
_ENG_SEL = {
    "card": "li.biography, li.media",
    "name": "h3.media-heading a",
    "link": "h3.media-heading a",
    "title": "p.media-title",
    "email": "a[href^='mailto:']",
}


# The Drupal profile pages label a "Research Information" section and put the
# areas under it; the listing carries none of it. Restricted to case.edu proper
# because the other three roster families link out to department WordPress
# subdomains and to artscidirectory.case.edu, neither of which labels anything.
_ENG_ENRICH = {
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE,
    "profile_url_re": r"https://case\.edu/",
    "throttle": 0.15,
}


def _eng(short: str, name: str, majors: list[str], url: str,
         field_filter: dict | None = None) -> dict:
    """A department on the shared case.edu Drupal media-card template."""
    scrape = {"url": url, "selectors": _ENG_SEL, "ladder_filter": _LADDER,
              "profile_enrich": _ENG_ENRICH}
    if field_filter:
        scrape["field_filter"] = field_filter
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---- Weatherhead: one shared directory, split by the rank line's department --
_WSOM_URL = "https://case.edu/weatherhead/about/faculty-and-staff-directory"
# The six department names as they appear in the rank line ("&", not "and", on
# most cards — but both spellings are in use, so match either).
_WSOM_DEPTS = (
    r"Accountancy|Banking (?:&|and) Finance|Design (?:&|and) Innovation"
    r"|Economics|Operations|Organizational Behavior"
)


def _wsom(short: str, name: str, majors: list[str], dept_re: str) -> dict:
    """A Weatherhead department, carved out of the school-wide directory."""
    return _eng(short, name, majors, _WSOM_URL,
                field_filter={"selector": "p.media-title",
                              "include": rf"Department of (?:{dept_re})"})


# ---- Arts & Sciences directory grid ----------------------------------------
# Each person is a div.directory-row with four positional .directory-data cells
# (Name link / Title / Email text / Phone text). The column-label row of each
# section carries .directory-header and is excluded.
_GRID_SEL = {
    "card": "div.directory-row:not(.directory-header)",
    "name": "div.directory-data:nth-of-type(1)",
    "link": "div.directory-data:nth-of-type(1) a",
    "title": "div.directory-data:nth-of-type(2)",
    "email": "div.directory-data:nth-of-type(3)",
}


def _grid(short: str, name: str, majors: list[str], url: str) -> dict:
    """An A&S department on the shared WordPress directory-grid template."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _GRID_SEL,
                       "ladder_filter": _LADDER}}


# ---- WPBakery column pseudo-table ------------------------------------------
# Name link / Title / Email / Phone, one wpb_column per field, no per-person
# class — the row element differs per site, so the caller passes the card.
_COL_SEL = {
    "name": "div.wpb_column:nth-of-type(1)",
    "link": "div.wpb_column:nth-of-type(1) a",
    "title": "div.wpb_column:nth-of-type(2)",
    "email": "div.wpb_column:nth-of-type(3)",
}


def _col(short: str, name: str, majors: list[str], url: str, card: str) -> dict:
    """A department whose roster is a WPBakery row-of-columns pseudo-table."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": {"card": card, **_COL_SEL},
                       "ladder_filter": _LADDER}}


# ---- Mathematics: older WordPress directory grid ----------------------------
# Each person is a div.row.directory-space; the info column (div.col-xs-7) holds
# the name link then rank / email / phone as <br>-separated bare text with no
# wrapping elements, so title_re lifts the rank and _clean_email regex-extracts
# the address from the whole cell.
_MATH_SEL = {
    "card": "div.row.directory-space",
    "name": "div.col-xs-7 a",
    "link": "div.col-xs-7 a",
    "email": "div.col-xs-7",
    "title_re": _RANK_RE,
}


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
        # ---- Case School of Engineering (all eight departments) -------------
        _eng("CS", "Department of Computer and Data Sciences",
             ["Computer Science", "Data Science and Analytics"],
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
        _eng("CHEME", "Department of Chemical and Biomolecular Engineering",
             ["Chemical Engineering"],
             "https://engineering.case.edu/chemical-and-biomolecular-engineering/faculty-and-staff"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering"],
             "https://engineering.case.edu/civil-and-environmental-engineering/faculty-and-staff"),
        _eng("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "https://engineering.case.edu/materials-science-and-engineering/faculty-and-staff"),
        _eng("EMSE", "Department of Macromolecular Science and Engineering",
             ["Polymer Science and Engineering", "Materials Science and Engineering"],
             "https://engineering.case.edu/macromolecular-science-and-engineering/faculty-and-staff"),
        # ---- College of Arts and Sciences: directory-grid template -----------
        _grid("PHYS", "Department of Physics", ["Physics", "Astronomy"],
              "https://physics.case.edu/directory/faculty/"),
        _grid("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.case.edu/faculty-staff/"),
        _grid("EEPS", "Department of Earth, Environmental and Planetary Sciences",
              ["Earth, Environmental, and Planetary Sciences"],
              "https://eeps.case.edu/faculty/"),
        _grid("ENGL", "Department of English", ["English"],
              "https://english.case.edu/directory/"),
        _grid("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.case.edu/people/"),
        _grid("SOC", "Department of Sociology", ["Sociology"],
              "https://sociology.case.edu/people/"),
        _grid("PSYC", "Department of Psychological Sciences",
              ["Psychological Sciences", "Cognitive Science"],
              "https://psychsciences.case.edu/people/"),
        _grid("THTR", "Department of Theater", ["Theater Arts"],
              "https://theater.case.edu/faculty/"),
        _grid("ARTH", "Department of Art History and Art — Art History",
              ["Art History"],
              "https://arthistory.case.edu/people-art-history/"),
        _grid("ARTS", "Department of Art History and Art — Art Studio",
              ["Art History"],
              "https://arthistory.case.edu/people-art-studio-education/"),
        _grid("MLL", "Department of Modern Languages and Literatures",
              ["Modern Languages and Literatures"],
              "https://mll.case.edu/faculty/"),
        _grid("RLGN", "Department of Religious Studies", ["Religious Studies"],
              "https://religion.case.edu/directory/"),
        # ---- College of Arts and Sciences: one-off markup --------------------
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
        _col("POLI", "Department of Political Science", ["Political Science"],
             "https://politicalscience.case.edu/people/", "div.vc_row.vc_inner"),
        _col("CLSC", "Department of Classics", ["Classics"],
             "https://classics.case.edu/people/", "div.entry-content > div.vc_row"),
        {
            "short": "HIST", "name": "Department of History", "majors": ["History"],
            "directory_url": "https://history.case.edu/about/people/",
            "scrape": {
                "url": "https://history.case.edu/about/people/",
                "ladder_filter": _LADDER,
                "selectors": {
                    "card": "table tr",
                    "name": "td:nth-of-type(1)",
                    "link": "td:nth-of-type(1) a",
                    "title": "td:nth-of-type(2)",
                    "research": "td:nth-of-type(3)",
                    "email": "td:nth-of-type(4)",
                },
            },
        },
        {
            # Person rows share div.vc_row.wpb_row with the page's layout
            # wrappers; requiring a mailto keeps only the real people.
            "short": "BIOL", "name": "Department of Biology", "majors": ["Biology"],
            "directory_url": "https://biology.case.edu/faculty/",
            "scrape": {
                "url": "https://biology.case.edu/faculty/",
                "ladder_filter": _LADDER,
                "field_filter": {"selector": "a[href^='mailto:']", "require_present": True},
                "selectors": {
                    "card": "div.vc_row.wpb_row",
                    "name": "a[href*='/faculty/']",
                    "name_strip": r",\s*$",
                    "link": "a[href*='/faculty/']",
                    "title_re": _RANK_RE,
                    "email": "a[href^='mailto:']",
                    # Each card carries a "Focus:" research line (comma list);
                    # zero-fetch listing win.
                    "research_re": r"Focus:\s*(.*?)</p>",
                },
            },
        },
        {
            # Unclosed <p> markup — only a browser's error-recovering parser
            # rebuilds the grid, so this one department renders headless.
            "short": "CHEM", "name": "Department of Chemistry", "majors": ["Chemistry"],
            "directory_url": "https://chemistry.case.edu/people/faculty/",
            "scrape": {
                "url": "https://chemistry.case.edu/people/faculty/",
                "render": True,
                "render_settle": 5000,
                "ladder_filter": _LADDER,
                "selectors": {
                    "card": "div.entry-content div.row",
                    "name": "a[href*='/faculty/']",
                    "link": "a[href*='/faculty/']",
                    "title": "div[class*='col-md-3'] p:nth-of-type(3)",
                    "research": "div[class*='col-md-3']:nth-of-type(4)",
                    "email": "div:nth-of-type(3)",
                },
            },
        },
        _eng("COGS", "Department of Cognitive Science", ["Cognitive Science"],
             "https://case.edu/artsci/cognitivescience/about/faculty-and-staff"),
        _eng("MUSC", "Department of Music", ["Music"],
             "https://case.edu/artsci/music/people/faculty-lecturers"),
        _eng("NEUR", "Department of Neurosciences", ["Neuroscience", "Biology"],
             "https://case.edu/medicine/neurosciences/people-research/faculty-name"),
        # ---- Weatherhead School of Management (shared directory, split) ------
        _wsom("ACCT", "Department of Accountancy", ["Accounting"], r"Accountancy"),
        _wsom("BAFI", "Department of Banking and Finance", ["Finance"],
              r"Banking (?:&|and) Finance"),
        _wsom("DESN", "Department of Design and Innovation",
              ["Business Information Technology", "Marketing"],
              r"Design (?:&|and) Innovation"),
        _wsom("ECON", "Department of Economics", ["Economics"], r"Economics"),
        _wsom("OPRE", "Department of Operations", ["Business Management", "Management"],
              r"Operations"),
        _wsom("ORBH", "Department of Organizational Behavior",
              ["Management", "Business Management"], r"Organizational Behavior"),
        _eng("WSOM", "Weatherhead School of Management",
             ["Business Management", "Management", "Marketing"], _WSOM_URL,
             field_filter={"selector": "p.media-title",
                           "exclude": rf"Department of (?:{_WSOM_DEPTS})"}),
        # ---- Frances Payne Bolton School of Nursing --------------------------
        {
            # A–Z table; the name cell is inverted ("Aaron, Siobhan").
            "short": "NURS", "name": "Frances Payne Bolton School of Nursing",
            "majors": ["Nursing"],
            "directory_url": "https://case.edu/nursing/about/fpb-directories/faculty-directory",
            "scrape": {
                "url": "https://case.edu/nursing/about/fpb-directories/faculty-directory",
                "ladder_filter": _LADDER,
                "name_flip": True,
                "selectors": {
                    "card": "table tr",
                    "name": "td:nth-of-type(1) a",
                    "link": "td:nth-of-type(1) a",
                    "title": "td:nth-of-type(2)",
                    "email": "td:nth-of-type(5)",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
