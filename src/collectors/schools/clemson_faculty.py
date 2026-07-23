"""Clemson University faculty config (via the faculty_graph engine).

Clemson's CMS server-renders every faculty roster as a plain static 200 to a
bare request (no WAF, no JS render needed), but the markup differs by college.
Seven server-rendered families cover 22 departments across four colleges.
Live-verified 2026-07-24.

* **CECAS "person-card" grid — School of Computing.**
  ``div.person-card`` cards. Name in ``h3.person-name`` (no profile link — the
  card exposes only a mailto), rank in the first ``p.about > strong``, address in
  a ``p.about a[href^=mailto:]``. The ``_CECAS_FIELD`` gate (require
  ``professor|lecturer`` on the rank ``<strong>``) drops the staff / postdoc /
  administrator cards these flat grids mix in.

* **CECAS "cell large-3" grid — ECE, Mechanical, Bioengineering, Chemical &
  Biomolecular, Industrial Engineering.**
  ``div.cell.large-3`` cards. Name in an ``h3 > a`` (profile link), rank in
  ``p.about > strong`` (ALL-CAPS), address a plain mailto. Same ``_CECAS_FIELD``
  rank gate isolates ladder faculty from the joint/research/staff cards.

* **CECAS "mse" card — Materials Science and Engineering.**
  Same ``div.cell.large-3`` shell but a hand-built inner layout: name in the
  first ``p > strong``, rank as bare text opening the second ``<p>``
  ("Associate Professor <br> phone <br> mailto"). ``title_strip_after`` clips the
  rank at the first phone/paren/email marker; the gate reads the same cell.

* **CECAS engineering table — Civil, Environmental Eng & Earth Sciences,
  Automotive Engineering.**
  A ``<table>`` of ``tr.cell`` rows. Civil keeps name (``td strong``, "Last,
  First") and rank (a same-cell ``<em>``) in one cell; EEES/Automotive split them
  (name ``td a strong``, rank ``td:nth-of-type(2)``). EEES lists "Last, First"
  (``name_flip``); Automotive lists "First Last". The gate requires
  ``professor|lecturer`` on the rank cell, dropping the admin/staff tables that
  share the page.

* **College of Science LiveWhale table — Physics & Astronomy, Chemistry,
  Mathematical & Statistical Sciences, Biological Sciences, Genetics &
  Biochemistry.**
  One ``<table>`` per department; each person a ``<tr>`` of category cell (td#1),
  name link (td#2, "Last, First" → ``name_flip``), rank (td#3), mailto (td#4).
  Grad students / postdocs / adjuncts / emeriti / staff dominate these rosters,
  so ``field_filter`` pins the category cell to the faculty tag (``^faculty$`` for
  most; Genetics tags its ladder faculty ``allfaculty``) and a ``ladder_filter``
  drops the rare non-ranked administrator left in that category.

* **CBSHS profile table — Psychology, Parks/Recreation & Tourism Management.**
  A ``<table>`` of plain ``<tr>`` rows carrying a college-directory
  ``/profiles/`` link: name (td#1, "Last, First" → ``name_flip``), rank (td#2),
  phone+mailto (td#3). The rank gate keeps ladder/teaching faculty.

* **Powers College of Business grid — Economics, Finance, Management,
  School of Accountancy, Marketing.**
  A ``div.columns`` info-column per person (paired with a photo column): name in
  ``h4 > a[href*=/profiles/]`` (First Last), rank in the first ``p > strong``,
  a "Fields:"/office/mailto block below. The gate requires
  ``professor|lecturer|chair`` (business rosters title endowed/interim chairs
  without the word "professor") and drops the lone admin-coordinator card.

Single source ("clemson_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-24 total ≈ 750 records, ~90%+ emailed on the listing.

DROPPED / phase-2 (no reliably-discoverable static faculty roster — the college
sub-nav is JS-rendered and per-department roster URLs are bespoke and flaky):
  * College of Agriculture, Forestry and Life Sciences (CAFLS) — dept slugs
    unresolved behind a JS accordion; landing catch-all soft-404s every guessed
    roster path. Needs render-nav discovery in phase-2.
  * College of Architecture, Arts and Humanities (``/cah/…``) — English,
    History & Geography, Languages, Philosophy & Religion, Performing Arts,
    School of Architecture: inconsistent per-dept roster paths, several flaky
    (200/404 flap). Needs per-dept render discovery in phase-2.
  * CBSHS Communication / Nursing / Public Health / Political Science /
    Sociology-Anthropology-Criminal Justice — no static roster page found
    (rendered nav exposes no roster link; rely on the college-wide directory).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- CECAS "person-card" grid (School of Computing) ------------------------
_CARD_SEL = {
    "card": "div.person-card",
    "name": "h3.person-name",
    "title": "p.about strong",
    "email": 'p.about a[href^="mailto:"]',
}

# ---- CECAS "cell large-3" grid (ECE, ME, Bioeng, ChemBio, Industrial) ------
_GRID_SEL = {
    "card": "div.cell.large-3",
    "name": "h3",
    "link": "h3 a",
    "title": "p.about strong",
    "email": 'p.about a[href^="mailto:"]',
}

# Shared CECAS rank gate: require a Professor/Lecturer rank word on the card's
# rank <strong>; require_present drops a card that has no rank element at all.
_CECAS_FIELD = {
    "selector": "p.about strong",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- CECAS "mse" card (Materials Science) ----------------------------------
# div.cell.large-3 shell but name in first p>strong, rank opening the 2nd <p>.
_MSE_SEL = {
    "card": "div.cell.large-3",
    "name": "p strong",
    "title": "p:nth-of-type(2)",
    "title_strip_after": r"\s*(?:\(|\d{3}|[\w.+-]+@)",
    "email": 'a[href^="mailto:"]',
}
_MSE_FIELD = {
    "selector": "p:nth-of-type(2)",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- College of Science LiveWhale table ------------------------------------
_SCI_SEL = {
    "card": "tr:has(a[href*='/profiles/'])",
    "name": "td a[href*='/profiles/']",
    "link": "td a[href*='/profiles/']",
    "title": "td:nth-of-type(3)",
    "email": 'td a[href^="mailto:"]',
}
_SCI_LADDER = {"require": r"professor|lecturer"}

# ---- CBSHS profile table (Psychology, PRTM) --------------------------------
_CB_SEL = {
    "card": "tr:has(a[href*='/profiles/'])",
    "name": "td a[href*='/profiles/']",
    "link": "td a[href*='/profiles/']",
    "title": "td:nth-of-type(2)",
    "email": 'td a[href^="mailto:"]',
}
_CB_FIELD = {
    "selector": "td:nth-of-type(2)",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- Powers College of Business grid ---------------------------------------
_BIZ_SEL = {
    "card": 'div.columns:has(h4 a[href*="/profiles/"])',
    "name": "h4 a",
    "link": "h4 a",
    "title": "p strong",
    "email": 'a[href^="mailto:"]',
}
_BIZ_FIELD = {
    "selector": "p strong",
    "require_present": True,
    "include": r"professor|lecturer|chair",
}


def _computing(short: str, name: str, majors: list[str], url: str) -> dict:
    """School of Computing on the CECAS person-card grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CARD_SEL, "field_filter": _CECAS_FIELD},
    }


