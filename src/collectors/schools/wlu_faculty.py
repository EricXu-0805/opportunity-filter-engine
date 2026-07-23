"""Washington and Lee University faculty config (via the faculty_graph engine).

Washington and Lee (W&L) is a top-tier US liberal arts college in Lexington,
Virginia, comprising The College (arts & sciences), The Williams School of
Commerce, Economics, and Politics, and the School of Law. Every undergraduate
academic department publishes its roster on ONE shared "areas of study"
template at ``wlu.edu/academics/areas-of-study/<slug>``: a "Meet the Faculty"
tray whose people are ``.slider-profile .slide`` cards. Each card carries a
plain ``<h3>`` name, a ``<p class="h6">`` rank line ("Professor of Biology",
"Associate Professor of …", "… Department Head and Professor of …"), a
``list-contact`` block with a ``tel:`` and a decodable ``mailto:`` (the contact
of record — emails are inline for essentially every professor), and a short
bio paragraph. Cards link only to a CV PDF, so there are no per-person profile
pages and every record falls back to the department directory URL; no
profile-enrichment pass is needed.

ONE selector family covers the whole college — sciences, social sciences,
humanities, arts, and the Williams School alike. Role gating rides a title
``ladder_filter`` on the ``p.h6`` rank text (keep professors/lecturers/
instructors; drop emeriti, visiting, and adjunct appointments plus the
non-teaching staff — coordinators, technicians — that share the card markup).

Interdisciplinary programs (Africana, Environmental, Neuroscience, WGSS,
Cognitive & Behavioral Science, Education) cross-list faculty from their home
departments; the engine's per-school email dedup collapses those to one record,
so listing them only widens coverage without producing duplicates. The
combined Physics & Engineering department shares one roster (the ``physics``
page); ``engineering`` is the same people.

Single source ("wlu_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown". No WAF, no render mode
anywhere.

Selectors + counts verified live (curl + bs4) on 2026-07-23 across sciences,
social sciences, humanities, arts, and the Williams School — e.g. Biology 15,
English 19, Romance Languages 27, Business Administration 22, Sociology &
Anthropology 18, Chemistry & Biochemistry 12, Economics 13, Accounting 14,
Mathematics 13, History 12.

Deferred (separate platform): the School of Law faculty (law.wlu.edu) runs on a
distinct CMS with no ``.slider-profile`` roster — a soft-404 on the guessed
directory paths — so it is not captured by this shared template; revisit with a
Law-specific selector family.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.wlu.edu/academics/areas-of-study/"

# Shared "Meet the Faculty" slider card (static HTML, one family for every dept).
_SELECTORS = {
    "card": ".slider-profile .slide",
    "name": "h3",
    "title": "p.h6",
    "email": "a[href^='mailto:']",
}

# Keep ladder faculty (professors/lecturers/instructors); drop emeriti,
# visiting, and adjunct appointments plus non-teaching staff whose rank line
# carries no professorial title.
_LADDER = {"require": r"professor|lecturer|instructor", "drop": r"emerit|visiting|adjunct"}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A W&L academic unit on the shared areas-of-study faculty slider."""
    url = f"{_BASE}{slug}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "wlu",
    "source": "wlu_faculty",
    "organization": "Washington and Lee University",
    "location": "Lexington, VA",
    "id_prefix": "wlu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Washington and Lee University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- The College: Sciences & Mathematics -------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"], "chemistry-and-biochemistry"),
        _dept("PHYS", "Department of Physics and Engineering",
              ["Physics", "Engineering"], "physics"),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], "mathematics"),
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("GEOL", "Department of Earth and Environmental Geoscience",
              ["Geology", "Environmental Geoscience"],
              "earth-and-environmental-geoscience"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("NEUR", "Neuroscience Program", ["Neuroscience"], "neuroscience"),
        _dept("ENVS", "Environmental Studies Program", ["Environmental Studies"],
              "environmental-studies"),
        _dept("COGS", "Cognitive and Behavioral Science Program",
              ["Cognitive and Behavioral Science"], "cognitive-and-behavioral-science"),
        # ---- The College: Social Sciences --------------------------------
        _dept("SOAN", "Department of Sociology and Anthropology",
              ["Sociology", "Anthropology"], "sociology-and-anthropology"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("EDUC", "Education Program", ["Education Studies"], "education-studies"),
        _dept("AFRC", "Africana Studies Program", ["Africana Studies"],
              "africana-studies"),
        _dept("WGSS", "Women's, Gender, and Sexuality Studies Program",
              ["Women's, Gender, and Sexuality Studies"],
              "womens-gender-and-sexuality-studies"),
        # ---- The College: Humanities -------------------------------------
        _dept("ENGL", "Department of English", ["English"], "english"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELG", "Department of Religion", ["Religion"], "religion"),
        _dept("CLAS", "Department of Classics",
              ["Classics", "Greek", "Latin"], "classics"),
        _dept("ROML", "Department of Romance Languages",
              ["French", "Spanish", "Italian", "Portuguese"], "romance-languages"),
        _dept("GERM", "Department of German and Russian",
              ["German", "Russian"], "german"),
        _dept("EALL", "Department of East Asian Languages and Literatures",
              ["Chinese", "Japanese"], "east-asian-languages-and-literatures"),
        _dept("JOUR", "Department of Journalism and Mass Communications",
              ["Journalism", "Mass Communications"],
              "journalism-and-mass-communications"),
        # ---- The College: Arts -------------------------------------------
        _dept("ARTH", "Department of Art and Art History",
              ["Art History", "Studio Art"], "art-history"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("THTR", "Department of Theater, Dance, and Film Studies",
              ["Theater", "Dance", "Film Studies"], "theater"),
        # ---- The Williams School -----------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("ACCT", "Department of Accounting", ["Accounting"], "accounting"),
        _dept("BUS", "Department of Business Administration",
              ["Business Administration"], "business-administration"),
        _dept("POL", "Department of Politics", ["Politics"], "politics"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
