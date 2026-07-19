"""University of Houston faculty config (via the faculty_graph engine).

Two server-rendered markup families cover UH's core STEM departments (every
recon page returns a clean plain-HTTP 200 — no WAF, no JS render):

* **College of Natural Sciences & Mathematics (NSM) — OU Campus row/col cards.**
  Computer Science, Physics, and Chemistry render each person as a Bootstrap
  card: an outer person row whose data column (``div.col-8.col-sm-10``) holds an
  inner row split into ``div.col-sm-7`` (name link + ``span.text-muted`` rank +
  degree, and — CS only — research-area ``a.badge`` links) and ``div.col-sm-5``
  (a ``mailto:`` email + phone + office). ``div.col-8.col-sm-10`` is the card so
  the sibling email column is in scope. The name anchor is a plain ``<a>``; the
  CS research links are ``a.badge`` in a later ``<p>``, so the name selector is
  ``a:not(.badge)`` (an anchorless card — a lecturer with no profile page — then
  yields no name and is skipped rather than grabbing a badge as the name). A
  ``ladder_filter`` (require professor/lecturer, drop adjunct/emeritus/visiting)
  drops the CS Adjunct section; the pages carry no grad students/postdocs (those
  and emeriti live on separate roster pages). Two tenure-line/research professors
  with no profile link (CS: Ernst Leiss; Chemistry: Boris Makarenko) are added as
  curated seeds so the anchor-based scrape doesn't lose them.

* **Cullen College of Engineering — Drupal ``faculty-info`` cards.**
  Electrical & Computer Engineering (ee.uh.edu) and Mechanical & Aerospace
  Engineering (me.uh.edu) run the same Drupal Views directory: one
  ``div.faculty-info`` card per person with ``.faculty-name`` (an ``<a>`` to
  ``/faculty/<slug>``), a ``.spamspan`` "x [at] uh.edu" obfuscated email that
  ``_clean_email`` reassembles, and a rich "Research Interests" field harvested
  via ``research_re``. The cards are grouped under ``<h3>`` role headings, so a
  ``section_filter`` (heading h3, exclude emeritus/adjunct) drops the Emeritus /
  Adjunct sections while keeping ladder + research + instructional faculty; the
  rank is not on a clean per-card element, so the record title defaults to
  "Professor". ECE names carry society-fellowship post-nominals ("Ji Chen,
  Fellow IEEE, Fellow AIMBE" / "Aaron Becker, Senior Member IEEE") that the
  engine's credential gate doesn't cover, so a ``name_strip`` trims them; ME
  names are clean apart from the "Dr." honorific the engine already strips.

Mathematics is deliberately DROPPED: its faculty table renders every name in
ALL CAPS ("ROBERT AZENCOTT") inside inconsistently nested ``<strong>`` tags that
leak the rank/comma into the name ("BERNHARD BODMANN ,\xa0Professor",
"JIAN CAO,"), and the engine has no case-normalization to recover a clean
proper-case pi_name — shipping it would be dirty, so the five clean departments
are shipped instead.

Single source ("houston_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-19 (cards on page / kept after gate, pre-dedupe):
CS 42/34 + 1 curated, ECE 49/45, Physics 36/36, Chemistry 39/34 + 1 curated,
ME 49/36.
"""

from __future__ import annotations

from .. import faculty_graph
from ..faculty_graph import faculty

