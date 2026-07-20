"""University of Texas at Dallas faculty config (via the faculty_graph engine).

Only the five Jonsson School of Engineering & Computer Science departments are
built here. The three Natural Sciences directories (Physics, Mathematics,
Chemistry) render their people from the ``profiles.utdallas.edu`` JS-SPA plugin
with no server-rendered listing, so they have no static scrape path and are
DROPPED (see ``departments_dropped`` in the onboarding report).

Every built page is server-rendered WordPress (Gutenberg blocks), plain static
200 through the proxy, emails as PLAIN ``mailto:`` (high yield). Names are
uniformly comma-inverted ("Last, First"), so ``name_flip`` un-inverts every
department. Live-verified 2026-07-20. Four distinct block decoders, one per
markup family:

* **Computer Science — a ``wp-block-table`` grid (decoder D).**
  ``cs.utdallas.edu/people/faculty/`` renders each person as a two-cell table
  row: the first cell holds the name split across one-to-three ``<a>`` anchors
  (last-name anchor, given-name anchor, optional middle-name anchor) followed by
  a ``<br>`` and the rank as bare text; the second cell holds the ``mailto:`` and
  phone. ``name`` + ``name_last`` stitch the first two anchors (a dropped middle
  initial is harmless), and ``title_html_re`` lifts the whole rank line after the
  first ``<br>`` so the retired-title guard still sees "Professor Emeritus" and
  drops the seven emeriti the roster mixes in.

* **Electrical & Computer Engineering — a ``wp-block-columns`` layout (decoder B).**
  ``ece.utdallas.edu/people/tenure-system-faculty/`` (the tenure-system page is
  the research core; the "of Instruction" teaching roster lives elsewhere) packs
  each professor into a ``div.wp-block-column`` holding a ``ul.wp-block-list``
  (name link / rank / honors / ``mailto:`` / "Research Interests:" line). The page
  also carries dozens of layout-only columns with no person, so the card selector
  is scoped to columns whose direct-child list contains a ``mailto:`` — nav/layout
  noise has none. Research interests ride the card via ``research_re_text``.

* **Mechanical Engineering (decoder A, ``ul`` variant).**
  ``me.utdallas.edu/faculty/`` renders each person as a ``ul.wp-block-list``
  carrying the class ``faculty-contact``: ``li`` 1 is the name (in a ``<strong>``,
  which for cross-listed joint faculty has no profile anchor — so ``name`` reads
  the ``<strong>`` text, not an ``<a>``), ``li`` 2 is the rank, a ``mailto:``
  ``li`` follows, and a ``li.focus`` holds the research interests.

* **Bioengineering (decoder A, ``div`` variant).**
  ``be.utdallas.edu/people/faculty/`` renders the same ``faculty-contact``
  component but on a ``div.wp-block-column`` wrapper with two child lists (person
  then research); the person list is scoped with ``:first-of-type`` and the
  research list is the second.

* **Materials Science & Engineering — a centered-paragraph layout (decoder C).**
  ``mse.utdallas.edu/ourteam/faculty/`` renders each person as one
  ``p.has-text-align-center``: name in a ``<strong>`` (inside or wrapping the
  profile ``<a>``), then ``<br>`` rank ``<br>`` ``mailto:``. ``title_html_re``
  lifts the rank between the two ``<br>``s.

All five share one ladder gate (``ladder_filter require professor|profesor|
lecturer|instructor`` — the ``profesor`` alternative catches a "Assistant
Profesor" typo on the CS page) that drops research scientists, deans, and
title-less staff/admin the rosters mix in, while keeping teaching
"Professor/Instructor of Instruction" ranks (they are real faculty, not
students). Emeriti are dropped by the engine's own retired-title guard.

Single source ("utdallas_faculty"); department rides each record, ids namespaced
by department short-code. Live-verified counts recorded in the onboarding run.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared ladder gate: keep every professor / lecturer / instructor rank (incl.
# teaching "of Instruction" faculty); drop research scientists, deans, and
# title-less admin/staff. "profesor" catches a typo'd rank on the CS roster.
_LADDER = {"require": r"profe?ss?or|lecturer|instructor"}


# ---- Decoder D: Computer Science wp-block-table -----------------------------
# Each person is a two-cell <tr>. The name spans 1-3 <a> anchors in the first
# cell before a <br>; the rank is bare text after it. name+name_last stitch the
# first two anchors, name_flip un-inverts "Last, First", and title_html_re lifts
# the full rank line after the first <br> (so "Professor Emeritus" reaches the
# retired guard). Email is the plain mailto in the second cell.
_CS_SEL = {
    "card": "figure.wp-block-table table tbody tr",
    "name": "td:first-child a",
    "name_last": "td:first-child a:nth-of-type(2)",
    "link": "td:first-child a",
    "title_html_re": r"<td>.*?<br\s*/?>(.*?)</td>",
    "email": "td a[href^='mailto:']",
}

# ---- Decoder B: ECE wp-block-columns ----------------------------------------
# A professor is a wp-block-column whose direct-child list carries a mailto (the
# many layout-only columns have none). Name link in li 1, rank in li 2, plain
# mailto anywhere in the card, research interests after a "Research Interests:"
# label lifted from the card text.
_ECE_SEL = {
    "card": 'div.wp-block-column:has(> ul.wp-block-list a[href^="mailto:"])',
    "name": "ul.wp-block-list > li:first-child",
    "link": "ul.wp-block-list > li:first-child a",
    "title": "ul.wp-block-list > li:nth-of-type(2)",
    "email": "a[href^='mailto:']",
    "research_re_text": r"Research Interests:\s*(.+)",
}

# ---- Decoder A (ul variant): Mechanical Engineering -------------------------
# One ul.wp-block-list.faculty-contact per person: name in li 1's <strong>
# (joint faculty have no profile <a>, so read the <strong> text), rank in li 2,
# plain mailto, research interests in li.focus.
_ME_SEL = {
    "card": "ul.wp-block-list.faculty-contact",
    "name": "li:first-child strong",
    "link": "li:first-child strong a",
    "title": "li:nth-of-type(2)",
    "email": "a[href^='mailto:']",
    "research": "li.focus em",
}

# ---- Decoder A (div variant): Bioengineering --------------------------------
# The same faculty-contact component on a div.wp-block-column with two child
# lists (person then research). Scope the person fields to the first list; the
# research is the second list.
_BE_SEL = {
    "card": "div.wp-block-column.faculty-contact",
    "name": "ul.wp-block-list:first-of-type > li:first-child strong",
    "link": "ul.wp-block-list:first-of-type > li:first-child a",
    "title": "ul.wp-block-list:first-of-type > li:nth-of-type(2)",
    "email": "a[href^='mailto:']",
    "research": "ul.wp-block-list:nth-of-type(2)",
}

# ---- Decoder C: Materials Science centered paragraph ------------------------
# One p.has-text-align-center per person: name in a <strong>, then <br> rank
# <br> mailto. title_html_re lifts the rank between the two <br>s.
_MSE_SEL = {
    "card": 'p.has-text-align-center:has(a[href^="mailto:"])',
    "name": "strong",
    "link": "a",
    "title_html_re": r"<br\s*/?>(.*?)<br\s*/?>",
    "email": "a[href^='mailto:']",
}


def _dept(short: str, name: str, majors: list[str], url: str, sel: dict) -> dict:
    """A UT Dallas engineering department on one of the four block decoders."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER,
                   "name_flip": True},
    }


SCHOOL: dict = {
    "school_slug": "utdallas",
    "source": "utdallas_faculty",
    "organization": "The University of Texas at Dallas",
    "location": "Richardson, TX",
    "id_prefix": "utdallas",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (The University of Texas at Dallas) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Software Engineering", "Data Science"],
              "https://cs.utdallas.edu/people/faculty/", _CS_SEL),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.utdallas.edu/people/tenure-system-faculty/", _ECE_SEL),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              "https://me.utdallas.edu/faculty/", _ME_SEL),
        _dept("BE", "Department of Bioengineering",
              ["Bioengineering", "Biomedical Engineering"],
              "https://be.utdallas.edu/people/faculty/", _BE_SEL),
        _dept("MSE", "Department of Materials Science and Engineering",
              ["Materials Science and Engineering"],
              "https://mse.utdallas.edu/ourteam/faculty/", _MSE_SEL),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
