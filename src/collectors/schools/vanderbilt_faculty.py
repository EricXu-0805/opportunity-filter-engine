"""Vanderbilt University faculty config (via the faculty_graph engine).

The College of Arts & Science runs on one shared WordPress multisite
(``as.vanderbilt.edu/<dept>/``, the older AnchorDown-CAS child theme) that
server-renders each department's faculty into a striped HTML table. ONE
selector set covers all of them — rows are ``table.table-striped tr``, the name
is the ``td strong a`` link (whose href is the ``/bio/<slug>`` profile), and the
public email is the row's ``mailto:`` — only the listing path differs per dept
(``/people/`` vs ``/faculty/``, resolved per entry from a live probe). The rank
sits as bare ``<br>``-separated text in the same cell (no stable element), so
records ship without a title and are recovered by the profile-enrichment pass;
email is present inline for essentially every row.

Single source ("vanderbilt_faculty"); department rides each record's
``department``, ids namespaced by short-code. Audience "unknown".

Deferred (tracked for a later pass): the A&S departments on the newer FL-Builder
"people-card" template (no striped table — African American & Diaspora Studies,
Communication Studies, Earth & Environmental Sciences, German-Russian, History
of Art, Mathematics, Cinema & Media Arts, Classical & Mediterranean, Asian
Studies, Gender & Sexuality, European Studies); the School of Engineering
(client-side FutureVU people directory — needs headless render); and Peabody
College + Blair School of Music (shared ``/wp-json/wp/v2/person`` REST — a
future ``api`` config once the faculty taxonomy categories are mapped).
"""

from __future__ import annotations

from .. import faculty_graph

# Shared College of Arts & Science striped-table selector (static HTML).
_CAS_SELECTORS = {
    "card": "table.table-striped tr",
    "name": "td strong a",
    "link": "td strong a",
    "email": "a[href^='mailto:']",
}


def _cas(short: str, name: str, majors: list[str], slug: str, path: str) -> dict:
    """A College of Arts & Science department (as.vanderbilt.edu/<slug>/<path>)."""
    url = f"https://as.vanderbilt.edu/{slug}/{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CAS_SELECTORS}}


# Keep ladder faculty across the FutureVU JSON rosters (Engineering, Blair):
# titles carry every rank; drop emeriti.
_LADDER = {"require": r"\bprofessor\b|\blecturer\b|\bartist\b", "drop": r"emerit"}


def _fv(short: str, name: str, majors: list[str], host: str, school: int,
        department="all", affiliated="primary") -> dict:
    """A school served by Vanderbilt's shared FutureVU peoplemanager JSON API."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": f"https://{host}/people/",
            "ajax": {"type": "futurevu", "host": host, "school": school,
                     "department": department, "affiliated": affiliated,
                     "profile_base": f"https://{host}/bio/", "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "vanderbilt",
    "source": "vanderbilt_faculty",
    "organization": "Vanderbilt University",
    "location": "Nashville, TN",
    "id_prefix": "vanderbilt",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Vanderbilt University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _cas("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology", "faculty/"),
        _cas("BSCI", "Department of Biological Sciences", ["Biological Sciences"],
             "biological-sciences", "people/"),
        _cas("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry", "faculty/"),
        _cas("ECON", "Department of Economics", ["Economics"], "economics", "people/"),
        _cas("ENGL", "Department of English", ["English"], "english", "people/"),
        _cas("FRIT", "Department of French & Italian", ["French", "Italian"],
             "french-italian", "faculty/"),
        _cas("HIST", "Department of History", ["History"], "history", "people/"),
        _cas("MHS", "Medicine, Health & Society", ["Medicine, Health & Society"],
             "medicine-health-society", "faculty/"),
        _cas("NSC", "Program in Neuroscience", ["Neuroscience"], "neuroscience", "faculty/"),
        _cas("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy", "people/"),
        _cas("PHYS", "Department of Physics & Astronomy", ["Physics", "Astronomy"],
             "physics-astronomy", "people/"),
        _cas("PSCI", "Department of Political Science", ["Political Science"],
             "political-science", "people/"),
        _cas("PSY", "Department of Psychology", ["Psychology"], "psychology", "faculty/"),
        _cas("RLST", "Department of Religious Studies", ["Religious Studies"],
             "religious-studies", "faculty/"),
        _cas("SOC", "Department of Sociology", ["Sociology"], "sociology", "people/"),
        _cas("SPAN", "Department of Spanish & Portuguese", ["Spanish", "Portuguese"],
             "spanish-portuguese", "people/"),
        _cas("THTR", "Department of Theatre", ["Theatre"], "theatre", "people/"),
        _cas("JS", "Program in Jewish Studies", ["Jewish Studies"], "jewish-studies", "faculty/"),
        _cas("ART", "Department of Art", ["Art", "Studio Art", "History of Art"], "art", "faculty/"),
        _cas("PPS", "Public Policy Studies", ["Public Policy"], "public-policy-studies", "people/"),
        # ---- A&S depts on the striped table but at other paths -----------
        _cas("AADS", "Department of African American & Diaspora Studies",
             ["African American & Diaspora Studies"], "african-american-diaspora-studies", "faculty/"),
        _cas("GRES", "Department of German, Russian & East European Studies",
             ["German Studies", "Russian Studies"], "german-russian-studies", "people/"),
        _cas("HART", "Department of History of Art & Architecture",
             ["History of Art", "Architecture"], "history-art-architecture", "faculty/"),
        _cas("MATH", "Department of Mathematics", ["Mathematics"], "math", "faculty/"),
        _cas("CMS", "Department of Classical & Mediterranean Studies",
             ["Classical & Mediterranean Studies"], "classical-mediterranean-studies", "people/"),
        # ---- School of Engineering (FutureVU peoplemanager JSON) ---------
        _fv("ENG", "School of Engineering",
            ["Biomedical Engineering", "Chemical Engineering", "Civil Engineering",
             "Computer Science", "Electrical Engineering", "Mechanical Engineering",
             "Engineering Science"], "engineering.vanderbilt.edu", 2),
        # ---- Blair School of Music (FutureVU peoplemanager JSON) ---------
        _fv("BLAIR", "Blair School of Music", ["Music", "Performance", "Composition"],
            "blair.vanderbilt.edu", 3, affiliated="all"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
