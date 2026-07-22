"""Swarthmore College faculty config (via the faculty_graph engine).

Swarthmore is a top-10 US liberal arts college (~1,650 undergraduates, no
graduate school) in the Tri-College Consortium with Bryn Mawr and Haverford.
Its entire public site is a single Drupal build, and every academic
department publishes its roster on one shared "people list" component, so ONE
selector family covers the whole college — no per-department bespoke markup.

Live-verified 2026-07-21 (~40 clean 200s, no WAF, no render mode anywhere):

* ``_dept`` — the shared ``c-person-detail`` bio card. Every academic
  department page at ``swarthmore.edu/<dept>/faculty-staff`` (three departments
  use ``/faculty-and-staff`` — Chemistry & Biochemistry, Educational Studies,
  English Literature) renders the same component. Cards carry a
  ``c-person-detail--faculty`` modifier on EVERYONE (faculty, teaching staff,
  departmental staff, and emeriti alike — the modifier is not a role marker),
  so role gating is done with a title ``ladder_filter`` on the
  ``.c-person-detail__role`` text, not the CSS class. The card name is a plain
  ``<h2 class="c-person-detail__title">`` (sometimes wrapping a mailto anchor),
  the rank is the first ``.c-person-detail__role`` (a second one may hold
  "Department Chair, …"), and the email is a decodable mailto under
  ``.c-person-detail__email``. There are no per-person profile pages — the card
  links straight to a mailto (or an external personal website), so every record
  falls back to the department directory URL and email is the contact of
  record. Names occasionally carry a Swarthmore alumni class-year suffix
  ("Bradley Davidson '91") stripped by ``name_strip``.

Ladder gate keeps Professors and Lecturers (the cold-emailable research /
teaching faculty) and drops emeriti, visiting, and adjunct appointments plus
all non-teaching staff (lab instructors, coordinators, postdocs, managers,
technicians) that share the same card markup.

The six Modern Languages & Literatures sections (Arabic, Chinese, French,
German, Russian, Spanish) each have their own department page and are captured
individually; the parent /modern-languages-literatures page only carries the
program chair and is skipped. Classics covers Greek, Latin, and Ancient
History.

Single source ("swarthmore_faculty"); department rides each record, ids
namespaced by department short-code. The engine's per-school email/name dedup
collapses the handful of faculty cross-listed onto more than one department
page (e.g. a language professor also under Comparative Literature).

Deferred (2026-07-21 recon):
* Japanese and Film & Media Studies — no faculty-staff / faculty-and-staff
  page resolves (their instructors surface under Modern Languages and the
  cross-listing departments); revisit if a dedicated roster path appears.
* Interdisciplinary programs (Environmental Studies, Cognitive Science,
  Gender & Sexuality Studies, Black Studies, Asian Studies, PPE, Peace &
  Conflict, etc.) — these list cross-appointed faculty whose home department
  is already captured above; adding them would only produce email-deduped
  duplicates with arbitrary department attribution, so they are covered on the
  campus side as programs, not as faculty departments here.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared bio-card selectors for the Drupal c-person-detail component.
_SELECTORS = {
    "card": ".c-person-detail",
    "name": ".c-person-detail__title",
    # Strip the Swarthmore alumni class-year suffix ("… '91", "… ’06").
    "name_strip": r"\s+[’'`]\d{2}\b",
    "title": ".c-person-detail__role",
    "email": ".c-person-detail__email a[href^='mailto:']",
}

# Keep Professors + Lecturers (research/teaching faculty); drop emeriti,
# visiting, adjunct, and the lab-instructor / staff / postdoc rows that share
# the same card markup.
_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|visiting|adjunct"}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty-staff") -> dict:
    """A department on the shared c-person-detail people-list component."""
    url = f"https://www.swarthmore.edu/{slug}/{path}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER},
    }


SCHOOL: dict = {
    "school_slug": "swarthmore",
    "source": "swarthmore_faculty",
    "organization": "Swarthmore College",
    "location": "Swarthmore, PA",
    "id_prefix": "swarthmore",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Swarthmore College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Engineering --------------------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry and Biochemistry",
              ["Chemistry", "Biochemistry"], "chemistry-biochemistry",
              path="faculty-and-staff"),
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("ENGR", "Department of Engineering", ["Engineering"], "engineering"),
        _dept("MATSTAT", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "mathematics-statistics"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics-astronomy"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("EDUC", "Department of Educational Studies", ["Educational Studies"],
              "educational-studies", path="faculty-and-staff"),
        _dept("LING", "Department of Linguistics", ["Linguistics"], "linguistics"),
        _dept("POLS", "Department of Political Science", ["Political Science"],
              "political-science"),
        _dept("SOAN", "Department of Sociology and Anthropology",
              ["Sociology", "Anthropology"], "sociology-anthropology"),
        # ---- Humanities & Arts ---------------------------------------------
        _dept("ART", "Department of Art", ["Studio Art", "Art History"], "art"),
        _dept("ARTH", "Department of Art History", ["Art History"], "art-history"),
        _dept("CLAS", "Department of Classics",
              ["Classics", "Greek", "Latin", "Ancient History"], "classics"),
        _dept("CPLT", "Department of Comparative Literature",
              ["Comparative Literature"], "comparative-literature"),
        _dept("ENGL", "Department of English Literature",
              ["English Literature", "Creative Writing"], "english-literature",
              path="faculty-and-staff"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("MUSI", "Department of Music", ["Music"], "music"),
        _dept("DANC", "Department of Dance", ["Dance"], "dance"),
        _dept("THTR", "Department of Theater", ["Theater"], "department-theater"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _dept("RELG", "Department of Religion", ["Religion"], "religion"),
        # ---- Modern Languages & Literatures --------------------------------
        _dept("ARAB", "Arabic Section (Modern Languages and Literatures)",
              ["Arabic"], "arabic"),
        _dept("CHIN", "Chinese Section (Modern Languages and Literatures)",
              ["Chinese"], "chinese"),
        _dept("FREN", "French and Francophone Studies Section (Modern Languages and Literatures)",
              ["French"], "french-francophone-studies"),
        _dept("GERM", "German Studies Section (Modern Languages and Literatures)",
              ["German Studies"], "german-studies"),
        _dept("RUSS", "Russian Section (Modern Languages and Literatures)",
              ["Russian"], "russian"),
        _dept("SPAN", "Spanish Section (Modern Languages and Literatures)",
              ["Spanish"], "spanish"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
