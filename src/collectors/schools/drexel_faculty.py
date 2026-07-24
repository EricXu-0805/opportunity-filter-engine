"""Drexel University faculty config (via the faculty_graph engine).

Full university-wide coverage across five colleges, four markup families:

* **College of Arts & Sciences (COAS) — one shared server-rendered table.**
  ``drexel.edu/coas/faculty-research/faculty-directory/`` lists every COAS
  department's people in a single HTML ``<table>`` of ``tr.FacultyTableRow`` rows
  (plain HTTP 200, no WAF, no JS). Each row's class list carries a department-
  assigned **track token** — ``faculty`` (tenure/research ladder), ``teaching``,
  ``emeriti``/``emeritus``, ``adjunct``, ``affiliated``, ``research``,
  ``visiting``, ``postdoc``, ``Courtesy`` (primary appointment elsewhere). The
  card selector keys off ``.faculty`` so the class IS the gate: teaching/emeriti/
  adjunct and — critically — cross-listed affiliates/courtesy appointees are
  excluded by construction. Each department is one ``link_filter`` slice of the
  same fetch (the profile-URL ``<dept>`` segment). Every ``.faculty`` row carries
  a plain ``mailto`` (100% email) and a "Research & Teaching Interests"
  ``span.no-bullets`` list, so faculty land emailed + keyworded in one pass. 13
  departments.

* **Antoinette Westphal College of Media Arts & Design — one server-rendered
  table.** ``drexel.edu/westphal/about/directory/`` is a single ``<table>``: one
  ``<tr>`` per person with a name/rank ``<td>`` (rank as bare text after the name
  anchor's ``<br>``, captured by ``title_html_re``), a ``Department(s): …`` cell,
  and a ``mailto`` cell. One page, no pagination — a ``field_filter`` on the
  department cell slices each catalog major, and a ``ladder_filter`` drops the
  emeriti/adjunct/staff the table mixes in. 7 departments.

* **LeBow College of Business — Drupal web-profile directory (paginated).**
  ``lebow.drexel.edu/directory`` renders faculty + staff as ``.wp.grid__item``
  cards (name/job-title/department/mailto) server-side, 10 per page, ``?page=N``
  paginated. The per-department pages carry no roster and ``field_filter`` +
  pagination truncates sparse departments (the engine breaks pagination when a
  page yields no in-department card), so LeBow is wired as ONE college department
  over the full directory with a ``ladder_filter`` (require professor/lecturer);
  emeriti drop out via the engine's ``_RETIRED_TITLE_RE``. Every page carries
  multiple professors, so pagination walks the whole directory. ~100% email.

* **College of Computing & Informatics (CCI) + College of Engineering — the
  shared "CoE" React directory, headless-rendered.** Both colleges' "people"
  pages are a client-side React widget (``#faculty-content .directory-result``)
  backed by a paginated JSON service (``drexel.edu/du-svc/CoEDirectory/Search/
  faculty``) that hard-caps 10 results/page and ignores ``perPage``/
  ``loadAllPages``. The widget is URL-driven (``?page=N`` re-renders that page),
  so ``scrape["render"]=True`` + ``paginate`` walks it headless. CCI's directory
  splits cleanly into Computer Science and Information Science (every page carries
  both, so a ``field_filter`` per department never truncates the paginator);
  Engineering's directory mixes six departments too sparsely per page to
  ``field_filter`` safely, so it ships as ONE college department. Names render
  "Last, First" (``name_flip``); the rank cell appends a "Pronouns:" line that
  ``title_strip_after`` trims. ~99% email; research areas land as keywords.

* **College of Nursing & Health Professions (CNHP) — per-department
  ``FacultyTableRow`` pages + profile enrichment.** Each CNHP department publishes
  a server-rendered ``tr.FacultyTableRow`` roster (name in ``.facultyNameTitle
  strong``, rank as bare text, a "Learn More" profile link) but NO email on the
  listing — the address lives on each profile page, so a ``profile_enrich``
  (``always``) follows every profile's ``mailto``. A ``ladder_filter`` on the
  rank keeps professors/lecturers. 3 departments (Nursing, Health Sciences,
  Nutrition).

Single source ("drexel_faculty"); department rides each record, ids namespaced
by department short-code.

DROPPED / not wired (see the wave notes):
* Engineering is shipped as one lumped college department, not its six real
  departments (ECE/MEM/Civil-Arch-Env/Chemical-Biological/Materials/Biomedical):
  the backing JSON API (pageId 2000…, 202 faculty, ~99% email, a per-record
  ``department`` field) would wire all six cheaply IF the engine's ``json_dir``
  tier paginated; it does not (single request only), and per-department headless
  ``field_filter`` over 21 pages × 6 depts is too many renders / truncates the
  sparse ones. A ``json_dir`` ``page``-cursor (like ``_fetch_faculty180`` already
  has) is the clean unlock. Biomedical Engineering is a separate school and is
  not in this directory at all.
* CoE department granularity for CCI beyond CS / Information Science, and any
  COAS/Westphal/LeBow center or non-catalog unit (advising, staff, "Engineering
  Leadership and Society", etc.).

Live-verified 2026-07-24.
"""

