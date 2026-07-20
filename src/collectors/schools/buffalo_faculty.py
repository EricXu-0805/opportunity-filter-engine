"""University at Buffalo (SUNY) faculty config (via the faculty_graph engine).

All six buildable departments share ONE campus component — UB's Communique CMS
``profileinfo-teaser`` card — served as a plain static HTTP 200 to a bare request
(no WAF, no JS render). Live-verified 2026-07-20. One card is a
``div.profileinfo-teaser.teaser-block`` holding:

* ``div.profileinfo-teaser-name`` whose first ``<a>`` is the display name (the
  link points at the person's ``…host.html/content/shared/…`` profile page). The
  name text carries a trailing ``,PhD`` credential the engine's
  ``_strip_credentials`` removes, and a sibling ``.profileinfo-teaser-degree``
  ("PhD, University of Chicago") that is OUTSIDE the anchor, so the name selector
  never absorbs it;
* the rank in a per-card element that DIFFERS by CMS skin — the Engineering and
  Arts&Sciences "new-profiles" sites (CSE/EE/Physics/Chemistry/MAE) put it in
  ``.profileinfo-teaser-dept-title``; the ``www.buffalo.edu/cas`` skin
  (Mathematics) puts it in ``.profileinfo-teaser-school-title``. One combined
  ``title`` selector covers both (only one variant exists per card);
* ``.profileinfo-teaser-contact`` with a ``mailto`` where the directory exposes an
  address (all six do — coverage is 90–100% per dept; the handful of profiles
  that publish no listing address are recovered by the downstream per-profile
  enrich pass via the profile link);
* an interests block whose topic list follows a
  ``.profileinfo-teaser-interests-title`` label span. The label wording varies by
  dept ("Research Topics:", "Research Interests:", and — on EE —
  "Specialty/Research Focus:", which the engine's shared label-strip does NOT
  know), so ``research`` is captured with a ``research_re`` that grabs the text
  AFTER the label span rather than a CSS selector that would fold the label into
  the first keyword chip. Departments that omit the block (Physics, Mathematics)
  land name+title+email and topics come from OpenAlex enrichment.

Title gate (``field_filter``): the directories mix in emeriti, a lone Instructor
(Chemistry), and — crucially — real professors whose FIRST rank element is an
administrative role ("Department Chair", "Associate Dean for Research",
"Director of Undergraduate Studies"). The clean per-card rank element
(``…-dept-title`` / ``…-school-title``) shows only that first role, so gating on
it would drop those real professors. Instead the ``field_filter`` reads the
fuller ``.profileinfo-teaser-titles`` blob ("Department Chair Professor
Department of Physics …"), which carries the "Professor" word wherever the person
holds a ladder rank — ``require_present`` drops title-less cards, ``include``
keeps only ranks containing professor/lecturer (dropping the Instructor and any
pure-admin/staff card), and the engine's own ``_RETIRED_TITLE_RE`` — run on the
clean per-card rank ("Emeritus") — drops the emeriti even though their titles
blob contains "Professor Emeritus". The displayed ``title`` stays the clean
per-card rank; an administrator's card shows their admin role (accurate — they do
hold it).

Single source ("buffalo_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-20 (cards / kept-after-gate): CSE 66/66, EE 28/28,
Physics 39/34 (5 emeriti dropped), Chemistry 32/31 (1 Instructor dropped),
Mathematics 47/47, MAE 28/27 (a duplicated Battaglia card collapses on id).
Emails land on ~95% of kept records; the two Chemistry professors and any others
without a listing mailto are recovered by the profile-enrich pass.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UB Communique "profileinfo-teaser" card. The first <a> under
# ``.profileinfo-teaser-name`` is the name+profile link (the degree line is a
# sibling div outside it). The rank element differs by CMS skin — Engineering /
# Arts&Sciences use ``…-dept-title``, the ``www.buffalo.edu/cas`` skin (Math)
# uses ``…-school-title`` — so the ``title`` selector matches either (only one
# exists per card). Email is the first mailto in the contact block; research is
# captured after the interests label span (research_re) so a non-standard label
# ("Specialty/Research Focus:" on EE) never leaks into the first keyword chip.
_SEL = {
    "card": "div.profileinfo-teaser",
    "name": ".profileinfo-teaser-name a",
    "link": ".profileinfo-teaser-name a",
    "title": ".profileinfo-teaser-dept-title, .profileinfo-teaser-school-title",
    "research_re": r"profileinfo-teaser-interests-title[^>]*>.*?</span>(.*?)</p>",
    "email": ".profileinfo-teaser-contact a[href^='mailto:']",
}

# Gate on the FULL titles blob (not the clean per-card rank) so a real professor
# whose first rank element is an admin role ("Department Chair") — but whose blob
# reads "Department Chair Professor …" — is kept, while the lone Instructor and
# any staff/title-less card are dropped. require_present blocks the missing-title
# default-to-"Professor"; emeriti drop via the engine's retired gate on the clean
# per-card rank.
_FIELD = {
    "selector": ".profileinfo-teaser-titles",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UB profileinfo-teaser component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


SCHOOL: dict = {
    "school_slug": "buffalo",
    "source": "buffalo_faculty",
    "organization": "University at Buffalo",
    "location": "Buffalo, NY",
    "id_prefix": "buffalo",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University at Buffalo, SUNY) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Engineering and Applied Sciences --------------------
        _dept("CSE", "Department of Computer Science and Engineering",
              ["Computer Science", "Computer Engineering", "Data Science"],
              "https://engineering.buffalo.edu/computer-science-engineering/people/faculty-directory.html"),
        _dept("EE", "Department of Electrical Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://engineering.buffalo.edu/ee/faculty/faculty_directory.html"),
        _dept("MAE", "Department of Mechanical and Aerospace Engineering",
              ["Mechanical Engineering", "Aerospace Engineering"],
              "https://engineering.buffalo.edu/mechanical-aerospace/people/faculty.html"),
        # ---- College of Arts and Sciences ----------------------------------
        _dept("PHYS", "Department of Physics", ["Physics"],
              "https://arts-sciences.buffalo.edu/physics/faculty/faculty-directory.html"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              "https://arts-sciences.buffalo.edu/chemistry/faculty/faculty-directory.html"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"],
              "https://www.buffalo.edu/cas/math/people/faculty.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
