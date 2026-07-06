"""Purdue University faculty config (via the faculty_graph engine).

Purdue's directories are server-rendered, so they scrape with a plain request
(no headless browser). Two themes cover most of campus:

* **College of Engineering** — all twelve schools share one ptProfile/ResourceDB
  template: an ``.list-info`` card whose name + profile link live in
  ``.list-name a`` and whose public ``mailto:`` sits on the card, so records land
  emailed + titled in a single listing pass. The rank selector is the only thing
  that varies (``.people-list-title`` for most, ``.short-title`` for ECE, an
  unclassed ``.list-name`` div for AAE/ENE). A ladder filter drops the emeriti /
  lecturers / adjuncts these pages mix in.

* **College of Science** — seven departments across four templates: Computer
  Science's ``.people-item`` grid (email on the profile via ``.bio-email``);
  Chemistry/Mathematics/Statistics isotope grids (email + often research on the
  listing); a shared ``data-position`` grid for Biological Sciences + EAPS
  (research on the listing, email profile-only); and Physics & Astronomy's
  server-rendered directory fragment (name + rank; its listing email is an
  un-parseable alias). A ladder gate keeps professorial faculty.

* **College of Agriculture** — all nine departments come from one JSON roster API
  (``faculty_graph._fetch_coa_api``), filtered by department id; each record lands
  name + rank + public email + profile URL.

* **College of Liberal Arts** — one static directory lists every CLA person with
  the department in the title cell after ``//`` and the email in the fourth cell;
  each department config filters that shared listing to its department.

More Purdue colleges (Health & Human Sciences, Polytechnic, Daniels Business) are
added as their markup is identified.

Single source ("purdue_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit"}

# College of Engineering shared template (engineering.purdue.edu ptProfile):
# ``.list-info`` cards, name/link in ``.list-name a``, public mailto on the card.
# The ranks mix in emeriti / lecturers / adjuncts, so a stricter ladder gate than
# the module default keeps only professorial ladder faculty.
_ENGR_HOST = "https://engineering.purdue.edu"
_ENGR_LADDER = {"require": r"\bprofessor\b",
                "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff"}
_ENGR_SEL = {"card": ".list-info", "name": ".list-name a",
             "link": ".list-name a", "email": "a[href^='mailto:']"}


def _engr(short: str, name: str, majors: list[str], path: str,
          title: str = ".people-list-title") -> dict:
    """One College of Engineering department (shared ptProfile template).

    ``path`` is the directory path under engineering.purdue.edu (``ptFaculty``
    variants serve a faculty-only list where ``Faculty`` would include staff).
    ``title`` overrides the rank selector for the two markup variants.
    """
    url = _ENGR_HOST + path
    sel = dict(_ENGR_SEL, title=title)
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _ENGR_LADDER}}


# College of Science: six departments on distinct directory templates (isotope
# grids for Chemistry/Math/Statistics, a shared ``data-position`` grid for
# Biology + EAPS, and a server-rendered XHR fragment for Physics). Ranks are
# mixed, so a ladder gate keeps professorial faculty.
_SCI_LADDER = {"require": r"\bprofessor\b",
               "drop": r"\bemerit|\badjunct|\baffiliat|\binstructional|\blecturer|\bvisiting"}
# Biology + EAPS share the same theme (``data-position="faculty"`` isolates
# ladder faculty; research areas are on the listing in ``div.areas``). Email is
# profile-only, recovered by the gated per-profile pass.
_BIO_SEL = {"card": "div.people-item[data-position='faculty']",
            "name": "p.people-name a", "link": "p.people-name a",
            "title": "p.people-title", "research": "div.areas"}


def _sci_bio(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _BIO_SEL, "ladder_filter": _SCI_LADDER}}


# College of Agriculture: all nine departments come from one JSON roster API
# (faculty_graph._fetch_coa_api), filtered by the department id from the college's
# ListDepartment endpoint. Name + rank + public email + profile URL on the record.
def _ag(short: str, name: str, majors: list[str], code: str, dept_id: int) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": f"https://ag.purdue.edu/department/{code}/directory.html",
            "coa_api": {"dept_id": dept_id}}


# College of Liberal Arts: one static directory lists every CLA person with the
# department encoded in the title cell (``td:2``) after a ``//`` separator and the
# public email in ``td:4``. Each department config filters that shared listing to
# its department (``field_filter`` anchored on ``// <Dept>`` so "History" doesn't
# also catch "Art History") and strips the "// Dept" tail off the rank.
_CLA_URL = "https://www.cla.purdue.edu/directory/"
_CLA_SEL = {"card": "table#results-table tr.profile-row",
            "name": "td:nth-child(1) a", "link": "td:nth-child(1) a",
            "title": "td:nth-child(2)", "title_strip_after": r"//",
            "email": "td:nth-child(4)"}
_CLA_LADDER = {"require": r"\bprofessor\b",
               "drop": r"\bemerit|\blecturer|\bvisiting|\badjunct|\bgraduate|\bcontinuing"}


def _cla(short: str, name: str, majors: list[str], include: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": _CLA_URL,
            "scrape": {"url": _CLA_URL, "selectors": _CLA_SEL,
                       "ladder_filter": _CLA_LADDER,
                       "field_filter": {"selector": "td:nth-child(2)", "include": include}}}


SCHOOL: dict = {
    "school_slug": "purdue",
    "source": "purdue_faculty",
    "organization": "Purdue University",
    "location": "West Lafayette, IN",
    "id_prefix": "purdue",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Purdue University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # --- College of Science ---
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Data Science"],
            "directory_url": "https://www.cs.purdue.edu/people/faculty/index.html",
            "scrape": {
                "url": "https://www.cs.purdue.edu/people/faculty/index.html",
                "selectors": {
                    "card": ".people-item",
                    "name": ".people-name a",
                    "link": ".people-name a",
                    "title": ".people-title",
                },
                "ladder_filter": _LADDER,
                # Email is not on the listing; the profile page carries it in
                # ``.bio-email``. Gated per-profile pass (OFE_ENRICH_PROFILES);
                # plain fetch (Purdue profiles are server-rendered too).
                "profile_enrich": {
                    "email_selector": ".bio-email a[href^='mailto:']",
                },
            },
        },
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Chemical Biology"],
            "directory_url": "https://www.chem.purdue.edu/people/faculty",
            "scrape": {
                "url": "https://www.chem.purdue.edu/people/faculty",
                "selectors": {
                    "card": "div.grid-item.person",
                    "name": ".content h3 a",
                    "link": ".content h3 a",
                    "title": "p.title strong",
                    "email": "a[href^='mailto:']",
                    "research": "p.interests",
                },
                "ladder_filter": _SCI_LADDER,
            },
        },
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics"],
            "directory_url": "https://www.math.purdue.edu/people/faculty",
            "scrape": {
                "url": "https://www.math.purdue.edu/people/faculty",
                "selectors": {
                    "card": "div.element.directory-row.faculty",
                    "name": "h2.peopleDirectoryName a",
                    "link": "h2.peopleDirectoryName a",
                    "title": "h2.peopleDirectoryName + strong",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _SCI_LADDER,
            },
        },
        {
            "short": "STAT",
            "name": "Department of Statistics",
            "majors": ["Statistics", "Data Science"],
            "directory_url": "https://www.stat.purdue.edu/people/faculty",
            "scrape": {
                "url": "https://www.stat.purdue.edu/people/faculty",
                "selectors": {
                    "card": "div.element.item.cat-regular_faculty",
                    "name": "h2.name a",
                    "link": "h2.name a",
                    "title": "p.title-p",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _SCI_LADDER,
            },
        },
        _sci_bio("BIO", "Department of Biological Sciences",
                 ["Biology", "Biochemistry", "Microbiology"],
                 "https://www.bio.purdue.edu/people/faculty"),
        _sci_bio("EAPS", "Department of Earth, Atmospheric, and Planetary Sciences",
                 ["Atmospheric Science", "Geology", "Planetary Science"],
                 "https://www.eaps.purdue.edu/people/faculty_directory.html"),
        {
            "short": "PHYS",
            "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astronomy"],
            # /people/faculty is a JS shell; the directory app pulls this
            # server-rendered fragment (all people, one shot). Names are
            # "Last, First" -> flip. Email is alias-only text (no usable mailto),
            # so records land name + rank + department.
            "directory_url": "https://www.physics.purdue.edu/people/faculty",
            "scrape": {
                "url": "https://www.physics.purdue.edu/php-scripts/people/people_list.php",
                "selectors": {
                    "card": "div.person-item[data-category='faculty']",
                    "name": "h2",
                    "title": "div.person-field > label",
                },
                "name_flip": True,
                "ladder_filter": _SCI_LADDER,
            },
        },
        # --- College of Engineering (shared ptProfile template) ---
        _engr("ECE", "Elmore Family School of Electrical & Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "/ECE/People/Faculty", title=".short-title"),
        _engr("ME", "School of Mechanical Engineering",
              ["Mechanical Engineering"], "/ME/People/Faculty"),
        _engr("CE", "Lyles School of Civil & Construction Engineering",
              ["Civil Engineering", "Construction Engineering"],
              "/CE/People/Faculty"),
        _engr("ChE", "Davidson School of Chemical Engineering",
              ["Chemical Engineering"], "/ChE/People/ptFaculty"),
        _engr("AAE", "School of Aeronautics & Astronautics",
              ["Aeronautical Engineering", "Astronautical Engineering"],
              "/AAE/People/Faculty", title=".list-name div:not(.pronouns)"),
        _engr("BME", "Weldon School of Biomedical Engineering",
              ["Biomedical Engineering"], "/BME/People/Faculty"),
        _engr("IE", "Edwardson School of Industrial Engineering",
              ["Industrial Engineering"], "/IE/People/Faculty"),
        _engr("MSE", "School of Materials Engineering",
              ["Materials Science and Engineering"], "/MSE/People/ptFaculty"),
        _engr("NE", "School of Nuclear Engineering",
              ["Nuclear Engineering"], "/NE/People/Faculty"),
        _engr("EEE", "Environmental & Ecological Engineering",
              ["Environmental and Ecological Engineering"], "/EEE/People/Faculty"),
        _engr("ABE", "Agricultural & Biological Engineering",
              ["Agricultural Engineering", "Biological Engineering"],
              "/ABE/People/ptFaculty"),
        _engr("ENE", "School of Engineering Education",
              ["Engineering Education"], "/ENE/People/Faculty",
              title=".list-name div:not(.pronouns)"),
        # --- College of Agriculture (shared JSON roster API) ---
        _ag("AGEC", "Department of Agricultural Economics",
            ["Agricultural Economics"], "agecon", 10),
        _ag("AGRY", "Department of Agronomy",
            ["Agronomy", "Soil Science", "Plant Science"], "agry", 11),
        _ag("ANSC", "Department of Animal Sciences",
            ["Animal Sciences"], "ansc", 12),
        _ag("BCHM", "Department of Biochemistry",
            ["Biochemistry"], "biochem", 13),
        _ag("BTNY", "Department of Botany & Plant Pathology",
            ["Botany", "Plant Pathology", "Plant Science"], "btny", 14),
        _ag("ENTM", "Department of Entomology",
            ["Entomology"], "entm", 15),
        _ag("FS", "Department of Food Science",
            ["Food Science"], "foodsci", 16),
        _ag("FNR", "Department of Forestry & Natural Resources",
            ["Forestry", "Natural Resources", "Wildlife"], "fnr", 17),
        _ag("HLA", "Department of Horticulture & Landscape Architecture",
            ["Horticulture", "Landscape Architecture"], "hla", 18),
        # --- College of Liberal Arts (shared static directory, dept via td 2) ---
        _cla("ENGL", "Department of English",
             ["English", "Literature", "Creative Writing"], r"//\s*English"),
        _cla("HIST", "Department of History", ["History"], r"//\s*History"),
        _cla("PHIL", "Department of Philosophy", ["Philosophy"], r"//\s*Philosophy"),
        _cla("POLS", "Department of Political Science",
             ["Political Science"], r"//\s*Political Science"),
        _cla("SOC", "Department of Sociology", ["Sociology"], r"//\s*Sociology"),
        _cla("ANTH", "Department of Anthropology",
             ["Anthropology"], r"//\s*Anthropology"),
        _cla("COMM", "Brian Lamb School of Communication",
             ["Communication"], r"//\s*Communication"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
