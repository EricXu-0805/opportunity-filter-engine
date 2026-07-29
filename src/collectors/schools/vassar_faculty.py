"""Vassar College faculty config (via the faculty_graph engine).

Vassar is a highly selective US liberal arts college (~2,400 undergraduates,
no graduate/professional schools) in Poughkeepsie, NY, known for strong
sciences (the URSI summer-research institute), arts, and humanities. The whole
public site is ONE Drupal 11 build (``www.vassar.edu``), and every academic
department renders its roster with the same college-wide ``faculty_list`` view
component, so a single selector family covers the entire college — no per-dept
bespoke markup (music excepted, see Deferred).

Live-verified 2026-07-23 (curl + bs4, all clean HTTP 200s, no WAF, no render
mode anywhere):

* Card family (``vassar_dept``) — each active professor is a Drupal node
  teaser ``article.node--type-faculty.node--view-mode-teaser``. The name +
  profile link is the ``span.field--name-title a`` (a ``/faculty/<slug>``
  page), and the rank is the ``div.faculty-title`` text ("Professor of
  Biology", "Associate Professor and Chair of Chemistry", "Lecturer in
  Biology", "Visiting Assistant Professor of Computer Science"). Emeriti render
  under a SEPARATE node type ``.node--type-faculty-emeriti`` that the card
  selector does not match, so retired faculty are excluded structurally (the
  ``drop: emerit`` gate is belt-and-suspenders). There is no email on the
  listing card — the public ``mailto:`` lives on each ``/faculty/<slug>``
  profile page, so an env-gated ``profile_enrich`` pass (OFF in CI / weekly
  refresh) backfills it on the deliberate one-shot local enrichment run; until
  then each record carries the profile URL as the contact path.

The department faculty page is ``/<dept>/faculty`` for most departments and
``/<dept>/faculty-staff`` for four (Biology, Dance, Drama, Earth Science &
Geography); each entry records the verified path.

Cross-listing: Vassar's interdisciplinary programs (Environmental Studies,
Women/Feminist/Queer Studies, Urban Studies, Africana Studies, Media Studies,
Asian Studies, Science-Technology-and-Society, Latin American & Latinx
Studies, etc.) re-list faculty whose tenure home is a core department, and each
professor has one canonical ``/faculty/<slug>`` profile URL. The core academic
departments are therefore listed FIRST so the engine's per-school url/email
dedup attributes each professor to a home department, and the interdisciplinary
programs follow (they contribute only the handful of faculty whose primary
appointment is the program itself).

Single source ("vassar_faculty"); department rides each record, ids namespaced
by department short-code. The ladder gate keeps professorial / lecturer /
instructor ranks and drops emeriti, visiting, and adjunct appointments plus the
non-teaching staff (coordinators, technicians, administrative deans) whose
titles carry no professorial rank.

Deferred (2026-07-23 recon):
* Music — its ``/music/faculty`` page uses a DIFFERENT markup family
  (``.field--name-field-display-title`` name cells, no ``.node--type-faculty``
  wrapper) dominated by applied-performance instructors rather than research
  faculty; it needs its own selector variant and is left for a follow-up.
* Athletics & Physical Education and the self-designed Independent Program —
  not research-faculty departments.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.vassar.edu"

# Shared college-wide Drupal faculty_list person-teaser card (static HTML).
_SELECTORS = {
    "card": "article.node--type-faculty.node--view-mode-teaser",
    "name": "span.field--name-title a",
    "link": "span.field--name-title a",
    "title": "div.faculty-title",
}

# Keep professorial / lecturer / instructor ranks; drop emeriti (also a
# separate node type), visiting, and adjunct appointments, plus staff whose
# titles carry no professorial rank.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}

# Public email lives only on the /faculty/<slug> profile page. Env-gated
# (OFF in CI / weekly refresh); backfilled on the deliberate local enrichment
# run and by the PI email enricher.
_ENRICH = {"email_selector": "a[href^='mailto:']", "throttle": 0.2,
           # Profile carries a "field-faculty-interests" Drupal field — a
           # semicolon-delimited interest line; rides the existing (env-gated)
           # per-profile pass.
           "research_html_re": r'field--name-field-faculty-interests[^>]*>(.*?)</div>'}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty") -> dict:
    """A Vassar department on the shared faculty_list card family."""
    url = f"{_BASE}/{slug}/{path}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _SELECTORS,
            "ladder_filter": _LADDER,
            "profile_enrich": _ENRICH,
        },
    }


SCHOOL: dict = {
    "school_slug": "vassar",
    "source": "vassar_faculty",
    "organization": "Vassar College",
    "location": "Poughkeepsie, NY",
    "id_prefix": "vassar",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Vassar College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics (home departments first) -------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology",
              path="faculty-staff"),
        _dept("BIOCHEM", "Program in Biochemistry", ["Biochemistry"],
              "biochemistry"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("CMPU", "Department of Computer Science", ["Computer Science"],
              "computerscience"),
        _dept("ESGE", "Department of Earth Science and Geography",
              ["Earth Science", "Geography"], "earth-science-and-geography",
              path="faculty-staff"),
        _dept("MATH", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "math"),
        _dept("NEUR", "Program in Neuroscience and Behavior",
              ["Neuroscience and Behavior"], "neuroscience-and-behavior"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics-and-astronomy"),
        # ---- Social Sciences ----------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),
        _dept("COGS", "Program in Cognitive Science", ["Cognitive Science"],
              "cognitive-science"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("EDUC", "Department of Education", ["Education"], "education"),
        _dept("POLI", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology"),
        # ---- Humanities ---------------------------------------------------
        _dept("ENGL", "Department of English",
              ["English", "Creative Writing"], "english"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELI", "Department of Religion", ["Religion"], "religion"),
        _dept("GRST", "Department of Greek and Roman Studies",
              ["Greek and Roman Studies"], "greek-and-roman-studies"),
        # ---- Languages & Literatures --------------------------------------
        _dept("FREN", "Department of French and Francophone Studies",
              ["French and Francophone Studies"], "french"),
        _dept("GERM", "Department of German Studies", ["German Studies"],
              "german"),
        _dept("ITAL", "Department of Italian", ["Italian"], "italian"),
        _dept("RUSS", "Department of Russian Studies", ["Russian Studies"],
              "russian"),
        _dept("HISP", "Department of Hispanic Studies", ["Hispanic Studies"],
              "hispanic-studies"),
        _dept("CHJA", "Department of Chinese and Japanese",
              ["Chinese", "Japanese"], "chinese-japanese"),
        # ---- Arts ---------------------------------------------------------
        _dept("ART", "Department of Art", ["Art History", "Studio Art"], "art"),
        _dept("DANC", "Department of Dance", ["Dance"], "dance",
              path="faculty-staff"),
        _dept("DRAM", "Department of Drama", ["Drama"], "drama",
              path="faculty-staff"),
        _dept("FILM", "Department of Film", ["Film"], "film"),
        # ---- Interdisciplinary & multidisciplinary programs ---------------
        _dept("AFRS", "Program in Africana Studies", ["Africana Studies"],
              "africana-studies"),
        _dept("AMNA",
              "Program in American and Native American Studies",
              ["American Studies", "Native American Studies"],
              "american-and-native-american-studies"),
        _dept("ASIA", "Program in Asian Studies", ["Asian Studies"],
              "asian-studies"),
        _dept("ENST", "Program in Environmental Studies",
              ["Environmental Studies"], "environmental-studies"),
        _dept("GNCS", "Program in Global Nineteenth-Century Studies",
              ["Global Nineteenth-Century Studies"],
              "global-nineteenth-century-studies"),
        _dept("INTL", "Program in International Studies",
              ["International Studies"], "internationalstudies"),
        _dept("JWST", "Program in Jewish Studies", ["Jewish Studies"],
              "jewish-studies"),
        _dept("LALS",
              "Program in Latin American and Latinx Studies",
              ["Latin American and Latinx Studies"], "latinamericanstudies"),
        _dept("MEDS", "Program in Media Studies", ["Media Studies"],
              "mediastudies"),
        _dept("MRST",
              "Program in Medieval and Renaissance Studies",
              ["Medieval and Renaissance Studies"],
              "medieval-and-renaissance-studies"),
        _dept("STS",
              "Program in Science, Technology, and Society",
              ["Science, Technology, and Society"],
              "science-technology-and-society"),
        _dept("URBS", "Program in Urban Studies", ["Urban Studies"],
              "urban-studies"),
        _dept("WFQS",
              "Program in Women, Feminist, and Queer Studies",
              ["Women, Feminist, and Queer Studies"],
              "women-feminist-and-queer-studies"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