# ---- NSM (CS / Physics / Chemistry): OU Campus row/col cards ----------------
# The card is the data column so the col-sm-5 email is a descendant. The name is
# the first non-badge anchor in col-sm-7 (CS research links are a.badge in a
# later <p>); rank is span.text-muted; CS research areas are the badge links.
_NSM_SEL = {
    "card": "div.col-8.col-sm-10",
    "name": "div.col-sm-7 p a:not(.badge)",
    "link": "div.col-sm-7 p a:not(.badge)",
    "title": "div.col-sm-7 span.text-muted",
    "email": "div.col-sm-5 a[href^='mailto:']",
    "research_items": "div.col-sm-7 a.badge",
}
# Keep ladder + instructional + lecturer + joint professors and endowed-CHAIR
# holders (whose most senior titles read "…Endowed Chair…"/"…Distinguished
# University Chair…" with no "Professor" word — e.g. Physics' Zhifeng Ren,
# Chemistry's Allan Jacobson); drop the CS Adjunct section and any emeritus/
# visiting. Titles are clean (span.text-muted).
_NSM_LADDER = {"require": r"professor|lecturer|chair",
               "drop": r"adjunct|emerit|visiting"}


def _nsm(short: str, name: str, majors: list[str], url: str,
         faculty_seed: list[dict] | None = None) -> dict:
    """An NSM department on the shared OU Campus row/col component."""
    dept = {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _NSM_SEL, "ladder_filter": _NSM_LADDER},
    }
    if faculty_seed:
        dept["faculty"] = faculty_seed
    return dept


# ---- Cullen College of Engineering (ECE / ME): Drupal faculty-info cards ----
_ENG_SEL = {
    "card": "div.faculty-info",
    "name": "div.faculty-name",
    "link": "a:has(> div.faculty-name)",
    # ".spamspan" is "x [at] uh.edu" obfuscation — _clean_email reassembles it.
    "email": ".spamspan",
    # Rank is loose <br>-separated text with no clean element; grab the rich
    # "Research Interests" value instead (bounded to its field <div>).
    "research_re": r"Research Interests</span>(.*?)</div>",
    # ECE post-nominals: "Ji Chen, Fellow IEEE, Fellow AIMBE" / "Aaron Becker,
    # Senior Member IEEE" / "Donald Wilton, IEEE Life Fellow, Member NAE" — trim
    # from the first society-credential comma (ME names have none, so unaffected;
    # the leading "Dr." is stripped by the engine's honorific gate).
    "name_strip": r"(?i),\s*(?:Fellow|Senior\s+Member|Member|IEEE|FRSC|NAI|Life\s+Fellow)\b.*$",
}
# Cards are grouped under <h3> role headings; drop the Emeritus / Adjunct
# sections, keep everything else (Chair / ladder / research / instructional /
# lecturer). Rank is not on a clean per-card element, so the title defaults to
# "Professor".
_ENG_SECTION = {"heading": "h3", "exclude": r"emerit|adjunct"}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Cullen Engineering department on the shared Drupal faculty-info view."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "section_filter": _ENG_SECTION},
    }


SCHOOL: dict = {
    "school_slug": "houston",
    "source": "houston_faculty",
    "organization": "University of Houston",
    "location": "Houston, TX",
    "id_prefix": "houston",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Houston) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Natural Sciences & Mathematics ----------------------
        _nsm("CS", "Department of Computer Science",
             ["Computer Science", "Data Science"],
             "https://www.uh.edu/nsm/computer-science/people/faculty/",
             faculty_seed=[
                 # Tenured/tenure-track Professor listed without a profile link
                 # (anchor-based scrape can't reach him); badges give keywords.
                 faculty("Ernst Leiss", title="Professor",
                         email="eleiss@uh.edu",
                         keywords=["Cyber Security", "Algorithms"]),
             ]),
        _nsm("PHYS", "Department of Physics", ["Physics"],
             "https://www.uh.edu/nsm/physics/people/tenure-track/"),
        _nsm("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
             "https://www.uh.edu/nsm/chemistry/people/faculty/",
             faculty_seed=[
                 # Research Associate Professor listed without a profile link.
                 faculty("Boris Makarenko", title="Research Associate Professor",
                         email="bmakarenko@uh.edu"),
             ]),
        # ---- Cullen College of Engineering ----------------------------------
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://www.ee.uh.edu/faculty"),
        _eng("ME", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "https://www.me.uh.edu/faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
