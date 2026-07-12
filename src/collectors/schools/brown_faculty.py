"""Brown University faculty config (via the faculty_graph engine).

Brown runs a single shared Drupal "people component" theme across almost every
``*.brown.edu`` department subdomain, so one selector set covers the whole
university. Each faculty member is an ``li.people_item`` card carrying the name
(``.people_item_name`` — wraps the profile ``<a>``), the rank
(``.people_item_title``), and, where the department publishes it, a public
mailto inside the card. Verified live against the Economics reference directory
(``economics.brown.edu/people/faculty`` → 49 ``li.people_item`` cards, name +
rank + ``mailto:``); the identical markup was confirmed by recon on chemistry,
classics, sociology, history, philosophy, engineering, HIAA, and ~30 more.

Only the *path* varies per department (``/people/faculty`` vs ``/faculty`` vs
``/people`` vs ``/about/people`` …), captured per-entry below. Departments whose
listing is the whole-roster ``/people`` page (faculty + staff + grads) are
sliced to ladder faculty by ``_LADDER`` (keep Professor/Lecturer, drop emeriti);
department pages that are already faculty-only keep the same filter harmlessly.

Two departments (DEEPS, Mathematics) render their roster client-side (Drupal +
React), so they use the engine's ``render: True`` headless-Chromium mode.

Single source ("brown_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown" (per-professor).

Deferred (bespoke, not the shared Drupal template — tracked for a later pass):
Anthropology (roster on an external Google Site), Computer Science (own
``cs.brown.edu`` plain-list template), School of Public Health (JS site-search
component; sub-depts have no subdomains), Warren Alpert Medical School (VIVO/
Vitro semantic directory), Slavic Studies (subdomain slug unresolved).
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Brown "people component" card (static HTML on every dept subdomain).
_BROWN_SELECTORS = {
    "card": "li.people_item",
    "name": ".people_item_name",
    "link": ".people_item_name a",
    "title": ".people_item_title",
    "email": "a[href^='mailto:']",
    "research_items": ".people_research .people_r_item, .people_research a",
}

# Whole-roster /people pages mix faculty with staff/grads/postdocs. Keep ladder
# faculty (Professor / Assistant / Associate / Lecturer / Senior Lecturer /
# Professor of the Practice); drop emeriti. Faculty-only listing pages pass this
# unchanged.
_LADDER = {"require": r"\bprofessor\b|\blecturer\b", "drop": r"emerit"}


def _d(short: str, name: str, majors: list[str], url: str, *, render: bool = False) -> dict:
    scrape = {"url": url, "selectors": _BROWN_SELECTORS, "ladder_filter": _LADDER}
    if render:
        scrape["render"] = True
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "brown",
    "source": "brown_faculty",
    "organization": "Brown University",
    "location": "Providence, RI",
    "id_prefix": "brown",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Brown University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Humanities (The College) ------------------------------------
        _d("AFRICANA", "Department of Africana Studies", ["Africana Studies"],
           "https://africana.brown.edu/people/our-faculty"),
        _d("AMST", "Department of American Studies", ["American Studies"],
           "https://americanstudies.brown.edu/about/people"),
        _d("CLAS", "Department of Classics", ["Classics"],
           "https://classics.brown.edu/people/faculty"),
        _d("COLT", "Department of Comparative Literature", ["Comparative Literature"],
           "https://complit.brown.edu/faculty"),
        _d("EAS", "Department of East Asian Studies",
           ["East Asian Studies", "Chinese", "Japanese", "Korean"],
           "https://eas.brown.edu/people"),
        _d("EGAS", "Department of Egyptology & Assyriology",
           ["Egyptology", "Assyriology", "Ancient Near Eastern Studies"],
           "https://e-a.brown.edu/people/faculty-staff"),
        _d("ENGL", "Department of English", ["English", "Literary Studies"],
           "https://english.brown.edu/faculty"),
        _d("FREN", "Department of French & Francophone Studies",
           ["French", "Francophone Studies"], "https://frenchstudies.brown.edu/people/faculty"),
        _d("GRMN", "Department of German Studies", ["German Studies"],
           "https://german.brown.edu/people"),
        _d("HISP", "Department of Hispanic Studies", ["Hispanic Studies", "Spanish"],
           "https://hispanicstudies.brown.edu/people"),
        _d("HIST", "Department of History", ["History"],
           "https://history.brown.edu/people"),
        _d("HIAA", "Department of History of Art & Architecture",
           ["History of Art & Architecture", "Art History"], "https://hiaa.brown.edu/people"),
        _d("JUDS", "Program in Judaic Studies", ["Judaic Studies"],
           "https://judaicstudies.brown.edu/people"),
        _d("LITR", "Literary Arts", ["Literary Arts", "Creative Writing"],
           "https://literaryarts.brown.edu/faculty"),
        _d("MCM", "Department of Modern Culture & Media",
           ["Modern Culture & Media", "Media Studies"], "https://mcm.brown.edu/people"),
        _d("MUSC", "Department of Music", ["Music"],
           "https://music.brown.edu/people"),
        _d("PHIL", "Department of Philosophy", ["Philosophy"],
           "https://philosophy.brown.edu/people"),
        _d("POBS", "Department of Portuguese & Brazilian Studies",
           ["Portuguese & Brazilian Studies", "Portuguese"],
           "https://portuguese-brazilian.brown.edu/people"),
        _d("RELS", "Department of Religious Studies", ["Religious Studies"],
           "https://religious-studies.brown.edu/people/faculty"),
        _d("TAPS", "Department of Theatre Arts & Performance Studies",
           ["Theatre Arts", "Performance Studies"], "https://taps.brown.edu/people/faculty"),
        _d("VART", "Department of Visual Art", ["Visual Art"],
           "https://visualart.brown.edu/about/people"),
        # ---- Social sciences (The College) -------------------------------
        _d("ECON", "Department of Economics", ["Economics"],
           "https://economics.brown.edu/people/faculty"),
        _d("EDUC", "Department of Education (Annenberg Institute)",
           ["Education", "Education Policy"], "https://education.brown.edu/people/faculty"),
        _d("POLS", "Department of Political Science", ["Political Science"],
           "https://polisci.brown.edu/people"),
        _d("SOC", "Department of Sociology", ["Sociology"],
           "https://sociology.brown.edu/people/faculty"),
        _d("IAPA", "Watson Institute — International & Public Affairs",
           ["International & Public Affairs", "Political Science", "Development Studies"],
           "https://watson.brown.edu/people/faculty"),
        # ---- Physical & life sciences (The College) ----------------------
        _d("APMA", "Division of Applied Mathematics", ["Applied Mathematics"],
           "https://appliedmath.brown.edu/people/faculty"),
        _d("CHEM", "Department of Chemistry", ["Chemistry"],
           "https://chemistry.brown.edu/people/faculty"),
        _d("COPSY", "Department of Cognitive & Psychological Sciences",
           ["Cognitive Science", "Psychology", "Cognitive Neuroscience"],
           "https://copsy.brown.edu/people/faculty"),
        _d("LING", "Department of Linguistics", ["Linguistics"],
           "https://linguistics.brown.edu/people"),
        _d("PHYS", "Department of Physics", ["Physics"],
           "https://physics.brown.edu/about/people/faculty"),
        _d("DEEPS", "Department of Earth, Environmental & Planetary Sciences",
           ["Earth Science", "Environmental Science", "Planetary Science", "Geology"],
           "https://deeps.brown.edu/people/faculty", render=True),
        _d("MATH", "Department of Mathematics", ["Mathematics"],
           "https://mathematics.brown.edu/people/faculty", render=True),
        # ---- Biology & medicine (basic-science depts) --------------------
        _d("EEOB", "Department of Ecology, Evolution & Organismal Biology",
           ["Ecology & Evolutionary Biology", "Organismal Biology"],
           "https://eeob.brown.edu/meet-our-team/faculty"),
        _d("MCB", "Department of Molecular Biology, Cell Biology & Biochemistry",
           ["Molecular Biology", "Cell Biology", "Biochemistry"],
           "https://mcb.brown.edu/about-mcb/people/faculty"),
        _d("NEUR", "Department of Neuroscience", ["Neuroscience"],
           "https://neuroscience.brown.edu/people/faculty"),
        # ---- School of Engineering ---------------------------------------
        _d("ENGN", "School of Engineering",
           ["Engineering", "Biomedical Engineering", "Chemical Engineering",
            "Electrical Engineering", "Materials Science", "Mechanical Engineering"],
           "https://engineering.brown.edu/people/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
