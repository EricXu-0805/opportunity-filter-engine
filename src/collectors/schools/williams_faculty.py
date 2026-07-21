"""Williams College faculty config (via the faculty_graph engine).

Williams (elite liberal-arts college #1) runs its whole public site on one
WordPress instance behind Cloudflare. Every academic department lives at
``www.williams.edu/academics/<slug>/`` and exposes a ``/faculty-staff/`` page
that embeds ONE shared "profile listing" web component
(``div.cc--profile-listing``, ``data-endpoint="/wp-json/williams/v1/profiles/list"``)
scoped to that department via ``data-departments="[<id>]"``. The component
fetches its roster over XHR and server-renders identical person cards:

    div.card.card-person
      .f--eyebrow span            -> department(s) the person is listed under
      .f--cta-title h3 a          -> name + /profile/<slug>/ link
      .f--description             -> rank ("Associate Professor of Computer Science")
      .contact-item.email span    -> public @williams.edu address (plain text)

ONE selector set covers all departments — only the department slug differs.
Because both the Cloudflare interstitial AND the roster XHR are client-side,
the pages are JS-only: ``render: True`` (headless Chromium) is mandatory; the
engine waits for the ``div.card.card-person`` cards to appear. Cloudflare is
per-request flaky from datacenter IPs, so the weekly refresh re-runs the shard
(the engine already retries each render up to 3x).

A single ladder filter keeps professorial/lecturer/artist ranks and drops the
support staff (administrative assistants, systems administrators, lab
coordinators) that share each ``/faculty-staff/`` page, plus visiting/adjunct;
emeriti are dropped unconditionally by the engine's ``_RETIRED_TITLE_RE``.
Cross-listed faculty (e.g. a CS professor also under Science & Technology
Studies) are de-duplicated school-wide by contact email.

Single source ("williams_faculty"); department rides each record's
``department``, ids namespaced by short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Williams profile-listing card (rendered by the WP web component).
_SEL = {
    "card": "div.card.card-person",
    "name": ".f--cta-title h3 a",
    "link": ".f--cta-title h3 a",
    "title": ".f--description",
    "email": ".contact-item.email span",
}

# Keep ladder + lecturer + performance (artist) faculty; drop visiting/adjunct.
# Support staff on the same page carry non-teaching titles (Administrative
# Assistant, Systems Administrator, Lab Coordinator) that match neither
# require alternative, so they are dropped. Emeriti fall to the engine's
# unconditional retired-title drop.
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b|\bartist\b",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}


def _dept(short: str, name: str, slug: str, majors: list[str]) -> dict:
    """An academic department at www.williams.edu/academics/<slug>/faculty-staff/."""
    url = f"https://www.williams.edu/academics/{slug}/faculty-staff/"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "render": True,
            "render_settle": 6000,
            "selectors": _SEL,
            "ladder_filter": _LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "williams",
    "source": "williams_faculty",
    "organization": "Williams College",
    "location": "Williamstown, MA",
    "id_prefix": "williams",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Williams College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Division III: Science & Mathematics -------------------------
        _dept("ASTR", "Department of Astronomy", "astronomy", ["Astronomy", "Astrophysics"]),
        _dept("BIOL", "Department of Biology", "biology", ["Biology"]),
        _dept("CHEM", "Department of Chemistry", "chemistry", ["Chemistry"]),
        _dept("CSCI", "Department of Computer Science", "computer-science", ["Computer Science"]),
        _dept("GEOS", "Department of Geosciences", "geosciences", ["Geosciences"]),
        _dept("MATH", "Department of Mathematics", "mathematics", ["Mathematics"]),
        _dept("STAT", "Department of Statistics", "statistics", ["Statistics"]),
        _dept("PHYS", "Department of Physics", "physics", ["Physics"]),
        _dept("NSCI", "Program in Neuroscience", "neuroscience", ["Neuroscience"]),
        _dept("PSYC", "Department of Psychology", "psychology", ["Psychology"]),
        # ---- Division II: Social Sciences --------------------------------
        _dept("ANSO", "Department of Anthropology & Sociology", "anthropology-sociology",
              ["Anthropology", "Sociology"]),
        _dept("ECON", "Department of Economics", "economics", ["Economics"]),
        _dept("HIST", "Department of History", "history", ["History"]),
        _dept("PSCI", "Department of Political Science", "political-science", ["Political Science"]),
        _dept("ENVI", "Center for Environmental Studies", "environmental-studies",
              ["Environmental Studies"]),
        # ---- Division I: Humanities --------------------------------------
        _dept("ARAB", "Program in Arabic Studies", "arabic-studies", ["Arabic Studies"]),
        _dept("CLAS", "Department of Classics", "classics", ["Classics", "Greek", "Latin"]),
        _dept("COMP", "Program in Comparative Literature", "comparative-literature",
              ["Comparative Literature"]),
        _dept("ENGL", "Department of English", "english", ["English"]),
        _dept("CHIN", "Chinese", "chinese", ["Chinese"]),
        _dept("JAPN", "Japanese", "japanese", ["Japanese"]),
        _dept("FREN", "French", "french", ["French"]),
        _dept("GERM", "German", "german", ["German"]),
        _dept("RUSS", "Russian", "russian", ["Russian"]),
        _dept("SPAN", "Spanish", "spanish", ["Spanish"]),
        _dept("PHIL", "Department of Philosophy", "philosophy", ["Philosophy"]),
        _dept("RELG", "Department of Religion", "religion", ["Religion"]),
        _dept("STS", "Program in Science & Technology Studies", "science-technology-studies",
              ["Science & Technology Studies"]),
        # ---- Division I: Arts --------------------------------------------
        _dept("ARTH", "Department of Art (History & Studio)", "art-history-and-studio-art",
              ["Art History", "Studio Art"]),
        _dept("MUS", "Department of Music", "music", ["Music"]),
        _dept("THEA", "Department of Theatre", "theatre", ["Theatre"]),
        _dept("DANC", "Program in Dance", "dance", ["Dance"]),
        # ---- Interdisciplinary programs ----------------------------------
        _dept("AFR", "Africana Studies", "africana-studies", ["Africana Studies"]),
        _dept("AMST", "Program in American Studies", "american-studies", ["American Studies"]),
        _dept("ASST", "Program in Asian Studies", "asian-studies", ["Asian Studies"]),
        _dept("WGSS", "Women's, Gender & Sexuality Studies", "wgss",
              ["Women's, Gender and Sexuality Studies"]),
        _dept("COGS", "Program in Cognitive Science", "cognitive-science", ["Cognitive Science"]),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
