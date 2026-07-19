"""New York University faculty config (via the faculty_graph engine).

NYU is not one platform — it is several independent ecosystems, each on its
own CMS. This module covers the ones that expose a clean, uniform,
server-rendered faculty listing (all live-verified 2026-07-19); the many
hand-authored legacy A&S department pages are documented as DEFERRED below.
No WAF blocks any covered host and nothing needs render mode.

Selector families
=================

* ``tandon`` — the NYU Tandon School of Engineering directory
  (engineering.nyu.edu, Drupal 10). Every department publishes a
  ``/academics/departments/<dept>/people`` page of identical
  ``article.node--type-profile`` cards: the name in ``.field--name-title``,
  the academic rank in ``.field--name-field-title`` (note the ``-field-``
  infix — the class WITHOUT it is the name), and the profile link in
  ``a.card-img-link`` (``/faculty/<slug>``). No email or research on the
  card and the profile pages expose no mailto, so Tandon records ship
  title-only (OpenAlex fills topics centrally). ``ladder_filter`` keeps
  professor/lecturer/instructor rows (Industry/Research/Global professors
  included) and drops emeriti. Ten departments; because NYU cross-lists
  affiliated faculty across department rosters, the engine's per-school
  url/id dedup collapses the overlap into one record per person.

* ``courant`` — the Courant Institute (Computer Science + Mathematics), a
  bespoke Django CMS shared by cs.nyu.edu and math.nyu.edu:
    - CS: ``ul.people-listing li`` cards, name ``p.name a``, rank
      ``p.title``. The ``/type/22/`` view is the Tenure-Track & Contract
      core roster (drops the emeriti/adjunct/visiting/affiliated buckets).
      The listing email is spaced-obfuscated ("ba2008 at nyu.edu") which the
      engine's ``_clean_email`` does not fold, so CS is title-only.
    - Math: ``div.people-link`` cards (``figure.people`` photo grid), name
      ``h2.name``, rank the first ``div.people-description > div``. No link
      or email on the card (records fall back to the directory URL); the
      ``Courant Instructor`` postdocs are kept as instructors, emeriti
      dropped.

* ``as_dir`` — the modern NYU Arts & Science "faculty directory bio"
  component (as.nyu.edu AEM), a clean ``div.filtered-items-item`` card with
  ``a.facultydirectorybio-person__name``, a ``span…__position`` rank and an
  inline ``span…__email a[mailto]``. Only two A&S departments have migrated
  to it so far: Psychology and the Center for Neural Science. The rank gate
  keeps professor/lecturer/instructor and drops emeriti (adjunct/clinical
  professors are kept — real mentoring faculty).

* ``as_flex`` — the legacy A&S hand-authored bio layout (Physics), a
  photo/text ``div[style*=flex]`` row with an ``<h3>`` name, the rank as a
  bare text node (recovered by ``title_re``) and the profile link. The page
  interleaves Department / Visiting / Associated / NYU Abu Dhabi / NYU
  Shanghai / Emeritus / In Memoriam sections, so a ``section_filter`` on the
  ``<h2>`` keeps only "Department Faculty". Listing carries no email; the
  env-gated profile pass backfills it from the profile page's mailto.

* ``steinhardt`` — the NYU Steinhardt School of Culture, Education, and Human
  Development directory (steinhardt.nyu.edu, Drupal). One page renders all
  ~320 faculty as ``div.teaser`` cards with the name
  (``.teaser__title-link``), rank (``.teaser__subtitle``) and an inline
  mailto (``a.teaser__link``). The department exposed-filter is client-side
  only (no per-card department attribute, no server/AJAX filter), so
  Steinhardt lands as ONE school-level department entry; the rank gate keeps
  professor/lecturer/instructor/artist and drops emeriti.

Single source ("nyu_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

Deferred (2026-07-19 recon)
===========================
* Most legacy A&S departments (Chemistry, Biology, English, History,
  Anthropology, French, German, Sociology, Linguistics, Philosophy,
  Economics, and the language/area departments) — each is a distinct
  hand-authored AEM page (``article.generic-content`` prose ``<p>`` lists, or
  ``div.columns-body.cols-25-75`` two-column grids) where name, rank and
  email are not in any consistent card structure. Each needs bespoke
  per-department selectors; deferred to a later pass rather than shipped
  fragile.
* Center for Data Science (cds.nyu.edu) — 403 WAF on the directory.
* Stern School of Business — the /faculty/search_name directory 302-redirects
  to a JS app with no server-rendered roster.
* Wagner (public policy) and the Silver School of Social Work — client-
  rendered directories with no server HTML roster / no inline email found.
* Law, Tisch, Gallatin, Global Public Health, School of Professional Studies,
  Dentistry, NYU Grossman School of Medicine (clinical scale) — separate
  platforms, not probed this session.
* NYU Abu Dhabi / NYU Shanghai portal campuses — out of scope for the
  New York, NY campus.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- shared ladder gates ---------------------------------------------------
# Keep professorial + teaching ranks; drop emeriti wherever a listing mixes
# them in. Adjunct/clinical/industry/research professors are kept (real
# mentoring faculty); postdocs/staff fail the "professor|lecturer|instructor"
# requirement.
_KEEP = r"professor|lecturer|instructor"
_KEEP_ARTS = r"professor|lecturer|instructor|artist"
_DROP = r"emerit"
_LADDER = {"require": _KEEP, "drop": _DROP}
_LADDER_ARTS = {"require": _KEEP_ARTS, "drop": _DROP}
_DROP_ONLY = {"drop": _DROP}


# ---- Tandon (engineering.nyu.edu Drupal profile cards) ---------------------
_TANDON_SELECTORS = {
    "card": "article.node--type-profile",
    "name": ".field--name-title",
    "link": "a[href*='/faculty/']",
    "title": ".field--name-field-title",
}
_TANDON_BASE = "https://engineering.nyu.edu/academics/departments"


def _tandon(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Tandon department served by the shared /people profile-card view.

    ``slug`` is the department machine name in the /people path (it differs
    from the department landing slug for Civil & Urban)."""
    url = f"{_TANDON_BASE}/{slug}/people"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _TANDON_SELECTORS,
                       "ladder_filter": _LADDER}}


