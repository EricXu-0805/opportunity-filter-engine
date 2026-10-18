"""Colby College faculty config (via the faculty_graph engine).

Colby is a top-tier US liberal arts college (~2,200 undergraduates, no graduate
school) in Waterville, Maine. Its entire public site sits behind Cloudflare,
which answers every plain HTTP request with a 403 challenge, so the roster is
read through the headless render (``render``). The sole roster surface is the
college-wide People Directory at ``colby.edu/people/people-directory/``, an
Inertia.js page that ships every person as JSON in ``#app[data-page]``
(``props.people``: name, business title, department, profile slug) and shows
only the first 100 in its DOM, so each department reads that JSON (one render
serves all of them) and keeps the people whose home department is its own.

Measured 2026-10-17: a plain GET returned 403 ``cf-mitigated: challenge``; the
render returned 1,177 people. Until then the roster was a curated copy of the
payload harvested 2026-07-23, which no refresh re-read; read live it keeps 233
of its 238 rows under the same ids. The other five are the page's changes: two
professors now titled Emerita and three people no longer listed. One name is
new (Andie Wang, EALC) and two titles changed. Kerill O'Neill and Liam O'Brien
keep their ids because the page's ``&#8217;`` is read as a plain apostrophe,
as the harvest stored it.

Emails are not published anywhere in the directory payload, so each record
carries the professor's public People Directory profile URL as the contact
path; topics come from OpenAlex enrichment.

Home department: the directory's department field, or its first entry when it
lists several ("Computer Science; Davis Institute for AI"); a leading
"Colby College" or "Center for Arts and Humanities" is skipped, as the harvest
did. Ladder gate, as at harvest: professorial + lecturer ranks and genuine
"Instructor of <discipline>" teaching faculty; emeriti, visiting, adjunct,
postdoc/fellow appointments and the non-research staff that share the
directory (lab instructors, applied-music instructors, coaches, ...) are
dropped, as is the President, who is listed under "Colby College".

Single source ("colby_faculty"); department rides each record, ids namespaced
by department short-code. Audience "unknown".

Deferred: non-academic units (athletics, libraries, IT, advancement, custodial,
facilities, admissions, dining) are staff directories, not research faculty,
and are intentionally excluded.
"""

from __future__ import annotations

import re

from .. import faculty_graph

_DIR = "https://www.colby.edu/people/people-directory/"

# Professorial, lecturer and "Instructor of <discipline>" titles; a person
# with no title is not kept (the engine's ladder gate lets an empty rank pass).
_RANK = r"\bprofessor\b|\blecturer\b|\binstructor of\b"
_DROP = r"emerit|\bvisiting\b|\badjunct\b|postdoc|\bfellow\b"


def _dept(short: str, name: str, majors: list[str], homes: list[str]) -> dict:
    """A Colby academic department: directory people whose home is in ``homes``."""
    home = (r"^\s*(?:(?:Colby College|Center for Arts and Humanities)\s*;\s*)?(?:"
            + "|".join(re.escape(h) for h in homes) + r")\s*(?:;|$)")
    return {"short": short, "name": name, "majors": majors, "directory_url": _DIR,
            "json_dir": {
                "url": _DIR,
                "render": True,
                "attr_json": {"selector": "#app[data-page]", "attr": "data-page"},
                "records_key": "props.people",
                "name_fields": ["post_title"],
                "ascii_apostrophe": True,
                "title_field": "business_title",
                "link_template": _DIR + "{post_name}/",
                "field_filters": [{"field": "department", "include": home},
                                  {"field": "business_title", "include": _RANK}],
                "ladder_filter": {"drop": _DROP},
            }}


SCHOOL: dict = {
    "school_slug": "colby",
    "source": "colby_faculty",
    "organization": "Colby College",
    "location": "Waterville, ME",
    "id_prefix": "colby",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Colby College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics ----------------------------
        _dept("BIOL", "Department of Biology", ["Biology", "Neuroscience"], ["Biology"]),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], ["Mathematics"]),
        _dept("CS", "Department of Computer Science", ["Computer Science"], ["Computer Science"]),
        _dept("PSYC", "Department of Psychology", ["Psychology", "Neuroscience"], ["Psychology"]),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"], ["Chemistry"]),
        _dept("ENVS", "Environmental Studies Program",
              ["Environmental Studies", "Environmental Science", "Environmental Policy"], ["Environmental Studies"]),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], ["Physics and Astronomy"]),
        _dept("STAT", "Department of Statistics", ["Statistics"], ["Statistics"]),
        _dept("EOAS", "Department of Earth, Oceans, and Atmospheric Science",
              ["Geology", "Earth Sciences"], ["Earth Sciences (formerly Geology)"]),
        _dept("STS", "Science, Technology and Society Program",
              ["Science, Technology and Society"], ["Science, Technology and Society"]),
        # ---- Social Sciences -------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], ["Economics"]),
        _dept("GOVT", "Department of Government",
              ["Government", "Political Science"], ["Government"]),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], ["Anthropology"]),
        _dept("SOC", "Department of Sociology", ["Sociology"], ["Sociology"]),
        _dept("EDUC", "Education Program", ["Education"], ["Education"]),
        _dept("GLBL", "Global Studies Program", ["Global Studies"], ["Global Studies"]),
        _dept("WGSS", "Women's, Gender, and Sexuality Studies Program",
              ["Women's, Gender, and Sexuality Studies"], ["Women's, Gender, and Sexuality Studies"]),
        _dept("AMST", "American Studies Program", ["American Studies"], ["American Studies"]),
        _dept("AAST", "African American Studies Program",
              ["African American Studies"], ["African American Studies"]),
        # ---- Humanities ------------------------------------------------
        _dept("ENGL", "Department of English", ["English", "Creative Writing"], ["English"]),
        _dept("SPAN", "Department of Spanish",
              ["Spanish", "Latin American Studies"], ["Spanish", "Latin American Studies", "Spanish & Latin American Studies"]),
        _dept("HIST", "Department of History", ["History"], ["History"]),
        _dept("FRIT", "Department of French and Italian",
              ["French", "Italian"], ["French and Italian"]),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], ["Philosophy"]),
        _dept("EALC", "Department of East Asian Languages and Cultures",
              ["Chinese", "Japanese", "East Asian Studies"], ["East Asian Languages and Cultures"]),
        _dept("WRIT", "Writing Department", ["Writing"], ["Writing Department"]),
        _dept("CLAS", "Department of Classics", ["Classics", "Latin", "Greek"], ["Classics"]),
        _dept("GERU", "Department of German and Russian",
              ["German", "Russian"], ["German and Russian"]),
        _dept("RELG", "Department of Religious Studies",
              ["Religious Studies"], ["Religious Studies"]),
        _dept("JEWS", "Jewish Studies Program", ["Jewish Studies"], ["Jewish Studies"]),
        # ---- Arts ------------------------------------------------------
        _dept("ART", "Department of Art",
              ["Art", "Art History", "Studio Art"], ["Art", "Art and STS"]),
        _dept("PTD", "Department of Performance, Theater, and Dance",
              ["Theater and Dance", "Performance"], ["Performance, Theater, and Dance"]),
        _dept("MUS", "Department of Music", ["Music"], ["Music"]),
        _dept("CINE", "Cinema Studies Program", ["Cinema Studies"], ["Cinema Studies"]),
    ],
}


def fetch_and_normalize(deep: bool = True,
                        unit_ledger: dict | None = None) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep,
                                            unit_ledger=unit_ledger)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
