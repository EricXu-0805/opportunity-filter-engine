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

Also covered (added in the coverage-completion pass, all clean server-HTML):
Bowers CIS — Computer Science + Information Science (paginated ``views-row``);
ILR School (``cu-person`` theme, single page); and the CALS static cohorts —
Ecology & Evolutionary Biology + Neurobiology & Behavior (A&S ``person-card``
theme) and Earth & Atmospheric Sciences (Duffield ``ce-block``).

Whole-roster pages are sliced to ladder faculty by ``_LADDER`` (keep Professor/
Lecturer, drop emeriti). Single source ("cornell_faculty"); department rides
each record's ``department``, ids namespaced by department short-code.

Still deferred (need headless render or bespoke handling — a later pass):
the CALS/Human-Ecology/Computational-Biology directories (AWS-WAF ``expert-card``
/ ``profile-directory-card`` grids that 403 a plain request — selectors known,
just gated on render), Statistics & Data Science (JS AJAX), AAP (``people-list__``
Algolia index), SC Johnson Business (aggregate app, 6 featured only), and the
Brooks School of Public Policy (host-level WAF; use publicpolicy.cornell.edu wp-json).
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

# Bowers College of Computing & Information Science — paginated Drupal views-row.
_CIS_SELECTORS = {
    "card": "div.views-row",
    "name": ".name",
    "link": ".name a",
    "title": ".position-titles .field__item",
    "email": ".email a[href^='mailto:']",
}

# ILR School — distinct Cornell Drupal ``cu-person`` theme (single page).
_ILR_SELECTORS = {
    "card": ".cu-person",
    "name": ".cu-person__name",
    "link": ".cu-person__name a",
    "title": ".cu-person__title",
    "email": "a[href^='mailto:']",
}

def _cis(short: str, name: str, majors: list[str], subdomain: str, max_pages: int) -> dict:
    """A Bowers CIS department (paginated ``?page=N`` views-row grid)."""
    url = f"https://{subdomain}.cornell.edu/people/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CIS_SELECTORS, "ladder_filter": _LADDER,
                       "paginate": {"param": "page", "max": max_pages}}}




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
        # ---- Bowers College of Computing & Information Science -----------
        _cis("CS", "Department of Computer Science", ["Computer Science"], "www.cs", 10),
        _cis("INFOSCI", "Department of Information Science",
             ["Information Science"], "infosci", 8),
        # ---- ILR School --------------------------------------------------
        {"short": "ILR", "name": "School of Industrial & Labor Relations",
         "majors": ["Industrial & Labor Relations", "Labor Economics", "Human Resource Studies"],
         "directory_url": "https://www.ilr.cornell.edu/people/faculty",
         "scrape": {"url": "https://www.ilr.cornell.edu/people/faculty",
                    "selectors": _ILR_SELECTORS, "ladder_filter": _LADDER}},
        # ---- College of Agriculture & Life Sciences (static cohorts) -----
        _as("EEB", "Department of Ecology & Evolutionary Biology",
            ["Ecology & Evolutionary Biology"], "ecologyandevolution"),
        _as("NBB", "Department of Neurobiology & Behavior",
            ["Neurobiology & Behavior", "Neuroscience"], "nbb"),
        {"short": "EAS", "name": "Department of Earth & Atmospheric Sciences",
         "majors": ["Earth & Atmospheric Sciences", "Geological Sciences"],
         "directory_url": "https://www.duffield.cornell.edu/eas/faculty-staff/",
         "scrape": {"url": "https://www.duffield.cornell.edu/eas/faculty-staff/",
                    "selectors": _CE_SELECTORS, "ladder_filter": _LADDER}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
