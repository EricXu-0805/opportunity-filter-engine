"""Stanford University faculty config (via the faculty_graph engine).

Scrape-first, like UW/GT. Two server-rendered Drupal templates cover the campus:

  * **School of Engineering** depts share a "stanford-person" node template
    (``.node.stanford-person.node-title`` → ``h3 a``) — one card per person,
    name + profile link only (rank/contact live on the profile page), so these
    land as accurate department/major-scoped cold-email targets. (ME, BioE, AA,
    MSE, ChemE, CEE.)
  * **Humanities & Sciences** depts render a "Views" grid of ``div.hb-card``
    whose ``.views-field-field-hs-person-research`` lists each research area as
    its own taxonomy link — so Physics, Statistics, Chemistry and Math land
    fully keyworded at UIUC parity. Math's combined faculty/lecturers page is
    title-filtered to ladder ranks.
  * **CS** uses the engineering "su-card" grid (name + profile link only).

EE stays deferred (a JS person grid with no server-rendered cards); Stanford
Profiles' CAP API is auth-gated.

Single source ("stanford_faculty"); department rides each record's
``department``, ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Stanford School of Engineering "stanford-person" directory selectors.
_SU_PERSON = {
    "card": ".node.stanford-person.node-title",
    "name": "h3 a",
    "link": "h3 a",
}

# Humanities & Sciences "Views" grid: research areas are per-area taxonomy links.
_HS_RESEARCH = ".views-field-field-hs-person-research a"


def _su(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, "selectors": _SU_PERSON}}


def _hb(short: str, name: str, majors: list[str], url: str, *,
        card: str = "div.hb-card", name_sel: str = ".views-field-title a",
        ladder_filter: dict | None = None) -> dict:
    scrape = {"url": url, "selectors": {
        "card": card, "name": name_sel, "link": name_sel,
        "title": ".views-field-field-hs-person-title",
        "research_items": _HS_RESEARCH,
    }}
    if ladder_filter:
        scrape["ladder_filter"] = ladder_filter
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "stanford",
    "source": "stanford_faculty",
    "organization": "Stanford University",
    "location": "Stanford, CA",
    "id_prefix": "stanford",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Stanford University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _su("ME", "Department of Mechanical Engineering",
            ["Mechanical Engineering"], "https://me.stanford.edu/people/faculty"),
        _su("BIOE", "Department of Bioengineering",
            ["Bioengineering"], "https://bioengineering.stanford.edu/people/faculty"),
        _su("AA", "Department of Aeronautics & Astronautics",
            ["Aeronautics & Astronautics", "Aerospace Engineering"], "https://aa.stanford.edu/people/faculty"),
        _su("MSE", "Department of Materials Science & Engineering",
            ["Materials Science & Engineering"], "https://mse.stanford.edu/people/faculty"),
        _su("CHEME", "Department of Chemical Engineering",
            ["Chemical Engineering"], "https://cheme.stanford.edu/people/faculty"),
        _su("CEE", "Department of Civil & Environmental Engineering",
            ["Civil Engineering", "Environmental Engineering"],
            "https://cee.stanford.edu/people/faculty"),
        {"short": "CS", "name": "Department of Computer Science",
         "majors": ["Computer Science"],
         "directory_url": "https://www.cs.stanford.edu/people/faculty",
         "scrape": {"url": "https://www.cs.stanford.edu/people/faculty",
                    "selectors": {"card": "article.su-card", "name": "a", "link": "a"}}},
        _hb("PHYSICS", "Department of Physics", ["Physics"],
            "https://physics.stanford.edu/people/faculty"),
        _hb("STATS", "Department of Statistics", ["Statistics", "Data Science"],
            "https://statistics.stanford.edu/people/faculty",
            name_sel=".hb-card__title h3 a"),
        _hb("CHEM", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.stanford.edu/people/faculty", card="div.hb-table-row",
            name_sel="a[href*='/people/']"),
        _hb("MATH", "Department of Mathematics", ["Mathematics"],
            "https://mathematics.stanford.edu/people/faculty-lecturers",
            ladder_filter={"require": r"professor", "drop": r"emerit|adjunct|lecturer|teaching"}),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