def _grid(short: str, name: str, majors: list[str], url: str) -> dict:
    """An engineering department on the CECAS cell-large-3 grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _GRID_SEL, "field_filter": _CECAS_FIELD},
    }


def _mse(short: str, name: str, majors: list[str], url: str) -> dict:
    """Materials Science on its hand-built cell-large-3 card."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _MSE_SEL, "field_filter": _MSE_FIELD},
    }


def _eng_table(short: str, name: str, majors: list[str], url: str, *,
               name_sel: str, title_sel: str, flip: bool) -> dict:
    """A CECAS engineering department on a tr.cell faculty table."""
    sel = {
        "card": "tr.cell",
        "name": name_sel,
        "link": name_sel,
        "title": title_sel,
        # A few Civil rows carry a trailing comma/space ("Amer, Omar,") that would
        # survive name_flip and leak a comma into the name; strip it pre-flip.
        "name_strip": r"[,\s]+$",
        "email": 'td a[href^="mailto:"]',
    }
    field = {"selector": title_sel, "require_present": True,
             "include": r"professor|lecturer"}
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": sel, "name_flip": flip,
                   "field_filter": field},
    }


def _science(short: str, name: str, majors: list[str], url: str,
             category: str = r"^faculty$") -> dict:
    """A College of Science department on the shared LiveWhale people table."""
    field = {"selector": "td:nth-of-type(1)", "require_present": True,
             "include": category}
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SCI_SEL, "name_flip": True,
                   "field_filter": field, "ladder_filter": _SCI_LADDER},
    }


