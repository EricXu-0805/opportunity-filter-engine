"""University of Utah faculty config (via the faculty_graph engine).

Two markup families cover the five buildable departments — all plain
server-rendered HTTP 200s (no render mode, no WAF). Live-verified 2026-07-19
(cards / kept-after-gate):

* **The7 "faculty card" grid (ECE + Mechanical Engineering).**
  ``www.ece.utah.edu/faculty/`` and ``www.mech.utah.edu/directory/faculty/``
  share one custom-templated The7 grid: each faculty member is a
  ``div.person-container`` whose ``div.t-entry`` holds the name (``h2.t-entry-title``),
  the rank (``h3.t-entry-meta``), a ``ul.card-links-list`` of phone/email/office,
  and a ``p.t-entry-excerpt`` of research prose (not scraped — it is free text,
  not a clean tag list, so topics come from OpenAlex). GOTCHA: the department's own
  hand-authored HTML mis-closes the headings (``<h2>Name</h3>``,
  ``<h3>Rank</h4>``) so ``html.parser`` nests every following node inside the
  heading — ``h2``'s text absorbs the rank+contacts and ``h3``'s absorbs the
  contacts+excerpt. ``name_strip`` trims the name back to the person by cutting
  at the first rank/role token; ``title_strip_after`` trims the rank at the first
  contact marker (Phone/Email/Office/…). Mechanical's headings are mis-closed on
  every card; ECE's mostly close cleanly, so the same two cleaners are harmless
  no-ops there. Both directories are faculty-only, so the professor|lecturer
  ladder gate is a safety net (drops 0), not the load-bearing filter.

* **Kahlert School of Computing (Gutenberg blocks).**
  ``www.cs.utah.edu/people/faculty/`` is a WordPress/The7 page but the faculty
  are hand-authored ``wp:heading``/``wp:paragraph`` blocks: each person is a
  ``div.t-entry`` with ``h2`` (name), ``h4`` (rank), a ``mailto`` paragraph, and a
  "Research Interests" paragraph. The page also lists ~23 adjunct / affiliated
  faculty as bare ``h2``-only cards with NO rank ``h4`` — a ``field_filter`` on
  ``h4`` (``require_present``) drops those title-less cross-listed cards before
  the engine's missing-title default ("Professor") could wave them through, then
  ``include: professor|lecturer`` keeps the 73 core faculty.

* **Chemistry (dedicated card grid).** ``www.chemistry.utah.edu/faculty-directory/``
  renders one ``div.chem-faculty-card`` per person: name in ``.h3``, the rank as
  the first ``.titles .title`` (a second ``.title`` holds an endowed-chair line),
  a ``mailto``, and research-area *icons* (aria-label only, no text — topics come
  from downstream OpenAlex enrichment). The lone emeriti are dropped by the
  engine's retired-title gate and the ladder gate; ~30 active faculty remain.

* **Mathematics (bio-list).** ``www.math.utah.edu/directory/faculty.php`` is a
  server-rendered ``ul`` of ``li.biolist-item`` rows sub-classed by track
  (``tenure-line`` / ``career-line-faculty`` / ``adjunct`` / ``emeritus`` /
  ``asia``). The card selector keeps only the ``tenure-line`` and
  ``career-line-faculty`` rows, so adjunct/courtesy, emeritus, and Asia-campus
  rows are excluded by construction (the class IS the gate). Name in
  ``h2.h3 a[href]`` (a leading empty in-page anchor is skipped by requiring
  ``href``), rank in ``h3.h5``, ``mailto`` in the row paragraph.

Physics & Astronomy is intentionally NOT built: every faculty endpoint on
web.physics.utah.edu (all-faculty.php / index.php / faculty-by-research-area.php)
returns an Apache "500 Internal Server Error" (a broken PHP directory backend),
so there is no server-rendered roster to scrape this pass.

Single source ("utah_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# The mis-closed The7 headings nest the rank + contacts inside the name heading;
# trim the name back to the person by cutting at the first rank/role token. On a
# cleanly-closed heading (most of ECE) there is no such token, so this is a
# no-op. Deliberately only genuine rank/role words that never occur inside a
# personal name, so it can never truncate a real surname.
_NAME_STRIP = (
    r"\s+(?:Distinguished|Associate|Assistant|Adjunct|Clinical|Visiting|Research"
    r"|Emeritus|Emerita|Endowed|USTAR|Professor|Lecturer|Instructor|Chair|Dept\.?"
    r"|Director|Dir\.?|Dean|Robotics|Advisor|Fellow|Scientist|Coordinator"
    r"|Program|Acting|Interim).*$"
)
# The rank heading absorbs the phone/email/office/excerpt below it; keep only the
# text before the first contact marker.
_TITLE_STRIP_AFTER = r"\s+(?:Phone|Email|Office|Advisor|Fax|Website)\b"

# The7 faculty-card grid shared by ECE and Mechanical Engineering. No research
# selector: the card's ``p.t-entry-excerpt`` is free-form prose ("My research
# focuses specifically on…"), which comma-splits into junk fragments
# ("specifically", "identification") rather than clean topic tags — so topics
# come from downstream OpenAlex enrichment, and the card ships name+title+email.
_CARD_SEL = {
    "card": "div.person-container",
    "name": "h2.t-entry-title",
    "name_strip": _NAME_STRIP,
    "title": "h3.t-entry-meta",
    "title_strip_after": _TITLE_STRIP_AFTER,
    "email": "li.card-email a[href^='mailto:']",
}
_CARD_LADDER = {"require": r"professor|lecturer"}


def _card_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """An ECE/ME department on the shared The7 faculty-card grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CARD_SEL, "ladder_filter": _CARD_LADDER},
    }


