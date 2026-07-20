"""University of South Florida faculty config (via the faculty_graph engine).

Every USF department directory runs the same Modern Campus / OmniUpdate static
``.aspx`` CMS — plain server-rendered HTTP 200s (no render mode, no WAF).
Live-verified 2026-07-20. The campus template does NOT wrap each person in a
self-contained "card" with class-tagged name/title/email fields; instead a person
is a loose run of ``<p>`` (or table-row / ``<h4>``) markup where the rank is bare
text after a ``<br>``. So the rank is recovered with a shared ``title_re`` over the
card text rather than a CSS selector, and three markup families cover the six
departments:

* **Image-grid, name-is-a-link (Bellini College — Computer Science & Engineering).**
  ``div.snippetImageGrid_item`` per person; the name is an ``a`` to
  ``…/people/faculty/<slug>.aspx`` with the rank as bare text after a ``<br>``, and
  the office/email sit in a sibling ``<p>`` (``mailto``) inside the same grid item.
  The page groups people under in-page anchors whose visible labels are ``<h3>``
  headers (Affiliated / Courtesy / Adjunct / Distinguished-Emeritus / Emeritus) —
  a ``section_filter`` (heading ``h3``, ``exclude``) keeps only the core Faculty
  section (its nearest preceding ``h3`` is an empty spacer heading, so it passes)
  and drops the five non-core sections, seven of which carry real profile links
  that would otherwise slip through the ladder gate.

* **Image-grid, name-is-a-heading (Chemistry, Mechanical Engineering).**
  Same ``div.snippetImageGrid_item`` grid, but the name is an ``<h4>`` and the
  rank/office/email live in the immediately-following ``<p>`` (``h4 + p``). These
  two pages MIX non-faculty into the roster (Chemistry lists lab managers /
  program directors; MAE lists Affiliate/Adjunct MAE Faculty in its Core-Faculty
  block plus Courtesy + Emeritus sections). The rank is bare text with no element
  of its own, so a title-only ladder gate would fall through to the engine's
  default "Professor" and ship a staff card — instead a ``field_filter`` reads the
  ``h4 + p`` title paragraph directly (``require_present``), keeps only
  professor/lecturer/instructor ranks, and ``exclude``s Affiliate/Adjunct/Emeritus.

* **Image-grid, name-is-a-``<strong>`` (Electrical & Computer Engineering).**
  ``div.snippetImageGrid_item`` where the name is a ``<strong>`` (sometimes wrapped
  in an ``a`` to ``…/faculty-staff/<slug>.aspx``, sometimes bare, and on one card an
  ``a`` with no ``<strong>``) — the ``strong, a[href*="/faculty-staff/"]`` union
  selector lands the name in every variant. The listing is faculty-only, so the
  ladder gate is a safety net.

* **Table (Physics, Mathematics & Statistics).**
  A ``<table>`` roster with one ``<tr>`` per person, the name an ``a`` to
  ``…/people/faculty/<slug>.aspx`` and the rank bare text after a ``<br>``. Physics
  keeps its Emeriti/Affiliated rosters in collapsible ``div.snippetToggle_content``
  tables, so the card selector scopes to the core table via the direct-child
  combinator ``div.mainContent_well > table tr`` (the toggled tables are deeper);
  Physics also publishes a clean single-area "Research Areas" cell (captured).
  Mathematics inverts names ("Last, First" → ``name_flip``) and lists Adjunct
  Instructors with profile links alongside permanent faculty (dropped via the
  ladder ``drop``); its Visiting-Faculty and Postdoctoral-Scholars tables carry no
  profile links, so the name selector excludes them by construction.

The USF college reorg (2025) moved Computer Science & Engineering into the new
Bellini College of AI, Cybersecurity and Computing; Electrical Engineering is the
ECE department and Mechanical is the MAE department, both in the College of
Engineering. Single source ("usf_faculty"); department rides each record, ids
namespaced by department short-code.

Live-verified 2026-07-20 (kept-after-gate): CSE 65, ECE 29, Physics 31,
Chemistry 43, Mathematics & Statistics 58, MAE 33.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared rank extractor: the USF template prints the rank as bare text after a
# ``<br>`` with no element of its own, so a regex over the card text recovers it
# (leftmost match = the rank right after the name, before office/abstract text).
# Ordered so a fuller phrase wins over bare "Professor"; the trailing Emeritus
# group rides along so the engine's retired-title gate can see "Professor Emeritus".
_USF_TITLE_RE = (
    r"((?:Distinguished\s+University\s+|Distinguished\s+|Executive\s+Associate\s+"
    r"|Associate\s+|Assistant\s+|Research\s+|Visiting\s+|Clinical\s+|Teaching\s+"
    r"|Adjunct\s+|Courtesy\s+|Senior\s+)*"
    r"(?:Professor|Lecturer|Instructor)(?:\s+of\s+Instruction)?(?:\s+Emerit\w+)?)"
)

# Keep every professor / lecturer / instructor rank (USF's teaching track is
# "Professor of Instruction" / "…Instructor"); the engine's retired gate drops
# emeriti. Instructor is included because USF Math's permanent teaching faculty
# carry "Assistant/Associate Instructor" ranks.
_LADDER = {"require": r"professor|lecturer|instructor"}


def _grid_link(short: str, name: str, majors: list[str], url: str,
               *, section_exclude: str | None = None) -> dict:
    """Grid where the name is an ``a`` → ``…/people/faculty/…`` (Bellini CSE)."""
    scrape: dict = {
        "url": url,
        "selectors": {
            "card": "div.snippetImageGrid_item",
            "name": 'a[href*="/people/faculty/"]',
            "link": 'a[href*="/people/faculty/"]',
            "title_re": _USF_TITLE_RE,
            "email": 'a[href^="mailto:"]',
        },
        "ladder_filter": _LADDER,
    }
    if section_exclude:
        scrape["section_filter"] = {"heading": "h3", "exclude": section_exclude}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _grid_h4(short: str, name: str, majors: list[str], url: str,
             *, field_exclude: str, section_include: str | None = None) -> dict:
    """Grid where the name is an ``<h4>`` and the rank is the following ``<p>``.

    Chemistry and MAE mix non-faculty into the roster, and the rank is bare text
    (no element), so the engine's title-only gate would default a role-less staff
    card to "Professor" and keep it. A ``field_filter`` reads the ``h4 + p`` title
    paragraph directly (``require_present``), keeps only professor/lecturer/
    instructor ranks, and ``exclude``s Affiliate/Adjunct/Emeritus/Retired lines.
    """
    scrape: dict = {
        "url": url,
        "selectors": {
            "card": "div.snippetImageGrid_item",
            "name": "h4",
            "link": "h4 a",
            "title_re": _USF_TITLE_RE,
            "email": 'a[href^="mailto:"]',
        },
        "field_filter": {
            "selector": "h4 + p",
            "require_present": True,
            "include": r"professor|lecturer|instructor",
            "exclude": field_exclude,
        },
        "ladder_filter": _LADDER,
    }
    if section_include:
        scrape["section_filter"] = {"heading": "h3", "include": section_include}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


_ECE_URL = "https://www.usf.edu/engineering/ece/faculty-staff/index.aspx"
_PHYS_URL = ("https://www.usf.edu/arts-sciences/departments/physics/"
             "people/faculty/index.aspx")
_MATH_URL = ("https://www.usf.edu/arts-sciences/departments/"
             "mathematics-statistics/people/faculty/index.aspx")


SCHOOL: dict = {
    "school_slug": "usf",
    "source": "usf_faculty",
    "organization": "University of South Florida",
    "location": "Tampa, FL",
    "id_prefix": "usf",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of South Florida) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Bellini College: Computer Science & Engineering ----------------
        # Grid with h3 section headers; keep only the core Faculty section and
        # drop the Affiliated / Adjunct / Courtesy / Distinguished-Emeritus /
        # Emeritus blocks (seven of which carry real profile links).
        _grid_link(
            "CSE", "Department of Computer Science and Engineering",
            ["Computer Science", "Artificial Intelligence", "Cybersecurity",
             "Data Science"],
            "https://www.usf.edu/ai-cybersecurity-computing/people/faculty/index.aspx",
            section_exclude=r"affiliated|adjunct|courtesy|emerit|distinguished",
        ),
        # ---- College of Engineering: Electrical & Computer Engineering ------
        {
            "short": "ECE",
            "name": "Department of Electrical Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": _ECE_URL,
            "scrape": {
                "url": _ECE_URL,
                "selectors": {
                    "card": "div.snippetImageGrid_item",
                    # Name is a <strong> — bare, wrapped in an <a>, or (one card)
                    # replaced by a bare <a> with no <strong>; the union lands it.
                    "name": 'strong, a[href*="/faculty-staff/"]',
                    "link": 'a[href*="/faculty-staff/"]',
                    "title_re": _USF_TITLE_RE,
                    "email": 'a[href^="mailto:"]',
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Engineering: Mechanical Engineering (MAE) -----------
        # Grid; Core-Faculty block mixes in Affiliate/Adjunct MAE Faculty, plus
        # Courtesy + Emeritus sections. Gate on the h4+p title paragraph.
        _grid_h4(
            "MAE", "Department of Mechanical Engineering",
            ["Mechanical Engineering", "Aerospace Engineering"],
            "https://www.usf.edu/engineering/mae/people/index.aspx",
            field_exclude=r"affiliate|adjunct|emerit|retired|courtesy",
            section_include=r"core",
        ),
        # ---- College of Arts & Sciences: Physics ----------------------------
        {
            "short": "PHYS",
            "name": "Department of Physics",
            "majors": ["Physics", "Applied Physics"],
            "directory_url": _PHYS_URL,
            "scrape": {
                "url": _PHYS_URL,
                "selectors": {
                    # Scope to the core faculty table: the Emeriti/Affiliated
                    # rosters sit in collapsible div.snippetToggle_content tables
                    # (deeper than a direct child of the mainContent well).
                    "card": "div.mainContent_well > table tr",
                    "name": 'a[href*="/people/faculty/"]',
                    "link": 'a[href*="/people/faculty/"]',
                    "title_re": _USF_TITLE_RE,
                    # Clean single research-area label in the last cell.
                    "research": "td:last-of-type",
                    "email": 'a[href^="mailto:"]',
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Arts & Sciences: Chemistry --------------------------
        # Grid; roster mixes in lab managers / program directors (no rank word),
        # so gate on the h4+p title paragraph.
        _grid_h4(
            "CHEM", "Department of Chemistry",
            ["Chemistry", "Biochemistry"],
            "https://www.usf.edu/arts-sciences/departments/chemistry/faculty/index.aspx",
            field_exclude=r"emerit|retired|adjunct",
        ),
        # ---- College of Arts & Sciences: Mathematics & Statistics -----------
        {
            "short": "MATH",
            "name": "Department of Mathematics and Statistics",
            "majors": ["Mathematics", "Statistics", "Applied Mathematics"],
            "directory_url": _MATH_URL,
            "scrape": {
                "url": _MATH_URL,
                "selectors": {
                    "card": "table tr",
                    "name": 'a[href*="/people/faculty/"]',
                    "link": 'a[href*="/people/faculty/"]',
                    "title_re": _USF_TITLE_RE,
                    "email": 'a[href^="mailto:"]',
                },
                # Names are inverted ("Abaquita, Edwin V." → "Edwin V. Abaquita").
                "name_flip": True,
                # Permanent Faculty is the only table with profile links besides
                # Adjunct Faculty (Adjunct Instructors) — drop those; Visiting +
                # Postdoc tables carry no profile links and drop by construction.
                "ladder_filter": {
                    "require": r"professor|lecturer|instructor",
                    "drop": r"adjunct|visiting|emerit",
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
