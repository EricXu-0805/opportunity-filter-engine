"""University of Central Florida faculty config (via the faculty_graph engine).

University-wide coverage across the colleges whose department directories
server-render their roster over plain HTTP (the engine already sends a browser
User-Agent; no host WAF-gates a plain request). Four markup families, all clean
static 200s, live-verified 2026-07-24:

* **CECS Elementor "filterable gallery".** ``www.cs.ucf.edu`` / ``www.ece.ucf.edu``
  / ``mae.ucf.edu`` / ``www.cece.ucf.edu`` / ``mse.ucf.edu`` all run the same
  WordPress + Essential-Addons filterable gallery: one person is a
  ``div.eael-filterable-gallery-item-wrap`` whose category is a body class
  (``eael-cf-faculty`` vs ``eael-cf-affiliated`` / ``eael-cf-emeritus`` /
  ``eael-cf-staff`` / sub-discipline tags). Name in ``.fg-item-title``, profile
  link in the card's ``/person/<slug>/`` anchor, rank + email in one
  ``.fg-item-content > p`` ("Associate Lecturer<br>name@ucf.edu"). ``email`` and
  ``title`` point at the same ``<p>``: ``title_strip_after`` cuts the address off
  the rank, ``_clean_email`` extracts it (a ``mailto:`` anchor on CS/ECE, plain
  text on MAE/CECE/MSE — both land via the ``<p>`` text).

  - **CS / ECE / CECE / MSE** carry a clean ``eael-cf-faculty`` category, so the
    card selector is ``[class*='eael-cf-faculty']`` — it also catches the
    trailing-dash data-entry variant (``eael-cf-faculty-``) while excluding the
    ``affiliated`` / ``emeritus`` / ``staff`` / sub-discipline-only buckets. The
    ladder gate drops any role-only rider (ECE's UCF-President entry).
  - **MAE** has no ``faculty`` category — its cards are tagged by sub-discipline
    (``aerospace`` / ``mechanical`` / ``biomedical``) plus an untagged bucket that
    mixes ~9 professors with lab managers and coordinators. So MAE selects ALL
    wraps and leans on the ladder gate + the engine's retired-title gate.

* **``ucfwp-post-list-people`` theme (listing carries email).** IEMS
  (``iems.ucf.edu/people/``), the Business department pages
  (``business.ucf.edu/departments-schools/<slug>/``) and Rosen
  (``hospitality.ucf.edu/about/our-people/faculty-directory/``) render one person
  as ``li.ucf-post-list-item`` → ``a.person-link`` (profile link) wrapping
  ``.person-name`` + ``.person-job-title``, with a sibling ``.person-email``
  mailto. IEMS and Rosen publish that email inline; the Business department pages
  omit it from the listing, so those recover it via the ``profile_enrich`` pass
  (each ``/person/<slug>/`` profile carries ``a.person-email``). The ladder gate
  reads ``.person-job-title``.

* **College of Sciences shared "Colleges" people theme.**
  ``sciences.ucf.edu/<dept>/people/`` renders one person as ``a.person-link``
  wrapping ``.person-name`` + ``.person-job-title`` (no per-card email). Physics,
  Chemistry, Biology, Psychology and Sociology group people into
  ``section.ucf-section-*`` blocks, so the card selector scopes to
  ``section.ucf-section-faculty a.person-link`` (drops the courtesy / joint /
  emeritus / staff sections); Math, Political Science, Anthropology and Statistics
  render people flat, so they select ``a.person-link`` and the ladder gate drops
  the postdocs / adjuncts / office staff. Every CoS record's email comes from the
  ``profile_enrich`` pass (each profile carries ``a.person-email``; the shared
  ``<dept>@ucf.edu`` inbox is dropped).

Title gate (ladder ``require: professor|lecturer|instructor``): keeps ladder,
teaching, research, and endowed-chair professors plus lecturers and instructors;
drops titleless/role-only staff, postdocs, coordinators, advisors, and
administrators. Emeriti are dropped by the engine's own ``_RETIRED_TITLE_RE``.

Single source ("ucf_faculty"); department rides each record, ids namespaced by
department short-code.

Dropped / phase-2 (needs a headless render, a new adapter, or a real email
source — all out of scope for this config-only pass):
* **College of Arts & Humanities** (English/History/Philosophy/Performing Arts/
  Visual Arts & Design/Writing & Rhetoric) — same ``ucfwp`` theme but the LISTING
  carries NO ``.person-job-title``, so the ladder gate can't separate the ~280
  adjuncts/staff on a performing-arts roster from ladder faculty without a
  per-profile title+email enrich (heavy, low precision). Phase-2.
* **College of Health Professions & Sciences** — ``healthprofessions.ucf.edu/
  directory/`` is a paginated WP-Views search (10 cards/page, inline email + a
  ``.profiledepartments`` field) with no reachable per-department taxonomy param,
  so it can't be split into departments config-only. Phase-2 (needs the Views
  filter endpoint).
* **College of Medicine (Burnett Biomedical Sciences)** — ``med.ucf.edu/
  directory/`` is client-rendered and its ``wp-json`` REST route is disabled
  (403/empty). Needs a headless render pass. Phase-2.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- CECS Elementor filterable gallery -------------------------------------
# Rank + email share one <p>; title_strip_after cuts the address off the rank,
# and the email selector re-reads the same <p> (_clean_email pulls the address —
# a mailto anchor on CS/ECE, plain text on MAE/CECE/MSE).
_ELEM_SEL = {
    "name": ".fg-item-title",
    "link": "a[href*='/person/']",
    "title": ".fg-item-content p",
    "title_strip_after": r"\s+[\w.+-]+@",
    "email": ".fg-item-content p",
}

# ---- ucfwp-post-list-people theme (li card, sibling .person-email) ---------
_UCFWP_CARD = "li.ucf-post-list-item"
_UCFWP_SEL = {
    "name": ".person-name",
    "link": "a.person-link",
    "title": ".person-job-title",
    "email": ".person-email a[href^='mailto:']",
}

# ---- College of Sciences shared "Colleges" people theme --------------------
_COS_SEL = {
    "name": ".person-name",
    "link": ":self",
    "title": ".person-job-title",
}

# Keep professor / lecturer / instructor ranks; drop role-only staff, postdocs,
# coordinators, advisors, and administrators. (Emeriti drop via the engine's
# retired-title gate.)
_LADDER = {"require": r"professor|lecturer|instructor"}

# Per-profile email recovery for the rosters whose LISTING omits it (all of
# College of Sciences + the Business department pages). Each UCF profile carries
# an ``a.person-email`` mailto; ``always`` runs it even without the env gate
# because the email IS the record's contact value, not optional depth. The drop
# regex keeps a shared department/office inbox from becoming a professor's
# address (which would also collapse the whole dept under one email in dedup).
_UCF_ENRICH = {
    "always": True,
    "email_selector": ".person-email a[href^='mailto:'], a.person-email[href^='mailto:']",
    "email_drop": (
        r"^(?:physics|chemistry|chem|math|mathematics|biology|bio|psychology|"
        r"psych|sociology|anthropology|anthro|politics|political|polsci|"
        r"statistics|stats|sciences|cos|business|cba|rosencollege|rosen|"
        r"hospitality|info|contact|dept|department|advising|advisor|office|"
        r"admin|frontdesk)@"
    ),
    "throttle": 0.0,
    "timeout": 8,
    "max_retries": 1,
}


# CECS profiles publish research areas as a clean <li> list under an Elementor
# "RESEARCH ..." heading widget; env-gated research-only per-profile pass.
_CECS_RESEARCH_ENRICH = {
    "research_items_selector": (
        'div.elementor-widget-heading:has(h4:-soup-contains("RESEARCH")) '
        '+ div.elementor-widget-text-editor li'),
    "throttle": 0.0, "timeout": 8, "max_retries": 1,
}


def _elem_dept(short: str, name: str, majors: list[str], url: str, card: str) -> dict:
    """A CECS department on the shared Elementor filterable gallery."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": card, **_ELEM_SEL},
            "ladder_filter": _LADDER,
            "profile_enrich": _CECS_RESEARCH_ENRICH,
        },
    }


