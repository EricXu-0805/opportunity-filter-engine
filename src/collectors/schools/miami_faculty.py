"""University of Miami faculty config (via the faculty_graph engine).

Two server-rendered markup families, both plain static 200s to a bare request
(no WAF, no JS render). Live-verified 2026-07-19.

* **Cascade CMS "people-profile" cards (six departments).**
  The College of Arts & Sciences (csc/physics/chemistry.as.miami.edu) and the
  College of Engineering (ece/mae/bme.coe.miami.edu) share one campus people
  component. Computer Science renders it as a table (``li.people-profile`` with a
  desktop + mobile copy per row); the other five render it as a grid
  (``div.people-profile``). Both carry the SAME inner classes, so ``.people-profile``
  as the card selector and ``.profile-name span`` / ``.profile-position span`` for
  name / rank cover every department. The profile link is the ``a.url-rewrite``
  that points at ``people.miami.edu/profile/<hash>``.

  Email is NOT recoverable here: every card hides the address in a
  ``<a class="email-decode" data-code="HEX">`` where HEX is the UTF-16-BE code
  units of the address (e.g. ``0076007800610033…`` → ``vxa305@miami.edu``),
  decoded client-side by Cascade's JS. The engine has no decoder for this scheme
  (it decodes Cloudflare / base64 ``data-email`` / rot13 ``data-mail-to`` only),
  so these six departments land name+title only — topics/emails come from
  downstream OpenAlex enrichment. See ``engine_gaps`` in the onboarding report.

  Title gate (``ladder_filter require: professor|lecturer``): the /people/faculty/
  pages are faculty-only but mix in a College Dean and an Assistant Vice Provost
  whose card titles carry no rank — the require gate drops those two while keeping
  every professor / lecturer rank (incl. research / visiting / professor-of-practice).
  Emeriti (rare on these pages) are dropped by the engine's own retired-title gate.

* **Mathematics — legacy hand-maintained ``<p>`` list.**
  ``mathematics.miami.edu/about-us/faculty/`` is NOT the people-profile template:
  each faculty member is one ``<content> <p>`` block holding ``<strong>Name</strong>,
  Rank <br> … Research Interests: <areas> <br> Email: <a mailto>``. Name in the
  ``<strong>`` (a trailing comma some rows put inside the strong is stripped),
  rank via a first-match ``title_re`` over the card text, research areas via
  ``research_re`` (the "Research Interests:" line), and — uniquely for this school
  — a real ``mailto`` per person. The ladder require drops the two honorary
  "Distinguished Scholar" rows (no professor rank) and the engine's retired gate
  drops the lone "Professor Emeritus".

Single source ("miami_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-19 (cards → kept-after-gate): CS 23/21, ECE 18/17,
Physics 23/23, Chemistry 29/27, MAE 17/17, BME 20/18, Mathematics 33/30.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Shared Cascade CMS "people-profile" component -------------------------
# CS renders it as a table row (li.people-profile, desktop + mobile copy),
# the other five as a grid card (div.people-profile); ``.people-profile`` covers
# both. select_one takes the first match, so the CS row's duplicate copies
# collapse to one name/title. Name sits in a <span> under .profile-name (an
# <h2> in the grid, an <h2><a> in the table); rank sits in .profile-position.
_CASCADE_SEL = {
    "card": ".people-profile",
    "name": ".profile-name span",
    "link": "a.url-rewrite[href*='/profile/']",
    "title": ".profile-position span",
    # Present on every card but the address is UTF-16 hex in data-code, which the
    # engine can't decode — so this yields None (name+title-only records). Kept so
    # a future engine decoder lights the field up without a config change.
    "email": "a.email-decode",
}
# Keep every professor / lecturer rank; drop the title-less admin cards (a College
# Dean, an Assistant Vice Provost) that ride the faculty page. Emeriti drop via the
# engine's retired-title gate.
_CASCADE_LADDER = {"require": r"professor|lecturer"}


def _cascade(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared Cascade people-profile component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CASCADE_SEL,
                   "ladder_filter": _CASCADE_LADDER},
    }


# ---- Mathematics: legacy <p>-list template ---------------------------------
_MATH_URL = "https://mathematics.miami.edu/about-us/faculty/index.html"
# First rank phrase in the card text ("Ming-Liang Cai, Associate Professor<br>…").
# Ordered so a fuller phrase wins over the bare "Professor" (Distinguished /
# Emeritus suffixes ride along so the retired gate can see "Professor Emeritus").
_MATH_TITLE_RE = (
    r"((?:Distinguished |Research |Visiting |Clinical |Senior )*"
    r"(?:Assistant |Associate )?Professor(?:\s+Emerit\w+)?|Senior Lecturer|Lecturer)"
)


SCHOOL: dict = {
    "school_slug": "miami",
    "source": "miami_faculty",
    "organization": "University of Miami",
    "location": "Coral Gables, FL",
    "id_prefix": "miami",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Miami) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences -----------------------------------
        _cascade("CS", "Department of Computer Science",
                 ["Computer Science", "Data Science"],
                 "https://csc.as.miami.edu/people/faculty/index.html"),
        _cascade("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
                 "https://physics.as.miami.edu/people/index.html"),
        _cascade("CHEM", "Department of Chemistry",
                 ["Chemistry", "Biochemistry"],
                 "https://chemistry.as.miami.edu/people/faculty/index.html"),
        # ---- College of Engineering ---------------------------------------
        _cascade("ECE", "Department of Electrical and Computer Engineering",
                 ["Electrical Engineering", "Computer Engineering"],
                 "https://ece.coe.miami.edu/people/faculty/index.html"),
        _cascade("MAE", "Department of Mechanical and Aerospace Engineering",
                 ["Mechanical Engineering", "Aerospace Engineering"],
                 "https://mae.coe.miami.edu/people/faculty/index.html"),
        _cascade("BME", "Department of Biomedical Engineering",
                 ["Biomedical Engineering"],
                 "https://bme.coe.miami.edu/people/faculty/index.html"),
        # ---- Department of Mathematics (legacy <p>-list) ------------------
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": _MATH_URL,
            "scrape": {
                "url": _MATH_URL,
                "selectors": {
                    "card": "content p",
                    "name": "strong",
                    "name_strip": r",\s*$",
                    "title_re": _MATH_TITLE_RE,
                    "research_re": r"Research Interests?:\s*(?:</em>)?(.*?)(?:<br\s*/?>\s*Email|Email\s*:)",
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
