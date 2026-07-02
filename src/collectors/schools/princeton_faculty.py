"""Princeton University faculty config (via the faculty_graph engine).

Princeton is heavily Cloudflare-walled: nearly every departmental subdomain
(``phy.``, ``mae.``, ``ece.``, ``molbio.``, ``orfe.``, ``eeb.``, ``psych.``,
``cbe.``, ``cee.``, ``pni.`` …) returns 403 to a non-browser client, and the CS
directory is client-side rendered (its cards never appear in the server HTML).
The departments hosted on the central Drupal platform under ``www.*.princeton.edu``
ARE reachable, and expose a clean ``.person-card`` grid.

Currently that means **Mathematics** (``www.math.princeton.edu``), a Drupal
"Views" grid filtered to the faculty position: each ``.person-card`` carries the
name (``.person-card__name``), the rank (``.person-card__title``), and a
``/people/<slug>`` profile link. No email or research area is on the listing, so
records ship "lite" (contact_email=None); per-profile enrichment is deferred.

More Princeton departments will be added here as reachable directories are found
(the Cloudflare-walled subdomains need a browser-context fetch this engine does
not yet do). Single source ("princeton_faculty"); department rides each record's
``department``, ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Princeton central-Drupal "person-card" grid (name + rank + profile link only).
_PERSON_CARD = {
    "card": ".person-card",
    "name": ".person-card__name",
    "link": ".person-card__image-link",
    "title": ".person-card__title",
}


# Keep ladder faculty (the PIs an undergraduate would do research with); the
# grid also lists postdocs, instructors, lecturers, and visiting scholars.
# "professor" matches Professor / Assistant Professor / Associate Professor /
# "… with Rank of Professor" / "Chair, Professor".
_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit"}


def _drupal(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _PERSON_CARD, "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "princeton",
    "source": "princeton_faculty",
    "organization": "Princeton University",
    "location": "Princeton, NJ",
    "id_prefix": "princeton",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Princeton University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _drupal(
            "MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"],
            "https://www.math.princeton.edu/people?combine=&field_position_target_id=115",
        ),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