SCHOOL: dict = {
    "school_slug": "utah",
    "source": "utah_faculty",
    "organization": "University of Utah",
    "location": "Salt Lake City, UT",
    "id_prefix": "utah",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Utah) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Kahlert School of Computing (Gutenberg blocks) -----------------
        {
            "short": "CS",
            "name": "Kahlert School of Computing",
            "majors": ["Computer Science", "Data Science", "Computer Engineering"],
            "directory_url": "https://www.cs.utah.edu/people/faculty/",
            "scrape": {
                "url": "https://www.cs.utah.edu/people/faculty/",
                "selectors": {
                    "card": "div.t-entry",
                    "name": "h2",
                    "title": "h4",
                    "email": "a[href^='mailto:']",
                    # Research Interests live in a <p> after a <strong> label;
                    # bound just that paragraph so the label doesn't leak in.
                    "research_re": r"Research Interests</strong>(.*?)</p>",
                },
                # The adjunct/affiliated cards are bare h2's with no rank h4 —
                # require the h4 to exist, then keep only professor/lecturer ranks.
                "field_filter": {
                    "selector": "h4",
                    "require_present": True,
                    "include": r"professor|lecturer",
                },
            },
        },
        # ---- The7 faculty-card grid: ECE + Mechanical Engineering -----------
        _card_dept("ECE", "Department of Electrical and Computer Engineering",
                   ["Electrical Engineering", "Computer Engineering"],
                   "https://www.ece.utah.edu/faculty/"),
        _card_dept("ME", "Department of Mechanical Engineering",
                   ["Mechanical Engineering"],
                   "https://www.mech.utah.edu/directory/faculty/"),
        # ---- College of Science: Chemistry ----------------------------------
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.chemistry.utah.edu/faculty-directory/",
            "scrape": {
                "url": "https://www.chemistry.utah.edu/faculty-directory/",
                "selectors": {
                    "card": "div.chem-faculty-card",
                    "name": "div.chem-faculty-card-content-inner div.h3",
                    "link": "div.chem-faculty-card-content-inner a[href*='/faculty/']",
                    # First .title is the rank; a second .title holds an endowed
                    # chair line, which select_one ignores.
                    "title": "div.titles div.title",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"professor|lecturer"},
            },
        },
        # ---- College of Science: Mathematics (bio-list) ---------------------
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics", "Statistics"],
            "directory_url": "https://www.math.utah.edu/directory/faculty.php",
            "scrape": {
                "url": "https://www.math.utah.edu/directory/faculty.php",
                # Keep only tenure-line + career-line faculty rows; adjunct,
                # emeritus, and Asia-campus rows are excluded by construction.
                "selectors": {
                    "card": "li.biolist-item.tenure-line, li.biolist-item.career-line-faculty",
                    # Name is the heading text: some rows link it (a leading empty
                    # <a id="..."> anchor contributes nothing to get_text), others
                    # print it as bare text with no profile anchor at all — so read
                    # the whole h2 and take the profile link only when present.
                    "name": "h2.h3",
                    "link": "h2.h3 a[href]",
                    # Rank is an .h5 element — usually <h3 class="h5"> but a few
                    # rows use <p class="h5">, so key off the class, not the tag.
                    "title": ".h5",
                    # Email is a mailto anywhere in the row (some rows wrap it in a
                    # <p>, some leave it as bare text after the office line).
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"professor|lecturer"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
