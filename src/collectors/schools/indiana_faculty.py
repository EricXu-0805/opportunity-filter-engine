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

* **JS-rendered rosters recovered via ``render`` (verified 2026-07-23).** The big
  departments dropped by the first pass paint their cards only after a client-
  side fetch, so ``scrape["render"] = True`` runs that JS and the same CSS
  selectors parse the result:
  - The **Luddy School** people directory (``luddy.iu.edu/people/``) is a shell
    whose JS POSTs the URL query to a ``search_results.php`` backend and renders
    ``div.rvt-card`` cards; rendering the wrapper with ``?aca_dept=<id>`` filters
    per department (Computer Science, Data Science, Informatics, Intelligent
    Systems Engineering, Information & Library Science), a ``startNum=50``
    follow-up page picks up the departments over 50 people, and the ladder gate
    drops the assistant-scientists/adjuncts/emeriti. (The Robotics ``aca_dept``
    is skipped — its six faculty are all cross-listed into the departments above
    and net zero unique records after dedup.)
  - **A&S Psychology** (``/directory/faculty/``) and **Cognitive Science**
    (``/directory/faculty-with-effort/``) render the standard ``profile.item``
    card (mailto email); **Statistics** (``/about/core-faculty/``) renders the
    ``profile.feed-item`` sub-title card.
  - The **Kelley School of Business** ``faculty-directory`` page is actually
    fully static — every faculty is an inlined ``div.faculty-directory.grid`` row
    with name + rank + mailto (the char-tabs only filter client-side) — so it
    ships as a single plain scrape, no render needed.

* **O'Neill School — Cascade "system-page" XML feed (no render needed).**
  ``oneill.indiana.edu``'s directory is painted client-side from a Cascade CMS
  export; rather than page-walk the widget, the feed URL
  (``/_feed-xml/faculty.xml``, ~327 ``system-page`` items) is fetched directly as
  the scrape URL — one request carries the whole roster and the engine's
  html.parser reads its data tags fine. Each node yields a name, the
  ``profile-details`` rank ``title``, and a plain ``contact-group email``; the
  ladder gate drops the adjunct / instructor / emeriti / postdoc ranks the export
  mixes in.

Single source ("indiana_faculty"); department rides each record, ids namespaced
by department short-code.

Live-verified card counts 2026-07-23 (pre-ladder / pre-dedupe): Physics 34,
Mathematics 72, Chemistry 98, Biology 92, Economics 26, English 55, Political
Science 24, Astronomy 10, Neuroscience 95, History 79, Biochemistry 36, Media
School 189, Music 226, SPH Epidemiology 43, SPH Kinesiology 48, SPH Applied
Health Science 91. Recovered depts, gate-passing net of dedup (full
fetch_and_normalize, 2026-07-23): Kelley 447, O'Neill 98, Computer Science 48,
Informatics 37, Psychology 36, Data Science 27, Intelligent Systems Engineering
20, Statistics 11, Information & Library Science 11, Cognitive Science 3 (the
Luddy interdisciplinary programs cross-list heavily, so per-department counts
run below their raw rosters after email/URL dedup).
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
# drop the non-faculty cards. Its card has no inline "Research Interests" block
# (so the inherited ``research_re`` never matches), but it DOES carry a clean
# per-person tag list right on the listing card — take those chips (no per-
# profile fetch needed); ``research_items`` is consulted before ``research_re``.
_PROFILE_HIST_SEL = {**_PROFILE_SEL, "title": "p.title",
                     "research_items": "li.profile-tags a"}

# Some A&S directories serve the SAME ``article.profile.item`` card, but only
# after their JS fetches the roster (a plain fetch lands an empty shell), and the
# email arrives as a plain ``mailto:`` anchor rather than the static pages'
# entity-encoded span. ``render: True`` runs that JS; this selector reads the
# rendered mailto.
_PROFILE_RENDER_SEL = {**_PROFILE_SEL,
                       "email": "li.icon-email a[href^='mailto:']"}

# Keep ladder + teaching faculty and lecturers; drop the postdocs, adjuncts, and
# visiting lecturers the rosters mix in. Emeriti are dropped by the engine's own
# retired-title guard (and by drop=emerit here).
_PROFILE_LADDER = {"require": r"professor|lecturer",
                   "drop": r"adjunct|visiting|emerit"}


