"""Johns Hopkins University faculty config (via the faculty_graph engine).

The Krieger School of Arts & Sciences serves its entire faculty from one
Cloudflare-walled TablePress table (``#tablepress-54`` at
krieger.jhu.edu/people/faculty-directory/) — Name / Department / Title / public
email, ~836 rows, every row emailed. A headless Chromium session clears the
Cloudflare challenge and the DataTables JS API returns all rows; the engine's
``krieger_table`` source (``faculty_graph._fetch_krieger_table``) fetches the
table once and slices it per department. Records land name + rank + email + dept
(no research keywords on the table — like Duke Trinity / UCSD bare link-lists).

Whiting School of Engineering + School of Medicine basic sciences are NOT in
this table (separate Cloudflare-walled sites) and are a follow-up.

Single source ("jhu_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# The KSAS directory mixes ladder faculty with lecturers, research scientists,
# and emeriti — keep any professorial rank (incl. Research/Teaching Professor),
# drop the rest.
_KT_LADDER = {"require": r"\bprof",
              "drop": (r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff|scientist"
                       r"|scholar|instructor|postdoc|\bfellow")}


def _kt(short: str, name: str, majors: list[str], department: str) -> dict:
    """One KSAS department, sliced from the shared Krieger directory table by its
    exact Department-column string."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": faculty_graph._KRIEGER_URL,
            "krieger_table": {"department": department, "ladder_filter": _KT_LADDER}}


SCHOOL: dict = {
    "school_slug": "jhu",
    "source": "jhu_faculty",
    "organization": "Johns Hopkins University",
    "location": "Baltimore, MD",
    "id_prefix": "jhu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Johns Hopkins University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # --- Krieger School of Arts & Sciences (shared directory table) ---
        _kt("BIO", "Department of Biology", ["Biology"], "Biology"),
        _kt("CHEM", "Department of Chemistry", ["Chemistry"], "Chemistry"),
        _kt("PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astronomy"], "Physics and Astronomy"),
        _kt("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"], "Mathematics"),
        _kt("BIOPHYS", "Thomas C. Jenkins Department of Biophysics",
            ["Biophysics"], "Biophysics"),
        _kt("COGSCI", "Department of Cognitive Science",
            ["Cognitive Science"], "Cognitive Science"),
        _kt("EPS", "Department of Earth and Planetary Sciences",
            ["Earth Sciences", "Planetary Science"], "Earth and Planetary Science"),
        _kt("ECON", "Department of Economics", ["Economics"], "Economics"),
        _kt("ENGL", "Department of English", ["English", "Literature"], "English"),
        _kt("HIST", "Department of History", ["History"], "History"),
        _kt("HART", "Department of History of Art",
            ["History of Art", "Art History"], "History of Art"),
        _kt("HOS", "Department of History of Science and Technology",
            ["History of Science"], "History of Science"),
        _kt("PHIL", "Department of Philosophy", ["Philosophy"], "Philosophy"),
        _kt("POLS", "Department of Political Science",
            ["Political Science"], "Political Science"),
        _kt("PBS", "Department of Psychological and Brain Sciences",
            ["Psychology", "Neuroscience"], "Psychological and Brain Sciences"),
        _kt("SOC", "Department of Sociology", ["Sociology"], "Sociology"),
        _kt("ANTH", "Department of Anthropology", ["Anthropology"], "Anthropology"),
        _kt("CLAS", "Department of Classics", ["Classics"], "Classics"),
        _kt("NES", "Department of Near Eastern Studies",
            ["Near Eastern Studies"], "Near Eastern Studies"),
        _kt("MLL", "Department of Modern Languages and Literatures",
            ["German", "French", "Italian", "Spanish"],
            "Modern Languages and Literatures"),
        _kt("WRIT", "The Writing Seminars",
            ["Creative Writing", "Writing Seminars"], "Writing Seminars"),
        _kt("NEURO", "Solomon H. Snyder Department of Neuroscience",
            ["Neuroscience"], "Neuroscience"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
