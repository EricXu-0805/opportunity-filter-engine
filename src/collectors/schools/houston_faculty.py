"""University of Houston faculty config (via the faculty_graph engine).

Full university-wide coverage across three colleges whose directories are clean,
server-rendered HTML (plain-HTTP 200 — no WAF, no JS render). Four markup
families:

* **College of Natural Sciences & Mathematics (NSM) — OU Campus row/col cards.**
  Computer Science, Physics, Chemistry, and Biology & Biochemistry render each
  person as a Bootstrap card: an outer person row whose data column
  (``div.col-8.col-sm-10``) holds an inner row split into ``div.col-sm-7`` (name
  link + ``span.text-muted`` rank + degree, and — CS only — research-area
  ``a.badge`` links) and ``div.col-sm-5`` (a ``mailto:`` email + phone + office).
  ``div.col-8.col-sm-10`` is the card so the sibling email column is in scope.
  The name anchor is a plain ``<a>``; CS research links are ``a.badge`` in a later
  ``<p>``, so the name selector is ``a:not(.badge)`` (an anchorless card — a
  lecturer with no profile page — then yields no name and is skipped rather than
  grabbing a badge as the name). A ``ladder_filter`` (require professor/lecturer,
  drop adjunct/emeritus/visiting) drops the CS Adjunct section; the pages carry no
  grad students/postdocs (those and emeriti live on separate roster pages). Two
  tenure-line/research professors with no profile link (CS: Ernst Leiss;
  Chemistry: Boris Makarenko) are added as curated seeds so the anchor-based
  scrape doesn't lose them.

* **NSM Earth & Atmospheric Sciences — OU Campus row/col cards, reversed names.**
  Same Bootstrap card, but names render "Last, First" ("Antonelli, Michael") with
  a ``<a class="small">Curriculum Vitae</a>`` link inside the name paragraph and no
  ``span.text-muted`` rank; the name selector excludes the CV link
  (``a:not(.small)``), ``name_flip`` un-inverts the surname-first ordering, and a
  ``title_re`` recovers the rank from the loose card text. The single page groups
  people under ``<h2>`` role headings, so a ``section_filter`` keeps only the
  Tenure-Track + Instructional/Research faculty and drops Emeritus / Adjunct /
  Research Scientists / Post-Docs.

* **Cullen College of Engineering — Drupal ``faculty-info`` cards.**
  Electrical & Computer, Mechanical & Aerospace, Civil & Environmental, Chemical &
  Biomolecular, Biomedical, Industrial, and Petroleum Engineering run the same
  Drupal Views directory: one ``div.faculty-info`` card per person with
  ``.faculty-name`` (an ``<a>`` to ``/faculty/<slug>``), a ``.spamspan``
  "x [at] uh.edu" obfuscated email that ``_clean_email`` reassembles, and (where
  present) a "Research Interests" field harvested via ``research_re``. Cards are
  grouped under ``<h3>`` role headings, so a ``section_filter`` drops the
  Emeritus / Adjunct / Past-Service / In-Memoriam sections while keeping ladder +
  research + instructional + joint faculty; the rank is not on a clean per-card
  element, so the record title defaults to "Professor". ECE names carry
  society-fellowship post-nominals ("Ji Chen, Fellow IEEE, Fellow AIMBE") that the
  engine's credential gate doesn't cover, so a ``name_strip`` trims them; the other
  departments' names are clean apart from the "Dr." honorific the engine strips.

* **C.T. Bauer College of Business — ASP directory table.**
  ``index2.asp?dept=<CODE>`` returns a server-rendered table filtered to one
  department; each ``<tr>`` is a person with a ``profile.asp`` name link, a rank
  cell, a phone cell, a home-department cell, and a ``mailto:`` cell. The card is
  the row; ``td:nth-of-type(2)`` is the rank; a ``ladder_filter`` (require
  professor/lecturer, drop adjunct/emeritus/visiting) gates the mixed roster down
  to real faculty (dropping staff, advisors, and PhD students). Five departments:
  Accountancy & Taxation, Finance, Marketing & Entrepreneurship, Management &
  Leadership, and Decision & Information Sciences.

Deliberately DROPPED (not safely scrapeable at the card contract):

* **NSM Mathematics** — its faculty table renders every name in ALL CAPS
  ("ROBERT AZENCOTT") inside inconsistently nested ``<strong>`` tags that leak the
  rank/comma into the name ("BERNHARD BODMANN ,\xa0Professor"), and the engine has
  no case-normalization to recover a clean proper-case pi_name.
* **College of Liberal Arts & Social Sciences (Psychology, Political Science,
  Economics, English, History, Sociology, Philosophy, Communication,
  Anthropology)** — hand-authored prose profile pages with no consistent
  per-person card wrapper and heavy per-department markup drift (English is a
  bare ``<ul><li><a>`` name list; Psychology/Economics are ``<p><img><a>...``
  blocks). No stable card/name/title/email selector spans the college.
* **Gerald D. Hines College of Architecture & Design** — the faculty roster is
  injected client-side by a ``#directory-widget`` JS plugin (empty static HTML).
* **Kathrine G. McGovern College of the Arts (Music, Art, Theatre & Dance)** —
  faculty are comma-joined "Name, Title" ``<li>`` items in accordions with no
  emails and no per-person structure.

Single source ("houston_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-23.
"""

