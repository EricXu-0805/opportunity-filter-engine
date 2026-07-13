"""Rice University faculty config (via the faculty_graph engine).

Rice runs every department site on one shared Drupal 10 platform (theme
``adm_rice``). Faculty rosters are NOT in the server HTML — each page ships an
empty ``<div class="js-profiles" data-tags="...">`` shell that a shared theme
script fills client-side from ONE central JSON endpoint:

    GET https://web-api2.rice.edu/profiles/search?tag=<TAGS>&netid=
    -> {"data": [{fname, lname, title, profile_url, img_url}, ...]}

The theme comma-joins each page's ``data-tags`` (``"Faculty, Computer Science"``
-> ``tag=Faculty,Computer Science``). So one engine source — the ``json_dir``
live-endpoint fetch with ``name_fields=[fname,lname]`` — covers the whole
university; only the per-department ``tag`` differs. Each dept's exact
``data-tags`` was harvested from its live page and the resulting API count
verified (e.g. CS 46, Physics 52, Economics 33). No email/keywords in the
listing JSON; the profile page (profiles.rice.edu/faculty/<slug>) carries them,
recovered later by the profile-enrichment pass.

Single source ("rice_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

Deferred (same platform, resolve later): ECE / Psychological Sciences / Modern
& Classical Languages (rate-limited 406 at harvest time), Earth-Environmental-
Planetary (roster on a sub-path, no js-profiles on landing), Kinesiology / Sport
Mgmt / Art / Art History / Asian Studies (tag unresolved), Shepherd Music
(bespoke authored page), Architecture (the one static-HTML outlier — separate
``scrape`` config, div.faculty-member).
"""

from __future__ import annotations

from urllib.parse import quote

from .. import faculty_graph

_API = "https://web-api2.rice.edu/profiles/search"


def _rice(short: str, name: str, majors: list[str], directory_url: str, data_tags: str) -> dict:
    """A Rice department served by the shared web-api2 profiles endpoint.

    ``data_tags`` is the verbatim ``data-tags`` attribute from the dept's live
    faculty page; the theme comma-joins it into the API ``tag`` param.
    """
    tag = ",".join(part.strip() for part in data_tags.split(","))
    url = f"{_API}?tag={quote(tag)}&netid="
    return {"short": short, "name": name, "majors": majors, "directory_url": directory_url,
            "json_dir": {"url": url, "records_key": "data",
                         "name_fields": ["fname", "lname"],
                         "title_field": "title", "link_field": "profile_url"}}


SCHOOL: dict = {
    "school_slug": "rice",
    "source": "rice_faculty",
    "organization": "Rice University",
    "location": "Houston, TX",
    "id_prefix": "rice",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Rice University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- George R. Brown School of Engineering & Computing -----------
        _rice("CS", "Department of Computer Science", ["Computer Science"],
              "https://csweb.rice.edu/people/faculty", "Faculty, Computer Science"),
        _rice("MECH", "Department of Mechanical Engineering", ["Mechanical Engineering"],
              "https://mech.rice.edu/people/faculty", "MECH - Faculty"),
        _rice("BIOE", "Department of Bioengineering", ["Bioengineering"],
              "https://bioengineering.rice.edu/people/faculty", "Bioengineering, Faculty"),
        _rice("CHBE", "Department of Chemical & Biomolecular Engineering",
              ["Chemical Engineering", "Biomolecular Engineering"],
              "https://chbe.rice.edu/people/faculty",
              "Chemical and Biomolecular Engineering, Faculty"),
        _rice("CEE", "Department of Civil & Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://cee.rice.edu/people/faculty", "Faculty, Civil and Environmental Engineering"),
        _rice("CMOR", "Computational Applied Mathematics & Operations Research",
              ["Computational & Applied Mathematics", "Operations Research"],
              "https://cmor.rice.edu/people/faculty", "CMOR - Faculty"),
        _rice("MSNE", "Department of Materials Science & Nanoengineering",
              ["Materials Science & NanoEngineering"],
              "https://msne.rice.edu/people/faculty",
              "Materials Science and Nanoengineering, Tenured"),
        _rice("STAT", "Department of Statistics", ["Statistics"],
              "https://statistics.rice.edu/people/faculty", "Statistics, Faculty"),
        # ---- Wiess School of Natural Sciences ----------------------------
        _rice("PHYA", "Department of Physics & Astronomy", ["Physics", "Astronomy"],
              "https://physics.rice.edu/core-faculty", "PHYA Core Faculty"),
        _rice("CHEM", "Department of Chemistry", ["Chemistry"],
              "https://chemistry.rice.edu/people/core-faculty", "chemistry, core faculty"),
        _rice("MATH", "Department of Mathematics", ["Mathematics"],
              "https://math.rice.edu/faculty", "mathematics, Faculty, Core Faculty"),
        _rice("BIOS", "Department of BioSciences", ["Biosciences", "Biology", "Ecology"],
              "https://biosciences.rice.edu/tenure-track-faculty", "Tenured faculty, Biosciences"),
        # ---- School of Social Sciences -----------------------------------
        _rice("ECON", "Department of Economics", ["Economics"],
              "https://economics.rice.edu/faculty", "Economics, Faculty"),
        _rice("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.rice.edu/faculty", "Anthropology, Faculty"),
        _rice("LING", "Department of Linguistics", ["Linguistics"],
              "https://linguistics.rice.edu/faculty", "Linguistics, Faculty"),
        _rice("POLI", "Department of Political Science", ["Political Science"],
              "https://politicalscience.rice.edu/faculty", "Political Science, Faculty"),
        _rice("SOCI", "Department of Sociology", ["Sociology"],
              "https://sociology.rice.edu/faculty", "Sociology, Faculty"),
        # ---- School of Humanities ----------------------------------------
        _rice("ENGL", "Department of English", ["English", "Creative Writing"],
              "https://english.rice.edu/faculty", "English, Core Faculty"),
        _rice("HIST", "Department of History", ["History"],
              "https://history.rice.edu/faculty", "History, Core Faculty"),
        _rice("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.rice.edu/faculty", "Philosophy, Core Faculty"),
        _rice("RELI", "Department of Religion", ["Religion", "Religious Studies"],
              "https://reli.rice.edu/faculty", "Religion, Core Faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
