"""Middlebury College faculty config (via the faculty_graph engine).

Middlebury runs one Drupal college site (``www.middlebury.edu/college``) whose
every academic department/program exposes a faculty listing at
``/college/academics/<slug>/<faculty-page>``. The faculty page slug is almost
always ``faculty-and-staff``; a handful use ``faculty-and-office-hours``
(Biology, Chemistry & Biochemistry, Theatre), ``faculty-and-affiliates``
(Food Studies), or ``faculty-and-staff-office-hours`` (French) — resolved per
entry from a live probe (2026-07-21, all clean 200s, no WAF, no render mode).

There is exactly ONE server-rendered person-card family college-wide, the
Drupal ``profile-list`` component. Each person is a ``.media-object`` inside a
``.profile-list`` section; the name is the ``<h3> <a>`` link (whose href is the
canonical ``/college/people/<slug>`` profile — the SAME url everywhere the
person is cross-listed, so the engine's url/email dedup collapses a professor
who appears under several interdisciplinary programs into ONE record), the rank
is the first ``p.f2`` paragraph, and the public email is an inline ``mailto:``
in the card's definition list. Emails are present inline for essentially every
professor, so no profile-enrichment pass is needed.

Role gating: pages are titled by section — "Department Chair", "Faculty",
"Academic Coordinator", "Retired Faculty" — and interleave staff and emeriti.
``ladder_filter`` requires a professor/lecturer/instructor rank (keeps teaching,
laboratory, research, and endowed-chair professors plus lecturers/instructors)
and drops emeritus/emerita/retired and visiting appointments. The require gate
alone also sheds "Academic Coordinator", "Language School" fellows, and pure
staff rows the ``faculty-and-staff`` listings carry. (The engine additionally
drops emeritus/retired titles unconditionally.)

Single source ("middlebury_faculty"); department rides each record's
``department``, ids namespaced by short-code. Audience "unknown".

Interdisciplinary programs (American Studies, Black Studies, Comparative
Literature, Environmental Studies, Food Studies, Gender/Sexuality/Feminist
Studies, Global Health, International & Global Studies, International Politics &
Economics, Jewish Studies, Linguistics, Neuroscience, Molecular Biology &
Biochemistry) cross-list faculty whose primary appointment is a disciplinary
department. Because every person carries the same ``/college/people/<slug>``
profile url and the same institutional email, the engine's per-school url/email
dedup keeps them ONCE — the per-dept rosters below overlap, but the net corpus
is the ~350 distinct professors of the College.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- the single college-wide Drupal profile-list person-card family --------
_SEL = {
    "card": ".profile-list .media-object",
    "name": ".media-object__body h3 a",
    "link": ".media-object__body h3 a",
    "title": ".media-object__body p.f2",
    "email": "a[href^='mailto:']",
}

# Keep the professor/lecturer/instructor ladder (incl. laboratory/teaching/
# research/endowed-chair professors); drop emeriti, retired, and visiting rows,
# plus the coordinator/staff lines the shared listings interleave.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|retired|visiting",
}

_BASE = "https://www.middlebury.edu/college/academics"


def _dept(short: str, name: str, majors: list[str], slug: str,
          page: str = "faculty-and-staff") -> dict:
    """A department/program on the shared Drupal profile-list component."""
    url = f"{_BASE}/{slug}/{page}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _SEL, "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "middlebury",
    "source": "middlebury_faculty",
    "organization": "Middlebury College",
    "location": "Middlebury, VT",
    "id_prefix": "middlebury",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Middlebury College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Sciences & Mathematics ----------------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology",
              "faculty-and-office-hours"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"], "chemistry-and-biochemistry",
              "faculty-and-office-hours"),
        _dept("CSCI", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("ECSC", "Department of Earth and Climate Sciences",
              ["Earth and Climate Sciences", "Geology"], "earth-climate-sciences"),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], "mathematics"),
        _dept("MBBC", "Program in Molecular Biology and Biochemistry",
              ["Molecular Biology and Biochemistry"], "molecular-biology-biochemistry"),
        _dept("NSCI", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("PHYS", "Department of Physics", ["Physics"], "physics"),
        _dept("ENVS", "Program in Environmental Studies",
              ["Environmental Studies"], "environmental-studies"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("EDST", "Program in Education Studies", ["Education Studies"],
              "education-studies"),
        _dept("GEOG", "Department of Geography", ["Geography"], "geography"),
        _dept("GLHL", "Program in Global Health", ["Global Health"], "global-health"),
        _dept("IGST", "Program in International and Global Studies",
              ["International and Global Studies"], "international-global-studies"),
        _dept("IPEC", "Program in International Politics and Economics",
              ["International Politics and Economics"], "international-politics-economics"),
        _dept("PSCI", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology"),
        # ---- Humanities: literature, languages, thought --------------------
        _dept("AMST", "Program in American Studies", ["American Studies"],
              "american-studies"),
        _dept("ARBC", "Department of Arabic", ["Arabic"], "arabic"),
        _dept("BLST", "Program in Black Studies", ["Black Studies"], "black-studies"),
        _dept("CHNS", "Department of Chinese", ["Chinese"], "chinese"),
        _dept("CLAS", "Department of Classics and Classical Studies",
              ["Classics", "Classical Studies"], "classics-and-classical-studies"),
        _dept("CMLT", "Program in Comparative Literature", ["Comparative Literature"],
              "comparative-literature"),
        _dept("ENAM", "Department of English and American Literatures",
              ["English", "American Literatures", "Creative Writing"], "english"),
        _dept("FDST", "Program in Food Studies", ["Food Studies"], "food-studies",
              "faculty-and-affiliates"),
        _dept("FREN", "Department of French", ["French"], "french",
              "faculty-and-staff-office-hours"),
        _dept("GSFS", "Program in Gender, Sexuality, and Feminist Studies",
              ["Gender, Sexuality, and Feminist Studies"],
              "gender-sexuality-feminist-studies"),
        _dept("GRMN", "Department of German", ["German"], "german"),
        _dept("HEBR", "Program in Hebrew", ["Hebrew"], "hebrew"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("ITAL", "Department of Italian", ["Italian"], "italian"),
        _dept("JAPN", "Department of Japanese", ["Japanese"], "japanese"),
        _dept("JWST", "Program in Jewish Studies", ["Jewish Studies"], "jewish-studies"),
        _dept("LNGT", "Program in Linguistics", ["Linguistics"], "linguistics"),
        _dept("LSHS", "Program in Luso-Hispanic Studies",
              ["Spanish", "Portuguese", "Luso-Hispanic Studies"], "luso-hispanic-studies"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELI", "Department of Religion", ["Religion"], "religion"),
        _dept("RUSS", "Department of Russian", ["Russian"], "russian"),
        # ---- Arts ----------------------------------------------------------
        _dept("DANC", "Program in Dance", ["Dance"], "dance"),
        _dept("FMMC", "Department of Film and Media Culture",
              ["Film and Media Culture"], "film-media-culture"),
        _dept("HARC", "Department of History of Art and Architecture",
              ["History of Art and Architecture", "Architectural Studies"],
              "history-art-architectural-studies"),
        _dept("MUSC", "Department of Music", ["Music"], "music"),
        _dept("ART", "Department of Studio Art", ["Studio Art"], "studio-art"),
        _dept("THTR", "Department of Theatre", ["Theatre"], "theatre",
              "faculty-and-office-hours"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