def _ucfwp_dept(short: str, name: str, majors: list[str], url: str,
                *, enrich: bool = False) -> dict:
    """A department on the ucfwp-post-list-people theme (li card + person-email).

    ``enrich=True`` for rosters whose LISTING omits the email (Business); the
    per-profile pass fills it. IEMS/Rosen publish it inline, so no enrich.
    """
    scrape = {
        "url": url,
        "selectors": {"card": _UCFWP_CARD, **_UCFWP_SEL},
        "ladder_filter": _LADDER,
    }
    if enrich:
        scrape["profile_enrich"] = _UCF_ENRICH
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _cos_dept(short: str, name: str, majors: list[str], url: str, card: str) -> dict:
    """A College of Sciences department on the shared "Colleges" people theme.

    The listing has no email, so every record's contact address comes from the
    per-profile enrich pass.
    """
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {"card": card, **_COS_SEL},
            "ladder_filter": _LADDER,
            "profile_enrich": _UCF_ENRICH,
        },
    }


# CS/ECE/CECE/MSE = the clean faculty category (+ trailing-dash variant);
# MAE = all wraps (no faculty category — sub-discipline-tagged).
_CECS_FACULTY_CARD = ".eael-filterable-gallery-item-wrap[class*='eael-cf-faculty']"
_MAE_CARD = ".eael-filterable-gallery-item-wrap"
# CoS: home-department faculty section where the theme groups by role; flat
# (all people, ladder-gated) where it doesn't.
_COS_FACULTY_CARD = "section.ucf-section-faculty a.person-link"
_COS_FLAT_CARD = "a.person-link"


