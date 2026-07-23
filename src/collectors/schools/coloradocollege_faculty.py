"""Colorado College faculty config (via the faculty_graph engine).

Colorado College is a top-tier US liberal arts college (~2,000
undergraduates, no graduate school) in Colorado Springs, CO, famous for the
"Block Plan" (one course at a time in intensive three-and-a-half-week
blocks). Its entire public site is a single SiteExecutive (Bootstrap-5) CMS
build, and every academic department publishes its roster with the SAME
person-card component, so ONE selector family covers the whole college — the
only per-department variation is the URL of the roster page (departments
place their faculty listing under an idiosyncratic path such as
``people/faculty.html``, ``people/index.html``, ``about_us/faculty_staff.html``,
``people/department-faculty.html``, etc.).

Live-verified 2026-07-23 (~50 clean HTTP 200s over curl, no WAF, no render
mode anywhere):

* Person card — ``div.panel-body``. Inside it, ``.panel-title a`` is the name
  and the profile link (an absolute
  ``/basics/contact/directory/people/<slug>.html`` central-directory URL),
  ``.text-muted.depts`` carries the rank ("Professor", "Associate Professor,
  Chair", "Assistant Professor", "Senior Lecturer"), and ``.email a[mailto]``
  is the inline public email (present for essentially every professor, so no
  profile-enrichment pass is needed). Pronouns live in a separate ``<em>``
  sibling under ``.panel-title`` and are NOT captured in the name.

Ladder gate keeps professorial + lecturer + instructor ranks (the
cold-emailable research/teaching faculty) and drops emeriti, visiting, and
adjunct appointments plus the departmental staff / lab coordinators /
technicians (whose card titles carry none of those words) that share the same
component on the "Faculty & Staff" style pages.

Single source ("coloradocollege_faculty"); department rides each record, ids
namespaced by department short-code. Several CC departments are heavily
cross-listed (e.g. Asian Studies, Neuroscience, Feminist & Gender Studies,
Comparative Literature, and Southwest Studies pull faculty whose home
department — Political Science, Psychology, Molecular Biology, English, etc. —
is also captured); the engine's per-school email/url dedup collapses those to
a single record, attributing each professor to a home department listed first.

Deferred (2026-07-23 recon):
* Biology — an umbrella gateway page with no roster of its own; the biologists
  are captured under Molecular Biology, Organismal Biology & Ecology, and
  Human Biology & Kinesiology.
* Film and Media Studies and Race, Ethnicity, and Migration Studies — purely
  interdisciplinary programs with no faculty-roster page; their affiliated
  faculty are captured via their home departments above.
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.coloradocollege.edu/academics/dept"

# Shared CC person-card component (SiteExecutive Bootstrap-5, static HTML).
_SELECTORS = {
    "card": "div.panel-body",
    "name": ".panel-title a",
    "link": ".panel-title a",
    "title": ".text-muted.depts",
    "email": ".email a[href^='mailto:']",
}

# Keep professorial + lecturer + instructor ranks; drop emeriti, visiting, and
# adjunct appointments as well as the staff / coordinator / technician rows
# (no professorial rank) that share the same card markup.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|visiting|adjunct",
}


def _dept(short: str, name: str, majors: list[str], slug: str, path: str) -> dict:
    """A CC department on the shared panel-body person-card component."""
    url = f"{_BASE}/{slug}/{path}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "coloradocollege",
    "source": "coloradocollege_faculty",
    "organization": "Colorado College",
    "location": "Colorado Springs, CO",
    "id_prefix": "coloradocollege",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Colorado College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics (core departments first) -------
        _dept("CHEM", "Department of Chemistry & Biochemistry",
              ["Chemistry", "Biochemistry"], "chemistry", "people/index.html"),
        _dept("MATHCS", "Department of Mathematics & Computer Science",
              ["Mathematics", "Computer Science"], "MathCS", "people/faculty.html"),
        _dept("PHYS", "Department of Physics", ["Physics"], "physics",
              "people/faculty.html"),
        _dept("GEOL", "Department of Geology", ["Geology"], "geology",
              "about-us/our-people.html"),
        _dept("MOLB", "Department of Molecular Biology", ["Molecular Biology"],
              "molecularbiology", "people/index.html"),
        _dept("OBE", "Department of Organismal Biology & Ecology",
              ["Organismal Biology", "Ecology"], "obe", "people/index.html"),
        _dept("HBK", "Department of Human Biology and Kinesiology",
              ["Human Biology and Kinesiology"], "humanbiologykinesiology",
              "people/index.html"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology",
              "people/index.html"),
        _dept("ENVS", "Environmental Studies and Science Program",
              ["Environmental Studies", "Environmental Science"],
              "environmentalstudiesscience", "people/ev-faculty.html"),
        _dept("NEUR", "Neuroscience Program", ["Neuroscience"], "neuroscience",
              "people/advisorsnew.html"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology", "about_us/faculty_staff.html"),
        _dept("ECON", "Department of Economics & Business",
              ["Economics", "Business"], "economics",
              "people/department-faculty.html"),
        _dept("HIST", "Department of History", ["History"], "history",
              "people/faculty-and-staff.html"),
        _dept("POLS", "Department of Political Science", ["Political Science"],
              "politicalscience", "people/ps-faculty-and-staff.html"),
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology",
              "people1/faculty-staff.html"),
        _dept("EDUC", "Education Department", ["Education"], "education",
              "people/faculty.html"),
        _dept("SWST", "Southwest Studies Program", ["Southwest Studies"],
              "southweststudies", "people/index.html"),
        # ---- Humanities ----------------------------------------------------
        _dept("ENGL", "Department of English", ["English", "Creative Writing"],
              "english", "people/faculty1.html"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy",
              "people/index.html"),
        _dept("RELG", "Department of Religion, Culture, Power", ["Religion"],
              "religion", "people/index.html"),
        _dept("CLAS", "Department of Classics", ["Classics"], "classics",
              "people/faculty.html"),
        _dept("CPLT", "Comparative Literature Program",
              ["Comparative Literature"], "comparativeliterature",
              "people/faculty1.html"),
        _dept("ASST", "Asian Studies Program", ["Asian Studies"], "asianstudies",
              "people/index.html"),
        _dept("GREAL",
              "Department of Chinese, German, Italian, Japanese and Russian Studies",
              ["Chinese", "German", "Italian", "Japanese", "Russian"], "greal",
              "people/faculty-staff.html"),
        _dept("FREN", "French & Francophone Studies Department", ["French"],
              "french", "people/index.html"),
        _dept("SPAN", "Department of Spanish & Portuguese",
              ["Spanish", "Portuguese"], "spanish", "about/people/index.html"),
        _dept("FGS", "Feminist & Gender Studies Program",
              ["Feminist and Gender Studies"], "feministandgenderstudies",
              "people/faculty.html"),
        # ---- Arts ----------------------------------------------------------
        _dept("ART", "Department of Art", ["Studio Art", "Art History"], "art",
              "people/faculty.html"),
        _dept("MUS", "Department of Music", ["Music"], "music",
              "people/index.html"),
        _dept("THDA", "Department of Theatre and Dance", ["Theatre", "Dance"],
              "theatredance", "people/index.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