from __future__ import annotations

from .. import faculty_graph

# ---------------------------------------------------------------------------
# College of Arts & Sciences — one shared FacultyTableRow directory
# ---------------------------------------------------------------------------
# Card = the department-assigned ``.faculty`` track token (tenure/research ladder
# only); the per-department ``link_filter`` slices this one page by the profile-
# URL ``<dept>`` segment. Rank is bare text between the name div's ``</h3></div>``
# and the next ``<br>`` (no element of its own — ``title_html_re`` strips tags +
# unescapes). Email is the ``mailto`` in the ``.fcontact`` block (100% coverage).
_COAS_SEL = {
    "card": "tr.FacultyTableRow.faculty",
    "name": ".fname h3 a",
    "link": ".fname h3 a",
    "title_html_re": r"</h3>\s*</div>\s*<br\s*/?>\s*(.*?)\s*<br",
    "research": "span.no-bullets",
    "email": "a[href^='mailto:']",
}
_COAS_LADDER = {"require": r"professor|lecturer"}
_COAS_URL = "https://drexel.edu/coas/faculty-research/faculty-directory/"


def _coas(short: str, name: str, majors: list[str], seg: str) -> dict:
    """A COAS department: one ``link_filter`` slice of the shared directory,
    keyed by the profile-URL ``<dept>`` segment."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": _COAS_URL,
        "scrape": {
            "url": _COAS_URL, "selectors": _COAS_SEL, "ladder_filter": _COAS_LADDER,
            "link_filter": rf"/faculty-directory/{seg}/",
        },
    }


# ---------------------------------------------------------------------------
# Westphal College of Media Arts & Design — one server-rendered table
# ---------------------------------------------------------------------------
# One ``<tr>`` per person: td0 = name anchor + bare-text rank, td1 = "Department(s):
# …", td2 = mailto. One page (no pagination) so a ``field_filter`` on the
# department cell slices each major without truncating anything.
_WEST_SEL = {
    "card": "tr",
    "name": "td a[href*='/directory/']",
    "link": "td a[href*='/directory/']",
    "title_html_re": r"</a>\s*<br\s*/?>\s*(.*?)\s*<br",
    "email": "td a[href^='mailto:']",
}
_WEST_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|adjunct|visiting"}
_WEST_URL = "https://drexel.edu/westphal/about/directory/"


def _west(short: str, name: str, majors: list[str], dept_match: str) -> dict:
    """A Westphal department: the shared table filtered to the "Department(s):"
    cell text via ``field_filter``."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": _WEST_URL,
        "scrape": {
            "url": _WEST_URL, "selectors": _WEST_SEL, "ladder_filter": _WEST_LADDER,
            "field_filter": {"selector": "td:nth-of-type(2)", "include": dept_match},
        },
    }


