"""Macalester College faculty config (via the faculty_graph engine).

Macalester is a highly ranked US liberal arts college (~2,100 undergraduates,
no graduate school) in Saint Paul, Minnesota, known for its internationalism,
strong economics program, and the natural sciences. Its entire public site is
one shared WordPress multisite build, and every academic department publishes
its roster on a ``/<dept>/facultystaff/`` page using the SAME
``card-profile`` (hCard ``vcard`` / ``tease-profile``) component, so ONE
selector family covers the whole college — no per-department bespoke markup and
no render mode anywhere.

Live-verified 2026-07-22 (~35 clean 200s over curl, no WAF challenge):

* ``_dept`` — the shared ``div.card-profile`` bio card. The name is a
  ``li.fn > a`` link to the person's profile page
  (``/<dept>/facultystaff/<slug>/``), the rank is ``li.title``, an optional
  ``li.position-description`` carries the person's research areas (fed into
  ``research_areas`` → keywords), and the email lives in ``li.email a`` as a
  Cloudflare email-protection link (``/cdn-cgi/l/email-protection#HEX`` +
  ``span.__cf_email__[data-cfemail]``) which the engine decodes automatically.

Ladder gate keeps Professors and Lecturers (the cold-emailable research /
teaching faculty) and drops emeriti, visiting appointments, retired faculty
(including the "(1994-2020)" year-range title convention used on the emeriti
rows), and — via the require clause — every non-teaching staff row (department
coordinators, lab supervisors/technicians, facility managers, postdoctoral
fellows, applied-music lesson instructors, and language-lab instructors) that
shares the same card markup.

Single source ("macalester_faculty"); department rides each record, ids
namespaced by department short-code. The engine's per-school email/name dedup
collapses the handful of faculty cross-listed onto more than one department
page (e.g. an economist also under International Studies) — the home
department, listed first below, wins the attribution.

Deferred (2026-07-22 recon): the interdisciplinary programs/concentrations
(African Studies, Asian Studies, Cognitive Science, Community & Global Health,
Critical Theory, Environmental Studies is kept as a department, Latin American
Studies, Legal Studies, International Development, Urban Studies, WGSS,
Biochemistry) list cross-appointed faculty whose home department is already
captured above; adding them would only produce email-deduped duplicates with
arbitrary department attribution, so they are covered on the campus side as
programs, not as faculty departments here.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared bio-card selectors for the WordPress card-profile / vcard component.
_SELECTORS = {
    "card": "div.card-profile",
    "name": "li.fn a",
    "link": "li.fn a",
    "title": "li.title",
    "research": "li.position-description",
    # Cloudflare-obfuscated mailto; engine decodes the /cdn-cgi/ href + data-cfemail.
    "email": "li.email a",
}

# Keep Professors + Lecturers (research/teaching faculty); drop emeriti, visiting,
# retired, and the year-range "(1994-2020)" former-faculty title convention. The
# require clause additionally drops every staff / coordinator / lab-instructor /
# applied-music lesson row that shares the same card markup.
_LADDER = {
    "require": r"professor|lecturer",
    "drop": r"emerit|visiting|retired|\(\d{4}",
}


def _dept(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A department on the shared card-profile people-list component."""
    url = f"https://www.macalester.edu/{slug}/facultystaff/"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "macalester",
    "source": "macalester_faculty",
    "organization": "Macalester College",
    "location": "Saint Paul, MN",
    "id_prefix": "macalester",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Macalester College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics --------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics"),
        _dept("GEOL", "Department of Geology", ["Geology"], "geology"),
        _dept("MSCS", "Department of Mathematics, Statistics, and Computer Science",
              ["Mathematics", "Statistics", "Computer Science"], "mscs"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("NEUR", "Neuroscience Studies Program", ["Neuroscience"],
              "neuroscience"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("GEOG", "Department of Geography",
              ["Geography", "Geographic Information Science"], "geography"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("INTL", "Department of International Studies",
              ["International Studies"], "internationalstudies"),
        _dept("POLI", "Department of Political Science", ["Political Science"],
              "politicalscience"),
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology"),
        _dept("AMST", "American Studies Department", ["American Studies"],
              "americanstudies"),
        _dept("ENVI", "Environmental Studies Department", ["Environmental Studies"],
              "environmentalstudies"),
        # ---- Humanities & Languages ----------------------------------------
        _dept("CLAS", "Department of Classics",
              ["Classics", "Greek", "Latin"], "classics"),
        _dept("ENGL", "Department of English and Creative Writing",
              ["English", "Creative Writing"], "english-and-creative-writing"),
        _dept("LING", "Department of Linguistics", ["Linguistics"], "linguistics"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELI", "Department of Religious Studies", ["Religious Studies"],
              "religiousstudies"),
        _dept("FREN", "French and Francophone Studies",
              ["French", "Francophone Studies"], "french"),
        _dept("GERM", "German Studies", ["German Studies"], "german"),
        _dept("RUSS", "Russian Studies", ["Russian Studies"], "russian"),
        _dept("SPAN", "Hispanic and Latin American Studies",
              ["Spanish", "Latin American Studies"], "spanish"),
        _dept("ASIA", "Asian Languages and Cultures",
              ["Chinese", "Japanese"], "asian"),
        # ---- Fine Arts -----------------------------------------------------
        _dept("ART", "Department of Art and Art History",
              ["Studio Art", "Art History"], "art"),
        _dept("MUSI", "Department of Music", ["Music"], "music"),
        _dept("THDA", "Department of Theater and Dance", ["Theater", "Dance"],
              "theater-and-dance"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