def _cbshs(short: str, name: str, majors: list[str], url: str) -> dict:
    """A CBSHS department on its /profiles/ faculty table."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CB_SEL, "name_flip": True,
                   "field_filter": _CB_FIELD},
    }


def _business(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Powers College of Business department on its info-column grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _BIZ_SEL, "field_filter": _BIZ_FIELD},
    }


_CECAS = "https://www.clemson.edu/cecas/departments"
_SCI = "https://www.clemson.edu/science/academics/departments"

SCHOOL: dict = {
    "school_slug": "clemson",
    "source": "clemson_faculty",
    "organization": "Clemson University",
    "location": "Clemson, SC",
    "id_prefix": "clemson",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Clemson University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering, Computing and Applied Sciences -------
        _computing("COMP", "School of Computing",
                   ["Computer Science", "Computer Information Systems",
                    "Data Science"],
                   f"{_CECAS}/computing/people/index.html"),
        _grid("ECE", "Holcombe Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              f"{_CECAS}/ece/people/index.html"),
        _grid("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              f"{_CECAS}/me/people/index.html"),
        _grid("BIOE", "Department of Bioengineering",
              ["Biomedical Engineering", "Bioengineering"],
              f"{_CECAS}/bioe/people/index.html"),
        _grid("CHBE", "Department of Chemical and Biomolecular Engineering",
              ["Chemical Engineering"],
              f"{_CECAS}/chbe/people/index.html"),
        _grid("IE", "Department of Industrial Engineering",
              ["Industrial Engineering"],
              f"{_CECAS}/ie/people/index.html"),
        _mse("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             f"{_CECAS}/mse/people/index.html"),
        _eng_table("CE", "Glenn Department of Civil Engineering",
                   ["Civil Engineering"],
                   f"{_CECAS}/ce/people/index.html",
                   name_sel="td strong", title_sel="td em", flip=True),
        _eng_table("EEES", "Department of Environmental Engineering and Earth Sciences",
                   ["Environmental Engineering", "Geology"],
                   f"{_CECAS}/eees/people/index.html",
                   name_sel="td a strong", title_sel="td:nth-of-type(2)", flip=True),
        _eng_table("AUE", "Department of Automotive Engineering",
                   ["Automotive Engineering"],
                   f"{_CECAS}/automotive-engineering/people/index.html",
                   name_sel="td a strong", title_sel="td:nth-of-type(2)", flip=False),
        # ---- College of Science -------------------------------------------
        _science("PHYS", "Department of Physics and Astronomy",
                 ["Physics", "Astronomy", "Astrophysics"],
                 f"{_SCI}/physics/about/people.html"),
        _science("CHEM", "Department of Chemistry",
                 ["Chemistry", "Biochemistry"],
                 f"{_SCI}/chemistry/about/people.html"),
        _science("MATH", "School of Mathematical and Statistical Sciences",
                 ["Mathematical Sciences", "Statistics", "Applied Mathematics"],
                 f"{_SCI}/mathstat/about/people.html"),
        _science("BIOSCI", "Department of Biological Sciences",
                 ["Biological Sciences", "Microbiology"],
                 f"{_SCI}/biosci/about/people.html"),
        _science("GEN", "Department of Genetics and Biochemistry",
                 ["Genetics", "Biochemistry"],
                 f"{_SCI}/genbio/about/people.html",
                 category=r"^allfaculty"),
        # ---- College of Behavioral, Social and Health Sciences ------------
        _cbshs("PSYC", "Department of Psychology",
               ["Psychology"],
               "https://www.clemson.edu/cbshs/departments/psychology/people.html"),
        _cbshs("PRTM", "Department of Parks, Recreation and Tourism Management",
               ["Parks, Recreation and Tourism Management"],
               "https://www.clemson.edu/cbshs/departments/prtm/about/prtm-directory.html"),
        # ---- Wilbur O. and Ann Powers College of Business -----------------
        _business("ECON", "John E. Walker Department of Economics",
                  ["Economics"],
                  "https://www.clemson.edu/business/academics/economics/faculty-staff/index.html"),
        _business("FIN", "Department of Finance",
                  ["Finance"],
                  "https://www.clemson.edu/business/academics/finance/faculty-staff/index.html"),
        _business("MGT", "Department of Management",
                  ["Management"],
                  "https://www.clemson.edu/business/academics/management/faculty-staff.html"),
        _business("ACCT", "School of Accountancy",
                  ["Accounting"],
                  "https://www.clemson.edu/business/academics/accountancy/faculty-staff.html"),
        _business("MKT", "Department of Marketing",
                  ["Marketing"],
                  "https://www.clemson.edu/business/academics/marketing/faculty-staff.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
