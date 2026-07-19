"""Indiana University Bloomington faculty config (via the faculty_graph engine).

Only the departments that server-render their faculty over plain HTTP are wired
here — all three verified live through a proxy on 2026-07-19 (clean 200s, no JS
render, no WAF). Two distinct campus templates:

* **Physics & Astronomy and Mathematics — the IU CMS "profile item" card.**
  ``physics.indiana.edu/about/directory/all-faculty-scientists/faculty/`` and
  ``math.indiana.edu/about/faculty/`` share one component: each person is an
  ``article.profile.item`` with the name in ``h1 > a`` (linking to a per-person
  ``<slug>.html`` page), one or more ``p.title.small`` rank lines, an email span
  under ``li.icon-email``, and a "Research Interests" block in the
  ``itemprop="description"`` paragraph. The email span is HTML-entity-encoded
  text (with rot13 *decoy* attributes the engine ignores) that decodes to the
  real ``@iu.edu`` address. Physics' page is already faculty-only (34 professors);
  Math's mixes in postdocs / adjuncts / visiting lecturers / a couple of
  administrators whose directorship is listed on the first title line, so a
  ``title_re`` recovers the academic rank from whichever line carries it and a
  ladder filter drops the postdocs/adjuncts/visiting. Research interests land as
  keywords.

* **Chemistry — the older Bootstrap ``dv-header`` grid.**
  ``www.chem.indiana.edu/people/faculty/`` is one flat grid of
  ``div.col-sm-4.text-center`` cards (name in ``div.dv-header > a`` linking to
  ``/faculty/<slug>``, rank in ``small.text-muted``, a ``mailto:`` email). It is
  the whole people roster — ladder faculty plus research scientists, adjuncts,
  emeriti, lecturers, and a few staff/directors. Several cards concatenate a
  faculty member's multiple roles with no separator ("ProfessorAdjunct Professor,
  Physics"); a ``title_strip_after`` camelCase split recovers the primary rank so
  the ladder filter can keep primary-chemistry professors (with a secondary
  physics adjunct) while dropping the pure adjunct / scientist / emeritus / staff
  cards. Chemistry cards carry no research text (topics come from downstream
  OpenAlex enrichment).

IU Bloomington's Computer Science, Intelligent Systems Engineering (its
electrical/computer-engineering home), and the mechanical/biomedical topics all
live in the Luddy School behind a JS-shell directory (``needs_render_js``) — a
plain-HTTP AJAX endpoint exists but the front page renders no cards, so those
three are deferred to a headless-render pass and not shipped here.

Single source ("indiana_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified 2026-07-19 (cards seen / kept after title gate): Physics 34/34,
Mathematics 72/54, Chemistry 98/53 (pre-dedupe).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- IU CMS "profile item" card (Physics & Astronomy, Mathematics) ----------
# One shared component. The name is the h1 anchor (the figure's image anchor has
# no text, so h1 a is unambiguous). The email span is entity-encoded text the
# engine's _email_from_el decodes (its rot13 decoy attrs carry no data-mail-to,
# so they're ignored). research_re bounds the "Research Interests" line; the
# engine splits it into keywords.
_PROFILE_SEL = {
    "card": "article.profile.item",
    "name": "h1 a",
    "link": "h1 a",
    "title": "p.title.small",
    # A person's academic rank may not be the first title line (an admin role can
    # lead, e.g. "Director of Graduate Studies" then "Professor"); pull the rank
    # from whichever line carries it. The optional Emeritus tail keeps the
    # retired-title guard working when title_re overrides the CSS title.
    "title_re": (
        r"((?:Adjunct |Clinical |Distinguished |Associate |Assistant |Senior "
        r"|Visiting |Provost |Teaching )*(?:Professor|Lecturer)(?: Emerit\w+)?)"
    ),
    "email": "li.icon-email span",
    "research_re": r"Research Interests</strong>(.*?)</p>",
}

# Keep ladder + teaching faculty and lecturers; drop the postdocs, adjuncts, and
# visiting lecturers the Math roster mixes in. Emeriti are dropped by the engine's
# own retired-title guard (and by drop=emerit here).
_PROFILE_LADDER = {"require": r"professor|lecturer",
                   "drop": r"adjunct|visiting|emerit"}


def _profile_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared IU CMS "profile item" component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _PROFILE_SEL,
                   "ladder_filter": _PROFILE_LADDER},
    }


# ---- Chemistry: older Bootstrap dv-header grid ------------------------------
_CHEM_URL = "https://www.chem.indiana.edu/people/faculty/"
_CHEM_SEL = {
    "card": "div.col-sm-4.text-center",
    "name": "div.dv-header a",
    "link": "div.dv-header a",
    "title": "small.text-muted",
    # Several cards concatenate multiple roles with no separator
    # ("ProfessorAdjunct Professor, Physics"); split at the lowercase→uppercase
    # boundary to keep the primary (first) role so the ladder gate reads it
    # cleanly and a secondary "Adjunct Professor of Physics" suffix can't drop a
    # primary-chemistry professor. A spaced "Professor Emeritus" has no such
    # boundary, so it stays intact for the retired-title guard.
    "title_strip_after": r"(?<=[a-z])(?=[A-Z])",
    "email": "a[href^='mailto:']",
}
# Keep professors + lecturers; drop research scientists (no professor/lecturer
# word), emeriti, pure/leading adjuncts, and visiting appointments. The
# camelCase split above already stripped secondary "Adjunct …" suffixes off
# primary-faculty cards, so drop=adjunct now targets only true adjunct-first
# cards.
_CHEM_LADDER = {"require": r"professor|lecturer",
                "drop": r"emerit|adjunct|visiting"}


SCHOOL: dict = {
    "school_slug": "indiana",
    "source": "indiana_faculty",
    "organization": "Indiana University Bloomington",
    "location": "Bloomington, IN",
    "id_prefix": "indiana",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Indiana University Bloomington) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences ------------------------------------
        _profile_dept(
            "PHYS", "Department of Physics",
            ["Physics", "Astronomy", "Astrophysics"],
            "https://physics.indiana.edu/about/directory/all-faculty-scientists/faculty/index.html"),
        _profile_dept(
            "MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"],
            "https://math.indiana.edu/about/faculty/index.html"),
        {
            "short": "CHEM", "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": _CHEM_URL,
            "scrape": {
                "url": _CHEM_URL,
                "selectors": _CHEM_SEL,
                "ladder_filter": _CHEM_LADDER,
                "link_filter": r"/faculty/",
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
