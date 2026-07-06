"""Duke University faculty config (via the faculty_graph engine).

Duke's Pratt School of Engineering department directories are client-side
rendered, so they use render mode; each shares a rich ``.faculty-overview`` card
carrying the name + profile link, a public mailto, and a research-interests
block, so records land emailed + keyworded in one pass. Trinity College / CS use
a thinner ``.member-card`` (name + Scholars@Duke link only) and are deferred
until per-profile Scholars enrichment is wired.

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
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