SCHOOL: dict = {
    "school_slug": "ucf",
    "source": "ucf_faculty",
    "organization": "University of Central Florida",
    "location": "Orlando, FL",
    "id_prefix": "ucf",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Central Florida) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering & Computer Science ---------------------
        _elem_dept("CS", "Department of Computer Science",
                   ["Computer Science", "Data Science"],
                   "https://www.cs.ucf.edu/faculty-directory/",
                   _CECS_FACULTY_CARD),
        _elem_dept("ECE", "Department of Electrical and Computer Engineering",
                   ["Electrical Engineering", "Computer Engineering",
                    "Photonic Science and Engineering"],
                   "https://www.ece.ucf.edu/faculty-directory/",
                   _CECS_FACULTY_CARD),
        _elem_dept("MAE", "Department of Mechanical and Aerospace Engineering",
                   ["Mechanical Engineering", "Aerospace Engineering",
                    "Biomedical Engineering"],
                   "https://mae.ucf.edu/faculty-directory/",
                   _MAE_CARD),
        _elem_dept("CECE", "Department of Civil, Environmental and Construction "
                   "Engineering",
                   ["Civil Engineering", "Environmental Engineering",
                    "Construction Engineering"],
                   "https://www.cece.ucf.edu/faculty_staff/",
                   _CECS_FACULTY_CARD),
        _elem_dept("MSE", "Department of Materials Science and Engineering",
                   ["Materials Science and Engineering"],
                   "https://mse.ucf.edu/facultystaff/",
                   _CECS_FACULTY_CARD),
        _ucfwp_dept("IEMS", "Department of Industrial Engineering and Management "
                    "Systems",
                    ["Industrial Engineering"],
                    "https://iems.ucf.edu/people/"),
        # ---- College of Sciences -------------------------------------------
        _cos_dept("PHYS", "Department of Physics", ["Physics", "Astronomy"],
                  "https://sciences.ucf.edu/physics/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("CHEM", "Department of Chemistry",
                  ["Chemistry", "Biochemistry"],
                  "https://sciences.ucf.edu/chemistry/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("MATH", "Department of Mathematics", ["Mathematics"],
                  "https://sciences.ucf.edu/math/people/",
                  _COS_FLAT_CARD),
        _cos_dept("BIO", "Department of Biology", ["Biology"],
                  "https://sciences.ucf.edu/biology/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("PSY", "Department of Psychology", ["Psychology"],
                  "https://sciences.ucf.edu/psychology/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("POLS", "Department of Political Science", ["Political Science"],
                  "https://sciences.ucf.edu/politics/people/",
                  _COS_FLAT_CARD),
        _cos_dept("SOC", "Department of Sociology", ["Sociology"],
                  "https://sciences.ucf.edu/sociology/people/",
                  _COS_FACULTY_CARD),
        _cos_dept("ANT", "Department of Anthropology", ["Anthropology"],
                  "https://sciences.ucf.edu/anthropology/people/",
                  _COS_FLAT_CARD),
        _cos_dept("STAT", "Department of Statistics and Data Science",
                  ["Statistics", "Data Science"],
                  "https://sciences.ucf.edu/statistics/people/",
                  _COS_FLAT_CARD),
        # ---- College of Business -------------------------------------------
        _ucfwp_dept("ACCT", "Kenneth G. Dixon School of Accounting",
                    ["Accounting"],
                    "https://business.ucf.edu/departments-schools/"
                    "kenneth-g-dixon-school-of-accounting/", enrich=True),
        _ucfwp_dept("FIN", "Department of Finance", ["Finance"],
                    "https://business.ucf.edu/departments-schools/finance/",
                    enrich=True),
        _ucfwp_dept("REAL", "Dr. P. Phillips School of Real Estate",
                    ["Real Estate"],
                    "https://business.ucf.edu/departments-schools/finance/"
                    "real-estate/", enrich=True),
        _ucfwp_dept("ECON", "Department of Economics", ["Economics"],
                    "https://business.ucf.edu/departments-schools/economics/",
                    enrich=True),
        _ucfwp_dept("MGMT", "Department of Management", ["Management"],
                    "https://business.ucf.edu/departments-schools/management/",
                    enrich=True),
        _ucfwp_dept("MKT", "Department of Marketing", ["Marketing"],
                    "https://business.ucf.edu/departments-schools/marketing/",
                    enrich=True),
        _ucfwp_dept("IBP", "Integrated Business Program", ["Integrated Business"],
                    "https://business.ucf.edu/departments-schools/"
                    "integrated-business-program/", enrich=True),
        # ---- Rosen College of Hospitality Management -----------------------
        _ucfwp_dept("HOSP", "Rosen College of Hospitality Management",
                    ["Hospitality Management", "Event Management",
                     "Theme Park and Attraction Management"],
                    "https://hospitality.ucf.edu/about/our-people/"
                    "faculty-directory/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
