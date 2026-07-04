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

Computer Science is added via the engine's ``render: true`` (headless-Chromium)
mode: its directory is a client-side ``.custom_card`` grid that a plain request
can't read, but a real browser renders it — and each card carries the rank plus
per-area research links, so CS lands fully keyworded (108 professors). The same
render mode also clears the Cloudflare wall on the dept subdomains, so more
Princeton departments can be added here as their (heterogeneous) card selectors
are identified.

Single source ("princeton_faculty"); department rides each record's
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

# Princeton "Site Builder" Drupal theme, shared across the (Cloudflare-walled)
# departmental subdomains: each faculty member is a ``.content-list-item`` whose
# name (``.field--name-title``), rank (``field-ps-people-position``), and — where
# published — email (``field-ps-people-email``) use theme-wide field classes.
# Reached via render mode (headless browser clears the 403). Emails land where the
# department exposes them (MAE, CBE, PSY, ASTRO); the rest ship emailless but ranked.
# ``research_items``: several departments file each person under a research
# subfield via the sitewide-category taxonomy (Physics → "Condensed Matter
# Theory"/"High Energy Theory", CEE → its research thrusts). Verified present on
# PHY (47/49) and CEE via headless render; absent on the rest (MAE/PSY/…), where
# the selector simply matches nothing and the record ships ranked-but-keywordless.
_SB_SELECTORS = {
    "card": ".content-list-item",
    "name": ".field--name-title",
    "link": "a[href*='/people/']",
    "title": ".field--name-field-ps-people-position",
    "email": ".field--name-field-ps-people-email a[href^='mailto:']",
    "research_items": ".field--name-field-ps-sitewide-category .field__item",
}


def _drupal(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _PERSON_CARD, "ladder_filter": _LADDER}}


# Site Builder PROFILE pages sit behind the same Cloudflare wall as the listing
# (→ render mode) and carry the fields the listing grid omits: a public mailto
# and, on departments that use it, a research-areas taxonomy. Gated behind
# OFE_ENRICH_PROFILES (render-per-profile is slow — it runs in the deliberate
# enrichment pass, not the weekly refresh); the recovered contact_email/keywords
# then ride the corpus forward via _carry_forward_enrichment. Verified live:
# ECE/Physics profiles expose ``field-ps-people-email`` (absent from their
# listing), and ECE lists ``field-research-areas .field__item`` as clean atomic
# keywords. Only records still missing the field are fetched, so depts that
# already ship emailed/keyworded (MAE/CBE listing emails, PHY/CEE categories)
# cost nothing extra.
_SB_PROFILE_ENRICH = {
    "render": True,
    "email_selector": ".field--name-field-ps-people-email a[href^='mailto:']",
    "research_items_selector": ".field--name-field-research-areas .field__item",
    "throttle": 0.3,
}


def _sb(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Cloudflare-walled Site Builder department, fetched via render mode."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "render": True, "selectors": _SB_SELECTORS,
                       "ladder_filter": _LADDER},
            "profile_enrich": _SB_PROFILE_ENRICH}


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
        # Computer Science: client-side .custom_card grid — needs render mode.
        # Each card exposes the rank (.position) and per-area research links
        # (.research_areas a), so records land keyworded (no email on the listing).
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": "https://www.cs.princeton.edu/people/faculty",
            "scrape": {
                "url": "https://www.cs.princeton.edu/people/faculty",
                "render": True,
                "selectors": {
                    "card": ".custom_card",
                    "name": ".custom_card__heading-link",
                    "link": ".custom_card__heading-link",
                    "title": ".position",
                    "research_items": ".research_areas a",
                },
                "ladder_filter": {"require": r"\bprofessor\b", "drop": r"\bemerit"},
            },
        },
        # Cloudflare-walled Site Builder subdomains (render mode). MAE + CBE
        # publish emails; Physics/EEB/CEE ship ranked-but-emailless.
        _sb("MAE", "Department of Mechanical & Aerospace Engineering",
            ["Mechanical Engineering", "Aerospace Engineering"],
            "https://mae.princeton.edu/people/faculty"),
        _sb("PHY", "Department of Physics", ["Physics"],
            "https://phy.princeton.edu/people/faculty"),
        _sb("EEB", "Department of Ecology & Evolutionary Biology",
            ["Ecology & Evolutionary Biology", "Biology"],
            "https://eeb.princeton.edu/people/faculty"),
        _sb("CBE", "Department of Chemical & Biological Engineering",
            ["Chemical Engineering", "Chemical & Biological Engineering"],
            "https://cbe.princeton.edu/people/faculty"),
        _sb("CEE", "Department of Civil & Environmental Engineering",
            ["Civil Engineering", "Environmental Engineering"],
            "https://cee.princeton.edu/faculty"),
        _sb("ECE", "Department of Electrical & Computer Engineering",
            ["Electrical Engineering", "Computer Engineering"],
            "https://ece.princeton.edu/people/faculty"),
        _sb("PNI", "Princeton Neuroscience Institute", ["Neuroscience"],
            "https://pni.princeton.edu/people/faculty"),
        _sb("PSY", "Department of Psychology", ["Psychology"],
            "https://psych.princeton.edu/people/faculty"),
        _sb("ORFE", "Department of Operations Research & Financial Engineering",
            ["Operations Research", "Financial Engineering"],
            "https://orfe.princeton.edu/people/faculty"),
        _sb("QCB", "Lewis-Sigler Institute for Integrative Genomics",
            ["Quantitative & Computational Biology", "Genomics"],
            "https://lsi.princeton.edu/people/faculty"),
        _sb("ASTRO", "Department of Astrophysical Sciences",
            ["Astrophysical Sciences", "Astronomy"],
            "https://web.astro.princeton.edu/people"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
