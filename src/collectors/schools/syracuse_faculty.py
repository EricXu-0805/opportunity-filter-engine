"""Syracuse University faculty config (via the faculty_graph engine).

Two server-rendered markup families, both plain static 200s to a bare request
through the proxy (no WAF, no JS render). Live-verified 2026-07-20.

* **College of Engineering & Computer Science — one shared WordPress directory.**
  All four ECS departments render from ONE combined ``ecs.syracuse.edu/
  faculty-staff/`` roster, differentiated by a server-side ``?category=<slug>``
  filter (so each department's scrape is the same page with a different query).
  Each person is a ``div.ecs-profile`` card: ``div.profile-name > a`` (name +
  ``/faculty-staff/<slug>`` profile link) and ``div.profile-title`` (rank). The
  listing mixes in department staff (Budget Manager, Office Coordinator, Academic
  Operations Specialist, Assistant to the Chair, Director of Academic Operations)
  and emeriti; the ladder gate (require ``professor|lecturer|instructor``) drops
  the staff, and the engine's own retired-title guard drops the emeriti. A few
  real chairs whose card title carries only an administrative role ("… Department
  Chair", "Interim Dean") and no professor word are dropped by the gate —
  accuracy over recall.

  EMAIL is absent from every ECS listing card (0 mailto). It lives on each
  person's profile page (``ecs.syracuse.edu/faculty-staff/<slug>``) as PLAIN
  TEXT (no mailto, no obfuscation) inside ``div.entry-content`` — so a
  ``profile_enrich`` block with ``email_selector: div.entry-content`` recovers it
  under the per-profile enrichment pass (``_email_from_el`` extracts the first
  address-shaped token; office/department precede it and carry no ``@``). The
  listing scrape itself lands name+title, emails arrive with enrichment.

* **College of Arts & Sciences — shared Wagtail "personcontainer" component.**
  physics / chemistry / mathematics / biology / earth-sciences each render one
  ``section.personcontainer`` per person, but the per-department directory URLs
  are inconsistent (hardcoded each). The directories are "faculty-and-staff" /
  "directory" rosters that mix core ladder faculty with affiliated/courtesy
  faculty (``/people/affiliated-faculty/`` — primary appointment in another
  department: EECS, Biomedical, Air Force Research Lab, other institutions),
  postdocs (``/people/research-associates/``), staff (``/people/staff/``),
  graduate students (``/people/graduate-students/``), and part-time instructors
  (``/people/part-time/``). Only the CORE faculty carry a ``/people/faculty/``
  profile link, so the name selector ``a[href*='/people/faculty/']`` isolates
  the home-department ladder exactly — it returns nothing on a non-faculty card
  (which is then skipped), and every faculty card carries exactly one such link
  (no portrait-link duplication on these pages, verified). Excluding the
  affiliated set is deliberate: those people are cross-listed from other
  departments (and appear as core faculty on their own ECS/other pages), so
  admitting them here would inject wrong-department professors and double-count.

  Title: regular faculty carry ``span.university-title``; department chairs /
  leadership render the rank in a leading ``<p>`` instead — ``span.university-
  title, p`` (first match in document order) covers both, and a leadership card
  with no rank word still defaults to "Professor" and passes the gate. Email is
  a PLAIN ``mailto`` on every A&S card. The ladder gate + the engine's
  retired-title guard drop the emeriti the directories list (Physics and Biology
  carry a dozen+ each) and non-ladder titles ("Faculty Fellow").

  Mathematics differs only in that the name link is a bare ``<a>`` (no wrapping
  ``<strong>``) and the email sits in ``div.show_email > a`` — both reached by
  the shared selectors unchanged.

Single source ("syracuse_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-20 (listing cards → kept-after-gate):
  ECS EECS 52/47, MAE 40/33, BMCE 24/19, CEE 28/21;
  A&S Physics 54/42, Chemistry 31/24, Mathematics 29/29, Biology 67/52,
  Earth & Env. Sciences 31/25.
Emails land on the A&S departments from the listing mailto (~100% of kept);
the four ECS departments land name+title on the listing and recover email via
the ``div.entry-content`` profile enrich pass.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- College of Engineering & Computer Science: shared ecs-profile card ----
# One combined ecs.syracuse.edu/faculty-staff/ directory, per-department via a
# ?category=<slug> query. No email on the listing card; the profile page carries
# it as plain text in div.entry-content (recovered by the enrich pass).
_ECS_SEL = {
    "card": "div.ecs-profile",
    "name": "div.profile-name > a",
    "link": "div.profile-name > a",
    "title": "div.profile-title",
}
# Keep professors / lecturers / instructors; drop the department staff (Budget
# Manager, Office Coordinator, Academic Operations Specialist, Director of
# Academic Operations, Assistant to the Chair) the shared roster mixes in.
# Emeriti drop via the engine's retired-title guard.
_ECS_LADDER = {"require": r"professor|lecturer|instructor"}
# Per-profile enrichment recovers the plain-text email the listing omits: the
# ECS profile page has no mailto, the address is bare text in div.entry-content
# (office/department precede it and carry no '@'), which _email_from_el lifts.
_ECS_ENRICH = {"email_selector": "div.entry-content"}


def _ecs(short: str, name: str, majors: list[str], url: str) -> dict:
    """An ECS department on the shared combined faculty-staff directory."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ECS_SEL, "ladder_filter": _ECS_LADDER,
                   "profile_enrich": _ECS_ENRICH},
    }