def _profile_dept(short: str, name: str, majors: list[str], url: str,
                  sel: dict = _PROFILE_SEL, *, render: bool = False) -> dict:
    """A department on the shared IU CMS "profile item" component.

    ``render=True`` routes the fetch through the headless browser for the
    directories that only paint their cards after a client-side roster fetch.
    """
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": _PROFILE_LADDER}
    if render:
        scrape["render"] = True
        scrape["render_settle"] = 4500
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": scrape,
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


# ---- Luddy School: soicbl people-directory (JS wrapper over a PHP search) ----
# ``luddy.iu.edu/people/`` is a shell whose ``people-directory.js`` POSTs the URL
# query (``websiteAddy`` + ``aca_dept``) to ``soicbl-people-directory.webapps.iu
# .edu/search_results.php`` and paints ``div.rvt-card`` cards. Rendering the
# wrapper with ``?aca_dept=<id>`` runs that JS (a plain fetch lands an empty
# skeleton). The server pages 50 cards at a time, so a ``startNum=50`` second
# page is followed for the larger departments. The rank is a bare text node in
# ``.rvt-card__eyebrow`` (which also wraps the name/email), so ``title_re`` lifts
# the clean rank and the ladder gate drops the assistant-scientists, adjuncts,
# and emeriti the roster mixes in. Computer Engineering has no own ``aca_dept`` —
# those faculty sit in Computer Science / Intelligent Systems Engineering.
_LUDDY_URL = "https://luddy.iu.edu/people/index.html"
_LUDDY_SEL = {
    "card": "div.rvt-card",
    "name": "h2.rvt-card__title a",
    "link": "h2.rvt-card__title a",
    "title": ".rvt-card__eyebrow",
    "title_re": _PROFILE_SEL["title_re"],
    "email": "a.email[href^='mailto:']",
}


def _luddy_dept(short: str, name: str, majors: list[str], aca_dept: int) -> dict:
    """A Luddy academic department off the rendered people-directory wrapper."""
    url = f"{_LUDDY_URL}?aca_dept={aca_dept}"
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": _LUDDY_URL,
        "scrape": {
            "url": url, "selectors": _LUDDY_SEL,
            "ladder_filter": _PROFILE_LADDER,
            "render": True, "render_settle": 4500,
            # 50 cards/page server-side; the biggest departments spill onto a
            # second page (a single ``startNum=50`` follow-up covers them — no
            # department here exceeds ~95 people). URL dedup collapses the
            # 1-page departments' clamped re-fetch.
            "paginate": {"param": "startNum", "start": 50, "max": 50},
        },
    }


# ---- Statistics core-faculty (rendered "sub-title" feed-item card) -----------
# ``stat.indiana.edu/about/core-faculty/`` renders ``article.profile.feed-item``
# cards after its roster fetch: the name is a ``span[itemprop=name]`` inside the
# ``h1`` link, the rank is a ``p.sub-title`` line, and the email is a plain
# mailto in the ``dl.meta``. (The ``/about/faculty/`` page carries only the
# adjunct roster, all cross-listed from other departments — deliberately unused.)
_STAT_URL = "https://stat.indiana.edu/about/core-faculty/index.html"
_STAT_SEL = {
    "card": "article.profile.feed-item.core",
    "name": "span[itemprop='name']",
    "link": "h1 a",
    "title": "p.sub-title",
    "email": "a.email[href^='mailto:']",
}

# ---- Kelley School of Business (static faculty-directory grid) ---------------
# ``kelley.iu.edu/faculty-research/faculty-directory/`` inlines every faculty as
# a ``div.faculty-directory.grid`` row (image / name+rank+email / area cell); the
# whole roster ships in the static HTML (the char-tabs only filter it client-
# side). The rank + mailto + office share one ``<p>``, so ``title_re`` lifts the
# rank and the ladder gate drops the emeriti/adjunct/visiting cards.
_KELLEY_URL = "https://kelley.iu.edu/faculty-research/faculty-directory/index.html"
_KELLEY_SEL = {
    "card": "div.faculty-directory.grid",
    "name": "h3 a",
    "link": "h3 a",
    "title": "div.text p",
    "title_re": _PROFILE_SEL["title_re"],
    "email": "a[href^='mailto:']",
    # The card's 3rd grid-item is a comma-delimited research-interest line
    # (verified: "Intercultural Communication, Qualitative Research and Analysis,
    # User Experience (UX) Research") — a zero-fetch listing win.
    "research": "div.grid-item:nth-of-type(3) .text p",
}

