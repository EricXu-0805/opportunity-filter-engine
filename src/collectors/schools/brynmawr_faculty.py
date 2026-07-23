"""Bryn Mawr College faculty config (via the faculty_graph engine).

Bryn Mawr is a top-tier women's liberal arts college (~1,350 undergraduates)
in the Tri-College Consortium with Haverford and Swarthmore and a Bi-College
partnership with Haverford, plus two graduate schools (the Graduate School of
Arts and Sciences and the Graduate School of Social Work and Social Research).
Its entire public site is one Drupal build, and every academic department
publishes its roster on the same college-wide "people list" directory
component, so ONE selector family covers the whole college — no per-department
bespoke markup.

Live-verified 2026-07-23 (~50 clean 200s, no WAF, no render mode anywhere):

* ``_dept`` — the shared ``directory-teaser-ppllist`` bio card served on every
  department's Faculty & Staff page at
  ``brynmawr.edu/inside/academic-information/departments-programs/<slug>/<path>``.
  Each person is a ``.directory-teaser-ppllist`` card: the name (wrapping the
  ``/inside/people/<slug>`` profile link) is ``.directory-teaser-ppllist__name``,
  the rank is ``.directory-teaser-ppllist__title`` ("Assistant Professor of
  Biology", "Frank B. Mallory Professor of Chemistry", named chairs), the public
  email is a plain (un-obfuscated) mailto under
  ``.directory-teaser-ppllist__contact-email``, and a short prose research blurb
  is ``.directory-teaser-ppllist__focus-content`` ("Population genetics/genomics,
  immunogenetics, molecular evolution, and genomic medicine.") from which
  keywords are derived. Emails are inline for essentially every professor, so no
  profile-enrichment pass is needed.

The Faculty & Staff path is ``faculty-staff`` for most departments; a handful
carry a slug-prefixed variant (``biology-faculty-staff``,
``chemistry-faculty-staff``, ``child-family-studies-faculty-staff``) and two
use a bare ``faculty`` path (Asian American Studies, International Studies) —
each is passed explicitly.

Because these are "Faculty & Staff" pages that also list the interdisciplinary
programs' cross-appointed faculty, each list mixes ladder faculty with lab
coordinators, technicians, staff, emeriti, and visiting appointments. The
``ladder_filter`` keeps only professorial + lecturer ranks and drops emeriti,
visiting, and adjunct appointments plus the non-teaching staff whose titles
carry neither "professor" nor "lecturer". Bryn Mawr professors are heavily
cross-listed across the interdisciplinary programs and their home department
(e.g. a Biology professor also under Health Studies, Gender & Sexuality
Studies, or Neuroscience); core departments are listed FIRST so the engine's
per-school email/url dedup collapses the cross-listings onto a home department.

Single source ("brynmawr_faculty"); department rides each record, ids
namespaced by department short-code. Audience "unknown".

Deferred (2026-07-23 recon): Computer Science, Environmental Studies, and East
Asian Languages & Cultures publish an older hand-authored people layout (plain
headings/lists, not the shared directory component) so they yield no cards from
this selector family; Dance's faculty page 404s and Linguistics' program page
carries no ladder faculty (cross-listed only). Computer Science overlaps the
captured Data Science department. Revisit if those pages migrate to the shared
component.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.brynmawr.edu/inside/academic-information/departments-programs"

# Person card on the shared Bryn Mawr Drupal "people list" directory component.
_SELECTORS = {
    "card": ".directory-teaser-ppllist",
    "name": ".directory-teaser-ppllist__name",
    "link": ".directory-teaser-ppllist__name a",
    "title": ".directory-teaser-ppllist__title",
    "research": ".directory-teaser-ppllist__focus-content",
    "email": ".directory-teaser-ppllist__contact-email a[href^='mailto:']",
}

# Keep professorial + lecturer ranks; drop emeriti, visiting, and adjunct
# appointments as well as the staff (lab coordinator/technician/manager) whose
# titles carry neither "professor" nor "lecturer".
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty-staff") -> dict:
    """A department on the shared directory-teaser-ppllist Faculty & Staff template."""
    url = f"{_BASE}/{slug}/{path}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "brynmawr",
    "source": "brynmawr_faculty",
    "organization": "Bryn Mawr College",
    "location": "Bryn Mawr, PA",
    "id_prefix": "brynmawr",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Bryn Mawr College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics ------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology",
              path="biology-faculty-staff"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry",
              path="chemistry-faculty-staff"),
        _dept("BMB", "Biochemistry and Molecular Biology Program",
              ["Biochemistry", "Molecular Biology"], "biochemistry-molecular-biology"),
        _dept("PHYS", "Department of Physics", ["Physics"], "physics"),
        _dept("GEOL", "Department of Geology", ["Geology"], "geology"),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], "mathematics"),
        _dept("DSCI", "Data Science Program", ["Data Science"], "data-science"),
        _dept("NEUR", "Neuroscience Program", ["Neuroscience"], "neuroscience"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        # ---- Social Sciences ---------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("EDUC", "Department of Education", ["Education"], "education"),
        _dept("POLS", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("CITY", "Growth and Structure of Cities Program",
              ["Growth and Structure of Cities", "Urban Studies"],
              "growth-structure-cities"),
        _dept("INTL", "International Studies Program", ["International Studies"],
              "international-studies", path="faculty"),
        _dept("HLTH", "Health Studies Program", ["Health Studies"], "health-studies"),
        _dept("CFS", "Child and Family Studies Program",
              ["Child and Family Studies"], "child-family-studies",
              path="child-family-studies-faculty-staff"),
        # ---- Humanities --------------------------------------------------
        _dept("ENGL", "Department of Literatures in English",
              ["Literatures in English", "English"], "literatures-english"),
        _dept("CRWR", "Creative Writing Program", ["Creative Writing"],
              "creative-writing"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("HART", "Department of History of Art", ["History of Art"],
              "history-art"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("CLNE", "Department of Classical and Near Eastern Archaeology",
              ["Classical and Near Eastern Archaeology", "Archaeology"],
              "classical-near-eastern-archaeology"),
        _dept("GLCS", "Department of Greek, Latin, and Classical Studies",
              ["Greek", "Latin", "Classical Studies"],
              "greek-latin-classical-studies"),
        _dept("CMPL", "Comparative Literature Program", ["Comparative Literature"],
              "comparative-literature"),
        _dept("MUSE", "Museum Studies Program", ["Museum Studies"], "museum-studies"),
        # ---- Languages & Area / Interdisciplinary Studies ----------------
        _dept("FREN", "Department of French and Francophone Studies",
              ["French and Francophone Studies"], "french-francophone-studies"),
        _dept("GERM", "Department of German and German Studies",
              ["German", "German Studies"], "german-studies"),
        _dept("RUSS", "Department of Russian", ["Russian"], "russian"),
        _dept("SPAN", "Department of Spanish", ["Spanish"], "spanish"),
        _dept("ROML", "Romance Languages Program", ["Romance Languages"],
              "romance-languages"),
        _dept("ITAL", "Transnational Italian Studies Program",
              ["Italian", "Transnational Italian Studies"],
              "transnational-italian-studies"),
        _dept("ARAB", "Arabic Program", ["Arabic"], "arabic"),
        _dept("AFRC", "Africana Studies Program", ["Africana Studies"],
              "africana-studies"),
        _dept("AAST", "Asian American Studies Program", ["Asian American Studies"],
              "asian-american-studies", path="faculty"),
        _dept("LAIL", "Latin American, Iberian, and Latina/o Studies Program",
              ["Latin American Studies", "Iberian Studies"],
              "latin-american-iberian-latinao-studies"),
        _dept("MECA",
              "Middle Eastern, Central Asian, and North African Studies Program",
              ["Middle Eastern Studies"],
              "middle-eastern-central-asian-north-african-studies"),
        _dept("HEBJ", "Hebrew and Judaic Studies Program",
              ["Hebrew and Judaic Studies"], "hebrew-judaic-studies"),
        _dept("GSST", "Gender and Sexuality Studies Program",
              ["Gender and Sexuality Studies"], "gender-sexuality-studies"),
        _dept("PCSJ",
              "Peace, Conflict, and Social Justice Studies Program",
              ["Peace, Conflict, and Social Justice Studies"],
              "peace-conflict-social-justice-studies"),
        # ---- Arts --------------------------------------------------------
        _dept("FILM", "Film Studies Program", ["Film Studies"], "film-studies"),
        _dept("THEA", "Theater Program", ["Theater"], "theater"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