# ---------------------------------------------------------------------------
# CCI + Engineering — the shared CoE React directory (headless render)
# ---------------------------------------------------------------------------
# ``#faculty-content`` scopes to the faculty tab (staff/student tabs excluded).
# Names render "Last, First" (name_flip); the rank cell appends a "Pronouns:"
# line that title_strip_after trims. Research areas are one <li> per area.
_COE_SEL = {
    "card": "#faculty-content .directory-result",
    "name": ".directory-result__name a",
    "link": ".directory-result__name a",
    "title": ".directory-result__title",
    "title_strip_after": r"\s*Pronouns\b",
    "email": ".directory-result__contact-card a[href^='mailto:']",
    "research_items": ".directory-result__research-areas li",
}
_COE_LADDER = {"require": r"professor|lecturer", "drop": r"adjunct|emerit|visiting"}


def _cci(short: str, name: str, majors: list[str], dept_match: str) -> dict:
    """A CCI department: the CoE faculty directory, headless-paginated, sliced to
    the per-card department span via ``field_filter`` (CS + Information Science
    each appear on every page, so the paginator never truncates)."""
    url = "https://drexel.edu/cci/about/directory/"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url, "selectors": _COE_SEL, "render": True, "render_settle": 6000,
            "name_flip": True, "ladder_filter": _COE_LADDER,
            "field_filter": {"selector": ".directory-result__section--department span",
                             "include": dept_match},
            # The CoE widget is 1-indexed and the base URL already IS ?page=1, so
            # the paginator must start at page 2 (starting at 1 re-fetches the base
            # page → no fresh rows → the loop stops before it walks anything).
            "paginate": {"param": "page", "start": 2, "max": 14},
        },
    }


# ---------------------------------------------------------------------------
# LeBow College of Business — Drupal web-profile directory (paginated)
# ---------------------------------------------------------------------------
_LEBOW_SEL = {
    "card": ".wp.grid__item",
    "name": "a.link--name",
    "link": "a.link--name",
    "title": ".paragraph--job-title",
    "email": "a.link--email",
}
# ``field_term_position_type_target_id=2070`` is the exposed "Faculty" filter —
# it excludes the Emeritus / Staff / PhD-candidate / LeBow-Associate position
# types the full directory mixes in (emeriti here are flagged only by that
# taxonomy, not always by a "Emeritus" title the engine's _RETIRED gate could
# catch), leaving current teaching + tenure-line faculty.
_LEBOW_URL = "https://www.lebow.drexel.edu/directory?field_term_position_type_target_id=2070"


# ---------------------------------------------------------------------------
# CNHP — per-department FacultyTableRow pages + profile-page email enrichment
# ---------------------------------------------------------------------------
# The listing carries name + rank + a "Learn More" profile link but no email, so
# a profile_enrich (always) follows each profile's mailto. Rank is bare text
# after the name <strong>; a ladder_filter keeps professors/lecturers.
_CNHP_SEL = {
    "card": "tr.FacultyTableRow",
    "name": ".facultyNameTitle strong",
    "link": ".facultyNameTitle a",
    "title_html_re": r"</strong>\s*<br\s*/?>\s*(.*?)\s*<br",
}
_CNHP_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|adjunct|visiting"}
_CNHP_ENRICH = {
    "always": True,
    "email_selector": "a[href^='mailto:']",
    "throttle": 0.15,
    "timeout": 8,
}


def _cnhp(short: str, name: str, majors: list[str], seg: str) -> dict:
    """A CNHP department: its own FacultyTableRow roster page, with per-profile
    email enrichment (the listing has no address)."""
    url = f"https://drexel.edu/cnhp/faculty/{seg}/"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url, "selectors": _CNHP_SEL, "ladder_filter": _CNHP_LADDER,
            "profile_enrich": _CNHP_ENRICH,
        },
    }


