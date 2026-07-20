"""Florida State University faculty config (via the faculty_graph engine).

Four server-rendered markup families cover the six buildable departments — every
page returns a clean static 200 to a bare request (no render mode, no WAF).
Live-verified 2026-07-20.

* **FSU Drupal "people view" (Physics + Mathematics).**
  ``www.physics.fsu.edu/people`` and ``mathematics.fsu.edu/people`` share the
  campus Drupal directory: each person is a Bootstrap ``div.col`` whose direct
  child is a ``div.views-field-title`` (name in an ``a`` → ``/person/<slug>``),
  with sibling ``div.views-field-field-position`` (rank) and
  ``div.views-field-field-email`` (a plain ``mailto``) fields. The card selector
  keys off the div that *directly* holds ``.views-field-title`` (``:has(>)``) so
  it never matches the outer grid wrapper. Both list only professors, and both
  publish an address for essentially everyone (Physics 49/50, Math 41/41), so the
  professor|lecturer ladder gate is a safety net (drops 0), not load-bearing.

* **FAMU-FSU College of Engineering Drupal (ECE + Mechanical Engineering).**
  ``eng.famu.fsu.edu/ece/people`` and ``eng.famu.fsu.edu/mae/people`` share the
  joint-college Drupal roster: one ``div.views-row`` per person holding a
  ``div.people-text`` with the name in ``h3 > a`` (a ``, Ph.D.`` credential the
  engine strips), the ranks as one-or-more ``span.faculty-job-titles`` inside the
  FIRST child ``div`` (``.people-text > div``), phone ``tel:`` links, and a
  ``div.email-links`` ``mailto`` (``@eng.famu.fsu.edu``). The title selector reads
  the WHOLE first div so an administrator's card ("Chair, … | Professor",
  "Sr. Associate Provost … | … Professor …") still exposes the professor rank to
  the ladder gate rather than getting dropped on its leading admin title. These
  rosters mix in Teaching Faculty, Research Faculty, department staff (Budget
  Analyst, Office Assistant, Coordinators), courtesy professors (whose home unit
  is elsewhere), and emeriti — the ``require: professor|lecturer`` +
  ``drop: emerit|courtesy`` gate keeps only the core ladder faculty (Teaching /
  Research Faculty and staff carry no "professor"/"lecturer" word and drop out;
  the engine's own retired-title gate is a second emeritus backstop). Emails land
  on nearly every KEPT card.

* **School of Computer Science (WordPress "faculty-card").**
  ``www.cs.fsu.edu/department/faculty/`` renders one ``article.faculty-card`` per
  person: name in ``a.faculty-name > strong`` (the profile link), rank in
  ``div.faculty-title``, NO email on the listing (recovered by the downstream
  per-profile enrichment pass). The single page mixes ~31 tenure-track professors
  with 15 Adjunct, 5 Affiliated, 9 Teaching Faculty, 6 Emeritus Professor, and a
  couple of staff/research-specialist cards; ``require: professor|lecturer`` drops
  Adjunct/Affiliated/Teaching/staff (no professor word) and ``drop: emerit`` drops
  the Emeritus Professors, leaving the core faculty.

* **Department of Chemistry & Biochemistry (WordPress OTW portfolio).**
  ``www.chem.fsu.edu/people/faculty/`` is an Organic-Themes portfolio: one
  ``div.otw_portfolio_manager-portfolio-full`` per person, the name a CSS-floated
  ``<span>Dr. </span>Last<span hidden>, </span><span>First</span>`` inside
  ``h3.otw_portfolio_manager-portfolio-title a`` — so the DOM text is
  ``"Dr. Last, First"``; ``name_strip`` removes the ``Dr.`` and ``name_flip``
  un-inverts to ``First Last`` (the two-comma ``"Last, First, III"`` generational
  form is handled by the engine's suffix-aware flip). There is NO rank field and
  NO email on the card, but the page is split into four ``<h1>`` sections —
  Faculty / Teaching Faculty / Affiliated Faculty / Faculty Emeritus — so a
  ``section_filter`` (heading ``h1``, include ``faculty``, exclude
  ``teaching|affiliated|emerit``) keeps only the ~34 core-faculty section and
  drops the teaching, cross-appointed affiliated (e.g. a Physics/Biology PI), and
  emeritus cards. Topics + emails come from downstream OpenAlex / profile
  enrichment.

Single source ("fsu_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- FSU Drupal "people view": Physics + Mathematics -----------------------
# The card is the Bootstrap column that DIRECTLY holds the title field, so the
# :has(>) keeps the selector from also matching the outer grid wrapper.
_DRUPAL_SEL = {
    "card": "div.col:has(> div.views-field-title)",
    "name": "div.views-field-title a",
    "link": "div.views-field-title a",
    "title": "div.views-field-field-position .field-content",
    "email": "div.views-field-field-email a[href^='mailto:']",
}
_DRUPAL_LADDER = {"require": r"professor|lecturer"}


def _drupal(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Physics/Math department on the shared FSU Drupal people view."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _DRUPAL_SEL,
                   "ladder_filter": _DRUPAL_LADDER},
    }


# ---- FAMU-FSU College of Engineering Drupal: ECE + Mechanical --------------
# Title reads the WHOLE first div (all faculty-job-titles spans joined) so an
# administrator's leading admin role doesn't hide the professor rank from the
# gate. Teaching/Research Faculty + staff carry no professor/lecturer word and
# drop via `require`; courtesy (home unit elsewhere) + emeriti drop via `drop`.
_ENG_SEL = {
    "card": "div.views-row",
    "name": "div.people-text h3 a",
    "link": "div.people-text h3 a",
    "title": "div.people-text > div",
    "email": "div.email-links a[href^='mailto:']",
}
_ENG_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|courtesy"}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """An ECE/ME department on the shared FAMU-FSU engineering Drupal roster."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "ladder_filter": _ENG_LADDER},
    }


