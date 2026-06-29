"""UCLA faculty config (via the faculty_graph engine, WordPress-REST source).

UCLA department sites run WordPress and expose faculty as custom post types over
``/wp-json/wp/v2/``. That structured JSON is far more reliable than CSS-scraping a
JS-rendered grid (the earlier ``.info-box`` / ``.tb-fields`` attempts over-listed
non-faculty), so these departments opt into the engine's ``api`` block:

  * **Chemistry & Biochemistry** (``directory`` post type) — filtered to the
    ``directory-category`` "Faculty" term (id 88), which excludes the Emeriti,
    Staff, Lecturer, Postdoc and Graduate-student categories. Keywords come from
    the clean ``specialties`` research taxonomy (Biochemistry, Biophysics,
    Chemical Biology, Catalysis, …), dropping the two teaching-track terms.
  * **MCDB** (Molecular, Cell & Developmental Biology, ``facultyinfo`` post type)
    — keywords from the ``model`` (organism) and ``research-area`` taxonomies.
  * **Psychology** (``faculty-page`` post type) — no research taxonomy, so a
    bounded per-profile enrich reads the rank ("…Professor" vs "Lecturer", which
    drops teaching-track and emeriti) and the "Primary Area" research line.

The seven **Samueli engineering** departments (BE, CBE, CEE, CS, ECE, MAE, MSE)
share one ``admin-ajax.php`` directory backend whose results come pre-grouped by
role — the engine keeps only the ladder-faculty containers (core / chair /
vice-chair / ieo / in-residence) and reads each profile's "RESEARCH AND
INTERESTS" toggle for clean keywords, so CS/ECE/MAE land at UIUC parity.

Math, Economics, and EEB are static-HTML ladder directories scraped directly.
**Physics & Astronomy** and **Statistics** sit behind an InCommon cert with an
incomplete chain (the server omits its intermediate); the shared fetcher now
supplies that intermediate (``ucb_common._ca_bundle`` — verification stays on),
so both scrape over the normal path: Physics from its ``/faculty.html`` table
(``h5`` name + a rank/research ``<p>`` trimmed of office/phone, emeriti dropped),
Statistics from its dedicated ladder page (lecturers dropped by title).

Single source ("ucla_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

SCHOOL: dict = {
    "school_slug": "ucla",
    "source": "ucla_faculty",
    "organization": "University of California, Los Angeles",
    "location": "Los Angeles, CA",
    "id_prefix": "ucla",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UCLA) — work authorization depends on the arrangement; "
        "ask the professor."
    ),
    "departments": [
        {
            "short": "CHEM",
            "name": "Department of Chemistry and Biochemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.chemistry.ucla.edu/faculty/",
            "api": {
                "type": "wp",
                "base": "https://www.chemistry.ucla.edu",
                "post_type": "directory",
                "category_include": {"directory-category": [88]},
                "keyword_tax": ["specialties"],
                "keyword_drop": ["instructional", "instructional support"],
                "name_flip": True,
            },
        },
        {
            "short": "MCDB",
            "name": "Department of Molecular, Cell and Developmental Biology",
            "majors": [
                "Molecular, Cell and Developmental Biology",
                "Biology",
                "Biochemistry",
            ],
            "directory_url": "https://www.mcdb.ucla.edu/faculty/",
            "api": {
                "type": "wp",
                "base": "https://www.mcdb.ucla.edu",
                "post_type": "facultyinfo",
                "keyword_tax": ["model", "research-area"],
            },
        },
        {
            "short": "PSYCH",
            "name": "Department of Psychology",
            "majors": ["Psychology", "Cognitive Science"],
            "directory_url": "https://www.psych.ucla.edu/faculty/",
            "api": {
                "type": "wp",
                "base": "https://www.psych.ucla.edu",
                "post_type": "faculty-page",
                "profile_enrich": {
                    "position_re": (
                        r"(?:Distinguished |Adjunct |Visiting |Acting |Research )?"
                        r"(?:Assistant |Associate )?Professor(?:\s+Emerit\w+)?"
                        r"|Senior Lecturer|Continuing Lecturer|Lecturer|Emerit\w+"
                    ),
                    "research_re": (
                        r"Primary Area:?\s*([A-Za-z &/-]{4,40}?)\s*"
                        r"(?:Home|Email|Address|Phone|Office|Department|Secondary|$)"
                    ),
                    "require_professor": True,
                },
            },
        },
        {
            "short": "BE",
            "name": "Department of Bioengineering",
            "majors": ["Bioengineering"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#be",
            "ajax": {"type": "seas", "department": "be", "research_enrich": True},
        },
        {
            "short": "CBE",
            "name": "Department of Chemical and Biomolecular Engineering",
            "majors": ["Chemical Engineering", "Chemical and Biomolecular Engineering"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#cbe",
            "ajax": {"type": "seas", "department": "cbe", "research_enrich": True},
        },
        {
            "short": "CEE",
            "name": "Department of Civil and Environmental Engineering",
            "majors": ["Civil Engineering", "Environmental Engineering"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#cee",
            "ajax": {"type": "seas", "department": "cee", "research_enrich": True},
        },
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Computer Science and Engineering"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#cs",
            "ajax": {"type": "seas", "department": "cs", "research_enrich": True},
        },
        {
            "short": "ECE",
            "name": "Department of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#ece",
            "ajax": {"type": "seas", "department": "ece", "research_enrich": True},
        },
        {
            "short": "MAE",
            "name": "Department of Mechanical and Aerospace Engineering",
            "majors": ["Mechanical Engineering", "Aerospace Engineering"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#mae",
            "ajax": {"type": "seas", "department": "mae", "research_enrich": True},
        },
        {
            "short": "MSE",
            "name": "Department of Materials Science and Engineering",
            "majors": ["Materials Science and Engineering", "Materials Science"],
            "directory_url": "https://samueli.ucla.edu/search-faculty/#mse",
            "ajax": {"type": "seas", "department": "mse", "research_enrich": True},
        },
        # College static directories (ladder-only pages; emeriti live separately).
        {
            "short": "ECON",
            "name": "Department of Economics",
            "majors": ["Economics", "Business Economics"],
            "directory_url": "https://economics.ucla.edu/faculty/ladder/",
            "scrape": {"url": "https://economics.ucla.edu/faculty/ladder/",
                       "selectors": {"card": "a[href*='/person/']",
                                     "name": ":self", "link": ":self"}},
        },
        {
            "short": "EEB",
            "name": "Department of Ecology and Evolutionary Biology",
            "majors": ["Ecology and Evolutionary Biology", "Biology"],
            "directory_url": "https://www.eeb.ucla.edu/faculty/",
            "scrape": {"url": "https://www.eeb.ucla.edu/faculty/",
                       "selectors": {"card": "a[href*='/indivfaculty/?faculty=']",
                                     "name": ":self", "link": ":self"}},
        },
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics"],
            "directory_url": "https://www.math.ucla.edu/people/faculty/",
            "scrape": {"url": "https://www.math.ucla.edu/people/faculty/",
                       "name_flip": True,
                       "selectors": {"card": "tr",
                                     "name": "a[href*='/people/ladder/']",
                                     "link": "a[href*='/people/ladder/']",
                                     "title": "td:nth-child(2)"},
                       "ladder_filter": {"drop": r"emerit"}},
        },
        {
            "short": "PHYS",
            "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astrophysics", "Astronomy"],
            "directory_url": "https://pa.ucla.edu/faculty.html",
            "scrape": {"url": "https://pa.ucla.edu/faculty.html",
                       "selectors": {"card": "tbody tr", "name": "h5",
                                     "link": "a", "title": "p",
                                     "title_strip_after": r"\s*(Office|Phone|Email|Fax|Tel)\b"},
                       "ladder_filter": {"require": r"professor", "drop": r"emerit"}},
        },
        {
            "short": "STAT",
            "name": "Department of Statistics and Data Science",
            "majors": ["Statistics", "Data Science"],
            "directory_url": "https://statistics.ucla.edu/index.php/people1/all-faculty/faculty/",
            "scrape": {"url": "https://statistics.ucla.edu/index.php/people1/all-faculty/faculty/",
                       "selectors": {"card": "div.abcfslTxtCntrGridA",
                                     "name": ".MP-F1", "title": ".MP-F3"},
                       "ladder_filter": {"require": r"professor",
                                         "drop": r"lecturer|emerit|adjunct|visiting"}},
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