SCHOOL: dict = {
    "school_slug": "drexel",
    "source": "drexel_faculty",
    "organization": "Drexel University",
    "location": "Philadelphia, PA",
    "id_prefix": "drexel",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Drexel University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences (shared FacultyTableRow directory) ----
        _coas("PHYS", "Department of Physics",
              ["Physics", "Astrophysics"], "physics"),
        _coas("CHEM", "Department of Chemistry",
              ["Chemistry", "Biochemistry"], "chemistry"),
        _coas("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"], "mathematics"),
        _coas("BIO", "Department of Biology",
              ["Biological Sciences", "Biology"], "biology"),
        _coas("BEES", "Department of Biodiversity, Earth and Environmental Science",
              ["Environmental Science"], "bees"),
        _coas("PSYC", "Department of Psychological and Brain Sciences",
              ["Psychology", "Neuroscience"], "psychology"),
        _coas("POLS", "Department of Politics",
              ["Political Science"], "politics"),
        _coas("SOC", "Department of Sociology",
              ["Sociology"], "sociology"),
        _coas("COM", "Department of Communication",
              ["Communication"], "communication"),
        _coas("ENGP", "Department of English and Philosophy",
              ["English", "Philosophy"], "english-philosophy"),
        _coas("HIST", "Department of History",
              ["History"], "history"),
        _coas("CJS", "Department of Criminology and Justice Studies",
              ["Criminology and Justice Studies"], "criminology-justice-studies"),
        _coas("GLBL", "Department of Global Studies and Modern Languages",
              ["Global Studies"], "global-studies"),
        # ---- Westphal College of Media Arts & Design (shared table) -----------
        _west("GD", "Department of Graphic Design",
              ["Graphic Design"], r"Graphic Design"),
        _west("ID", "Department of Interior Design",
              ["Interior Design"], r"Interior Design"),
        _west("FASH", "Department of Fashion Design",
              ["Fashion Design"], r"Fashion Design"),
        _west("FILM", "Department of Film and Television",
              ["Film & Television"], r"Film & Television"),
        _west("GAME", "Department of Game Design and Production",
              ["Game Design & Production"], r"Game Design"),
        _west("MUSI", "Music Industry Program",
              ["Music Industry"], r"Music Industry"),
        _west("ARCH", "Department of Architecture",
              ["Architecture"], r"Architecture"),
        # ---- College of Computing & Informatics (CoE React directory) ---------
        _cci("CS", "Department of Computer Science",
             ["Computer Science", "Data Science",
              "Artificial Intelligence & Machine Learning",
              "Computing and Security Technology"],
             r"^Computer Science$"),
        _cci("INFO", "Department of Information Science",
             ["Information Systems", "Data Science"],
             r"^Information Science$"),
        # ---- College of Engineering (CoE React directory, lumped college) -----
        {
            "short": "ENG",
            "name": "College of Engineering",
            "majors": ["Chemical Engineering", "Civil Engineering",
                       "Electrical Engineering", "Computer Engineering",
                       "Mechanical Engineering & Mechanics",
                       "Materials Science and Engineering",
                       "Environmental Engineering", "Architectural Engineering",
                       "Biomedical Engineering"],
            "directory_url": "https://drexel.edu/engineering/about/faculty-staff/",
            "scrape": {
                "url": "https://drexel.edu/engineering/about/faculty-staff/",
                "selectors": _COE_SEL, "render": True, "render_settle": 6000,
                "name_flip": True, "ladder_filter": _COE_LADDER,
                # 1-indexed widget, base URL is page 1 — start the walk at page 2.
                "paginate": {"param": "page", "start": 2, "max": 24},
            },
        },
        # ---- LeBow College of Business (Drupal directory, lumped college) -----
        {
            "short": "LEBOW",
            "name": "LeBow College of Business",
            "majors": ["Accounting", "Finance", "Marketing", "Management",
                       "Business Analytics", "Economics", "International Business"],
            "directory_url": _LEBOW_URL,
            "scrape": {
                "url": _LEBOW_URL, "selectors": _LEBOW_SEL,
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"visiting"},
                "paginate": {"param": "page", "max": 14},
            },
        },
        # ---- College of Nursing & Health Professions (FacultyTableRow + enrich)
        _cnhp("NURS", "Department of Nursing",
              ["Nursing"], "undergraduate-nursing"),
        _cnhp("GNURS", "Graduate Nursing",
              ["Nursing"], "graduate-nursing"),
        _cnhp("HSCI", "Department of Health Sciences",
              ["Health Sciences", "Exercise Science"], "health-sciences"),
        _cnhp("NUTR", "Department of Nutrition Sciences",
              ["Nutrition and Foods"], "nutrition"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
