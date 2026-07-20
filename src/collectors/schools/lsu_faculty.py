"""Louisiana State University faculty config (via the faculty_graph engine).

LSU has NO shared campus directory template — every department ships its own
hand-built OmniUpdate (a.cms.omniupdate.com) or Drupal markup, so each of the
nine departments below carries its own selector set. Every page is a plain
server-rendered 200 through a bare request (no WAF, no JS render) and every
address is a plain ``mailto:`` (no cfemail / base64 / hex obfuscation anywhere),
so the engine's existing selectors + decoders cover all of them. Live-verified
2026-07-20. Four distinct markup families:

* **Engineering "faculty-entry" card (CSE, CHE).** Each person is a
  ``div.faculty-entry`` with a two-column Bootstrap row: the left ``col-lg-5``
  wraps the portrait (in an ``h3`` or a ``p``), the right ``col-lg-7`` holds the
  name and contact block. CSE renders the name in ``h3 > strong`` and the rank in
  the first ``p > em`` (endowed-chair titles ride the first ``em``); CHE renders
  the name in a bare centered ``h3`` and the rank as ``<strong>`` text in the
  following ``p`` — but the department chair's first ``p`` is "Department Chair"
  with the real professor rank one ``p`` down, so CHE lifts the rank with
  ``title_re`` over the whole card instead of the first ``p``. Both expose a
  "View BIO" ``a.btn-purple`` profile link and a plain ``mailto``.

* **Engineering table with name+rank packed in one cell (MIE, PHYS).** MIE's main
  faculty table packs ``<a>Last, First</a><br>Rank<br>…`` in the name cell
  (``name_flip`` un-inverts it, ``title_re`` lifts the rank) with the address in a
  separate contact ``<td>``. The page also carries Research / Affiliated /
  Emeritus / "Past Faculty Contributors" ``<h2>`` sections whose rows would leak
  (a "Past Faculty Contributor" carries a live-looking "Professor of…" title), so
  a ``section_filter`` excludes those four ``<h2>`` groups — the main table sits
  under the page ``<h1>`` with no ``<h2>`` of its own and passes. PHYS packs
  ``<img><a>Name</a><br>Rank<br>PhD…<br>Area`` in the name cell of a two-column
  table; the card selector is scoped to ``div.col-md-12 > table`` (the active
  faculty table) so the second ``div.table-responsive`` table (mostly emeriti)
  is excluded. A handful of PHYS instructors publish no profile anchor and are
  dropped (accuracy over recall).

* **Clean columnar table with rank in its own cell (CHEM, BIOSCI).** Name / Rank /
  Phone / Email (+ Office / Division / Research-Theme for CHEM). The name is taken
  from ``td:nth-of-type(1)`` (its text, not its anchor) because instructors with
  no profile page leave the name cell anchor-less — keying off ``td a`` there
  would grab the row's ``mailto`` as the name. CHEM's ``<h2>`` sections let a
  ``section_filter`` drop the Emeritus and Adjunct/Gratis groups; BIOSCI's
  ``faculty.php`` is a single clean table (adjuncts/emeriti live on separate
  pages) and the ladder gate drops its non-ladder "Teaching Associate" staff.

* **Loose ``<p>`` blocks (CEE) / Bootstrap ``col-lg-3`` grid (BAE) / Drupal
  ``div.person`` (MATH).** CEE is a flat sequence of ``<p>`` blocks
  (name-anchor + ``<br>``-rank + ``mailto``); the card selector is ``p`` and the
  name selector is scoped to the ``/eng/cee/people/<slug>.php`` profile anchor so
  the section-nav links (faculty-and-instructors / staff / emeritus / pastfaculty)
  are never selected. BAE is a card grid of ``div.col-lg-3`` (empty grid cells
  self-drop for lacking a name anchor). MATH (own subdomain www.math.lsu.edu) is
  Drupal: ``div.personalinfo`` holds a bold ``span[style*='larger']`` name, a
  first ``<br>``-line that is often a society-fellowship line (so ``title_re``
  lifts the professor rank), a "Research interest:" line (``research_re``), and a
  plain ``mailto``.

Every department carries a ladder gate (``ladder_filter require:
professor|lecturer|instructor``) so teaching staff / coordinators / directors and
grad-student rows drop while ladder + research + teaching + adjunct professors and
lecturers/instructors are kept; emeriti are dropped by the engine's own
retired-title guard (all LSU emeritus rank cells contain "Emeritus").

DROPPED — Electrical & Computer Engineering (ece.lsu.edu): the department's
``.php`` faculty page is a JS SPA and the only static source is
``.../fac/faculty-az-insert-fierce.js`` — a JavaScript blob holding a
backslash-escaped HTML table (``div.name>a`` / ``div.nrank`` / plain ``mailto``,
~25 incl. emeritus). Ingesting it needs a bespoke fetch-``.js``-then-JS-unescape
source in the engine, not a CSS selector config, so ECE is deferred rather than
shipped with an engine change. Nine clean departments beat eight clean + one
that forces an engine edit.

Single source ("lsu_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-20 (listing cards → kept-after-gate/normalize):
CSE 40→38, CHE 26→25, MIE 34→34, CEE 30→~29, BAE 24→24, CHEM 45→45,
BIOSCI 86→86, PHYS 43→43, MATH 48→48. Email coverage is high everywhere the
listing exposes an address (BIOSCI/PHYS/BAE/MATH ~100%, CSE/CHE/CHEM ~93-100%,
MIE 100%).
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + research + teaching + adjunct professors and lecturers/
# instructors; drop coordinators / directors / teaching-associate staff whose
# titles carry none of these words. Emeriti drop via the engine's retired gate.
_LADDER = {"require": r"professor|lecturer|instructor"}

# First rank phrase in a card's text — used where the rank has no clean element
# of its own (the name+rank-in-one-cell tables, the CHE department-chair case,
# the loose-<p>/grid/Drupal blocks). Ordered so a fuller phrase wins over a bare
# "Professor"; an Emeritus suffix rides along so the retired gate can see it.
_TITLE_RE = (
    r"((?:Distinguished |Research |Visiting |Clinical |Adjunct |Teaching "
    r"|Senior )*(?:Assistant |Associate )?Professor(?:\s+Emerit\w+)?"
    r"|Senior Lecturer|Lecturer|Instructor)"
)

_MAILTO = "a[href^='mailto:']"


# ---- Engineering "faculty-entry" card (CSE, CHE) ---------------------------
# CSE: name in h3>strong, rank in the first p>em. CHE: bare centered h3 name,
# rank as <strong> text in a following p — but the chair's first p is "Department
# Chair", so CHE reads the rank with title_re over the whole card instead.
_CSE_SEL = {
    "card": "div.faculty-entry",
    "name": "h3 strong",
    "link": "a.btn-purple",
    "title": "p em",
    "email": _MAILTO,
}
_CHE_SEL = {
    "card": "div.faculty-entry",
    "name": ".col-lg-7 h3",
    "link": "a.btn-purple",
    "title": ".col-lg-7 p",
    "title_re": _TITLE_RE,
    "email": _MAILTO,
}


SCHOOL: dict = {
    "school_slug": "lsu",
    "source": "lsu_faculty",
    "organization": "Louisiana State University",
    "location": "Baton Rouge, LA",
    "id_prefix": "lsu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Louisiana State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering: faculty-entry card -------------------
        {
            "short": "CSE",
            "name": "Division of Computer Science and Engineering",
            "majors": ["Computer Science", "Computer Engineering", "Data Science"],
            "directory_url": "https://www.lsu.edu/eng/cse/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/cse/people/faculty/index.php",
                "selectors": _CSE_SEL,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "CHE",
            "name": "Cain Department of Chemical Engineering",
            "majors": ["Chemical Engineering"],
            "directory_url": "https://www.lsu.edu/eng/che/people/faculty.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/che/people/faculty.php",
                "selectors": _CHE_SEL,
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Engineering: name+rank-in-one-cell table ----------
        {
            "short": "MIE",
            "name": "Department of Mechanical and Industrial Engineering",
            "majors": ["Mechanical Engineering", "Industrial Engineering"],
            "directory_url": "https://www.lsu.edu/eng/mie/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/mie/people/faculty/index.php",
                "selectors": {
                    "card": "table tr",
                    "name": "td:nth-of-type(2) a",
                    "title_re": _TITLE_RE,
                    "email": _MAILTO,
                },
                "name_flip": True,
                # The main faculty table sits under the page <h1> with no <h2>;
                # exclude the four <h2> sub-sections (Research / Affiliated /
                # Emeritus / Past) whose rows would otherwise leak.
                "section_filter": {
                    "heading": "h2",
                    "exclude": r"Research Faculty|Affiliated Faculty|Emeritus Faculty|Past Faculty",
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Engineering: loose <p> blocks ---------------------
        {
            "short": "CEE",
            "name": "Department of Civil and Environmental Engineering",
            "majors": ["Civil Engineering", "Environmental Engineering"],
            "directory_url": "https://www.lsu.edu/eng/cee/people/faculty-and-instructors.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/cee/people/faculty-and-instructors.php",
                "selectors": {
                    "card": "p",
                    "name": "a[href*='/eng/cee/people/'][href$='.php']",
                    # CEE anchor text carries heavy post-nominals ("Louay N.
                    # Mohammad, Ph.D., P.E. (WY), F. ASCE"); the engine's
                    # credential stripper misses the state-license parentheticals.
                    # Names here are "First Last" (never flipped), so any comma
                    # begins the credential tail — cut from the first comma.
                    "name_strip": r",.*$",
                    "title_re": _TITLE_RE,
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Engineering: Bootstrap col-lg-3 grid --------------
        {
            "short": "BAE",
            "name": "Department of Biological and Agricultural Engineering",
            "majors": ["Biological Engineering", "Biological and Agricultural Engineering"],
            "directory_url": "https://www.lsu.edu/eng/bae/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/bae/people/faculty/index.php",
                "selectors": {
                    "card": "div.col-lg-3",
                    "name": "a[href*='/eng/bae/people/faculty/'][href$='.php']",
                    "title_re": _TITLE_RE,
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Science: clean columnar table ---------------------
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.lsu.edu/science/chemistry/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/science/chemistry/faculty/index.php",
                "selectors": {
                    "card": "table tr",
                    "name": "td:nth-of-type(1)",
                    "link": "td:nth-of-type(1) a[href$='.php']",
                    "title": "td:nth-of-type(2)",
                    "email": _MAILTO,
                    "research": "td:nth-of-type(7)",
                },
                "section_filter": {"heading": "h2", "exclude": r"Emeritus|Adjunct|Gratis"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "BIOSCI",
            "name": "Department of Biological Sciences",
            "majors": ["Biological Sciences", "Biology", "Microbiology"],
            "directory_url": "https://www.lsu.edu/science/biosci/faculty-and-staff/faculty.php",
            "scrape": {
                "url": "https://www.lsu.edu/science/biosci/faculty-and-staff/faculty.php",
                "selectors": {
                    "card": "table tr",
                    "name": "td:nth-of-type(1)",
                    "link": "td:nth-of-type(1) a[href$='.php']",
                    "title": "td:nth-of-type(2)",
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Science: name+rank-in-one-cell table (Physics) ----
        {
            "short": "PHYS",
            "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astronomy", "Medical Physics"],
            "directory_url": "https://www.lsu.edu/physics/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/physics/people/faculty/index.php",
                "selectors": {
                    # Scope to the active-faculty table (div.col-md-12 > table);
                    # the second (div.table-responsive) table is mostly emeriti.
                    "card": "div.col-md-12 > table tr",
                    "name": "td a[href*='/people/faculty/']",
                    "title_re": _TITLE_RE,
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- Department of Mathematics (own subdomain, Drupal) ------------
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://www.math.lsu.edu/people/professors",
            "scrape": {
                "url": "https://www.math.lsu.edu/people/professors",
                "selectors": {
                    "card": "div.personalinfo",
                    "name": "span[style*='larger']",
                    "link": "a[href*='/~']",
                    "title_re": _TITLE_RE,
                    "research_re": r"Research interest[s]?:\s*</span>\s*(.*?)\s*<br",
                    "email": _MAILTO,
                },
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
