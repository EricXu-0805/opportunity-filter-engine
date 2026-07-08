"""Northwestern University faculty config (via the faculty_graph engine).

Weinberg College of Arts & Sciences runs a shared "Cascade" CMS across nearly
all departments: a ``div.people-wrap`` card with name + profile link in
``h3 a``, rank in ``p.title``, and a public ``mailto:`` on the card, so records
land name + title + email in a single server-rendered listing pass (no headless
browser). Three departments use a different theme (Sociology's HTML table,
Molecular Biosciences' ``div.directory`` roster, the CIERA astrophysics center's
WordPress directory) — those carry their variant selectors inline.

McCormick School of Engineering (9 depts) uses its own ``.faculty`` card theme
(``.faculty-info`` name/rank + ``a.mail_link`` mailto). Feinberg basic sciences +
Medill/SESP/Communication/Bienen are a follow-up.

Single source ("northwestern_faculty"); department rides each record's
``department``, ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Weinberg Cascade card theme.
_NW_SEL = {"card": "div.people-wrap", "name": "h3 a", "link": "h3 a",
           "title": "p.title", "email": "a[href^='mailto:']"}
# Drop Northwestern's large teaching track ("... of Instruction"), emeriti,
# lecturers, adjuncts, visiting, postdoctoral fellows, and staff; keep
# professorial ladder faculty (endowed chairs contain "Professor").
_NW_LADDER = {"require": r"\bprofessor\b",
              "drop": (r"\bemerit|instruction|\blecturer|\bvisiting|\badjunct"
                       r"|\bpostdoctoral|\bfellow\b|\bstaff\b")}


def _nw(short: str, name: str, majors: list[str], url: str,
        link_filter: str | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": _NW_SEL, "ladder_filter": _NW_LADDER}
    if link_filter:
        scrape["link_filter"] = link_filter
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# McCormick School of Engineering: shared theme distinct from Weinberg's — a
# ``.faculty`` card (name/link in ``.faculty-info h3 a``, rank in the first
# ``.faculty-info p``, public mailto in ``a.mail_link``) at
# mccormick.northwestern.edu/<slug>/people/faculty/ (ECE uses /people/faculty.html).
_MCC_SEL = {"card": ".faculty", "name": ".faculty-info h3 a",
            "link": ".faculty-info h3 a", "title": ".faculty-info p",
            "email": "a.mail_link[href^='mailto:']"}
_MCC_LADDER = {"require": r"\bprofessor\b",
               "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bcourtesy|instruction|\bstaff\b"}


def _mcc(short: str, name: str, majors: list[str], slug: str,
         path: str = "/people/faculty/index.html") -> dict:
    url = f"https://www.mccormick.northwestern.edu/{slug}{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _MCC_SEL, "ladder_filter": _MCC_LADDER}}


SCHOOL: dict = {
    "school_slug": "northwestern",
    "source": "northwestern_faculty",
    "organization": "Northwestern University",
    "location": "Evanston, IL",
    "id_prefix": "northwestern",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Northwestern University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # --- Weinberg College of Arts & Sciences (shared Cascade theme) ---
        _nw("ANTH", "Department of Anthropology", ["Anthropology"],
            "https://anthropology.northwestern.edu/people/faculty/"),
        _nw("ARTH", "Department of Art History", ["Art History"],
            "https://arthistory.northwestern.edu/people/faculty/"),
        _nw("CHEM", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.northwestern.edu/people/faculty/"),
        _nw("CLASSICS", "Department of Classics", ["Classics", "Classical Studies"],
            "https://classics.northwestern.edu/people/faculty/"),
        _nw("ECON", "Department of Economics", ["Economics"],
            "https://economics.northwestern.edu/people/faculty/"),
        _nw("ENGL", "Department of English",
            ["English", "Literature", "Creative Writing"],
            "https://english.northwestern.edu/people/faculty/"),
        _nw("FRIT", "Department of French & Italian", ["French", "Italian"],
            "https://frenchanditalian.northwestern.edu/people/faculty/"),
        _nw("GSF", "Department of Gender & Sexuality Studies",
            ["Gender & Sexuality Studies"],
            "https://gendersexuality.northwestern.edu/people/faculty/core-faculty/index.html"),
        _nw("GERMAN", "Department of German", ["German", "German Studies"],
            "https://german.northwestern.edu/people/faculty/continuing/index.html"),
        _nw("HIST", "Department of History", ["History"],
            "https://history.northwestern.edu/people/faculty/"),
        _nw("LING", "Department of Linguistics", ["Linguistics"],
            "https://linguistics.northwestern.edu/people/core-faculty/"),
        _nw("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"],
            "https://www.math.northwestern.edu/people/faculty/"),
        _nw("NEURO", "Department of Neurobiology", ["Neurobiology", "Neuroscience"],
            "https://neurobiology.northwestern.edu/people/core-faculty/index.html"),
        _nw("PHIL", "Department of Philosophy", ["Philosophy"],
            "https://philosophy.northwestern.edu/people/continuing-faculty/index.html"),
        _nw("PHYS", "Department of Physics & Astronomy", ["Physics", "Astronomy"],
            "https://physics.northwestern.edu/people/faculty/core-faculty/index.html"),
        _nw("POLISCI", "Department of Political Science", ["Political Science"],
            "https://polisci.northwestern.edu/people/core-faculty/"),
        _nw("PSYCH", "Department of Psychology", ["Psychology"],
            "https://psychology.northwestern.edu/people/faculty/core/index.html"),
        _nw("RELIG", "Department of Religious Studies", ["Religious Studies"],
            "https://religious-studies.northwestern.edu/people/faculty/"),
        _nw("SLAVIC", "Department of Slavic Languages & Literatures",
            ["Slavic Languages & Literatures", "Russian"],
            "https://slavic.northwestern.edu/people/faculty/"),
        # Cross-listed affiliates carry an absolute foreign-subdomain profile link
        # + a "| Department of X" name suffix; a relative-only link_filter keeps
        # home faculty with clean names.
        _nw("SPANPORT", "Department of Spanish & Portuguese", ["Spanish", "Portuguese"],
            "https://spanish-portuguese.northwestern.edu/people/faculty/",
            link_filter=r"^(?!https?://)"),
        _nw("STAT", "Department of Statistics & Data Science",
            ["Statistics", "Data Science"],
            "https://statistics.northwestern.edu/people/faculty/"),
        _nw("EPS", "Department of Earth, Planetary & Environmental Sciences",
            ["Earth Science", "Environmental Sciences", "Planetary Science"],
            "https://deeps.northwestern.edu/our-people/faculty/index.html"),
        # --- variant themes ---
        {
            "short": "SOC", "name": "Department of Sociology", "majors": ["Sociology"],
            "directory_url": "https://sociology.northwestern.edu/people/faculty/",
            "scrape": {
                "url": "https://sociology.northwestern.edu/people/faculty/",
                "selectors": {
                    "card": "table#directory tbody tr",
                    "name": "td:nth-child(1) a", "link": "td:nth-child(1) a",
                    "title": "td:nth-child(2)",
                    "email": "td:nth-child(3) a[href^='mailto:']",
                },
                "ladder_filter": _NW_LADDER,
            },
        },
        {
            "short": "MOLBIO", "name": "Department of Molecular Biosciences",
            "majors": ["Molecular Biosciences", "Biochemistry", "Molecular Biology"],
            "directory_url": "https://molbiosci.northwestern.edu/people/core-faculty/index.html",
            # 'directory' card theme, no rank on the card; the page IS the
            # Core-Faculty roster so no ladder filter (title defaults to Professor).
            "scrape": {
                "url": "https://molbiosci.northwestern.edu/people/core-faculty/index.html",
                "selectors": {
                    "card": "div.directory", "name": "h3 a", "link": "h3 a",
                    "email": "a[href^='mailto:']",
                },
            },
        },
        {
            "short": "CIERA",
            "name": "Center for Interdisciplinary Exploration & Research in Astrophysics",
            "majors": ["Astronomy", "Astrophysics", "Physics"],
            "directory_url": "https://ciera.northwestern.edu/directory/",
            "scrape": {
                "url": "https://ciera.northwestern.edu/directory/",
                "selectors": {
                    "card": "div.people-wrap", "name": "h4 a", "link": "h4 a",
                    "title": "p[itemprop='jobTitle']",
                    "email": "a.email-link[href^='mailto:']",
                },
                # A WordPress center directory mixing grad students / postdocs /
                # staff and external-institution professors — strict drop keeps
                # Northwestern ladder professors.
                "ladder_filter": {
                    "require": r"\bprofessor\b",
                    "drop": (r"\bemerit|instruction|\bvisiting|\bpostdoctoral|postdoc"
                             r"|\bgraduate\b| at |\bscholar|\bfellow\b|adjunct"
                             r"|research assistant professor|\breader\b|specialist"
                             r"|scientist|director of operations|assistant director"
                             r"|,\s+(?:the\s+)?(?:university|northern|princeton"
                             r"|wake forest|illinois|mcgill|tata|national|adler"
                             r"|uc\b|mit\b|arizona|warwick|berkeley|chinese)"),
                },
            },
        },
        # --- McCormick School of Engineering (shared .faculty theme) ---
        _mcc("MCC-BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "biomedical"),
        _mcc("MCC-CHBE", "Department of Chemical & Biological Engineering",
             ["Chemical Engineering", "Biological Engineering"], "chemical-biological"),
        _mcc("MCC-CEE", "Department of Civil & Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "civil-environmental"),
        _mcc("MCC-CS", "Department of Computer Science",
             ["Computer Science"], "computer-science"),
        _mcc("MCC-ECE", "Department of Electrical & Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], "electrical-computer",
             path="/people/faculty.html"),
        _mcc("MCC-ESAM", "Department of Engineering Sciences & Applied Mathematics",
             ["Applied Mathematics"], "applied-math"),
        _mcc("MCC-IEMS", "Department of Industrial Engineering & Management Sciences",
             ["Industrial Engineering"], "industrial"),
        _mcc("MCC-MSE", "Department of Materials Science & Engineering",
             ["Materials Science"], "materials-science"),
        _mcc("MCC-ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"], "mechanical"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
