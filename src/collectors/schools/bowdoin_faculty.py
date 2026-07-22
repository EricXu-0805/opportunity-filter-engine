"""Bowdoin College faculty config (via the faculty_graph engine).

Bowdoin (a top-tier liberal arts college in Brunswick, Maine) runs its whole
academic site on one shared CMS: every department/program publishes a
``bowdoin.edu/<dept>/faculty-and-staff/index.html`` page that server-renders
each person as an ``article.profile-card`` (headshot + ``h4.profile-card-name``
link to ``/profiles/faculty/<netid>/index.html`` + ``em.profile-card-title``
rank). ONE selector family covers all 40 departments — only the department
slug changes. Cards are grouped under sibling ``<h2>`` role headings
("Faculty", "Staff", "Faculty Emeriti", "Research Affiliate"), so a
``section_filter`` on ``^faculty$`` lands exactly the home-department ladder
faculty and drops staff/emeriti/affiliates; a drop-only ``ladder_filter`` then
prunes the handful of postdoctoral scholars and visiting appointments that sit
inside the Faculty section. Live-verified 2026-07-21 (all 40 pages HTTP 200,
299 raw Faculty-section cards before the engine's cross-listing dedup — Bowdoin
lists a professor on every program they contribute to).

No public email: Bowdoin does not publish faculty email addresses anywhere on
the listing OR the individual profile pages (no ``mailto:``, no obfuscated
token — the only contact link is the college switchboard), so records ship
without ``contact_email`` and topical enrichment comes from OpenAlex. No render
mode needed — the CMS is fully server-rendered, no WAF.

Single source ("bowdoin_faculty"); department rides each record's
``department``, ids namespaced by short-code. Audience "unknown".

Deferred: Urban Studies (a minor with only cross-listed "Contributing Faculty"
— no home roster of its own; its people already land via their home
departments).
"""

from __future__ import annotations

from .. import faculty_graph

# Shared profile-card selector — identical across every Bowdoin department page.
_CARD_SEL = {
    "card": "article.profile-card",
    "name": "h4.profile-card-name a",
    "link": "h4.profile-card-name a",
    "title": "em.profile-card-title",
}

# Cards are grouped under sibling <h2> role headings; keep only the exact
# "Faculty" section (drops "Staff", "Faculty Emeriti", "Research Affiliate",
# "Contributing Faculty", "... Advisors").
_FACULTY_SECTION = {"heading": "h2", "include": r"^faculty$"}

# Within the Faculty section, prune the few non-ladder rows (postdoctoral
# scholars, research affiliates, visiting/adjunct); emeriti are already
# section-gated out and the engine drops any residual emeritus title.
_LADDER = {"drop": r"emerit|adjunct|visiting|postdoc|research affiliate|teaching fellow"}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Bowdoin department on the shared faculty-and-staff profile-card page."""
    url = f"https://www.bowdoin.edu/{slug}/faculty-and-staff/index.html"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CARD_SEL,
                   "section_filter": _FACULTY_SECTION, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "bowdoin",
    "source": "bowdoin_faculty",
    "organization": "Bowdoin College",
    "location": "Brunswick, ME",
    "id_prefix": "bowdoin",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Bowdoin College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics --------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("BIOC", "Biochemistry Program", ["Biochemistry"], "biochemistry"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics"),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], "math"),
        _dept("CSCI", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("DCS", "Digital and Computational Studies",
              ["Digital and Computational Studies"], "digital-and-computational-studies"),
        _dept("EOS", "Department of Earth and Oceanographic Science",
              ["Earth and Oceanographic Science"], "earth-oceanographic-science"),
        _dept("NEUR", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("ENVS", "Environmental Studies Program", ["Environmental Studies"],
              "environmental-studies"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("GOVT", "Department of Government and Legal Studies",
              ["Government and Legal Studies"], "government"),
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("EDUC", "Education Department", ["Education"], "education"),
        # ---- Humanities ----------------------------------------------------
        _dept("ENGL", "Department of English", ["English"], "english"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELG", "Department of Religion", ["Religion"], "religion"),
        _dept("CLAS", "Department of Classics", ["Classics"], "classics"),
        _dept("ARTH", "Department of Art History", ["Art History"], "art-history"),
        # ---- Languages & Regional Studies ----------------------------------
        _dept("ROML", "Department of Romance Languages and Literatures",
              ["Romance Languages", "French", "Spanish"], "romance-languages"),
        _dept("HISP", "Hispanic Studies", ["Hispanic Studies", "Spanish"],
              "hispanic-studies"),
        _dept("FRAN", "Francophone Studies", ["Francophone Studies", "French"],
              "francophone-studies"),
        _dept("ITAL", "Italian Studies", ["Italian Studies", "Italian"], "italian"),
        _dept("GERM", "German Department", ["German"], "german"),
        _dept("RUSS", "Russian, East European, and Eurasian Studies",
              ["Russian"], "russian"),
        _dept("ARAB", "Arabic", ["Arabic"], "arabic"),
        _dept("CHIN", "Chinese", ["Chinese"], "chinese"),
        _dept("JAPN", "Japanese", ["Japanese"], "japanese"),
        _dept("ASNS", "Asian Studies Program", ["Asian Studies"], "asian-studies"),
        _dept("AFRS", "Africana Studies Program", ["Africana Studies"],
              "africana-studies"),
        _dept("LACL", "Latin American, Caribbean, and Latinx Studies",
              ["Latin American Studies"], "latin-american-studies"),
        _dept("MENA", "Middle Eastern and North African Studies",
              ["Middle Eastern and North African Studies"], "mena"),
        _dept("GSWS", "Gender, Sexuality, and Women's Studies",
              ["Gender, Sexuality, and Women's Studies"], "gender-women"),
        # ---- Arts ----------------------------------------------------------
        _dept("VART", "Department of Visual Arts", ["Visual Arts", "Art"],
              "visual-arts"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("THDA", "Department of Theater and Dance", ["Theater", "Dance"],
              "theater-dance"),
        _dept("CINE", "Cinema Studies Program", ["Cinema Studies"], "cinema-studies"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
