"""Wellesley College faculty config (via the faculty_graph engine).

Wellesley is a top-tier undergraduate liberal arts college for women; its
faculty are the professors/lecturers/instructors an undergraduate would
cold-email for mentored research. The whole academic catalog is one
server-rendered Sitecore site (no WAF, no render mode — ~35 recon fetches all
clean 200s, live-verified 2026-07-21) with a SINGLE shared faculty-card markup
family across every department page.

Family ``wl_card`` — every department lives at
``https://www.wellesley.edu/academics/department/<slug>`` and lists its people
as ``.faculty_related_item`` cards under two h2 sections ("Our faculty" and
"Faculty emeriti"). Each card carries:

* name in ``span.faculty_related_item_title_link_label`` (clean, no BOM);
* the profile link in ``a.faculty_related_item_title_link``
  (→ ``https://www.wellesley.edu/people/<slug>``);
* the rank in ``p.faculty_related_item_position`` (e.g. "Associate Professor
  of Chemistry", "Assistant Teaching Professor in Computer Science",
  "Professor Emerita of Chemistry", "Visiting Assistant Teaching Professor").

Cards are rendered twice in the DOM (desktop + mobile blocks) — the engine's
per-dept url/id dedupe collapses the duplicates. Emeriti share the exact same
card markup but always carry "Emerit" in the position text, so a single
``ladder_filter`` (require professor/lecturer/instructor, drop
emerit/visiting/adjunct) cleanly separates the active teaching-and-research
faculty without needing section gating. Faculty cards have no inline email;
every ``/people/<slug>`` profile carries a plain ``mailto:`` (verified
carumain@wellesley.edu etc.), so the env-gated profile pass backfills email
(shared-inbox aliases dropped). Physical Education, Recreation & Athletics is
deliberately excluded (coaching/athletics staff, not research contacts).

Single source ("wellesley_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred: interdisciplinary program pages (Biochemistry, Data Science,
Cognitive & Linguistic Sciences, Media Arts & Sciences, the area-studies
programs) share the same faculty already captured under their home
departments — folding them in would only add already-deduped names.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.wellesley.edu/academics/department/"

# Active teaching-and-research faculty; emeriti/visiting/adjunct carry those
# markers in the position line and drop out.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|visiting|adjunct",
}

# Shared per-card selectors — identical across all 29 department pages.
_SEL = {
    "card": ".faculty_related_item",
    "name": ".faculty_related_item_title_link_label",
    "link": "a.faculty_related_item_title_link",
    "title": "p.faculty_related_item_position",
}

# Every /people/<slug> profile publishes a plain mailto; drop shared-office
# aliases so one inbox doesn't collapse many professors in dedup.
_EMAIL_DROP = r"^(?:info|contact|office|admin|dept|advising|undergrad|web)@"
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "throttle": 0.2,
}


def _dept(short: str, name: str, slug: str, majors: list[str]) -> dict:
    """A department on the shared Wellesley faculty-card component."""
    url = _BASE + slug
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _SEL,
            "ladder_filter": _LADDER,
            "profile_enrich": _ENRICH,
        },
    }


SCHOOL: dict = {
    "school_slug": "wellesley",
    "source": "wellesley_faculty",
    "organization": "Wellesley College",
    "location": "Wellesley, MA",
    "id_prefix": "wellesley",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Wellesley College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Humanities ----------------------------------------------------
        _dept("AFR", "Department of Africana Studies", "africana-studies",
              ["Africana Studies"]),
        _dept("AMST", "Department of American Studies", "american-studies",
              ["American Studies"]),
        _dept("ART", "Department of Art", "art",
              ["Studio Art", "Art History", "Architecture"]),
        _dept("CLAS", "Department of Classical Studies", "classical-studies",
              ["Classical Studies", "Classical Civilization", "Greek", "Latin"]),
        _dept("EALC", "Department of East Asian Languages and Cultures",
              "east-asian-languages-cultures",
              ["Chinese Language and Culture", "Japanese Language and Culture",
               "East Asian Studies"]),
        _dept("ENG", "Department of English and Creative Writing", "english",
              ["English", "Creative Writing"]),
        _dept("FRIT",
              "Department of French, Francophone, and Italian Studies",
              "french-francophone-and-italian-studies",
              ["French Cultural Studies", "French", "Italian Studies"]),
        _dept("GER", "Department of German", "german", ["German Studies"]),
        _dept("HIST", "Department of History", "history", ["History"]),
        _dept("MUS", "Department of Music", "music", ["Music"]),
        _dept("PHIL", "Department of Philosophy", "philosophy", ["Philosophy"]),
        _dept("REL", "Department of Religious Studies", "religious-studies",
              ["Religion"]),
        _dept("RUSS", "Department of Russian", "russian",
              ["Russian", "Russian Area Studies"]),
        _dept("SPAN", "Department of Spanish and Portuguese", "spanish",
              ["Spanish", "Portuguese"]),
        # ---- Social Sciences -----------------------------------------------
        _dept("ANTH", "Department of Anthropology", "anthropology",
              ["Anthropology"]),
        _dept("ECON", "Department of Economics", "economics", ["Economics"]),
        _dept("EDUC", "Department of Education", "education", ["Education"]),
        _dept("POL", "Department of Political Science", "political-science",
              ["Political Science", "International Relations"]),
        _dept("PSYC", "Department of Psychology", "psychology", ["Psychology"]),
        _dept("SOC", "Department of Sociology", "sociology", ["Sociology"]),
        _dept("WGST", "Department of Women's and Gender Studies",
              "womens-and-gender-studies", ["Women's and Gender Studies"]),
        # ---- Natural Sciences and Mathematics ------------------------------
        _dept("BISC", "Department of Biological Sciences", "biological-sciences",
              ["Biological Sciences", "Biochemistry"]),
        _dept("CHEM", "Department of Chemistry", "chemistry",
              ["Chemistry", "Biochemistry", "Chemical Physics"]),
        _dept("CS", "Department of Computer Science", "computer-science",
              ["Computer Science", "Data Science"]),
        _dept("ES", "Department of Environmental Studies", "environmental-studies",
              ["Environmental Studies"]),
        _dept("GEOS", "Department of Geosciences", "geosciences",
              ["Geosciences"]),
        _dept("MATH", "Department of Mathematics", "mathematics",
              ["Mathematics", "Statistics"]),
        _dept("NEUR", "Department of Neuroscience", "neuroscience",
              ["Neuroscience"]),
        _dept("PHYS", "Department of Physics and Astronomy",
              "physics-and-astronomy",
              ["Physics", "Astronomy", "Astrophysics"]),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
