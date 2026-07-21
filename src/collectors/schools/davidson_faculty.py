"""Davidson College faculty config (via the faculty_graph engine).

Davidson is a top-10 US liberal arts college; it is a single undergraduate
college, so there is no graduate/professional-school sprawl — every academic
department publishes its roster on ONE shared Drupal template at
``davidson.edu/academic-departments/<dept>/faculty-staff``. A single selector
set covers all of them: each person is a ``div.global-spacing--3x.cell`` card
whose name/link is the ``.person-teaser__label a`` (an ``/people/<slug>``
profile), rank is the first ``.person-teaser__info`` list item, the "Primary
Areas of Expertise" list (the card's second ``<ul>``) yields clean atomic
research keywords, and the public email is the ``.person-teaser__contact``
``mailto:``. Emails are inline for essentially every professor, so no
profile-enrichment pass is needed.

Single source ("davidson_faculty"); department rides each record's
``department``, ids namespaced by short-code. Audience "unknown". The
``ladder_filter`` keeps professors/lecturers/instructors and drops emeriti,
visiting appointments, and non-teaching staff (lab managers, coordinators,
technicians — none of whom carry a professorial rank). Interdisciplinary
programs cross-list faculty from their home departments; the engine's
per-school email/url dedup collapses those to one record.

Selectors + counts verified live (curl + bs4) across sciences, humanities,
social sciences and arts on 2026-07-21 (e.g. Biology 19, Mathematics & CS 18,
History 16, Political Science 14, Chemistry 11).

Deferred (no faculty-staff roster page — HTTP 404): Applied Mathematics,
Engineering (dual-degree advising track), and the Structured Independent
Language Program.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.davidson.edu/academic-departments/"

# Shared Davidson department "Faculty & Staff" person-teaser template (static HTML).
_SELECTORS = {
    "card": "div.global-spacing--3x.cell",
    "name": ".person-teaser__label a",
    "link": ".person-teaser__label a",
    "title": ".person-teaser__info ul li",
    "research_items": ".person-teaser__info ul:nth-of-type(2) li",
    "email": ".person-teaser__contact a[href^='mailto:']",
}

# Keep ladder faculty; drop emeriti, visiting appointments, and (via the
# require gate) non-teaching staff whose titles carry no professorial rank.
_LADDER = {"require": r"professor|lecturer|instructor", "drop": r"emerit|visiting"}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty-staff") -> dict:
    """A Davidson academic department on the shared faculty-staff template."""
    url = f"{_BASE}{slug}/{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "davidson",
    "source": "davidson_faculty",
    "organization": "Davidson College",
    "location": "Davidson, NC",
    "id_prefix": "davidson",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Davidson College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Sciences ----------------------------------------------------
        _dept("BIO", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("PHYS", "Department of Physics", ["Physics"], "physics"),
        _dept("MCS", "Department of Mathematics & Computer Science",
              ["Mathematics", "Computer Science"], "mathematics-and-computer-science"),
        _dept("DSCI", "Data Science", ["Data Science"], "data-science"),
        _dept("GENO", "Genomics Program", ["Genomics"], "genomics"),
        _dept("NEUR", "Neuroscience Program", ["Neuroscience"], "neuroscience"),
        _dept("ENVS", "Environmental Studies", ["Environmental Studies"],
              "environmental-studies"),
        _dept("PBH", "Public Health", ["Public Health"], "public-health"),
        _dept("PREM", "Premedicine & Allied Health Professions",
              ["Premedical Studies"], "premedicine-and-allied-health-professions"),
        # ---- Social Sciences ---------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("EDUC", "Educational Studies", ["Educational Studies"],
              "educational-studies"),
        _dept("POLI", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("PPE", "Philosophy, Politics & Economics",
              ["Philosophy, Politics and Economics"],
              "philosophy-politics-and-economics"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("COMM", "Communication Studies", ["Communication Studies"],
              "communication-studies"),
        # ---- Humanities --------------------------------------------------
        _dept("ENGL", "Department of English", ["English"], "english-department"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELS", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies"),
        _dept("CLAS", "Department of Classics", ["Classics"], "classics"),
        _dept("HUM", "Humanities Program", ["Humanities"], "humanities",
              path="faculty-staff-fellows"),
        _dept("WRIT", "Writing Program", ["Writing"], "writing-program"),
        _dept("GLT", "Global Literary Theory", ["Global Literary Theory"],
              "global-literary-theory"),
        _dept("LING", "Linguistics", ["Linguistics"], "linguistics"),
        # ---- Languages & Area Studies ------------------------------------
        _dept("HISP", "Hispanic Studies", ["Hispanic Studies"], "hispanic-studies"),
        _dept("FREN", "French & Francophone Studies",
              ["French and Francophone Studies"], "french-and-francophone-studies"),
        _dept("GERM", "German Studies", ["German Studies"], "german-studies"),
        _dept("RUS", "Russian Studies", ["Russian Studies"], "russian-studies"),
        _dept("CHIN", "Chinese Studies", ["Chinese Studies"], "chinese-studies"),
        _dept("ARB", "Arab Studies", ["Arab Studies"], "arab-studies"),
        _dept("SAS", "South Asian Studies", ["South Asian Studies"],
              "south-asian-studies"),
        _dept("AFR", "Africana Studies", ["Africana Studies"], "africana-studies"),
        _dept("LALC", "Latin American, Latinx & Caribbean Studies",
              ["Latin American Studies"],
              "latin-american-latinx-and-caribbean-studies"),
        _dept("GSS", "Gender & Sexuality Studies",
              ["Gender and Sexuality Studies"], "gender-and-sexuality-studies"),
        # ---- Arts --------------------------------------------------------
        _dept("ART", "Department of Art", ["Art History", "Studio Art"],
              "art-department"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("THTR", "Department of Theatre", ["Theatre"], "theatre"),
        _dept("DANC", "Dance Program", ["Dance"], "dance"),
        _dept("FMS", "Film, Media & Digital Studies",
              ["Film and Media Studies", "Digital Studies"],
              "film-media-and-digital-studies"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
