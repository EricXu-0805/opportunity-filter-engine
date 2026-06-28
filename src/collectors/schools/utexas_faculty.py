"""UT Austin faculty config (via the faculty_graph engine).

UT Austin's departments run separate CMSes; this engine covers each via the
cleanest source it exposes:

  * **Computer Science** + **ECE** — server-rendered Drupal "Views" grids (CS
    carries research groups inline → fully keyworded; ECE name + position).
  * **Cockrell School engineering** (ChemE, Aerospace, Civil/Arch/Env, BME) —
    one WordPress ``person`` post type per department, filtered to the
    ``cockrell_person_type`` "Faculty" term AND the ``cockrell_person_job_type``
    "Tenure-Track" term (drops emeritus/research/teaching/adjunct), keyworded
    from the ``cockrell_person_research_area`` taxonomy.
  * **College of Natural Sciences** (Physics, Chemistry, Math) — the CNS
    directory is a JS client over a public Algolia index; queried directly,
    filtered to tenure-track and de-emeritus'd, keyworded from
    ``areas_of_research``.
  * **Mechanical Engineering** — a server-rendered Joomla directory
    (``div.facdata``), title-filtered to ladder ranks, with public emails.

Deferred: Physics is JS only via Algolia (covered); no department remains on the
headless path.

Single source ("utexas_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph


# Cockrell School WordPress: faculty = a `person` post type filtered to the
# Faculty type AND the Tenure-Track job-type term (ids verified live per dept),
# keyworded from the research-area taxonomy.
def _cockrell(short: str, name: str, majors: list[str], base: str,
              type_id: int, tt_id: int) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": f"{base}/faculty",
            "api": {"type": "wp", "base": base, "post_type": "person",
                    "category_include": {"cockrell_person_type": [type_id],
                                         "cockrell_person_job_type": [tt_id]},
                    "keyword_tax": ["cockrell_person_research_area"]}}


# UT Austin College of Natural Sciences shared Algolia directory index.
_CNS_ALGOLIA = {"app_id": "R1M3WN6NBD",
                "api_key": "1323cc0cdac884501409d31207bb2d4b",
                "index": "directory_LIVE", "drop_title_re": r"emerit"}


def _cns(short: str, name: str, majors: list[str], dept: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://cns.utexas.edu/directory",
            "algolia": {**_CNS_ALGOLIA,
                        "filters": f'department:"{dept}" AND '
                                   'position_type:"1-Tenure-Track/Tenured Faculty"'}}


SCHOOL: dict = {
    "school_slug": "utexas",
    "source": "utexas_faculty",
    "organization": "The University of Texas at Austin",
    "location": "Austin, TX",
    "id_prefix": "utexas",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UT Austin) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Computer Engineering", "Data Science"],
            "directory_url": "https://www.cs.utexas.edu/people",
            "scrape": {
                "url": "https://www.cs.utexas.edu/people",
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-contact-faculty",
                    "research": ".views-field-field-research-groups",
                },
            },
        },
        {
            "short": "ECE",
            "name": "Chandra Family Department of Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering"],
            "directory_url": "https://ece.utexas.edu/people/faculty",
            "scrape": {
                "url": "https://ece.utexas.edu/people/faculty",
                "selectors": {
                    "card": ".facentry",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-faculty-position",
                },
            },
        },
        _cockrell("CHEME", "McKetta Department of Chemical Engineering",
                  ["Chemical Engineering"], "https://che.utexas.edu", 218, 226),
        _cockrell("AERO", "Department of Aerospace Engineering & Engineering Mechanics",
                  ["Aerospace Engineering", "Engineering Mechanics"],
                  "https://www.ae.utexas.edu", 3012, 3015),
        _cockrell("CAEE", "Department of Civil, Architectural & Environmental Engineering",
                  ["Civil Engineering", "Architectural Engineering", "Environmental Engineering"],
                  "https://www.caee.utexas.edu", 45, 180),
        _cockrell("BME", "Department of Biomedical Engineering",
                  ["Biomedical Engineering"], "https://bme.utexas.edu", 569, 571),
        _cns("PHYSICS", "Department of Physics", ["Physics"], "Physics"),
        _cns("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"], "Chemistry"),
        _cns("MATH", "Department of Mathematics", ["Mathematics"], "Mathematics"),
        {
            "short": "ME",
            "name": "Walker Department of Mechanical Engineering",
            "majors": ["Mechanical Engineering"],
            "directory_url": "https://www.me.utexas.edu/people/faculty-directory",
            "scrape": {
                "url": "https://www.me.utexas.edu/people/faculty-directory",
                "selectors": {"card": "div.facdata", "name": "h2",
                              "link": "p.h6-style a", "title": "p.facpos",
                              "email": "a.email"},
                "ladder_filter": {"drop": r"emerit|adjunct|research (professor|scientist)"
                                          r"|practice|instruction|lecturer|visiting"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
