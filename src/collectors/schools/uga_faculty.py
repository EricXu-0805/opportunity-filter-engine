"""University of Georgia faculty config (via the faculty_graph engine).

UGA runs a single, remarkably uniform faculty-directory platform across the
Franklin College of Arts & Sciences department sites and the Warnell School:
a Drupal ("UGA Franklin" theme) "directory" View that renders every person as
a ``div.views-row`` carrying four fields — ``field-last-name`` (which despite
its name holds the FULL name inside an ``<h2>`` wrapped in an
``a.util-delink`` → ``/directory/people/<slug>`` profile link),
``field-job-title``, ``field-email`` (a plain ``mailto:`` — no obfuscation),
and ``field-experts-url``. Server-rendered, no WAF, no render mode anywhere;
~80 recon fetches all clean 200s (verified live 2026-07-19).

One selector family:

* ``franklin_directory`` — the shared Drupal directory View. Cards are
  ``div.views-row``; name = ``.views-field-field-last-name h2``; profile link
  = ``.views-field-field-last-name a`` (the name anchor — the email anchor
  also carries ``util-delink`` so we scope the link to the name cell); title =
  ``.views-field-field-job-title``; email = the ``mailto:`` in
  ``.views-field-field-email``. Titles occasionally append the person's
  terminal degree as a second span ("Associate Professor of Computer Science,
  Ph.D.: Middle East Technical University, 1998") — ``title_strip_after`` cuts
  at the "``, <Degree>:``" marker so the metadata rank stays clean and the
  ladder gate sees only the real rank (the rank always precedes the degree
  tail, so ladder matching is unaffected). Most sites live at
  ``/directory/faculty``; Physics & Astronomy uses ``/directory/Regular-
  Faculty`` and Chemistry uses ``/directory/Core-Faculty`` (their "Faculty"
  view mixes in cross-listed/affiliated people). Warnell is a Drupal-10 site
  but ships the IDENTICAL field markup, so it rides the same family. The
  faculty-only category path already excludes the emeritus/adjunct/courtesy/
  postdoc/staff/grad-student categories, so the ladder_filter is a light
  belt-and-suspenders gate (require professor|lecturer|instructor, drop the
  non-ladder roles). Each View renders its whole roster on one page (math 82,
  music 76, warnell 74 in a single fetch) — no pagination needed.

Emails and authoritative ranks are inline on every card, so no profile-enrich
pass is configured: the listing is already complete. Profiles carry only
contact/office info and an "Experts" link — no research-interest block — so
research keywords are left to the central OpenAlex enrichment pass.

Single source ("uga_faculty"); department rides each record, ids namespaced by
department short-code. Same-person cross-listings (e.g. a physics/chemistry
joint appointment appearing in both Regular-Faculty and Core-Faculty) collapse
on the engine's per-school contact_email dedup.

Deferred (2026-07-19 recon):
* College of Engineering (engineering.uga.edu) — WordPress; the ``team_member``
  custom post type is NOT REST-exposed and the /directory grid is a bespoke
  JS-driven template with no scrapeable roster. Needs a dedicated mechanism.
* Terry College of Business (terry.uga.edu) — WordPress ``directory`` CPT
  (employee-type=faculty ≈ 266) but the name/email/job-title live entirely in
  ACF fields the wp fetcher can't read (it reads ``meta_box`` only), and the
  public www.terry.uga.edu profile host is behind an Incapsula 403 wall, so
  profile-enrich can't recover them either.
* Grady College (grady.uga.edu) — WordPress ``faculty`` CPT but ``title
  .rendered`` is the surname only ("Dickinson") and all real fields are ACF.
* College of Agricultural & Environmental Sciences (caes.uga.edu) — custom
  ``.html`` platform (no Drupal View, no REST people feed) with per-department
  pages; each department needs bespoke selectors.
* College of Public Health, College of Education, School of Public &
  International Affairs — WordPress sites with no people custom-post-type
  exposed; directories are page-builder layouts without a stable roster feed.
* Lamar Dodd School of Art (art.uga.edu) — directory not on the shared View.
* Biochemistry & Molecular Biology (bcmb.uga.edu) — host did not resolve
  during recon; revisit.
"""

from __future__ import annotations

from .. import faculty_graph

# The faculty category already screens out emeritus/adjunct/courtesy/staff,
# so this is a light confirming gate.
_LADDER = {
    "require": r"professor|lecturer|instructor",
    "drop": r"emerit|adjunct|courtesy|visiting|\bpostdoc",
}

# Cut a trailing "``, <Degree>:`` <institution>" education clause off the rank.
_TITLE_STRIP = r",\s*[A-Za-z][A-Za-z.]{0,5}\.?\s*:"