# ---- College of Arts & Sciences: shared Wagtail personcontainer card -------
# section.personcontainer for every person, but the core ladder faculty are the
# only ones with a /people/faculty/ profile link — so the name selector isolates
# them and skips affiliated faculty / postdocs / staff / grad students / part-
# time instructors (all on other /people/<role>/ paths). Regular faculty rank is
# span.university-title; chairs/leadership put it in a leading <p>; the comma
# selector picks the first of either. Email is a plain mailto on every card.
_AS_SEL = {
    "card": "section.personcontainer",
    "name": "a[href*='/people/faculty/']",
    "link": "a[href*='/people/faculty/']",
    "title": "span.university-title, p",
    "email": "a[href^='mailto:']",
}
_AS_LADDER = {"require": r"professor|lecturer|instructor"}


def _as(short: str, name: str, majors: list[str], url: str) -> dict:
    """An A&S department on the shared personcontainer component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _AS_SEL, "ladder_filter": _AS_LADDER},
    }


SCHOOL: dict = {
    "school_slug": "syracuse",
    "source": "syracuse_faculty",
    "organization": "Syracuse University",
    "location": "Syracuse, NY",
    "id_prefix": "syracuse",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Syracuse University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering & Computer Science (?category= filter) --
        _ecs("EECS", "Department of Electrical Engineering and Computer Science",
             ["Electrical Engineering", "Computer Engineering", "Computer Science"],
             "https://ecs.syracuse.edu/faculty-staff/?category=electrical-engineering-and-computer-science"),
        _ecs("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "https://ecs.syracuse.edu/faculty-staff/?category=mechanical-and-aerospace-engineering"),
        _ecs("BMCE", "Department of Biomedical and Chemical Engineering",
             ["Biomedical Engineering", "Chemical Engineering"],
             "https://ecs.syracuse.edu/faculty-staff/?category=biomedical-and-chemical-engineering"),
        _ecs("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://ecs.syracuse.edu/faculty-staff/?category=civil-and-environmental-engineering"),
        # ---- College of Arts & Sciences (personcontainer) -------------------
        _as("PHYS", "Department of Physics", ["Physics"],
            "https://artsandsciences.syracuse.edu/physics/faculty-and-affiliates/"),
        _as("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
            "https://artsandsciences.syracuse.edu/chemistry/chemistry-faculty-and-staff/"),
        _as("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"],
            "https://artsandsciences.syracuse.edu/mathematics/mathematics-faculty/"),
        _as("BIO", "Department of Biology",
            ["Biology", "Biochemistry", "Neuroscience"],
            "https://artsandsciences.syracuse.edu/biology/biology-department-directory/"),
        _as("EES", "Department of Earth and Environmental Sciences",
            ["Earth Sciences", "Environmental Geoscience"],
            "https://artsandsciences.syracuse.edu/earth-sciences-department/earth-sciences-faculty-and-staff/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