from __future__ import annotations

from .. import faculty_graph
from ..faculty_graph import faculty

# ---- NSM (CS / Physics / Chemistry / Biology): OU Campus row/col cards -------
# The card is the data column so the col-sm-5 email is a descendant. The name is
# the first non-badge anchor in col-sm-7 (CS research links are a.badge in a
# later <p>); rank is span.text-muted; CS research areas are the badge links.
_NSM_SEL = {
    "card": "div.col-8.col-sm-10",
    "name": "div.col-sm-7 p a:not(.badge)",
    "link": "div.col-sm-7 p a:not(.badge)",
    "title": "div.col-sm-7 span.text-muted",
    "email": "div.col-sm-5 a[href^='mailto:']",
    "research_items": "div.col-sm-7 a.badge",
}
# Keep ladder + instructional + lecturer + joint professors and endowed-CHAIR
# holders (whose most senior titles read "…Endowed Chair…"/"…Distinguished
# University Chair…" with no "Professor" word — e.g. Physics' Zhifeng Ren,
# Chemistry's Allan Jacobson); drop the CS Adjunct section and any emeritus/
# visiting. Titles are clean (span.text-muted).
_NSM_LADDER = {"require": r"professor|lecturer|chair",
               "drop": r"adjunct|emerit|visiting"}


def _nsm(short: str, name: str, majors: list[str], url: str,
         faculty_seed: list[dict] | None = None) -> dict:
    """An NSM department on the shared OU Campus row/col component."""
    dept = {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _NSM_SEL, "ladder_filter": _NSM_LADDER},
    }
    if faculty_seed:
        dept["faculty"] = faculty_seed
    return dept


# ---- NSM Earth & Atmospheric Sciences: OU Campus card, reversed names --------
# Same Bootstrap card, but names are "Last, First" with an inline CV link and no
# span.text-muted rank. Exclude the CV link from the name, flip the surname-first
# ordering, and recover the rank from the loose card text via title_re.
_EAS_SEL = {
    "card": "div.col-8.col-sm-10",
    "name": "div.col-sm-7 p a:not(.small)",
    "link": "div.col-sm-7 p a:not(.small)",
    "title_re": (r"(?i)\b((?:Associate |Assistant |Research |Clinical |Visiting )*"
                 r"(?:Professor|Lecturer|Instructor))\b"),
    "email": "div.col-sm-5 a[href^='mailto:']",
}
# People are grouped under <h2> role headings on one page; keep Tenure-Track +
# Instructional/Research faculty, drop Emeritus / Adjunct / Research Scientists /
# Post-Doctoral Researchers.
_EAS_SECTION = {"heading": "h2", "exclude": r"emerit|adjunct|scientist|post-doc"}


# ---- Cullen College of Engineering: Drupal faculty-info cards ----------------
_ENG_SEL = {
    "card": "div.faculty-info",
    "name": "div.faculty-name",
    "link": "a:has(> div.faculty-name)",
    # ".spamspan" is "x [at] uh.edu" obfuscation — _clean_email reassembles it.
    "email": ".spamspan",
    # Rank is loose <br>-separated text with no clean element; grab the rich
    # "Research Interests" value instead (bounded to its field <div>).
    "research_re": r"Research Interests</span>(.*?)</div>",
    # ECE post-nominals: "Ji Chen, Fellow IEEE, Fellow AIMBE" / "Aaron Becker,
    # Senior Member IEEE" / "Donald Wilton, IEEE Life Fellow, Member NAE" — trim
    # from the first society-credential comma (other depts' names have none, so
    # unaffected; the leading "Dr." is stripped by the engine's honorific gate).
    "name_strip": r"(?i),\s*(?:Fellow|Senior\s+Member|Member|IEEE|FRSC|NAI|Life\s+Fellow)\b.*$",
}
# Cards are grouped under <h3> role headings; drop the Emeritus / Adjunct /
# Past-Service / In-Memoriam sections, keep everything else (Chair / ladder /
# research / instructional / lecturer / joint). Rank is not on a clean per-card
# element, so the title defaults to "Professor".
_ENG_SECTION = {"heading": "h3", "exclude": r"emerit|adjunct|memoriam|past service"}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Cullen Engineering department on the shared Drupal faculty-info view."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "section_filter": _ENG_SECTION},
    }


