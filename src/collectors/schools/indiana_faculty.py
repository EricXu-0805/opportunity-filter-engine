"""Indiana University Bloomington faculty config (via the faculty_graph engine).

Only the departments that server-render their faculty over plain HTTP are wired
here — every URL below was live-verified through a proxy on 2026-07-23 (clean
200s, real card grids in the static HTML, no JS-only render, no WAF). IU
Bloomington's campus sites run several CMS templates; four distinct card shapes
are covered:

* **IU CMS "profile item" card** — the College of Arts & Sciences workhorse.
  ``<subdomain>.indiana.edu/about/faculty/`` (Biology, Economics, English,
  Political Science, Biochemistry), ``.../directory/faculty/`` (Astronomy), and
  the Physics / Mathematics directories all render each person as an
  ``article.profile.item``: name in ``h1 > a`` (linking to a per-person page),
  a ``p.title.small`` rank line, an entity-encoded email span under
  ``li.icon-email`` (rot13 *decoy* attributes the engine ignores), and a
  "Research Interests" block. A ``title_re`` recovers the academic rank from
  whichever title line carries it (an admin role can lead), and a ladder filter
  drops the postdocs / adjuncts / visiting / emeriti the mixed rosters include.
  History uses the same card but the rank sits in a plain ``p.title`` (no
  ``small``) alongside genuine staff, so its selector reads ``p.title`` directly
  and lets the ladder gate drop the non-faculty.

* **Chemistry — the older Bootstrap ``dv-header`` grid.**
  ``www.chem.indiana.edu/people/faculty/`` is one flat grid of
  ``div.col-sm-4.text-center`` cards; a ``title_strip_after`` camelCase split
  recovers the primary rank from concatenated multi-role cards so the ladder
  filter keeps primary-chemistry professors while dropping adjunct / scientist /
  emeritus / staff cards.

* **IU "sub-title" card** — the Media School and Jacobs School of Music.
  ``mediaschool.indiana.edu/people/faculty/`` (``article.profile.item``) and
  ``music.indiana.edu/faculty/`` (``article.profile.feed-item``) share a body
  layout: the name is a ``span[itemprop=name]`` inside the ``p.title`` link and
  the rank is a separate ``p.sub-title`` line, with a plain ``mailto:`` email.

* **School of Public Health ``sph-profile`` card.**
  ``publichealth.indiana.edu/about/directory/`` is one static campus-wide grid of
  ``article.sph-profile`` cards carrying a per-card ``.sph-profile__department``
  cell — so a single URL, gated by a ``field_filter`` on that cell, yields each
  SPH department (Epidemiology & Biostatistics, Kinesiology, Applied Health
  Science) cleanly. Research interests ride as ``.rvt-badge`` chips.

Not shipped (JS-rendered or WAF-walled, verified 2026-07-23 — a plain-HTTP fetch
returns an empty skeleton or a ``data-config-file`` feed shell with zero cards):
the Luddy School (Computer Science, Informatics, Intelligent Systems Engineering,
Data Science, Computer Engineering), the Kelley School of Business (names live
only in image ``alt`` text, no titles), the O'Neill School, and the A&S
Psychology, Statistics, and Cognitive Science directories. Those are deferred to
a headless-render pass and omitted here rather than shipped unverified.

Single source ("indiana_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified card counts 2026-07-23 (pre-ladder / pre-dedupe): Physics 34,
Mathematics 72, Chemistry 98, Biology 92, Economics 26, English 55, Political
Science 24, Astronomy 10, Neuroscience 95, History 79, Biochemistry 36, Media
School 189, Music 226, SPH Epidemiology 43, SPH Kinesiology 48, SPH Applied
Health Science 91.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- IU CMS "profile item" card (College of Arts & Sciences) -----------------
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

# History uses the same profile-item card but keeps the rank in a plain
# ``p.title`` (no ``small``) and lists genuine staff alongside faculty — reading
# the real title element (not the "Professor" default) lets the ladder gate below
# drop the non-faculty cards.
_PROFILE_HIST_SEL = {**_PROFILE_SEL, "title": "p.title"}

# Keep ladder + teaching faculty and lecturers; drop the postdocs, adjuncts, and
# visiting lecturers the rosters mix in. Emeriti are dropped by the engine's own
# retired-title guard (and by drop=emerit here).
_PROFILE_LADDER = {"require": r"professor|lecturer",
                   "drop": r"adjunct|visiting|emerit"}


def _profile_dept(short: str, name: str, majors: list[str], url: str,
                  sel: dict = _PROFILE_SEL) -> dict:
    """A department on the shared IU CMS "profile item" component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": sel, "ladder_filter": _PROFILE_LADDER},
    }


