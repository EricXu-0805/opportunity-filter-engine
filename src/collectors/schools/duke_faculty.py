"""Duke University faculty config (via the faculty_graph engine).

Two directory themes:

* **Pratt School of Engineering** — client-side-rendered department pages sharing
  a rich ``.faculty-overview`` card (name + profile link, public mailto, research
  interests), so records land emailed + keyworded in one render pass.

* **Trinity College of Arts & Sciences** — server-rendered department pages sharing
  a thin ``.member-card`` (a photo + name wrapped in a single ``<a>`` to the
  person's Scholars@Duke profile — no rank, email, or research on the listing).
  Like UCSD's bare link-lists, the record's core fields live on the profile, so a
  per-profile pass runs on every refresh (``always``): it reads the rank from the
  Scholars ``.sub-h1`` and the public email from ``.prof-contact-info``, and the
  ladder gate fires afterward (the ``/people/faculty`` listing mixes in cross-
  appointed emeriti). A ``link_filter`` keeps only Scholars-linked cards, dropping
  the handful of legacy dept-page emeritus links that can't be enriched.

Single source ("duke_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit"}

# Pratt School of Engineering shared theme: an ``article.faculty-overview`` card
# whose name + profile link live in ``.faculty-overview__info h3 a``, the public
# mailto in ``.faculty-overview__email``, and research interests in
# ``.faculty-overview__research``. Client-side rendered -> render mode.
_PRATT = {
    "card": ".faculty-overview",
    "name": ".faculty-overview__info h3 a",
    "link": ".faculty-overview__info h3 a",
    "email": ".faculty-overview__email",
    "research": ".faculty-overview__research",
}


def _pratt(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "render": True, "selectors": _PRATT,
                       "ladder_filter": _LADDER}}


# Trinity College shared theme: ``div.member-card`` = a single ``<a href=
# "scholars.duke.edu/person/..">`` wrapping the photo + a ``.h4`` name heading.
# No rank/email/research on the listing -> the Scholars@Duke profile pass supplies
# them (server-rendered, plain fetch). ``link_filter`` keeps only Scholars-linked
# cards so every kept record is enrichable + ladder-gatable.
_TRINITY = {"card": ".member-card", "name": ".h4", "link": "a"}
_SCHOLARS_ENRICH = {
    "always": True,
    "title_selector": ".sub-h1.font-bold",
    "email_selector": ".prof-contact-info a[href^='mailto:']",
    "ladder_recheck": {"require": r"\bprofessor\b",
                       "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer"},
    "throttle": 0.25,
}


def _trinity(short: str, name: str, majors: list[str], host: str) -> dict:
    url = f"https://{host}.duke.edu/people/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _TRINITY,
                       "link_filter": r"scholars\.duke\.edu/person/",
                       "profile_enrich": _SCHOLARS_ENRICH}}


SCHOOL: dict = {
    "school_slug": "duke",
    "source": "duke_faculty",
    "organization": "Duke University",
    "location": "Durham, NC",
    "id_prefix": "duke",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Duke University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # --- Pratt School of Engineering (render mode, rich cards) ---
        _pratt("ECE", "Department of Electrical & Computer Engineering",
               ["Electrical Engineering", "Computer Engineering"],
               "https://ece.duke.edu/faculty"),
        _pratt("BME", "Department of Biomedical Engineering",
               ["Biomedical Engineering"], "https://bme.duke.edu/faculty"),
        _pratt("MEMS", "Department of Mechanical Engineering & Materials Science",
               ["Mechanical Engineering", "Materials Science"],
               "https://mems.duke.edu/faculty"),
        _pratt("CEE", "Department of Civil & Environmental Engineering",
               ["Civil Engineering", "Environmental Engineering"],
               "https://cee.duke.edu/faculty"),
        # --- Trinity College of Arts & Sciences (Scholars@Duke enrich) ---
        _trinity("BIO", "Department of Biology", ["Biology"], "biology"),
        _trinity("CHEM", "Department of Chemistry", ["Chemistry"], "chem"),
        _trinity("CS", "Department of Computer Science",
                 ["Computer Science"], "cs"),
        _trinity("ECON", "Department of Economics", ["Economics"], "econ"),
        _trinity("MATH", "Department of Mathematics", ["Mathematics"], "math"),
        _trinity("PHYS", "Department of Physics", ["Physics"], "phy"),
        _trinity("POLSCI", "Department of Political Science",
                 ["Political Science"], "polisci"),
        _trinity("PSYNEURO", "Department of Psychology & Neuroscience",
                 ["Psychology", "Neuroscience"], "psychandneuro"),
        _trinity("STAT", "Department of Statistical Science",
                 ["Statistical Science"], "stat"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
