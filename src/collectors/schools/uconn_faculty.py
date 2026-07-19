"""University of Connecticut faculty config (via the faculty_graph engine).

Five UConn departments share the campus-standard WordPress "person-card"
component — server-rendered, no WAF, no JS render needed (every page returns a
clean 200 to a plain request). One card is a ``div`` whose class list carries a
``personcount-N person-<id>`` pair; inside it:

* an ``h4.person-name`` with the display name (wrapping an ``a.person-permalink``
  profile link and a screen-reader-only "(opens in new window)" span the
  ``name_strip`` regex removes);
* a ``p.person-title`` holding the rank in a ``<strong>``;
* a ``p.person-keywords`` "Research Interests: …" line on the departments that
  publish it (Computer Science does; the engine's ``_RESEARCH_LABEL_RE`` strips
  the label and comma-splits the rest into clean keyword chips — the other four
  omit this field, so those records land name+title+email and topics come from
  downstream OpenAlex enrichment);
* a ``p.person-email`` mailto where the directory exposes one (Chemistry, ME and
  CS publish addresses; Physics and Math publish almost none).

Because the component is uniform, one shared selector set + one title gate covers
all five departments. The card selector keys off ``personcount-`` (present on
every card, unlike the ``col-sm-3``/``col-sm-4`` grid-width class that varies by
department) so it is width-agnostic.

Title gate (``field_filter``, require ``professor|lecturer``): the directories
mix in emeriti, adjuncts, instructors-in-residence, department-admin/liaison
staff, and — in Mathematics — dozens of adjuncts and actuarial-science adjuncts.
A ``field_filter`` (not ``ladder_filter``) is used so a title-less staff card
can't fall through the engine's default-to-"Professor": ``require_present`` reads
``p.person-title`` directly and drops the card when it is absent, then
``include`` keeps only Professor/Lecturer ranks. Emeriti are additionally dropped
by the engine's own ``_RETIRED_TITLE_RE``. A few real professors carrying only an
endowed-chair or department-head title (no "Professor" word) are dropped by the
gate — accuracy over recall, so no non-ladder rows leak in.

DROPPED — Electrical & Computer Engineering: there is no clean core-faculty
source. The modern engineering-CMS ECE subdomains do not resolve, ece.uconn.edu
redirects to a 3-person "faculty coordinators" stub, and the only full
server-rendered list (www.ee.uconn.edu/…/faculty_alphabetical, an old SiteOrigin
page) contains emeriti + adjuncts + affiliated/courtesy faculty whose PRIMARY
appointment is another department (Chemistry, Biomedical, Mechanical, Physics,
CS) rather than the core ECE ladder — scraping it would inject wrong-department
professors, so ECE is deferred rather than shipped dirty.

UConn's Mechanical Engineering unit is the renamed School of Mechanical,
Aerospace & Manufacturing Engineering (me.uconn.edu is dead; the canonical host
is on the *.engineering.uconn.edu CMS).

Single source ("uconn_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-19 (cards / kept-after-gate): CS 65/55, Physics 46/45,
Chemistry 78/58, Mathematics 149/84, ME 42/41 → 283 total. Emails land on
154/283 (CS/Chemistry/ME publish mailtos; Physics/Math publish almost none).
Only 5 records (1.8%) are genuine joint appointments listed under two
departments (Russell/Aguiar/Bi across CS↔Math, Trallero Physics↔Chemistry,
Olgac Mechanical↔Math) — the email/URL de-dup keeps them because the second
listing exposes no email; that is a correct cross-listing, not pollution.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UConn campus WordPress "person-card" component — identical markup on
# computing.engineering / physics / chemistry / math / mechanical-aerospace-
# manufacturing subdomains. Card keyed on the width-agnostic ``personcount-``
# class; the name h4 wraps a screen-reader "(opens in new window)" span stripped
# via name_strip; research keywords land only where the dept renders them.
_SEL = {
    "card": 'div[class*="personcount-"]',
    "name": "h4.person-name",
    "link": "h4.person-name a",
    "name_strip": r"\s*\(opens in new window\)\s*",
    "title": "p.person-title",
    "research": "p.person-keywords",
    "email": 'p.person-email a[href^="mailto:"]',
}

# Keep Professors (ladder + in-residence teaching + distinguished) and Lecturers;
# drop the emeriti, adjuncts, instructors, and admin/liaison staff the directories
# mix in. field_filter (not ladder_filter) so a title-less staff card can't fall
# through the engine's default-to-"Professor": require_present reads the title
# element directly and drops the card when absent; include then keeps only
# Professor/Lecturer ranks. Emeriti are additionally dropped by the retired gate.
_FIELD = {
    "selector": "p.person-title",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UConn person-card component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


SCHOOL: dict = {
    "school_slug": "uconn",
    "source": "uconn_faculty",
    "organization": "University of Connecticut",
    "location": "Storrs, CT",
    "id_prefix": "uconn",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Connecticut) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        _dept("CSE", "Department of Computer Science and Engineering",
              ["Computer Science", "Computer Engineering", "Data Science"],
              "https://computing.engineering.uconn.edu/people/faculty/"),
        _dept("PHYS", "Department of Physics", ["Physics"],
              "https://physics.uconn.edu/people/faculty/"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              "https://chemistry.uconn.edu/faculty/"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics", "Actuarial Science"],
              "https://math.uconn.edu/people/faculty/"),
        _dept("ME", "School of Mechanical, Aerospace and Manufacturing Engineering",
              ["Mechanical Engineering", "Aerospace Engineering",
               "Manufacturing Engineering"],
              "https://mechanical-aerospace-manufacturing.engineering.uconn.edu/people/faculty/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