# ---- Arts & Science modern "faculty directory bio" component ---------------
_AS_DIR_SELECTORS = {
    "card": "div.filtered-items-item",
    "name": "a.facultydirectorybio-person__name",
    "link": "a.facultydirectorybio-person__name",
    "title": "span.facultydirectorybio-person__position",
    "email": "span.facultydirectorybio-person__email a[href^='mailto:']",
}


def _as_dir(short: str, name: str, majors: list[str], slug: str) -> dict:
    """An A&S department on the modern filtered-items-item directory."""
    url = f"https://as.nyu.edu/departments/{slug}/people/faculty.html"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_DIR_SELECTORS,
                       "ladder_filter": _LADDER}}


# ---- Physics: legacy A&S hand-authored flex bio rows -----------------------
# Rank is a bare text node after the <h3> name ("Associate Professor of
# Physics", immediately followed by "Personal Homepage"/"Lab Homepage" link
# text in the same run of text). Capture the rank word + its leading
# modifiers only — anchored to real rank modifiers so the preceding name is
# never swallowed and the trailing homepage link text is never absorbed.
_AS_TITLE_RE = (
    r"((?:(?:University |Global |Distinguished |Silver |Collegiate |Clinical "
    r"|Research |Associate |Assistant |Visiting |Adjunct )*)"
    r"(?:Professor|Lecturer|Instructor)"
    r"(?:\s+(?:of|in)\s+Physics)?)"
)
_PHYS_SELECTORS = {
    "card": "div[style*='display: flex']:has(h3)",
    "name": "h3",
    "link": "a[href*='/faculty/']",
    "title_re": _AS_TITLE_RE,
}
# The AEM profile page (/content/nyu-as/as/faculty/<slug>.html) carries a
# clean personal mailto — the env-gated pass backfills it.
_AS_ENRICH = {"email_selector": "a[href^='mailto:']", "throttle": 0.3}


# ---- Steinhardt (steinhardt.nyu.edu Drupal teaser directory) ---------------
_STEIN_SELECTORS = {
    "card": "div.teaser:has(a.teaser__title-link)",
    "name": "a.teaser__title-link",
    "link": "a.teaser__title-link",
    "title": ".teaser__subtitle",
    "email": "a.teaser__link[href^='mailto:']",
}


