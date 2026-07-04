"""UC Santa Barbara faculty config (via the faculty_graph engine).

Third UC-system rollout school. Every UCSB department runs Drupal (SiteFarm) —
no WordPress, no JSON:API — so the whole school is CSS-scraped, in five Views
card layouts (selectors verified against live HTML, Jul 2026):

- **Family A** — ``div.views-row`` with ``.group-second``/``.group-third``:
  email AND a research-interest line on the listing. ECE, Economics, Geography,
  EEMB, Physics, MCDB. Rank is loose text in ``.group-second`` (an endowed-chair
  line can precede it), so it's pulled with ``title_re``.
- **Family A′** — Bren's clean-field variant (``.views-field-title-1`` +
  ``.views-field-field-title``); email on listing, heavy ladder filter (the page
  bundles affiliated/lecturer/emeritus).
- **Family B** — ``div.views-row`` with an ``h2``/``h3`` heading and stacked
  ``<p>`` lines: Computer Science (email on listing), Communication (email on
  profile), Mechanical Engineering (``/people``).
- **Family B′** — PSTAT's ``article.people-profile`` sub-variant (``h4 a`` +
  ``p.break-words`` email).
- **Family C** — unfiltered all-people pages (``.view-content > div`` cards, no
  ``div.views-row``): Political Science, Sociology, Chemistry & Biochemistry,
  Mathematics. These list grad students / alumni / emeriti / affiliates, so they
  need a strict ladder filter on the title; Math labels ladder faculty with the
  generic "Faculty", handled in its filter. Email is on the profile page.
- **Family D** — ``.view-content li`` item lists: Chemical Engineering (clean),
  Materials (Drupal-7, unfiltered — mostly grad students, heavy ladder filter).
- **Family E** — Psychological & Brain Sciences' ``tr.rev--people--row`` table;
  faculty are the rows whose profile path is ``/people/faculty/`` (section gate),
  with a research-area line on the listing.

Humanities departments (History/Philosophy/English/Linguistics) are deferred:
their rosters load via a Drupal views-AJAX call the static fetch can't reach.

Single source ("ucsb_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_LADDER = {"require": r"\bprofessor\b",
           "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer|of teaching"
                   r"|teaching professor|\baffiliated|graduate student|\balum"
                   r"|postdoc|\bspecialist"}

# Loose-text rank pattern for the Drupal card families whose title is a bare
# text node (Family A) — capture the ladder/teaching rank; _LADDER drops the
# teaching/affiliated/emeritus ones afterward.
_RANK_RE = (r"((?:Assistant |Associate |Distinguished )?Professor"
            r"(?:\s+of\s+Teaching)?)")


def _dept(short: str, name: str, majors: list[str], url: str, scrape: dict) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, **scrape}}


# Family A: email + research on listing; rank via title_re.
def _famA(short: str, name: str, majors: list[str], url: str) -> dict:
    return _dept(short, name, majors, url, {
        "selectors": {
            "card": "div.views-row",
            "name": ".group-second h3 a",
            "link": ".group-second h3 a",
            "email": ".group-second a[href^='mailto:']",
            "title_re": _RANK_RE,
            "research": ".group-third",
        },
        "ladder_filter": _LADDER,
    })


SCHOOL: dict = {
    "school_slug": "ucsb",
    "source": "ucsb_faculty",
    "organization": "University of California, Santa Barbara",
    "location": "Santa Barbara, CA",
    "id_prefix": "ucsb",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC Santa Barbara) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Family A (email + research on listing) -------------------------
        _famA("ECE", "Department of Electrical & Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.ucsb.edu/people/faculty"),
        _famA("ECON", "Department of Economics",
              ["Economics", "Financial Mathematics & Statistics"],
              "https://econ.ucsb.edu/people/faculty"),
        _famA("GEOG", "Department of Geography",
              ["Geography"], "https://www.geog.ucsb.edu/people/faculty"),
        _famA("EEMB", "Department of Ecology, Evolution & Marine Biology",
              ["Ecology & Evolution", "Aquatic Biology", "Marine Biology"],
              "https://www.eemb.ucsb.edu/people/faculty"),
        _famA("PHYS", "Department of Physics",
              ["Physics"], "https://www.physics.ucsb.edu/people/faculty"),
        _famA("MCDB", "Department of Molecular, Cellular & Developmental Biology",
              ["Biological Sciences", "Biochemistry", "Cell & Developmental Biology"],
              "https://www.mcdb.ucsb.edu/people/faculty"),
        # ---- Family B / B′ --------------------------------------------------
        _dept(
            "CS", "Department of Computer Science",
            ["Computer Science", "Computer Engineering"],
            "https://cs.ucsb.edu/people/faculty",
            {
                "selectors": {
                    "card": "div.views-row",
                    "name": "h2 a",
                    "link": "h2 a",
                    "title_re": _RANK_RE,
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "COMM", "Department of Communication",
            ["Communication"],
            "https://www.comm.ucsb.edu/people/faculty",
            {
                # Email lives on the profile page here (none on the listing).
                "selectors": {
                    "card": "div.views-row",
                    "name": "h3 a",
                    "link": "h3 a",
                    "title_re": _RANK_RE,
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "ME", "Department of Mechanical Engineering",
            ["Mechanical Engineering"],
            "https://me.ucsb.edu/people",
            {
                # ME's card heading is .me-ppl-title (not h2/h3).
                "selectors": {
                    "card": "div.views-row",
                    "name": ".me-ppl-title a",
                    "link": ".me-ppl-title a",
                    "title_re": _RANK_RE,
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "PSTAT", "Department of Statistics & Applied Probability",
            ["Statistics & Data Science", "Actuarial Science", "Financial Mathematics & Statistics"],
            "https://www.pstat.ucsb.edu/people/faculty",
            {
                "selectors": {
                    "card": "div.views-row article",
                    "name": "h4 a",
                    "link": "h4 a",
                    "title": "p:not(.break-words)",
                    "email": "p.break-words a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ---- Family C (unfiltered all-people; strict ladder; email on profile)
        _dept(
            "POLSCI", "Department of Political Science",
            ["Political Science"],
            "https://www.polsci.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        _dept(
            "SOC", "Department of Sociology",
            ["Sociology"],
            "https://www.soc.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        _dept(
            "CHEM", "Department of Chemistry & Biochemistry",
            ["Chemistry", "Biochemistry"],
            "https://www.chem.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        _dept(
            "MATH", "Department of Mathematics",
            ["Mathematics", "Financial Mathematics & Statistics"],
            "https://www.math.ucsb.edu/people",
            {
                "selectors": {
                    "card": "div.view-content > div",
                    "name": ".views-field-nothing h3 a",
                    "link": ".views-field-nothing h3 a",
                    "title": ".views-field-field-title",
                },
                # Math labels ladder faculty with the generic "Faculty"; keep that
                # plus explicit professor ranks, drop the rest.
                "ladder_filter": {
                    "require": r"\bprofessor\b|^\s*Faculty\s*$",
                    "drop": r"\bemerit|\bvisiting|\baffiliated|\blecturer|math fellow"
                            r"|graduate student|\bpostdoc"},
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        # ---- Family D (item-list) -------------------------------------------
        _dept(
            "CHEMENGR", "Department of Chemical Engineering",
            ["Chemical Engineering"],
            "https://chemengr.ucsb.edu/people/faculty",
            {
                "selectors": {
                    "card": ".view-content li",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-titles--departments",
                    "email": ".views-field-field-people-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "MATSCI", "Department of Materials",
            ["Materials"],
            "https://materials.ucsb.edu/people/faculty",
            {
                # Drupal-7 unfiltered roster (mostly grad students) — strict
                # ladder filter carries the correctness here.
                "selectors": {
                    "card": ".view-content li",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-titles--departments",
                    "email": ".views-field-field-people-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
        # ---- Family E (psych table; section by URL path) --------------------
        _dept(
            "PSYCH", "Department of Psychological & Brain Sciences",
            ["Psychological & Brain Sciences", "Biopsychology"],
            "https://psych.ucsb.edu/people",
            {
                "selectors": {
                    "card": "tr.rev--people--row",
                    "name": "td h2 a",
                    "link": "td h2 a",
                    "title": "td h2 + p",
                    "research_items": "tr td:last-child a",
                },
                # Faculty are the rows whose profile link is /people/faculty/.
                "link_filter": r"/people/faculty/",
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']", "throttle": 1.0},
            },
        ),
        # ---- Family A′ (Bren) -----------------------------------------------
        _dept(
            "BREN", "Bren School of Environmental Science & Management",
            ["Environmental Studies"],
            "https://bren.ucsb.edu/people/faculty?person_types=91",
            {
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field-title-1 h3 a",
                    "link": ".views-field-title-1 h3 a",
                    "title": ".views-field-field-title .field-content",
                    "email": ".views-field-field-email a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        ),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
