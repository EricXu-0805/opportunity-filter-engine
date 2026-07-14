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

Added in the AWS-WAF render pass (all cornell.edu hosts sit behind an AWS-WAF
JS challenge that 403s a plain ``requests`` fetch but is cleared by a headless
render): seven CALS departments (Entomology, Animal Science, Biological &
Environmental Engineering, SIPS, Food Science, Global Development, Computational
Biology — shared ``expert-card`` grid), the College of Human Ecology (Drupal
role-filtered ``profile-directory-card`` directory), Statistics & Data Science,
and the Jeb E. Brooks School of Public Policy (publicpolicy.cornell.edu, WP
``paged`` directory — brooks.cornell.edu is mail-only).

Still deferred (bespoke source shape — a later pass): the College of
Architecture, Art & Planning (``aap.cornell.edu`` client-side Algolia index —
needs an ``algolia`` source config), and the SC Johnson College of Business /
Dyson (``business.cornell.edu`` directory paginated by a row ``offset`` step,
which the engine's ?param=N pager can't walk); plus the remaining CALS
departments not yet enumerated (Nutritional Sciences, Communication, Natural
Resources, Landscape Architecture, Public & Ecosystem Health — same expert-card
platform, just need their listing paths harvested).
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


# College of Agriculture & Life Sciences — shared Drupal "expert-card" person
# nodes on the CANONICAL cals.cornell.edu host (the per-dept alias subdomains,
# e.g. entomology.cals.cornell.edu, serve a decoy home shell). The whole host is
# behind an AWS-WAF JS challenge that 403s a plain ``requests`` fetch, so these
# render (a headless browser clears the challenge). Email is spamspan-obfuscated
# rather than a mailto, so records ship title-only and emails are recovered by
# the profile / OpenAlex enrichment pass.
_CALS_SELECTORS = {
    "card": ".node--type-person",
    "name": ".expert-card-front a.link",
    "link": ".expert-card-front a.link",
    "title": "p.department",
    "email": "a[href^='mailto:']",
}


def _cals(short: str, name: str, majors: list[str], path: str) -> dict:
    """A CALS department (canonical cals.cornell.edu host, render past AWS-WAF)."""
    url = f"https://cals.cornell.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CALS_SELECTORS, "render": True,
                       "ladder_filter": _LADDER}}


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
        # ---- CALS departments (render past AWS-WAF; expert-card grid) -----
        _cals("ENTOM", "Department of Entomology", ["Entomology"],
              "/entomology/about/people/faculty-adjuncts-emeriti"),
        _cals("ANSCI", "Department of Animal Science", ["Animal Science"],
              "/animal-science/about/people"),
        _cals("BEE", "Department of Biological & Environmental Engineering",
              ["Biological Engineering", "Environmental Engineering"],
              "/biological-environmental-engineering/about/people/faculty"),
        _cals("SIPS", "School of Integrative Plant Science",
              ["Plant Sciences", "Plant Breeding", "Plant Pathology", "Horticulture",
               "Soil & Crop Sciences"],
              "/school-integrative-plant-science/about/people/faculty-senior-academics"),
        _cals("FDSCI", "Department of Food Science", ["Food Science"],
              "/food-science/about/people"),
        _cals("GDEV", "Department of Global Development",
              ["Global Development", "International Agriculture & Rural Development"],
              "/global-development/about/people/faculty"),
        _cals("COMPBIO", "Department of Computational Biology",
              ["Computational Biology", "Bioinformatics"], "/computational-biology/people"),
        # ---- College of Human Ecology (Drupal role-filtered directory) ---
        {"short": "HUMECO", "name": "College of Human Ecology",
         "majors": ["Human Development", "Nutritional Sciences",
                    "Design & Environmental Analysis", "Policy Analysis & Management",
                    "Fiber Science & Apparel Design"],
         "directory_url": "https://human.cornell.edu/people?role%5B%5D=24",
         "scrape": {"url": "https://human.cornell.edu/people?role%5B%5D=24", "render": True,
                    "selectors": {"card": "div.profile-directory-card", "name": "a.name",
                                  "link": "a.name", "title": ".professional-info-name p",
                                  "email": "a.email[href^='mailto:']"},
                    "ladder_filter": {"require": r"professor|lecturer|dean|research|extension|instructor|scholar|fellow",
                                      "drop": r"emerit"}}},
        # ---- Department of Statistics & Data Science (Drupal directory) --
        {"short": "STAT", "name": "Department of Statistics & Data Science",
         "majors": ["Statistics", "Data Science"],
         "directory_url": "https://stat.cornell.edu/directory",
         "scrape": {"url": "https://stat.cornell.edu/directory", "render": True,
                    "selectors": {"card": ".directory-card", "name": ".name a",
                                  "link": ".name a", "title": ".position-titles .field__item",
                                  "email": "a[href^='mailto:']"},
                    "ladder_filter": _LADDER, "paginate": {"param": "page", "max": 4}}},
        # ---- Jeb E. Brooks School of Public Policy (WP directory) --------
        # Host is publicpolicy.cornell.edu (brooks.cornell.edu is mail-only);
        # render past the WAF, WP ``paged`` starts at 2 (base URL is page 1).
        {"short": "BROOKS", "name": "Jeb E. Brooks School of Public Policy",
         "majors": ["Public Policy", "Public Administration", "Health Policy"],
         "directory_url": "https://publicpolicy.cornell.edu/about-us/directory/?roles=full-time-faculty",
         "scrape": {"url": "https://publicpolicy.cornell.edu/about-us/directory/?roles=full-time-faculty",
                    "render": True,
                    "selectors": {"card": ".card.roles-full-time-faculty", "name": ".deco",
                                  "link": ".group-image a", "title": ".professional-title",
                                  "email": "a[href^='mailto:']"},
                    "paginate": {"param": "paged", "start": 2, "max": 8}}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
