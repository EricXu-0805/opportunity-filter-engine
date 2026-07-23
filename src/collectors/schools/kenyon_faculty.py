"""Kenyon College faculty config (via the faculty_graph engine).

Kenyon is a top-tier US liberal arts college (~1,800 undergraduates, no
graduate school) in Gambier, Ohio, long known for its English/creative-writing
program (home of The Kenyon Review) and its strong natural sciences. Every
academic department publishes a dedicated "<Dept> Faculty" roster page on the
same college-wide "BigTree" CMS template under
``kenyon.edu/academics/departments-and-majors/<dept>/<dept>-faculty/`` — there
is no single scrapeable college-wide directory (``/directory/`` is a JS search
box), but every department page shares ONE markup family, so a single scrape
source with per-department URLs covers the whole college.

Live-verified 2026-07-22 (all plain HTTP 200s, no WAF, no render mode):

* ``entity_table`` — each roster is one or more ``table.entity_table`` grids
  (grouped "Chair", then the main faculty list); every person is a
  ``tr.entity_table_row`` whose first cell holds ``h2.entity_name`` (name +
  ``/directory/<slug>/`` profile link), a ``.entity_title`` rank
  ("Assistant Professor of Biology", named chairs like "Robert A. Oden, Jr.
  Professor of Biology"), and a plain-prose ``.entity_expertise`` "Areas of
  Expertise" block. The contact cell exposes a decodable ``mailto:`` under
  ``.entity_detail_item.email``. Header rows (``<th>``) carry no
  ``h2.entity_name`` and are skipped at name-parse time.

Emails are inline for essentially every professor (verified across Biology,
English, Chemistry, Mathematics & Statistics), so no profile-enrichment pass
is needed — the ``.entity_expertise`` prose seeds keyword derivation and
OpenAlex fills topics.

Ladder gate keeps professorial / lecturer / instructor ranks (the
cold-emailable research + teaching faculty) and drops emeriti, visiting, and
adjunct appointments plus the lab-instructor / coordinator / technician staff
that share the same row markup. Interdisciplinary programs cross-list faculty
whose home department is also captured; the engine's per-school email/url dedup
collapses those to a single record, so the core disciplinary departments are
listed FIRST.

Faculty-page path is ``<slug>/<slug>-faculty/`` for almost every department; a
handful use a shorter ``/faculty/`` (Biochemistry & Molecular Biology, Gender &
Sexuality Studies, Islamic Civilizations & Cultures) or a bespoke tail (Asian &
Middle East Studies ``asian-middle-east-studies-faculty``, IPHS
``iphs-faculty``) — passed explicitly via ``fac``.

Single source ("kenyon_faculty"); department rides each record, ids namespaced
by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.kenyon.edu/academics/departments-and-majors/"

# Person row on the shared Kenyon BigTree "entity_table" roster template.
_SELECTORS = {
    "card": "tr.entity_table_row",
    "name": "h2.entity_name .entity_name_link_label",
    "link": "a.entity_name_link",
    "title": ".entity_title",
    "research": ".entity_expertise",
    "email": ".entity_detail_item.email a[href^='mailto:']",
}

# Keep professorial + lecturer + instructor ranks; drop emeriti, visiting, and
# adjunct appointments as well as the staff (lab instructor / coordinator /
# technician) whose titles carry no professorial rank.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|visiting|adjunct",
}


def _dept(short: str, name: str, majors: list[str], slug: str,
          fac: str | None = None) -> dict:
    """A Kenyon department on the shared entity_table faculty roster."""
    fac = fac or f"{slug}-faculty"
    url = f"{_BASE}{slug}/{fac}/"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "kenyon",
    "source": "kenyon_faculty",
    "organization": "Kenyon College",
    "location": "Gambier, OH",
    "id_prefix": "kenyon",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Kenyon College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    # Core disciplinary departments are listed FIRST so a cross-listed
    # professor attributes to a home department; the interdisciplinary / area /
    # policy programs that aggregate cross-listed faculty come LAST (the
    # engine's per-school email/url dedup then collapses the duplicates onto
    # the disciplinary home).
    "departments": [
        # ---- Natural Sciences (core disciplines) --------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("PHYS", "Department of Physics",
              ["Physics", "Astronomy"], "physics"),
        _dept("MATH", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "mathematics-statistics"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        # ---- Social Sciences (core disciplines) ---------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("POSC", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("SOCY", "Department of Sociology", ["Sociology"], "sociology"),
        # ---- Humanities (core disciplines) --------------------------------
        _dept("ENGL", "Department of English",
              ["English", "Creative Writing"], "english"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RLST", "Department of Religious Studies", ["Religious Studies"],
              "religious-studies"),
        _dept("CLAS", "Department of Classics",
              ["Classics", "Greek", "Latin", "Classical Civilization"], "classics"),
        _dept("MLL", "Department of Modern Languages and Literatures",
              ["French", "German", "Spanish", "Chinese", "Japanese", "Arabic",
               "Italian", "Russian"], "modern-languages-literatures"),
        # ---- Fine Arts (core disciplines) ---------------------------------
        _dept("ARTH", "Department of Art History", ["Art History"], "art-history"),
        _dept("SART", "Department of Studio Art", ["Studio Art"], "studio-art"),
        _dept("MUS", "Department of Music", ["Music"], "music"),
        _dept("DDF", "Department of Dance, Drama and Film",
              ["Dance", "Drama", "Film"], "dance-drama-film"),
        # ---- Interdisciplinary / area / policy programs (aggregate
        #      cross-listed faculty; listed last so home depts win) ----------
        _dept("BMB", "Program in Biochemistry and Molecular Biology",
              ["Biochemistry", "Molecular Biology"],
              "biochemistry-molecular-biology", fac="faculty"),
        _dept("NEUR", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("COMP", "Program in Computing",
              ["Scientific Computing"], "computing"),
        _dept("ENVS", "Program in Environmental Studies",
              ["Environmental Studies"], "environmental-studies"),
        _dept("PPOL", "Program in Public Policy", ["Public Policy"], "public-policy"),
        _dept("INTL", "Program in International Studies", ["International Studies"],
              "international-studies"),
        _dept("LAWS", "Program in Law and Society", ["Law and Society"],
              "law-society"),
        _dept("AMST", "Program in American Studies", ["American Studies"],
              "american-studies"),
        _dept("AMES", "Program in Asian and Middle East Studies",
              ["Asian and Middle East Studies"],
              "asian-and-middle-east-studies",
              fac="asian-middle-east-studies-faculty"),
        _dept("ISLC", "Program in Islamic Civilizations and Cultures",
              ["Islamic Civilizations and Cultures"],
              "islamic-civilizations-cultures", fac="faculty"),
        _dept("ADST", "Program in African Diaspora Studies",
              ["African Diaspora Studies"], "african-diaspora-studies"),
        _dept("LTNE", "Program in Latine Studies", ["Latine Studies"],
              "latine-studies"),
        _dept("GSS", "Program in Gender and Sexuality Studies",
              ["Gender and Sexuality Studies"], "gender-sexuality-studies",
              fac="faculty"),
        _dept("IPHS", "Integrated Program in Humane Studies",
              ["Integrated Program in Humane Studies"],
              "integrated-program-in-humane-studies", fac="iphs-faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
