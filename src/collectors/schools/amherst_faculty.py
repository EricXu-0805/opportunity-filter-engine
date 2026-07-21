"""Amherst College faculty config (via the faculty_graph engine).

Amherst is a top-10 US liberal arts college (~1,800 undergraduates, no
graduate school). Every academic department publishes a "Faculty & Staff"
page on the same college-wide Drupal template at
``amherst.edu/academiclife/departments/<slug>/faculty`` — there is NO single
college-wide people directory (``/people/faculty`` 404s), but every dept page
shares ONE markup family, so a single scrape source with per-dept URLs covers
the whole college. Live-verified 2026-07-21 (all plain HTTP 200s, no WAF, no
render mode).

Markup family (``amherst_dir``): each person is a
``div.faculty_listing_small`` card — ``h4.faculty_listing_small_name a`` is
the name + profile link (``/people/facstaff/<slug>``), and
``p.faculty_listing_title`` carries the rank ("Assistant Professor of
Biology", "Senior Lecturer in Mathematics", named chairs like "Ford Family
Professor of Biology"). Emails are image-obfuscated on both the listing and
the profile pages (only a shared ``info@amherst.edu`` decoy is exposed), so
no email is captured — records carry the profile URL as the contact path.

Because these are "Faculty & Staff" pages, each list mixes teaching faculty
with lab instructors, coordinators, technicians, and department staff (whose
titles carry no "professor"/"lecturer"), plus emeriti and visiting/postdoc
appointments. The ladder filter keeps only professorial + lecturer ranks and
drops emeriti/visiting/postdoc/adjunct. Amherst professors are frequently
cross-listed across an interdisciplinary program and their home department
(e.g. a Biology professor also under Environmental Studies or Neuroscience);
the engine's per-school URL dedupe collapses these to a single record, so the
core departments are listed FIRST and the interdisciplinary programs after,
letting each professor attribute to a home department where possible.

Profiles carry a plain-prose "Research Interests" block (``h3`` + following
``<p>``); an env-gated profile pass backfills research areas from it (off in
CI/weekly refresh, so no keywords are inferred by default — topics come from
OpenAlex).

Single source ("amherst_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred: Mathematics uses the slug ``mathematics`` (the ``mathematics_statistics``
alias 403s); Physics & Astronomy is served under both ``physics`` and
``astronomy`` (identical page) — ``physics`` is used once. No render mode
anywhere.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.amherst.edu/academiclife/departments"

# Person card on the shared Amherst Drupal "Faculty & Staff" template.
_SELECTORS = {
    "card": "div.faculty_listing_small",
    "name": "h4.faculty_listing_small_name a",
    "link": "h4.faculty_listing_small_name a",
    "title": "p.faculty_listing_title",
}

# Keep professorial + lecturer ranks; drop emeriti, visiting, postdoc, and
# adjunct appointments as well as the staff (lab instructor/coordinator/
# technician/manager) whose titles carry neither "professor" nor "lecturer".
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": r"emerit|\bvisiting\b|postdoc|\badjunct\b",
}

# Profiles carry a prose "Research Interests" block. Env-gated (OFF in CI /
# weekly refresh); when the deliberate local enrichment run turns it on it
# backfills research areas for keyword derivation.
_ENRICH = {
    "research_selector": 'h3:-soup-contains("Research Interests") + p',
    "throttle": 0.2,
}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A department on the shared amherst_dir Faculty & Staff template."""
    url = f"{_BASE}/{slug}/faculty"
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
    "school_slug": "amherst",
    "source": "amherst_faculty",
    "organization": "Amherst College",
    "location": "Amherst, MA",
    "id_prefix": "amherst",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Amherst College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Core academic departments (listed first so cross-listed
        #      professors attribute to a home department) -------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "Biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("COSC", "Department of Computer Science", ["Computer Science"],
              "computer_science"),
        _dept("MATH", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "mathematics"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics"),
        _dept("GEOL", "Department of Geology", ["Geology"], "geology"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("ANTH", "Department of Anthropology and Sociology",
              ["Anthropology", "Sociology"], "anthropology_sociology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("POSC", "Department of Political Science", ["Political Science"],
              "political_science"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELI", "Department of Religion", ["Religion"], "religion"),
        _dept("ENGL", "Department of English",
              ["English", "Creative Writing"], "english"),
        _dept("CLAS", "Department of Classics", ["Classics"], "classics"),
        _dept("FREN", "Department of French", ["French"], "french"),
        _dept("GERM", "Department of German", ["German"], "german"),
        _dept("RUSS", "Department of Russian", ["Russian"], "russian"),
        _dept("SPAN", "Department of Spanish", ["Spanish"], "spanish"),
        _dept("ASLC", "Department of Asian Languages and Civilizations",
              ["Asian Languages and Civilizations"], "asian"),
        _dept("ARHA", "Department of Art and the History of Art",
              ["Art", "History of Art"], "art"),
        _dept("MUSI", "Department of Music", ["Music"], "music"),
        _dept("THDA", "Department of Theater and Dance",
              ["Theater and Dance"], "theater_dance"),
        # ---- Interdisciplinary programs / departments --------------------
        _dept("AMST", "Department of American Studies",
              ["American Studies"], "american_studies"),
        _dept("BLST", "Department of Black Studies", ["Black Studies"],
              "black_studies"),
        _dept("ENST", "Department of Environmental Studies",
              ["Environmental Studies"], "environmental_studies"),
        _dept("EUST", "Program in European Studies", ["European Studies"],
              "european_studies"),
        _dept("FAMS", "Program in Film and Media Studies",
              ["Film and Media Studies"], "film"),
        _dept("LJST", "Department of Law, Jurisprudence, and Social Thought",
              ["Law, Jurisprudence, and Social Thought"], "ljst"),
        _dept("NEUR", "Program in Neuroscience", ["Neuroscience"],
              "neuroscience"),
        _dept("SWAG",
              "Department of Sexuality, Women's and Gender Studies",
              ["Sexuality, Women's and Gender Studies"],
              "sexuality_womens_gender_studies"),
        _dept("AAPI",
              "Program in Asian American and Pacific Islander Studies",
              ["Asian American and Pacific Islander Studies"], "aapi"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
