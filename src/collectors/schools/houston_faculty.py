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

* **Campus-wide "Redline" people API (JS-directory recovery).**
  Four colleges' own web rosters defeat any static card contract — Mathematics
  (ALL-CAPS names in inconsistently nested ``<strong>`` tags), Liberal Arts &
  Social Sciences (hand-authored prose profile pages, per-department markup
  drift), the College of the Arts (comma-joined "Name, Title" accordion ``<li>``
  items, no emails), and Architecture (roster injected client-side by a
  ``#directory-widget`` JS plugin). All are recovered from the JSON endpoint that
  backs the architecture widget (``api.uh.edu/architecture-directory/v1/people``),
  which is campus-wide, not architecture-specific: a ``division`` (college) filter
  plus an exact ``department.name`` match yields each department's roster with a
  real rank and a plaintext uh.edu email on every card. ``faculty=true&staff=
  false`` drops staff/students server-side; the ``_API_LADDER`` gate drops the
  adjunct/emeritus/visiting/affiliate/retiree lines. 14 departments (9 CLASS +
  3 Arts + Math + Architecture); no research field in the feed, so these land
  keyword-sparse (Bauer/Engineering tier). Wired via the engine's ``json_dir``
  source; ``department.name`` is the PRIMARY appointment, so cross-listed faculty
  land once in their home department.

Single source ("houston_faculty"); department rides each record, ids namespaced
by department short-code.

Deliberately NOT wired (out of the catalog's college/major scope, not blocked):
non-departmental Redline units (dean's offices, CWM Center for the Arts, Military
/ Aerospace Studies, area-studies programs, Communication Disorders, Health &
Human Performance). No department needs a headless render — the Redline API
reaches every JS/prose/ALL-CAPS roster directly.

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


# ---- Campus-wide "Redline" people API (JS-directory recovery) ----------------
# The Hines architecture faculty page is a JS ``#directory-widget`` whose backing
# endpoint (``api.uh.edu/architecture-directory/v1/people``) is NOT architecture-
# specific: dropping the division filter returns every college, so ``division``
# (college code) + a client-side ``department.name`` match expose the four
# colleges whose own web rosters no static card contract spans — Liberal Arts &
# Social Sciences and the College of the Arts (prose / accordion pages), NSM
# Mathematics (ALL-CAPS table), and Architecture itself (the JS widget). The feed
# is ``{"meta":..,"data":[{fullName,title,contact:{email},division,department}]}``
# with a real rank on every card and a 100%-covered uh.edu mailto; ``faculty=true
# &staff=false`` drops non-instructional staff/students server-side, and the
# ladder gate drops the adjunct/emeritus/visiting/affiliate/retiree lines the
# roster still mixes in. No profile URL or research field in the feed, so records
# land titled + emailed but keyword-sparse (same tier as the Bauer/Engineering
# depts). Division H0403 (architecture) returns base64 photos → a ~15 MB body,
# well inside the client's 25 s read.
_API_BASE = ("https://api.uh.edu/architecture-directory/v1/people"
             "?campus=HR730&faculty=true&staff=false&student=false&limit=800")
_API_LADDER = {"require": r"professor|lecturer",
               "drop": r"adjunct|emerit|visiting|affiliate|retiree"}


def _api(short: str, name: str, majors: list[str], division: str,
         department: str, directory: str) -> dict:
    """A department recovered from the campus-wide Redline people API — scoped to
    a college by ``division`` at the endpoint, then to the department by an exact
    ``department.name`` match (the feed's PRIMARY-appointment field)."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": directory,
        "json_dir": {
            "url": f"{_API_BASE}&division={division}",
            "records_key": "data",
            "name_fields": ["fullName"],
            "title_field": "title",
            "email_field": "contact.email",
            "filter_field": "department.name",
            "filter_value": department,
            "ladder_filter": _API_LADDER,
        },
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
                # Each profile lists research areas as a clean "#research" <ul><li>;
                # env-gated research-only per-profile pass.
                "profile_enrich": {
                    "research_items_selector": "#research li",
                    "throttle": 0.2,
                },
            },
        },
        # Mathematics' own page renders names in ALL CAPS in inconsistently
        # nested <strong> tags no card contract normalizes — recovered instead
        # from the campus Redline API (clean proper-case names + ranks + email).
        _api("MATH", "Department of Mathematics",
             ["Mathematics", "Data Science"], "H0411", "Mathematics",
             "https://www.uh.edu/nsm/math/people/faculty/"),
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
        # ---- College of Liberal Arts and Social Sciences (Redline API) ------
        # Hand-authored prose profile pages with per-department markup drift no
        # static card contract spans — recovered from the campus people API.
        _api("ENGL", "Department of English",
             ["English"], "H0409", "English",
             "https://www.uh.edu/class/english/"),
        _api("PSYC", "Department of Psychology",
             ["Psychology"], "H0409", "Psychology",
             "https://www.uh.edu/class/psychology/"),
        _api("POLS", "Department of Political Science",
             ["Political Science"], "H0409", "Political Science",
             "https://www.uh.edu/class/political-science/"),
        _api("HIST", "Department of History",
             ["History"], "H0409", "History",
             "https://www.uh.edu/class/history/"),
        _api("COMM", "Valenti School of Communication",
             ["Communication"], "H0409", "Communication",
             "https://www.uh.edu/class/communication/"),
        _api("ECON", "Department of Economics",
             ["Economics"], "H0409", "Economics",
             "https://www.uh.edu/class/economics/"),
        _api("SOCI", "Department of Sociology",
             ["Sociology"], "H0409", "Sociology",
             "https://www.uh.edu/class/sociology/"),
        _api("ANTH", "Department of Comparative Cultural Studies (Anthropology)",
             ["Anthropology"], "H0409", "Anthropology & Compara Studies",
             "https://www.uh.edu/class/comparative-cultural-studies/"),
        _api("PHIL", "Department of Philosophy",
             ["Philosophy"], "H0409", "Philosophy",
             "https://www.uh.edu/class/philosophy/"),
        # ---- Kathrine G. McGovern College of the Arts (Redline API) ---------
        # Faculty are comma-joined "Name, Title" accordion <li> items with no
        # per-person structure and no emails — recovered from the campus API.
        _api("MUSIC", "Moores School of Music",
             ["Music"], "H0593", "Music",
             "https://www.uh.edu/kgmca/msm/about/faculty.php"),
        _api("ART", "School of Art",
             ["Art History"], "H0593", "Art",
             "https://www.uh.edu/kgmca/soa/about/faculty.php"),
        _api("THEA", "School of Theatre and Dance",
             ["Theatre", "Dance"], "H0593", "Theatre",
             "https://www.uh.edu/kgmca/sotd/about/faculty.php"),
        # ---- Gerald D. Hines College of Architecture and Design (Redline) ---
        # The faculty roster is injected client-side by a #directory-widget JS
        # plugin (empty static HTML); its own backing API IS the Redline feed.
        _api("ARCH", "Gerald D. Hines College of Architecture and Design",
             ["Architecture", "Industrial Design", "Interior Architecture"],
             "H0403", "Dean, Architecture and Design",
             "https://www.uh.edu/architecture/about/faculty/index.php"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
