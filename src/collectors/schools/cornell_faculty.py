"""Cornell University faculty config (via the faculty_graph engine).

Cornell spreads faculty across several college platforms; this config covers the
two largest that serve clean server-rendered cards to a plain request:

* College of Arts & Sciences (~24 departments). Each dept has its own
  ``<dept>.cornell.edu`` subdomain on a shared A&S Drupal theme. The canonical
  listing path is ``/faculty`` (``/people`` frequently 301s or 403s). Each
  faculty member is an ``article.person-card`` carrying the name
  (``.person-content h2 a`` — also the ``/slug`` profile link), the rank
  (``p.person-title``), and research areas (``p.person-departments``). Email is
  not on the listing (recovered later via profile enrichment). Verified live:
  Economics 63, Government 64, History 59, Physics 51.

* College of Engineering (Duffield platform, ``www.<dept>.cornell.edu``). Each
  faculty member is an ``li.ce-block__people-list-item`` carrying the name
  (``.ce-block__people-list-person-name`` → profile link
  ``.ce-block__people-list-item-link``), rank
  (``.ce-block__people-list-person-title``), and a public ``mailto:`` — so
  Engineering lands fully emailed. Verified live: MAE.

Whole-roster pages are sliced to ladder faculty by ``_LADDER`` (keep Professor/
Lecturer, drop emeriti). Single source ("cornell_faculty"); department rides
each record's ``department``, ids namespaced by department short-code.

Deferred (distinct platforms / pagination / WAF — tracked for a later pass):
CIS/Bowers (CS + InfoSci, paginated ``views-row``), CALS (mixed subdomains +
``cals.cornell.edu`` subpaths), Human Ecology (one college-wide
``profile-directory-card`` grid, filter by dept), ILR (``cu-person`` theme),
AAP (``people-list__`` theme), SC Johnson Business (aggregate directory), and
the Brooks School of Public Policy (Cloudflare/WAF — needs headless render).
"""

from __future__ import annotations

from .. import faculty_graph

# College of Arts & Sciences — shared Drupal "person-card" (static HTML).
_AS_SELECTORS = {
    "card": "article.person-card",
    "name": ".person-content h2 a",
    "link": ".person-content h2 a",
    "title": ".person-title",
    "email": "a[href^='mailto:']",
}

# College of Engineering — Duffield "ce-block people-list" (static HTML, mailto).
_CE_SELECTORS = {
    "card": "li.ce-block__people-list-item",
    "name": ".ce-block__people-list-person-name",
    "link": ".ce-block__people-list-item-link",
    "title": ".ce-block__people-list-person-title",
    "email": "a[href^='mailto:']",
}

# Keep ladder faculty (Professor / Assistant / Associate / Lecturer / Senior
# Lecturer); drop emeriti. Faculty-only listing pages pass this unchanged.
_LADDER = {"require": r"\bprofessor\b|\blecturer\b", "drop": r"emerit"}


def _as(short: str, name: str, majors: list[str], subdomain: str, *, render: bool = False) -> dict:
    """A College of Arts & Sciences department (<subdomain>.cornell.edu/faculty)."""
    url = f"https://{subdomain}.cornell.edu/faculty"
    scrape = {"url": url, "selectors": _AS_SELECTORS, "ladder_filter": _LADDER}
    if render:  # a few A&S subdomains 403 a plain request (Cloudflare); headless clears it.
        scrape["render"] = True
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


def _eng(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    """A College of Engineering department (www.<subdomain>.cornell.edu/people/faculty)."""
    url = f"https://www.{subdomain}.cornell.edu/people/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CE_SELECTORS, "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "cornell",
    "source": "cornell_faculty",
    "organization": "Cornell University",
    "location": "Ithaca, NY",
    "id_prefix": "cornell",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Cornell University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences ----------------------------------
        _as("GOVT", "Department of Government", ["Government", "Political Science"], "government"),
        _as("ECON", "Department of Economics", ["Economics"], "economics"),
        _as("PSYCH", "Department of Psychology", ["Psychology"], "psychology"),
        _as("PHYS", "Department of Physics", ["Physics"], "physics"),
        _as("HIST", "Department of History", ["History"], "history"),
        _as("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _as("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _as("MATH", "Department of Mathematics", ["Mathematics"], "math"),
        _as("CHEM", "Department of Chemistry & Chemical Biology",
            ["Chemistry", "Chemical Biology"], "chemistry"),
        _as("ANTHRO", "Department of Anthropology", ["Anthropology"], "anthropology", render=True),
        _as("ASTRO", "Department of Astronomy", ["Astronomy", "Astrophysics"], "astro"),
        _as("CLASS", "Department of Classics", ["Classics"], "classics"),
        _as("ENGL", "Department of Literatures in English", ["English", "Literature"], "english"),
        _as("COMPLIT", "Department of Comparative Literature", ["Comparative Literature"],
            "complit", render=True),
        _as("LING", "Department of Linguistics", ["Linguistics"], "linguistics"),
        _as("MUSIC", "Department of Music", ["Music"], "music"),
        _as("ROMANCE", "Department of Romance Studies",
            ["French", "Spanish", "Italian", "Romance Studies"], "romancestudies"),
        _as("GERMAN", "Department of German Studies", ["German Studies"], "german"),
        _as("ASIAN", "Department of Asian Studies", ["Asian Studies"], "asianstudies"),
        _as("STS", "Department of Science & Technology Studies",
            ["Science & Technology Studies"], "sts"),
        _as("PMA", "Department of Performing & Media Arts",
            ["Performing & Media Arts", "Theatre", "Film"], "pma"),
        _as("ARTH", "Department of History of Art & Visual Studies",
            ["History of Art", "Visual Studies"], "arthistory"),
        _as("AFRICANA", "Africana Studies & Research Center", ["Africana Studies"], "africana"),
        # ---- College of Engineering --------------------------------------
        _eng("MAE", "Sibley School of Mechanical & Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], "mae"),
        _eng("CEE", "School of Civil & Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "cee"),
        _eng("ECE", "School of Electrical & Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], "ece"),
        _eng("CHEME", "Smith School of Chemical & Biomolecular Engineering",
             ["Chemical Engineering", "Biomolecular Engineering"], "cheme"),
        _eng("MSE", "Department of Materials Science & Engineering",
             ["Materials Science & Engineering"], "mse"),
        _eng("AEP", "School of Applied & Engineering Physics",
             ["Applied Physics", "Engineering Physics"], "aep"),
        _eng("BME", "Meinig School of Biomedical Engineering",
             ["Biomedical Engineering"], "bme"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
