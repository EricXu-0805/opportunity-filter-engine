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
  emeriti/adjunct/staff the table mixes in. 19 of the table's rows carry NO rank
  text at all; the rank capture reads those rows' remaining cells instead of
  coming back empty, so they fail ``require`` and drop rather than inherit the
  engine's "Professor" default (which would also smuggle adjuncts past the
  ladder gate). 7 departments.

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
  ``title_strip_after`` trims (and ``title_html_re`` re-reads the same cell from
  the markup so its newline-separated second role lands collapsed, not as a raw
  \\n). Engineering is 21 pages, and the engine's paginator stops at the FIRST
  page that yields nothing new — a page captured before its cards hydrate is
  indistinguishable from the end of the directory, which is how the Sh–Z tail
  went missing — so both walks render with ``render_wait="networkidle"``. A card
  whose rank cell is EMPTY drops instead of inheriting the "Professor" default
  (the one live case, ECE's Michael Lui, is adjunct faculty).
  ~99% email; research areas land as keywords.

* **College of Nursing & Health Professions (CNHP) — per-department
  ``FacultyTableRow`` pages + profile enrichment.** Each CNHP department publishes
  a server-rendered ``tr.FacultyTableRow`` roster (name in ``.facultyNameTitle
  strong``, rank as bare text, a "Learn More" profile link) but NO email on the
  listing — the address lives on each profile page, so a ``profile_enrich``
  (``always``) follows every profile's ``mailto`` — the pass runs on a patient
  timeout/retry budget because here a timed-out profile is not lost depth, it
  is the record's only address. A ``ladder_filter`` on the rank keeps
  professors/lecturers. 3 departments (Nursing, Health Sciences, Nutrition).

Single source ("drexel_faculty"); department rides each record, ids namespaced
by department short-code.

DROPPED / not wired (see the wave notes):
* Engineering is shipped as one lumped college department, not its six real
  departments (ECE/MEM/Civil-Arch-Env/Chemical-Biological/Materials/Biomedical):
  the backing JSON API (``…/Search/faculty`` + an engineering Referer, 202
  faculty, ~99% email, a per-record ``department`` field) would wire all six
  cheaply — and would retire the headless walk entirely — IF the engine's
  ``json_dir`` tier paginated. It does not (single request only), and the
  service hard-caps 10 results/page: ``perPage``/``pageSize``/``take``/``limit``
  are echoed back but never honoured (re-verified 2026-07-25), so one request
  can never carry the roster. A ``json_dir`` ``page``-cursor (like
  ``_fetch_faculty180`` already has) is the clean unlock, and the same cursor
  would make this tier deterministic instead of render-flake-dependent.
  Biomedical Engineering is a separate school and is not in this directory.
* CoE department granularity for CCI beyond CS / Information Science, and any
  COAS/Westphal/LeBow center or non-catalog unit (advising, staff, "Engineering
  Leadership and Society", etc.).

Live-verified 2026-07-25.
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
    # The interests cell delimits areas with bare NEWLINES ("Malacology\n
    # Systematic Biology\n…"), and a CSS ``research`` selector keeps them
    # verbatim — literal \n then leaks into research_areas, into the
    # description, and (where newline is the only delimiter) into a single
    # ragged keyword. Reading the same cell through ``research_re_text`` runs it
    # over the card's RENDERED text, which the engine both entity-decodes and
    # whitespace-collapses ("Detector R&D" stays an ampersand, not "&amp;").
    # The interests are the card's last cell, so the label anchors the capture.
    "research_re_text": r"Research & Teaching Interests\s*(.+)$",
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
    # 19 rows carry NO rank text at all ("<a><b>Name</b></a><br/><br/></td>")
    # and 22 more hide the rank behind a leading blank <br>; a capture that
    # comes back empty leaves the engine's default rank, "Professor" — a
    # fabricated professorship that also defeats the ladder_filter's
    # adjunct/emeriti drop (Sequoyah Hunter-Cuyjet has been an Interior Design
    # adjunct since 2019; Karl Fowlkes is Music Industry adjunct faculty). So
    # branch 1 matches exactly the rank-less shape — only <br>s between the name
    # anchor and the end of the cell — and captures the row's REMAINING cells
    # (department + contact), text that carries no rank word, so ``require``
    # drops the row instead of inventing a rank for it. Branch 2 is the ordinary
    # case: the rank text up to the next <br> or the cell end, skipping any
    # leading blank <br> so those 22 rows land their real rank (and tolerating
    # inline markup inside the rank, which would otherwise fail to match and
    # fall back to the same fabricated default).
    "title_html_re": (r"</a>\s*(?:<br\s*/?>\s*)+"
                      r"(</td>[\s\S]*|(?:(?!<br|</td>)[\s\S])*?(?:<br\s*/?>|</td>))"),
    # Prefixes/post-nominals this table bakes into the name link ("Dr.-Ing.
    # Ulrike Altenmüller-Lewis", "Karl Fowlkes, Esq.") — neither is covered by
    # the engine's honorific/credential strip (it keys off "Dr. " and off
    # all-caps acronyms), and both leak into pi_name.
    "name_strip": r"^Dr\.\s*-\s*Ing\.\s*|,\s*Esq\.?$",
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
    # The rank cell is one text node whose roles are separated by literal
    # newlines ("Associate Professor\nAssociate Department Head for Graduate
    # Affairs and Research"), which a CSS get_text keeps verbatim — the \n then
    # ships inside faculty_title and the description. The ``title_html_re``
    # path collapses whitespace, so re-reading the same cell from the markup
    # lands one clean line; branch 2's lookahead stops the capture before the
    # trailing "Pronouns:" line, which title_strip_after (applied earlier)
    # would no longer reach. Branch 1 handles the EMPTY rank cell (ECE adjunct
    # Michael Lui): an empty capture would leave the "Professor" default, so it
    # reads the card's department section instead — rank-free text that fails
    # ``require``, dropping the card rather than promoting an adjunct.
    "title_html_re": (r"directory-result__title[^>]*>\s*"
                      r"(</div>[\s\S]{0,400}?Department</h6>(?:\s*<span>[^<]*</span>)?"
                      r"|[\s\S]*?(?=\s*Pronouns:|\s*</div>))"),
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
            "url": url, "selectors": _COE_SEL, "render": True,
            # The paginator stops at the FIRST page that surfaces no new card,
            # and a page captured before its XHR-fed cards hydrate looks exactly
            # like the end of the directory — one slow render truncates the rest
            # of the alphabet. "networkidle" blocks until the widget's fetch has
            # actually landed, so a page is never read half-rendered.
            "render_wait": "networkidle", "render_settle": 3000,
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
    # Post-nominals a few profiles bake into the name field ("Maneesh Chhabria,
    # PhD CFA"). The engine's credential strip only takes comma-separated
    # degrees or all-caps acronyms, so a space-joined run survives it.
    "name_strip": r",\s*(?:Ph\.?\s?D|CFA|CPA|MBA|J\.?D|Esq)\.?"
                  r"(?:[,\s]+(?:Ph\.?\s?D|CFA|CPA|MBA|J\.?D|Esq)\.?)*$",
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
    # The listing carries no address at all, so a profile fetch that times out
    # is the difference between an emailed record and a dead one (Linda Celia
    # and Maura Nitka both shipped email-less off an 8s/1-try budget while
    # their profiles publish clean mailtos). This pass is ~90 pages, not
    # thousands, so it can afford a patient budget.
    "timeout": 20,
    "max_retries": 2,
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
                "selectors": _COE_SEL, "render": True,
                # 21 pages of 10 — the longest walk in this config, and the one
                # a half-rendered page truncates hardest (a capture taken before
                # the widget's XHR lands reads as "no new cards" and ends the
                # walk; that is how the Sh–Z tail went missing). "networkidle"
                # waits for the fetch that fills the grid.
                "render_wait": "networkidle", "render_settle": 3000,
                "name_flip": True, "ladder_filter": _COE_LADDER,
                # 1-indexed widget, base URL is page 1 — start the walk at page 2.
                # 202 people / 10 per page = 21 pages; the cap leaves headroom.
                "paginate": {"param": "page", "start": 2, "max": 26},
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