SCHOOL: dict = {
    "school_slug": "nyu",
    "source": "nyu_faculty",
    "organization": "New York University",
    "location": "New York, NY",
    "id_prefix": "nyu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (New York University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Tandon School of Engineering ---------------------------------
        _tandon("CSE", "Department of Computer Science and Engineering",
                ["Computer Science", "Computer Engineering"],
                "computer-science-and-engineering"),
        _tandon("ECE", "Department of Electrical and Computer Engineering",
                ["Electrical Engineering", "Computer Engineering"],
                "electrical-and-computer-engineering"),
        _tandon("MAE", "Department of Mechanical and Aerospace Engineering",
                ["Mechanical Engineering", "Aerospace Engineering"],
                "mechanical-and-aerospace-engineering"),
        _tandon("BME", "Department of Biomedical Engineering",
                ["Biomedical Engineering"], "biomedical-engineering"),
        _tandon("CUE", "Department of Civil and Urban Engineering",
                ["Civil Engineering", "Urban Engineering", "Environmental Engineering"],
                "civil-and-urban-engineering"),
        _tandon("CBE", "Department of Chemical and Biomolecular Engineering",
                ["Chemical Engineering", "Biomolecular Engineering"],
                "chemical-and-biomolecular-engineering"),
        _tandon("FRE", "Department of Finance and Risk Engineering",
                ["Financial Engineering", "Risk Engineering"],
                "finance-and-risk-engineering"),
        _tandon("APHY", "Department of Applied Physics",
                ["Applied Physics"], "applied-physics"),
        _tandon("TMI", "Department of Technology Management and Innovation",
                ["Technology Management", "Management of Technology"],
                "technology-management-and-innovation"),
        _tandon("TCS", "Department of Technology, Culture and Society",
                ["Integrated Digital Media", "Science and Technology Studies"],
                "technology-culture-and-society"),
        # ---- Courant Institute of Mathematical Sciences -------------------
        {"short": "CS", "name": "Department of Computer Science (Courant)",
         "majors": ["Computer Science", "Data Science"],
         "directory_url": "https://cs.nyu.edu/dynamic/people/faculty/",
         "scrape": {"url": "https://cs.nyu.edu/dynamic/people/faculty/type/22/",
                    "selectors": {"card": "ul.people-listing li",
                                  "name": "p.name a", "link": "p.name a",
                                  "title": "p.title"},
                    "ladder_filter": _LADDER}},
        {"short": "MATH", "name": "Department of Mathematics (Courant)",
         "majors": ["Mathematics", "Applied Mathematics"],
         "directory_url": "https://math.nyu.edu/dynamic/people/faculty/",
         "scrape": {"url": "https://math.nyu.edu/dynamic/people/faculty/",
                    "selectors": {"card": "div.people-link",
                                  "name": "h2.name", "link": "h2.name",
                                  "title": "div.people-description > div"},
                    "ladder_filter": _DROP_ONLY}},
        # ---- Faculty of Arts and Science ----------------------------------
        _as_dir("PSYCH", "Department of Psychology", ["Psychology"], "psychology"),
        _as_dir("CNS", "Center for Neural Science",
                ["Neural Science", "Neuroscience"], "cns"),
        {"short": "PHYS", "name": "Department of Physics", "majors": ["Physics"],
         "directory_url": "https://as.nyu.edu/departments/physics/people/faculty.html",
         "scrape": {"url": "https://as.nyu.edu/departments/physics/people/faculty.html",
                    "selectors": _PHYS_SELECTORS,
                    "section_filter": {"heading": "h2", "include": r"^department faculty$"},
                    "ladder_filter": _DROP_ONLY,
                    "profile_enrich": _AS_ENRICH}},
        # ---- Steinhardt School (one school-level entry) -------------------
        {"short": "STEIN",
         "name": "Steinhardt School of Culture, Education, and Human Development",
         "majors": ["Education", "Applied Psychology", "Media, Culture, and Communication",
                    "Music", "Art and Art Professions", "Nutrition and Food Studies",
                    "Physical Therapy", "Occupational Therapy",
                    "Communicative Sciences and Disorders", "Applied Statistics"],
         "directory_url": "https://steinhardt.nyu.edu/faculty",
         "scrape": {"url": "https://steinhardt.nyu.edu/faculty",
                    "selectors": _STEIN_SELECTORS,
                    "ladder_filter": _LADDER_ARTS}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
