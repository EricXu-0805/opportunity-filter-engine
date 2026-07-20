"""University of Kentucky faculty config (via the faculty_graph engine).

Two server-rendered markup families, both plain static 200s through the proxy
(no WAF, no JS render). Live-verified 2026-07-20.

* **College of Engineering — one shared Drupal "people-list" View.**
  All seven engineering departments render from ONE base
  (``engr.uky.edu/people``) differentiated only by a server-side
  ``?field_department_target_id=<id>`` filter, so every department is the exact
  same markup at a different URL. The View is a two-column table; each person is
  one ``td.views-field-rendered-entity`` cell holding
  ``span.people-list--name > a.underline-link`` (name + ``/people/<slug>``
  profile link), ``span.people-list--title`` (rank), and a ``contact-info``
  definition list whose Email ``<dd>`` carries a PLAIN ``mailto:`` (emails land
  on the listing at ~100%). The View mixes ladder faculty with department Staff
  (advisors, coordinators, systems programmers, business officers) and Emeriti,
  so a ladder gate (``require professor|lecturer|instructor``) drops the Staff
  bucket and the engine's own retired-title guard drops the Emeriti. A handful of
  real faculty carrying only an endowed-chair / dean / interim-chair title with
  no "Professor" word are dropped by the gate too (accuracy over recall, so no
  staff leak in). No pagination — every department's full roster is on one page
  (card counts match recon exactly: CS 46, ECE 50, MAE 62, BME 18, CME 39,
  CE 37, Mining 21).

* **College of Arts & Sciences — one shared Drupal "directory-card" grid.**
  Physics/Chemistry/Mathematics/Statistics each live on their own
  ``<dept>.as.uky.edu/faculty`` subdomain but share one card component:
  ``div.directory-card`` wrapping a ``.directory-content`` block whose bold div
  (``div.text.color-wildcat-blue.font-bold > a``) holds the name +
  ``/users/<netid>`` profile link and whose sibling non-bold div
  (``div.text.color-wildcat-blue:not(.font-bold)``) holds the rank. There is NO
  email anywhere on these listings (0 mailto) — name+title-only records here;
  addresses come from the downstream per-profile enrichment pass via the
  ``/users/<netid>`` link. The same ladder gate keeps professors/lecturers/
  instructors and drops the few coordinators/joint-faculty/blank-title cards;
  emeriti drop via the retired-title guard. Mathematics paginates (``?page=N``,
  40 on page 0 + 6 on page 1 = 46) so it carries a ``paginate`` block; the other
  three are single-page. Two Mathematics name anchors bake the rank into the
  anchor text ("Richard Ehrenborg, Professor") — a ``name_strip`` trims the
  trailing ", … Professor" so the pi_name is clean.

Single source ("uky_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-20 (cards → kept-after-gate): see the onboarding report.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- College of Engineering: shared Drupal people-list table ---------------
# One person = one rendered-entity cell. Name/title in dedicated spans; the
# email is the plain mailto in the contact-info definition list (a sibling tel:
# link is ignored because the selector keys on the mailto scheme). Profile hrefs
# are root-relative (/people/<slug>) and the engine urljoins them onto the base.
_ENG_SEL = {
    "card": "td.views-field-rendered-entity",
    "name": "span.people-list--name a.underline-link",
    "link": "span.people-list--name a.underline-link",
    "title": "span.people-list--title",
    "email": "a[href^='mailto:']",
}
# Keep ladder + teaching (lecturer/instructor) faculty; drop the Staff bucket
# (advisors, coordinators, systems/business staff) whose titles carry none of
# these words. Emeriti pass this gate ("Emeritus Professor" contains "Professor")
# and are dropped by the engine's own retired-title guard in _normalize.
_ENG_LADDER = {"require": r"professor|lecturer|instructor"}


def _eng(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    """An engineering department on the shared people-list table."""
    url = f"https://engr.uky.edu/people?field_department_target_id={dept_id}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "ladder_filter": _ENG_LADDER},
    }


# ---- College of Arts & Sciences: shared Drupal directory-card grid ----------
# The bold div holds the name link (/users/<netid>); the non-bold sibling div
# holds the rank. No email on the listing (enrichment recovers it via the
# profile link). name_strip trims a rank baked into two Mathematics anchors.
_AS_SEL = {
    "card": "div.directory-card",
    "name": "div.directory-content div.font-bold a",
    "link": "div.directory-content div.font-bold a",
    "name_strip": r",\s*[A-Za-z ]*Professor\s*$",
    "title": "div.directory-content div.text.color-wildcat-blue:not(.font-bold)",
}
_AS_LADDER = {"require": r"professor|lecturer|instructor"}


def _as(short: str, name: str, majors: list[str], url: str,
        paginate: dict | None = None) -> dict:
    """An Arts & Sciences department on the shared directory-card grid."""
    scrape = {"url": url, "selectors": _AS_SEL, "ladder_filter": _AS_LADDER}
    if paginate:
        scrape["paginate"] = paginate
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": scrape,
    }


SCHOOL: dict = {
    "school_slug": "uky",
    "source": "uky_faculty",
    "organization": "University of Kentucky",
    "location": "Lexington, KY",
    "id_prefix": "uky",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Kentucky) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (shared people-list table) -------------
        _eng("CS", "Department of Computer Science",
             ["Computer Science", "Data Science"], 30),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], 38),
        _eng("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], 54),
        _eng("BME", "F. Joseph Halcomb III, M.D. Department of Biomedical Engineering",
             ["Biomedical Engineering"], 17),
        _eng("CME", "Department of Chemical and Materials Engineering",
             ["Chemical Engineering", "Materials Engineering", "Materials Science"], 24),
        _eng("CE", "Department of Civil Engineering",
             ["Civil Engineering", "Environmental Engineering"], 27),
        _eng("MNG", "Department of Mining Engineering",
             ["Mining Engineering"], 55),
        # ---- College of Arts & Sciences (shared directory-card grid) -------
        _as("PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astronomy"], "https://pa.as.uky.edu/faculty"),
        _as("CHEM", "Department of Chemistry",
            ["Chemistry", "Biochemistry"], "https://chem.as.uky.edu/faculty"),
        _as("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"], "https://math.as.uky.edu/faculty",
            paginate={"param": "page", "max": 3}),
        _as("STAT", "Dr. Bing Zhang Department of Statistics",
            ["Statistics", "Data Science"], "https://stat.as.uky.edu/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