# ---- IU "sub-title" card (Media School, Jacobs School of Music) --------------
# The name is a span[itemprop=name] inside the p.title link; the rank is a
# separate p.sub-title line. Only the card class differs between the two schools
# (Media = article.profile.item, Music = article.profile.feed-item), so the body
# selectors below are shared and the card is injected per department.
_SUBTITLE_SEL = {
    "name": "span[itemprop='name']",
    "link": "p.title a",
    "title": "p.sub-title",
    "email": "a[href^='mailto:']",
}


def _subtitle_dept(short: str, name: str, majors: list[str], url: str,
                   card: str) -> dict:
    """A department on the IU "sub-title" card (name span + p.sub-title rank)."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": {**_SUBTITLE_SEL, "card": card},
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


# ---- School of Public Health: campus-wide sph-profile grid ------------------
# One static directory of every SPH person; each card carries its home
# department in ``.sph-profile__department``. A field_filter on that cell splits
# the single URL into per-department rosters, and the ladder gate keeps only the
# professorial/lecturer titles (dropping the research managers, coordinators, and
# other staff the campus directory mixes in). Interest chips ride as keywords.
_SPH_URL = "https://publichealth.indiana.edu/about/directory/index.html"
_SPH_SEL = {
    "card": "article.sph-profile",
    "name": ".sph-profile__name",
    "link": ".sph-profile__name a",
    "title": ".sph-profile__title",
    "email": ".sph-profile__email a",
    "research_items": ".sph-profile__interest-tags .rvt-badge",
}
_SPH_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|visiting"}


def _sph_dept(short: str, name: str, majors: list[str], dept_match: str) -> dict:
    """An SPH department carved out of the campus-wide directory by field_filter."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": _SPH_URL,
        "scrape": {
            "url": _SPH_URL, "selectors": _SPH_SEL,
            "ladder_filter": _SPH_LADDER,
            "field_filter": {"selector": ".sph-profile__department",
                             "require_present": True, "include": dept_match},
        },
    }


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
        _profile_dept(
            "BIOL", "Department of Biology", ["Biology"],
            "https://biology.indiana.edu/about/faculty/index.html"),
        _profile_dept(
            "BIOC", "Department of Molecular and Cellular Biochemistry",
            ["Biochemistry", "Biology"],
            "https://biochemistry.indiana.edu/about/faculty/index.html"),
        _profile_dept(
            "NSCI", "Program in Neuroscience", ["Neuroscience"],
            "https://neuroscience.indiana.edu/about/faculty/index.html"),
        _profile_dept(
            "ASTR", "Department of Astronomy",
            ["Astronomy and Astrophysics", "Astronomy", "Astrophysics"],
            "https://astro.indiana.edu/directory/faculty/index.html"),
        _profile_dept(
            "ECON", "Department of Economics", ["Economics"],
            "https://economics.indiana.edu/about/faculty/index.html"),
        _profile_dept(
            "ENGL", "Department of English", ["English"],
            "https://english.indiana.edu/about/faculty/index.html"),
        _profile_dept(
            "POLS", "Department of Political Science", ["Political Science"],
            "https://polisci.indiana.edu/about/faculty/index.html"),
        _profile_dept(
            "HIST", "Department of History", ["History"],
            "https://history.indiana.edu/faculty_staff/index.html",
            sel=_PROFILE_HIST_SEL),
        # ---- The Media School ----------------------------------------------
        _subtitle_dept(
            "MSCH", "The Media School",
            ["Journalism", "Media", "Game Design", "Public Relations"],
            "https://mediaschool.indiana.edu/people/faculty/index.html",
            card="article.profile.item"),
        # ---- Jacobs School of Music ----------------------------------------
        _subtitle_dept(
            "MUS", "Jacobs School of Music",
            ["Music Performance", "Music Composition", "Jazz Studies"],
            "https://music.indiana.edu/faculty/index.html",
            card="article.profile.feed-item"),
        # ---- School of Public Health-Bloomington ---------------------------
        _sph_dept(
            "EPID", "Department of Epidemiology and Biostatistics",
            ["Epidemiology"], r"Epidemiology and Biostatistics"),
        _sph_dept(
            "KIN", "Department of Kinesiology", ["Exercise Science"],
            r"Kinesiology"),
        _sph_dept(
            "AHS", "Department of Applied Health Science",
            ["Nutrition Science"], r"Applied Health Science"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
