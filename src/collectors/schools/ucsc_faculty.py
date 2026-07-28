"""UC Santa Cruz faculty config (via the faculty_graph engine).

UCSC runs a **campus-standard "h-card" people component** — server-rendered,
no WAF, no JS render needed — on nearly every department directory across all
five academic divisions (Baskin Engineering, Physical & Biological Sciences,
Social Sciences, Humanities, Arts). One card is
``div.section-item.h-card.wrap`` carrying:

* an ``h3.item-name`` with the display name in ``span.p-name`` and a profile
  link in ``a.u-url`` (Baskin depts link out to
  ``campusdirectory.ucsc.edu/cd_detail?uid=<cruzid>`` absolutely; many other
  depts use a relative ``?directoryprofilecruzid=<cruzid>`` form the engine
  resolves against the directory URL);
* an ``ul.item-info`` list whose "Title" row holds the rank in a nested
  ``ul.inline-list``, and (on the pages that expose it) a "Campus Email" row
  with a plain ``a.u-email`` mailto.

Because the component is uniform, one shared selector set + one ladder gate
covers ~20 departments. The listing carries no research/interests field, so
records land name+title+email only (topics come from downstream OpenAlex
enrichment) — that matches the recon (research_selector empty everywhere).

Title gate (``require: professor|lecturer``): the directories mix in staff,
advisors, and — in the sciences especially — dozens of graduate students,
postdocs, project scientists, and researchers alongside faculty. Requiring a
"Professor"/"Lecturer" rank keeps ladder + teaching faculty and lecturers while
dropping titleless staff rows, Deans/Directors/Vice-Provosts, and the
grad-student/postdoc bulk. Emeriti are dropped by the engine's own
``_RETIRED_TITLE_RE`` (emeritus/emerita/retired), and chairs/directors that
appear twice (a leadership card + a faculty card) collapse via the engine's
name/url dedupe.

MCD (Molecular, Cell & Developmental) Biology does NOT use the h-card component
— it hand-builds a Gutenberg column layout (``div.wp-block-column`` with an
``h4.wp-block-heading`` name link and a ``mailto:``). It gets its own selector
set (no rank on the listing → the engine defaults "Professor"; the page is a
faculty-only roster so that is correct).

UCSC's "BME" is BIOMOLECULAR Engineering (genomics / protein / synthetic bio),
NOT biomedical. UCSC has no separate Mechanical Engineering department, and
Applied Mathematics (Baskin) is the applied-math unit while Mathematics
(PBSci) is the pure-math department — both are included.

COVERAGE (live-verified 2026-07-24):
  Baskin Engineering: CS, ECE, Biomolecular Eng, Statistics, Applied Math
  Phys & Bio Sciences: Physics, Mathematics, Earth & Planetary Sciences,
    Ocean Sciences, Microbiology & Env Toxicology, MCD Biology (custom layout)
  Social Sciences: Psychology, Economics, Anthropology, Politics,
    Environmental Studies, Latin American & Latino Studies, Education
  Humanities: History, Philosophy, Literature, Linguistics, Feminist Studies,
    Critical Race & Ethnic Studies
  Arts: Art, Film & Digital Media, History of Art & Visual Culture, Music

DROPPED / phase-2:
  * Chemistry & Biochemistry — its roster (chemistry.ucsc.edu/people-auto/)
    stopped rendering the Campus Email row site-wide (1 u-email / 142 cards as
    of 2026-07-24; it carried emails at the last audit). Email-less; cruzid in
    the profile link, so profile-enrich can recover it. Needs phase-2.
  * Ecology & Evolutionary Biology (EEB) — its only roster (eeb.ucsc.edu/people/)
    renders the h-card WITHOUT the Campus Email row (1 mailto / 192 cards).
    Email-less; the profile links carry the cruzid, so a profile-enrich pass
    can recover addresses. Needs phase-2.
  * Sociology — /people/faculty/ renders h-cards with Title + Website rows but
    NO Campus Email row (0 mailto / 50 cards). Email-less; cruzid in the profile
    link. Needs profile-enrich/phase-2.
  * Theater Arts — theater.ucsc.edu/people/ is a WordPress news feed, not a
    directory (0 h-cards even in raw HTML; roster painted elsewhere/client-side).
    No reachable roster. Phase-2.
  * Languages & Applied Linguistics (languages.ucsc.edu) — host does not resolve
    through the collector's network path (consistent DNS/000). Unreachable.

Single source ("ucsc_faculty"); department rides each record, ids namespaced
by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UCSC campus "h-card" people component. The title selector lands the
# inner rank <li> under the item-info row whose <strong> label is "Title".
_SEL = {
    "card": "div.section-item.h-card.wrap",
    "name": "h3.item-name span.p-name",
    "link": "h3.item-name a.u-url",
    "title": 'ul.item-info > li:has(> strong:-soup-contains("Title")) > ul.inline-list > li',
    "email": "a.u-email",
}

# Keep Professors (ladder + teaching + distinguished + research) and Lecturers;
# drop titleless staff, Deans/Directors/Vice-Provosts, and the grad students /
# postdocs / project scientists the directories mix in. Emeriti are dropped by
# the engine's own retired-title guard.
#
# A field_filter (not ladder_filter) is the gate here: staff/advisor cards carry
# NO "Title" row at all, and the engine defaults a missing title to "Professor" —
# which a ladder ``require`` would then wave through. field_filter's
# ``require_present`` reads the title element directly and drops the card when it
# is absent, so titleless staff are excluded before the default kicks in;
# ``include`` then keeps only Professor/Lecturer ranks.
_FIELD = {
    "selector": 'ul.item-info > li:has(> strong:-soup-contains("Title")) > ul.inline-list > li',
    "require_present": True,
    "include": r"professor|lecturer",
}

# MCD Biology's hand-built Gutenberg roster (no h-card, no rank text). Each
# faculty sits in a wp-block-column with an <h4> name link and a mailto; the
# engine defaults the (absent) rank to "Professor", which is correct for a
# faculty-only page. No field_filter — a column with no <h4> name is skipped by
# the engine, so layout-wrapper columns drop out on their own.
_MCD_SEL = {
    "card": "div.wp-block-column.is-layout-flow",
    "name": "h4.wp-block-heading a",
    "link": "h4.wp-block-heading a",
    "email": "a[href^='mailto:']",
}


# Research lives on the individual profile, in one of two campus templates:
# Baskin Engineering links out to campusdirectory.ucsc.edu, whose profile lists
# "Research Interests"/"Areas of Expertise" as a <ul><li> under a <label>; the
# PBSci SiteFarm dept profiles use a "Faculty Areas of Expertise" <dt>/<dd>.
# Both are matched — whichever the fetched profile carries wins, the other yields
# nothing (safe on depts with neither). Env-gated research-only per-profile pass.
_RESEARCH_ENRICH = {
    "research_items_selector": (
        'p:has(> label:-soup-contains("Research Interests")) > ul > li, '
        'p:has(> label:-soup-contains("Areas of Expertise")) > ul > li, '
        'div:has(> dt:-soup-contains("Areas of Expertise")) > dd'),
    "throttle": 0.2, "timeout": 8, "max_retries": 1,
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UCSC h-card component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD,
                   "profile_enrich": _RESEARCH_ENRICH},
    }


SCHOOL: dict = {
    "school_slug": "ucsc",
    "source": "ucsc_faculty",
    "organization": "University of California, Santa Cruz",
    "location": "Santa Cruz, CA",
    "id_prefix": "ucsc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC Santa Cruz) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Baskin School of Engineering ----------------------------------
        _dept("CS", "Department of Computer Science and Engineering",
              ["Computer Science", "Computer Engineering"],
              "https://engineering.ucsc.edu/departments/computer-science-and-engineering/people/"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://engineering.ucsc.edu/departments/electrical-and-computer-engineering/people/"),
        _dept("BME", "Department of Biomolecular Engineering",
              ["Biomolecular Engineering", "Bioinformatics", "Bioengineering"],
              "https://engineering.ucsc.edu/departments/biomolecular-engineering/people/"),
        _dept("STAT", "Department of Statistics", ["Statistics", "Data Science"],
              "https://engineering.ucsc.edu/departments/statistics/people/"),
        _dept("AM", "Department of Applied Mathematics",
              ["Applied Mathematics", "Mathematics"],
              "https://engineering.ucsc.edu/departments/applied-mathematics/people/"),
        # ---- Physical & Biological Sciences ---------------------------------
        _dept("PHYS", "Department of Physics", ["Physics", "Applied Physics"],
              "https://physics.ucsc.edu/people/faculty/"),
        _dept("MATH", "Department of Mathematics", ["Mathematics"],
              "https://math.ucsc.edu/people/"),
        _dept("EPS", "Department of Earth and Planetary Sciences",
              ["Earth Sciences", "Environmental Sciences"],
              "https://eps.ucsc.edu/people/"),
        _dept("OCEAN", "Department of Ocean Sciences",
              ["Marine Biology", "Environmental Sciences", "Ocean Sciences"],
              "https://ocean.ucsc.edu/people/senate-faculty/"),
        _dept("METX", "Department of Microbiology and Environmental Toxicology",
              ["Microbiology", "Environmental Toxicology", "Biology"],
              "https://metx.ucsc.edu/people/faculty/"),
        # MCD Biology — custom Gutenberg roster, own selector set.
        {"short": "MCD",
         "name": "Department of Molecular, Cell and Developmental Biology",
         "majors": ["Molecular, Cell, and Developmental Biology", "Biology",
                    "Neuroscience", "Human Biology"],
         "directory_url": "https://mcd.ucsc.edu/people/faculty/",
         "scrape": {"url": "https://mcd.ucsc.edu/people/faculty/",
                    "selectors": _MCD_SEL}},
        # ---- Social Sciences ------------------------------------------------
        _dept("PSYC", "Department of Psychology", ["Psychology", "Neuroscience"],
              "https://psychology.ucsc.edu/people/faculty/"),
        _dept("ECON", "Department of Economics",
              ["Economics", "Business Management Economics", "Global Economics"],
              "https://economics.ucsc.edu/people/faculty/"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthro.ucsc.edu/people/faculty/"),
        _dept("POLI", "Department of Politics", ["Politics", "Legal Studies"],
              "https://politics.ucsc.edu/people/faculty/"),
        _dept("ENVS", "Department of Environmental Studies",
              ["Environmental Studies", "Environmental Sciences"],
              "https://envs.ucsc.edu/people/faculty/"),
        _dept("LALS", "Department of Latin American and Latino Studies",
              ["Latin American and Latino Studies"],
              "https://lals.ucsc.edu/people/faculty/"),
        _dept("EDUC", "Department of Education",
              ["Education, Democracy, and Justice", "Education"],
              "https://education.ucsc.edu/people/faculty/"),
        # ---- Humanities -----------------------------------------------------
        _dept("HIST", "Department of History", ["History", "Classical Studies"],
              "https://history.ucsc.edu/people/"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.ucsc.edu/people/faculty/"),
        _dept("LIT", "Department of Literature", ["Literature"],
              "https://literature.ucsc.edu/people/literature-department-faculty/"),
        _dept("LING", "Department of Linguistics", ["Linguistics", "Language Studies"],
              "https://linguistics.ucsc.edu/people/faculty/"),
        _dept("FMST", "Department of Feminist Studies", ["Feminist Studies"],
              "https://feministstudies.ucsc.edu/people/"),
        _dept("CRES", "Department of Critical Race and Ethnic Studies",
              ["Critical Race and Ethnic Studies"],
              "https://cres.ucsc.edu/people-in-cres/"),
        # ---- Arts Division --------------------------------------------------
        _dept("ART", "Department of Art",
              ["Art", "Art and Design: Games and Playable Media"],
              "https://art.ucsc.edu/people/"),
        _dept("FILM", "Department of Film and Digital Media",
              ["Film and Digital Media"],
              "https://film.ucsc.edu/people/faculty/"),
        _dept("HAVC", "Department of History of Art and Visual Culture",
              ["History of Art and Visual Culture"],
              "https://havc.ucsc.edu/people/faculty/"),
        _dept("MUS", "Department of Music", ["Music"],
              "https://music.ucsc.edu/people/faculty/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