SCHOOL: dict = {
    "school_slug": "fsu",
    "source": "fsu_faculty",
    "organization": "Florida State University",
    "location": "Tallahassee, FL",
    "id_prefix": "fsu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Florida State University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Computer Science (WordPress faculty-card) -----------
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Data Science", "Cybersecurity",
                       "Computer Engineering"],
            "directory_url": "https://www.cs.fsu.edu/department/faculty/",
            "scrape": {
                "url": "https://www.cs.fsu.edu/department/faculty/",
                "selectors": {
                    "card": "article.faculty-card",
                    "name": "a.faculty-name > strong",
                    "link": "a.faculty-name",
                    "title": "div.faculty-title",
                },
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit"},
            },
        },
        # ---- FAMU-FSU College of Engineering (shared Drupal roster) --------
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://eng.famu.fsu.edu/ece/people"),
        _eng("MAE", "Department of Mechanical Engineering",
             ["Mechanical Engineering"],
             "https://eng.famu.fsu.edu/mae/people"),
        # ---- FSU Drupal people view: Physics + Mathematics -----------------
        _drupal("PHYS", "Department of Physics",
                ["Physics", "Astrophysics"],
                "https://www.physics.fsu.edu/people"),
        _drupal("MATH", "Department of Mathematics",
                ["Mathematics", "Applied Mathematics", "Statistics",
                 "Biomathematics", "Financial Mathematics"],
                "https://mathematics.fsu.edu/people"),
        # ---- Chemistry & Biochemistry (WordPress OTW portfolio) ------------
        {
            "short": "CHEM",
            "name": "Department of Chemistry and Biochemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.chem.fsu.edu/people/faculty/",
            "scrape": {
                "url": "https://www.chem.fsu.edu/people/faculty/",
                "selectors": {
                    "card": "div.otw_portfolio_manager-portfolio-full",
                    "name": "h3.otw_portfolio_manager-portfolio-title a",
                    "link": "h3.otw_portfolio_manager-portfolio-title a",
                    # "Dr. Last, First" (CSS-floated spans) → strip Dr., flip.
                    "name_strip": r"^Dr\.?\s*",
                },
                "name_flip": True,
                # No rank field; the page groups people under four <h1> section
                # headings — keep only the core "Faculty" section.
                "section_filter": {
                    "heading": "h1",
                    "include": r"faculty",
                    "exclude": r"teaching|affiliated|emerit",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