# ---- O'Neill School: Cascade "system-page" XML feed --------------------------
# ``oneill.indiana.edu`` paints its directory client-side from a Cascade CMS
# export — ``xml-filter.js`` fetches ``/_feed-xml/faculty.xml`` (~327
# ``system-page`` items) and renders the cards, so a page scrape lands nothing.
# But the feed URL itself is fetched directly as the scrape URL: one request
# carries the whole roster and html.parser reads the data tags cleanly (no
# button page-walk or XML parser needed). Each node has a ``display-name``, the
# ``profile-details`` rank ``title`` (scoped past the social-media share
# ``title`` that precedes it), and a plain ``contact-group email``. The feed
# exposes no per-profile href, so records fall back to the dept listing URL and
# de-dupe on the distinct per-person email; the ladder gate drops the adjunct /
# instructor / emeriti / postdoc ranks the faculty export mixes in.
_ONEILL_URL = "https://oneill.indiana.edu/_feed-xml/faculty.xml"
_ONEILL_SEL = {
    "card": "system-page",
    "name": "display-name",
    "title": "profile-details title",
    "email": "contact-group email",
    # The Cascade XML feed carries per-person <interests><interest> nodes —
    # clean atomic areas straight off the feed (no per-profile fetch).
    "research_items": "interests interest",
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
                # Each profile lists its research areas as "Research Areas"
                # chip buttons; env-gated research-only per-profile pass.
                "profile_enrich": {
                    "research_items_selector": "a.btn-chemiub-blue",
                    "throttle": 0.2,
                },
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
        # A&S directories that render the same profile-item card only after a
        # client-side roster fetch (email arrives as a plain mailto).
        _profile_dept(
            "PSY", "Department of Psychological and Brain Sciences",
            ["Psychology", "Neuroscience"],
            "https://psych.indiana.edu/directory/faculty/index.html",
            sel=_PROFILE_RENDER_SEL, render=True),
        _profile_dept(
            "COGS", "Cognitive Science Program", ["Cognitive Science"],
            "https://cogs.indiana.edu/directory/faculty-with-effort/index.html",
            sel=_PROFILE_RENDER_SEL, render=True),
        {
            "short": "STAT", "name": "Department of Statistics",
            "majors": ["Statistics", "Data Science"],
            "directory_url": _STAT_URL,
            "scrape": {"url": _STAT_URL, "selectors": _STAT_SEL,
                       "ladder_filter": _PROFILE_LADDER,
                       "render": True, "render_settle": 4500},
        },
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
        # ---- Luddy School of Informatics, Computing, and Engineering -------
        _luddy_dept(
            "CS", "Department of Computer Science",
            ["Computer Science BS", "Computer Science BA", "Computer Engineering"],
            aca_dept=1),
        _luddy_dept(
            "DS", "Department of Data Science", ["Data Science"], aca_dept=5),
        _luddy_dept(
            "INFO", "Department of Informatics", ["Informatics"], aca_dept=3),
        _luddy_dept(
            "ISE", "Department of Intelligent Systems Engineering",
            ["Intelligent Systems Engineering", "Computer Engineering"],
            aca_dept=4),
        _luddy_dept(
            "ILS", "Department of Information and Library Science",
            ["Information Science", "Library Science"], aca_dept=2),
        # (The Luddy Robotics program, ``aca_dept=7``, is deliberately not wired:
        # all six of its gate-passing faculty are cross-listed and land under
        # Computer Science / Intelligent Systems Engineering / Informatics, so a
        # standalone Robotics department nets zero unique records after dedup.)
        # ---- Kelley School of Business (single static directory) -----------
        {
            "short": "KELLEY", "name": "Kelley School of Business",
            "majors": ["Accounting", "Finance", "Marketing", "Business Analytics",
                       "Supply Chain Management", "Business Economics", "Management",
                       "Operations Management", "Information Systems"],
            "directory_url": _KELLEY_URL,
            "scrape": {"url": _KELLEY_URL, "selectors": _KELLEY_SEL,
                       "ladder_filter": _PROFILE_LADDER},
        },
        # ---- O'Neill School of Public and Environmental Affairs ------------
        {
            "short": "ONEILL",
            "name": "O'Neill School of Public and Environmental Affairs",
            "majors": ["Environmental Science", "Policy Analysis",
                       "Law and Public Policy",
                       "Nonprofit Management and Leadership"],
            "directory_url": "https://oneill.indiana.edu/faculty-research/directory/index.html",
            "scrape": {"url": _ONEILL_URL, "selectors": _ONEILL_SEL,
                       "ladder_filter": _PROFILE_LADDER},
        },
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
