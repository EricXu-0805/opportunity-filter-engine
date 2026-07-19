"""UC Santa Cruz faculty config (via the faculty_graph engine).

Every UCSC department directory probed for this pass runs the same
campus-standard "h-card" people component — server-rendered, no WAF, no JS
render needed (all seven pages return clean 200s to a plain request). One card
is ``div.section-item.h-card.wrap`` carrying:

* an ``h3.item-name`` with the display name in ``span.p-name`` and a profile
  link in ``a.u-url`` (Baskin Engineering depts link out to
  ``campusdirectory.ucsc.edu/cd_detail?uid=<cruzid>`` absolutely; physics and
  chemistry use a relative ``?directoryprofilecruzid=<cruzid>`` form the engine
  resolves against the directory URL);
* an ``ul.item-info`` list whose "Title" row holds the rank in a nested
  ``ul.inline-list``, and a "Campus Email" row with a plain ``a.u-email`` mailto.

Because the component is uniform, one shared selector set + one ladder gate
covers all departments. The listing carries no research/interests field, so
records land name+title+email only (topics come from downstream OpenAlex
enrichment) — that matches the recon (research_selector empty everywhere).

Title gate (``require: professor|lecturer``): the directories mix in staff,
advisors, and — in Chemistry especially — dozens of graduate students,
postdocs, project scientists, and researchers alongside faculty. Requiring a
"Professor"/"Lecturer" rank keeps ladder + teaching faculty and lecturers while
dropping titleless staff rows, Deans/Directors/Vice-Provosts, and the
grad-student/postdoc bulk. Emeriti are dropped by the engine's own
``_RETIRED_TITLE_RE`` (emeritus/emerita/retired), and chairs/directors that
appear twice (a leadership card + a faculty card) collapse via the engine's
name/url dedupe.

UCSC's "BME" is BIOMOLECULAR Engineering (genomics / protein / synthetic bio),
NOT biomedical. UCSC has no separate Math or Mechanical Engineering department,
so Applied Mathematics is included as the closest math unit.

Single source ("ucsc_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-19 (card counts / kept-after-gate): CS 88/66, ECE 48/34,
BME 39/28, Physics 45/34, Chemistry 142/30, Statistics 25/20, Applied Math
29/17 (pre-dedupe; the engine collapses cross-listed duplicates).
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UCSC campus "h-card" people component — identical markup on
# engineering.ucsc.edu, physics.ucsc.edu, and chemistry.ucsc.edu. The title
# selector lands the inner rank <li> under the item-info row whose <strong>
# label is "Title" (siblings are "Campus Email"/"Office Location").
_SEL = {
    "card": "div.section-item.h-card.wrap",
    "name": "h3.item-name span.p-name",
    "link": "h3.item-name a.u-url",
    "title": 'ul.item-info > li:has(> strong:-soup-contains("Title")) > ul.inline-list > li',
    "email": "a.u-email",
}

# Keep Professors (ladder + teaching + distinguished + research) and Lecturers;
# drop titleless staff, Deans/Directors/Vice-Provosts, and the grad students /
# postdocs / project scientists the Chemistry directory mixes in. Emeriti are
# dropped by the engine's own retired-title guard.
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


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UCSC h-card component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
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
        _dept("PHYS", "Department of Physics", ["Physics"],
              "https://physics.ucsc.edu/people/faculty/"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"],
              "https://chemistry.ucsc.edu/people-auto/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