# ---- C.T. Bauer College of Business: ASP directory table --------------------
# index2.asp?dept=<CODE> is a per-department server-rendered table. The card is
# the row; the name is the profile.asp link, the rank is the 2nd cell, the email
# is the mailto cell. A ladder_filter drops staff / advisors / PhD students.
_BAUER_SEL = {
    "card": "tr",
    "name": "td a[href*='profile.asp']",
    "link": "td a[href*='profile.asp']",
    "title": "td:nth-of-type(2)",
    "email": "td a[href^='mailto:']",
}
_BAUER_LADDER = {"require": r"professor|lecturer", "drop": r"adjunct|emerit|visiting"}
_BAUER_DIR = "https://www.bauer.uh.edu/search/directory/index2.asp?dept="


def _bauer(short: str, name: str, majors: list[str], code: str) -> dict:
    """A Bauer department on the shared ASP directory table (filtered by code)."""
    url = f"{_BAUER_DIR}{code}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _BAUER_SEL, "ladder_filter": _BAUER_LADDER},
    }


SCHOOL: dict = {
    "school_slug": "houston",
    "source": "houston_faculty",
    "organization": "University of Houston",
    "location": "Houston, TX",
    "id_prefix": "houston",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Houston) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Natural Sciences & Mathematics ----------------------
        _nsm("CS", "Department of Computer Science",
             ["Computer Science", "Data Science"],
             "https://www.uh.edu/nsm/computer-science/people/faculty/",
             faculty_seed=[
                 # Tenured/tenure-track Professor listed without a profile link
                 # (anchor-based scrape can't reach him); badges give keywords.
                 faculty("Ernst Leiss", title="Professor",
                         email="eleiss@uh.edu",
                         keywords=["Cyber Security", "Algorithms"]),
             ]),
        _nsm("PHYS", "Department of Physics", ["Physics"],
             "https://www.uh.edu/nsm/physics/people/tenure-track/"),
        _nsm("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
             "https://www.uh.edu/nsm/chemistry/people/faculty/",
             faculty_seed=[
                 # Research Associate Professor listed without a profile link.
                 faculty("Boris Makarenko", title="Research Associate Professor",
                         email="bmakarenko@uh.edu"),
             ]),
        _nsm("BIO", "Department of Biology and Biochemistry",
             ["Biology", "Biochemistry"],
             "https://www.uh.edu/nsm/biology-biochemistry/people/faculty/"),
        {
            "short": "EAS",
            "name": "Department of Earth and Atmospheric Sciences",
            "majors": ["Geology", "Geophysics", "Environmental Sciences"],
            "directory_url": "https://www.uh.edu/nsm/earth-atmospheric/people/faculty/",
            "scrape": {
                "url": "https://www.uh.edu/nsm/earth-atmospheric/people/faculty/",
                "selectors": _EAS_SEL,
                "name_flip": True,
                "section_filter": _EAS_SECTION,
            },
        },
        # ---- Cullen College of Engineering ----------------------------------
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://www.ee.uh.edu/faculty"),
        _eng("ME", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "https://www.me.uh.edu/faculty"),
        _eng("CIVE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering"],
             "https://www.cive.uh.edu/faculty"),
        _eng("CHEE", "Department of Chemical and Biomolecular Engineering",
             ["Chemical Engineering"],
             "https://www.chee.uh.edu/faculty"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"],
             "https://www.bme.uh.edu/faculty"),
        _eng("IE", "Department of Industrial Engineering",
             ["Industrial Engineering"],
             "https://www.ie.uh.edu/faculty"),
        _eng("PETRO", "Petroleum Engineering Program",
             ["Petroleum Engineering"],
             "https://petro.egr.uh.edu/faculty"),
        # ---- C.T. Bauer College of Business ---------------------------------
        _bauer("ACCT", "Department of Accountancy and Taxation",
               ["Accounting"], "ACCT"),
        _bauer("FINA", "Department of Finance", ["Finance"], "FINA"),
        _bauer("MARK", "Department of Marketing and Entrepreneurship",
               ["Marketing", "Entrepreneurship"], "MARK"),
        _bauer("MANA", "Department of Management and Leadership",
               ["Management"], "MANA"),
        _bauer("DISC", "Department of Decision and Information Sciences",
               ["Management Information Systems", "Supply Chain Management"],
               "DISC"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