_SELECTORS = {
    "card": "div.views-row",
    "name": ".views-field-field-last-name h2",
    "link": ".views-field-field-last-name a",
    "title": ".views-field-field-job-title",
    "title_strip_after": _TITLE_STRIP,
    "email": ".views-field-field-email a[href^='mailto:']",
}


def _dir(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UGA Franklin/Warnell directory View."""
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "uga",
    "source": "uga_faculty",
    "organization": "University of Georgia",
    "location": "Athens, GA",
    "id_prefix": "uga",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Georgia) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Franklin College of Arts & Sciences — sciences ----------------
        _dir("CS", "School of Computing", ["Computer Science"],
             "https://cs.uga.edu/directory/faculty"),
        _dir("PHYS", "Department of Physics and Astronomy",
             ["Physics", "Astronomy", "Astrophysics"],
             "https://physast.uga.edu/directory/Regular-Faculty"),
        _dir("CHEM", "Department of Chemistry", ["Chemistry"],
             "https://chem.uga.edu/directory/Core-Faculty"),
        _dir("MATH", "Department of Mathematics", ["Mathematics"],
             "https://math.uga.edu/directory/faculty"),
        _dir("STAT", "Department of Statistics", ["Statistics"],
             "https://stat.uga.edu/directory/faculty"),
        _dir("GENE", "Department of Genetics", ["Genetics"],
             "https://genetics.uga.edu/directory/faculty"),
        _dir("PBIO", "Department of Plant Biology", ["Plant Biology", "Biology"],
             "https://plantbio.uga.edu/directory/faculty"),
        _dir("CBIO", "Department of Cellular Biology",
             ["Cellular Biology", "Biology"],
             "https://cellbio.uga.edu/directory/faculty"),
        _dir("MIBO", "Department of Microbiology", ["Microbiology"],
             "https://mib.uga.edu/directory/faculty"),
        _dir("MARS", "Department of Marine Sciences", ["Marine Sciences"],
             "https://marsci.uga.edu/directory/faculty"),
        _dir("GEOG", "Department of Geography",
             ["Geography", "Atmospheric Sciences"],
             "https://geography.uga.edu/directory/faculty"),
        _dir("GEOL", "Department of Geology", ["Geology", "Earth Sciences"],
             "https://geology.uga.edu/directory/faculty"),
        _dir("PSYC", "Department of Psychology", ["Psychology"],
             "https://psychology.uga.edu/directory/faculty"),
        # ---- Franklin College — arts, humanities & social sciences ---------
        _dir("ENGL", "Department of English", ["English", "Creative Writing"],
             "https://english.uga.edu/directory/faculty"),
        _dir("HIST", "Department of History", ["History"],
             "https://history.uga.edu/directory/faculty"),
        _dir("PHIL", "Department of Philosophy", ["Philosophy"],
             "https://phil.uga.edu/directory/faculty"),
        _dir("CLAS", "Department of Classics", ["Classics", "Classical Culture"],
             "https://classics.uga.edu/directory/faculty"),
        _dir("RELG", "Department of Religion", ["Religion"],
             "https://religion.uga.edu/directory/faculty"),
        _dir("LING", "Department of Linguistics", ["Linguistics"],
             "https://linguistics.uga.edu/directory/faculty"),
        _dir("SOCI", "Department of Sociology", ["Sociology"],
             "https://sociology.uga.edu/directory/faculty"),
        _dir("ANTH", "Department of Anthropology", ["Anthropology"],
             "https://anthropology.uga.edu/directory/faculty"),
        _dir("ROML", "Department of Romance Languages",
             ["Romance Languages", "Spanish", "French", "Italian", "Portuguese"],
             "https://rom.uga.edu/directory/faculty"),
        _dir("MUS", "Hugh Hodgson School of Music", ["Music"],
             "https://music.uga.edu/directory/faculty"),
        _dir("THEA", "Department of Theatre and Film Studies",
             ["Theatre", "Film Studies"],
             "https://drama.uga.edu/directory/faculty"),
        _dir("COMM", "Department of Communication Studies",
             ["Communication Studies"],
             "https://comm.uga.edu/directory/faculty"),
        _dir("AFAM", "Department of African American Studies",
             ["African American Studies"],
             "https://afam.uga.edu/directory/faculty"),
        # ---- Warnell School of Forestry and Natural Resources --------------
        _dir("WARN", "Warnell School of Forestry and Natural Resources",
             ["Forestry", "Natural Resources", "Wildlife Sciences",
              "Fisheries and Aquatic Sciences"],
             "https://warnell.uga.edu/directory/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
