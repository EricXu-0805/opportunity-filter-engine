"""University of Iowa faculty config (via the faculty_graph engine).

Every department probed for this pass runs the same campus-standard SiteNow
(Drupal) "people" card — server-rendered, no WAF, no JS render needed (all six
pages return clean 200s to a plain request). One card is ``div.views-row``
wrapping ``div.card--layout-left…card`` and carrying:

* an ``h3.headline`` whose ``a[href^='/people/']`` links to the person's profile
  and whose ``span.headline__heading`` holds the display name (often with a
  ", PhD" credential the engine's ``_strip_credentials`` trims);
* a ``div.field--name-field-person-position`` block whose ``.field__items`` holds
  one ``.field__item`` per appointment — the rank ("Professor", "Assistant
  Professor", "Professor of Instruction", "Lecturer") plus, for some people,
  administrative roles ("Chair, Department of …", "Director of Graduate Studies")
  and endowed-title designations ("Emeriti-Faculty Scholar"). Order varies (rank
  may be first or last), so a positional ``.field__item`` selector can't reliably
  land the rank;
* a ``div.field--name-field-person-email`` block with a plain ``mailto:`` anchor
  (every kept record lands emailed).

Because the component is uniform, one shared selector set + one gate covers all
six departments. The engineering departments (ECE, ME) live under the college
host ``engineering.uiowa.edu`` (the ``ece.uiowa.edu`` / ``me.uiowa.edu``
subdomains don't resolve) but render the identical SiteNow card.

Gate — a ``field_filter`` on the position block (``require_present`` +
``include: professor|lecturer``), not a ``ladder_filter``:

* the position block's varying item order defeats a single-item ``title``
  selector, and the engine defaults a *missing* title to "Professor" — which a
  ladder ``require`` would then wave through. ``field_filter.require_present``
  reads the position field directly and drops any card lacking it (advisors /
  administrators with no rank), while ``include`` drops research scientists,
  department administrators, program specialists, and postdocs the ECE page
  mixes in (verified: 5 such non-faculty dropped on ECE).
* ``title_re`` then extracts just the clean rank phrase for display (so a chair's
  administrative items don't leak into the record title), and — by capturing a
  trailing "Emeritus"/"Emerita" — feeds the engine's ``_RETIRED_TITLE_RE`` so
  the eight ECE emeritus professors are dropped. The endowed "Emeriti-Faculty
  Scholar/Fellow" designation is NOT the whole-word "emeritus"/"emerita" the
  retired gate keys on, so those active professors are correctly kept.

Physics is the Department of Physics and Astronomy (no separate Astronomy unit);
Statistics is a separate CLAS department (stat.uiowa.edu) and is not built here.

Single source ("uiowa_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-19 (cards / kept-after-gate): CS 28/28, ECE 36/23 (5
non-faculty + 8 emeriti dropped), Physics 30/30, Chemistry 25/25, Mathematics
27/27, Mechanical Engineering 21/21 — 154 faculty total, email 100%.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared University of Iowa SiteNow "people" card. ``title_re`` extracts the
# rank from the whole card text (the position block is the first place a rank
# word appears), keeping the trailing "Emeritus"/"Emerita" so the engine's
# retired-title gate can drop actual emeriti while the field_filter below handles
# non-rank staff.
_SEL = {
    "card": "div.views-row",
    "name": ".headline__heading",
    "link": "h3.headline a",
    "email": ".field--name-field-person-email .field__item a",
    "title_re": (
        r"((?:Adjunct |Visiting |Clinical |Research |Distinguished |Assistant "
        r"|Associate |Emeritus |Emerita )*Professor(?:\s+Emerit(?:us|a))?"
        r"(?:\s+of\s+Instruction)?|Lecturer|Instructor)"
    ),
}

# Keep Professors (ladder + teaching "of Instruction" + distinguished/endowed)
# and Lecturers; drop the research scientists, department administrators,
# graduate-program specialists, and postdocs the directories (ECE especially)
# mix in. The position field is read directly (require_present) so a card
# without a rank can't fall through into the engine's "Professor" default;
# ``include`` then keeps only professor/lecturer ranks. Emeriti are dropped
# downstream by the engine's retired-title guard via the title_re-extracted rank.
_FIELD = {
    "selector": ".field--name-field-person-position .field__items",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared University of Iowa SiteNow people card."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


SCHOOL: dict = {
    "school_slug": "uiowa",
    "source": "uiowa_faculty",
    "organization": "University of Iowa",
    "location": "Iowa City, IA",
    "id_prefix": "uiowa",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Iowa) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Liberal Arts & Sciences ----------------------------
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Data Science", "Informatics"],
              "https://cs.uiowa.edu/people/faculty"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"],
              "https://physics.uiowa.edu/people/faculty"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"],
              "https://chem.uiowa.edu/people/faculty"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Actuarial Science"],
              "https://math.uiowa.edu/people/faculty"),
        # ---- College of Engineering ----------------------------------------
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Science and Engineering"],
              "https://engineering.uiowa.edu/ece/people"),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              "https://engineering.uiowa.edu/people/me-people/me-faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
