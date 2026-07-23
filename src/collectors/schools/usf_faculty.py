"""University of South Florida faculty config (via the faculty_graph engine).

USF runs three distinct faculty-directory platforms; this config covers all
three:

1. **Modern Campus / OmniUpdate static ``.aspx`` CMS** (``www.usf.edu``) — the
   College of Engineering, the Bellini College, and most Arts & Sciences
   departments. Plain server-rendered HTTP 200s (no render mode, no WAF). The
   template does NOT wrap each person in a class-tagged card; a person is a loose
   run of ``<p>`` / ``<h3>`` / ``<h4>`` / table-row markup where the rank is bare
   text (often after a ``<br>``). So the rank is recovered with a shared
   ``title_re`` over the card text rather than a CSS selector, and a handful of
   markup families (image-grid vs table; name-as-link vs ``<h3>`` vs ``<h4>`` vs
   ``<strong>`` vs ``<h5>``) cover every department. Because a title-only gate
   falls through to the engine's default "Professor" on a role-less staff card,
   rosters that MIX non-faculty are gated on the rank field directly
   (``field_filter``) or by role heading (``section_filter``) or by the ladder
   ``drop`` list (Visiting / Adjunct / Emeritus / Affiliate carry those words in
   the captured title).

2. **USF Health "FacultyDirectory" app, server-rendered** (``health.usf.edu``) —
   the College of Public Health and the College of Nursing. Clean class-tagged
   markup (``div.item`` / ``li.directory-person``) with the rank and a real
   ``mailto`` on every card; gated to ladder/teaching faculty on the rank field.

3. **Two A&S link-list directories whose LISTING carries no email** — the School
   of Interdisciplinary Global Studies (Political Science) and Anthropology list
   name + profile-link + rank but paint the address only on the individual
   profile page. These use a per-profile enrich pass (``profile_enrich`` with
   ``always``) that follows each profile and lifts the personal ``mailto`` (a
   shared ``cas-technology@usf.edu`` alias is dropped), so they ship
   majority-emailed rather than as email-less stubs.

Coverage (live-verified 2026-07-24, kept-after-gate counts are approximate):

* Bellini College of AI, Cybersecurity & Computing — CSE.
* College of Engineering — ECE, MAE, Chemical/Biological/Materials (CHBME),
  Civil & Environmental (CEE), Industrial & Management Systems (IMSE),
  Biomedical (BME, core faculty only).
* College of Arts & Sciences — Physics, Chemistry, Mathematics & Statistics,
  Molecular Biosciences + Integrative Biology (Biology), History, Economics,
  Geosciences (Geology / Environmental Science), Communication, School of
  Information, Political Science (SIGS, profile-enriched), Anthropology
  (profile-enriched).
* College of Public Health — one combined roster (all departments).
* College of Nursing — one combined roster.

Dropped / phase-2 (each verified unreachable, not padding):

* **Psychology, Sociology, Philosophy, Journalism, Women's & Gender Studies**
  (A&S) and **all CBCS departments** (Criminology, Social Work, Communication
  Sciences & Disorders, Child & Family Studies, Aging Studies) and the **Muma
  College of Business** (Accounting/Finance/Marketing/Management/ISDS): the
  roster is injected client-side by the ``cloud.usf.edu`` directory/search SPA.
  Verified email-less even under a headless render (only shared inboxes like
  ``cas-technology@usf.edu`` / ``criminology@usf.edu`` appear) — needs phase-2
  reverse-engineering of the ``cloud.usf.edu/FacultyDirectory`` /
  ``cloud.usf.edu/search`` JSON API.
* **World Languages, Public Affairs (Public Administration)**: the ``.aspx``
  listing renders but is majority email-less (addresses on profile pages only);
  candidates for a future profile-enrich pass.

Single source ("usf_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared rank extractor: the USF template prints the rank as bare text after a
# ``<br>`` with no element of its own, so a regex over the card text recovers it
# (leftmost match = the rank right after the name, before office/abstract text).
# Ordered so a fuller phrase wins over bare "Professor"; the trailing Emeritus
# group rides along so the engine's retired-title gate can see "Professor Emeritus".
_USF_TITLE_RE = (
    r"((?:Distinguished\s+University\s+|Distinguished\s+|Executive\s+Associate\s+"
    r"|Associate\s+|Assistant\s+|Research\s+|Visiting\s+|Clinical\s+|Teaching\s+"
    r"|Adjunct\s+|Courtesy\s+|Affiliate\s+|Senior\s+)*"
    r"(?:Professor|Lecturer|Instructor)(?:\s+of\s+(?:Instruction|Practice))?"
    r"(?:\s+Emerit\w+)?)"
)

# Keep every professor / lecturer / instructor rank (USF's teaching track is
# "Professor of Instruction" / "…Instructor"); the engine's retired gate drops
# emeriti. Instructor is included because USF Math's permanent teaching faculty
# carry "Assistant/Associate Instructor" ranks.
_LADDER = {"require": r"professor|lecturer|instructor"}
# For rosters that list Visiting / Adjunct / Emeritus / Affiliate faculty under
# the SAME flat card grid (the title_re captures those modifier words), drop them
# so only home-department ladder faculty ship.
_LADDER_DROP = {
    "require": r"professor|lecturer|instructor",
    "drop": r"visiting|adjunct|emerit|affiliate|courtesy|retired",
}


def _grid(short: str, name: str, majors: list[str], url: str, *,
          name_sel: str, link_sel: str | None = None, ladder: dict | None = None,
          section: dict | None = None, research: str | None = None,
          name_strip: str | None = None, name_title_case: bool = False,
          field_filter: dict | None = None, enrich: dict | None = None) -> dict:
    """A ``div.snippetImageGrid_item`` roster (the USF image-grid family)."""
    selectors: dict = {
        "card": "div.snippetImageGrid_item",
        "name": name_sel,
        "link": link_sel or name_sel,
        "title_re": _USF_TITLE_RE,
        "email": 'a[href^="mailto:"]',
    }
    if research:
        selectors["research"] = research
    if name_strip:
        selectors["name_strip"] = name_strip
    if name_title_case:
        selectors["name_title_case"] = True
    scrape: dict = {"url": url, "selectors": selectors,
                    "ladder_filter": ladder or _LADDER}
    if section:
        scrape["section_filter"] = section
    if field_filter:
        scrape["field_filter"] = field_filter
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _grid_link(short: str, name: str, majors: list[str], url: str,
               *, section_exclude: str | None = None) -> dict:
    """Grid where the name is an ``a`` → ``…/people/faculty/…`` (Bellini CSE)."""
    section = ({"heading": "h3", "exclude": section_exclude}
               if section_exclude else None)
    return _grid(short, name, majors, url,
                 name_sel='a[href*="/people/faculty/"]', section=section)


def _grid_h4(short: str, name: str, majors: list[str], url: str,
             *, field_exclude: str, section_include: str | None = None) -> dict:
    """Grid where the name is an ``<h4>`` and the rank is the following ``<p>``.

    Chemistry and MAE mix non-faculty into the roster, and the rank is bare text
    (no element), so the engine's title-only gate would default a role-less staff
    card to "Professor" and keep it. A ``field_filter`` reads the ``h4 + p`` title
    paragraph directly (``require_present``), keeps only professor/lecturer/
    instructor ranks, and ``exclude``s Affiliate/Adjunct/Emeritus/Retired lines.
    """
    section = ({"heading": "h3", "include": section_include}
               if section_include else None)
    return _grid(short, name, majors, url, name_sel="h4", link_sel="h4 a",
                 field_filter={"selector": "h4 + p", "require_present": True,
                               "include": r"professor|lecturer|instructor",
                               "exclude": field_exclude},
                 section=section)


# Drop table rows that carry no ``mailto`` — the USF A&S table directories append
# a name-only Affiliated / Emeriti / Courtesy roster (rank-less, so a title gate
# defaults it to "Professor" and keeps it). Requiring the address present keeps
# only the real, contactable ladder faculty. (Not used on the profile-enrich
# tables, where the address arrives after the scrape.)
_REQUIRE_EMAIL = {"selector": 'a[href^="mailto:"]', "require_present": True}


def _table(short: str, name: str, majors: list[str], url: str, *,
           link_sub: str, ladder: dict | None = None, name_flip: bool = False,
           research: str | None = None, field_filter: dict | None = None,
           enrich: dict | None = None) -> dict:
    """A ``<table>`` roster: one ``<tr>`` per person, name an ``a`` to a profile."""
    selectors: dict = {
        "card": "table tr",
        "name": f'a[href*="{link_sub}"]',
        "link": f'a[href*="{link_sub}"]',
        "title_re": _USF_TITLE_RE,
        "email": 'a[href^="mailto:"]',
    }
    if research:
        selectors["research"] = research
    scrape: dict = {"url": url, "selectors": selectors,
                    "ladder_filter": ladder or _LADDER}
    if name_flip:
        scrape["name_flip"] = True
    if field_filter:
        scrape["field_filter"] = field_filter
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# Profile-enrich pass for the two A&S link-list directories (SIGS, Anthropology)
# whose listing has no email: follow each profile and lift its first personal
# mailto. ``always`` runs it in the normal refresh (the address is the record's
# core value, not optional depth); the shared campus alias is dropped so it never
# becomes anyone's personal address.
_CAS_EMAIL_ENRICH = {
    "always": True,
    "email_selector": 'a[href^="mailto:"]',
    "email_drop": r"cas-technology@|^info@|^cas@",
    "timeout": 8,
    "max_retries": 1,
}

_ECE_URL = "https://www.usf.edu/engineering/ece/faculty-staff/index.aspx"
_PHYS_URL = ("https://www.usf.edu/arts-sciences/departments/physics/"
             "people/faculty/index.aspx")
_MATH_URL = ("https://www.usf.edu/arts-sciences/departments/"
             "mathematics-statistics/people/faculty/index.aspx")
_AS = "https://www.usf.edu/arts-sciences/departments"


SCHOOL: dict = {
    "school_slug": "usf",
    "source": "usf_faculty",
    "organization": "University of South Florida",
    "location": "Tampa, FL",
    "id_prefix": "usf",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of South Florida) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ================= Bellini College =================================
        # Grid with h3 section headers; keep only the core Faculty section and
        # drop the Affiliated / Adjunct / Courtesy / Distinguished-Emeritus /
        # Emeritus blocks (seven of which carry real profile links).
        _grid_link(
            "CSE", "Department of Computer Science and Engineering",
            ["Computer Science", "Artificial Intelligence", "Cybersecurity",
             "Data Science"],
            "https://www.usf.edu/ai-cybersecurity-computing/people/faculty/index.aspx",
            section_exclude=r"affiliated|adjunct|courtesy|emerit|distinguished",
        ),
        # ================= College of Engineering ==========================
        # Electrical & Computer Engineering: name is a <strong> (bare, wrapped in
        # an <a>, or one bare <a>); the union selector lands it. Faculty-only.
        {
            "short": "ECE",
            "name": "Department of Electrical Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": _ECE_URL,
            "scrape": {
                "url": _ECE_URL,
                "selectors": {
                    "card": "div.snippetImageGrid_item",
                    "name": 'strong, a[href*="/faculty-staff/"]',
                    "link": 'a[href*="/faculty-staff/"]',
                    "title_re": _USF_TITLE_RE,
                    "email": 'a[href^="mailto:"]',
                },
                "ladder_filter": _LADDER,
            },
        },
        # Mechanical (MAE): Core-Faculty block mixes in Affiliate/Adjunct plus
        # Courtesy + Emeritus sections. Gate on the h4+p title paragraph.
        _grid_h4(
            "MAE", "Department of Mechanical Engineering",
            ["Mechanical Engineering", "Aerospace Engineering"],
            "https://www.usf.edu/engineering/mae/people/index.aspx",
            field_exclude=r"affiliate|adjunct|emerit|retired|courtesy",
            section_include=r"core",
        ),
        # Chemical, Biological & Materials Engineering (CHBME): the core-faculty
        # name is an <h3> (the rank is the following <h4>); Emeritus and
        # Affiliated faculty put the name in an <h4> instead — so a ``name = h3``
        # selector lands ONLY core faculty and skips the other two sections by
        # construction (they have no <h3> inside the card). Names carry a "Dr."
        # prefix and some SHOUT, so strip + title-case.
        _grid(
            "CHBME", "Department of Chemical, Biological and Materials Engineering",
            ["Chemical Engineering", "Biomedical Engineering", "Materials Science"],
            "https://www.usf.edu/engineering/chbme/people/index.aspx",
            name_sel="h3", link_sel="h3 a",
            name_strip=r"(?i)^Dr\.\s*", name_title_case=True,
        ),
        # Civil & Environmental Engineering (CEE): name is a <strong>; the rank is
        # the <p> immediately after the name's <p>. All 30 cards are faculty +
        # emailed, but the roster carries one "(retired) Professor" and a couple
        # of research-center directors with no rank word — gate on that rank <p>
        # (require a rank word, drop retired). Strip "Dr." + trailing credentials.
        {
            "short": "CEE",
            "name": "Department of Civil and Environmental Engineering",
            "majors": ["Civil Engineering", "Environmental Engineering"],
            "directory_url": "https://www.usf.edu/engineering/cee/faculty-staff/index.aspx",
            "scrape": {
                "url": "https://www.usf.edu/engineering/cee/faculty-staff/index.aspx",
                "selectors": {
                    "card": "div.snippetImageGrid_item",
                    "name": "strong",
                    "link": 'a[href*="/faculty-staff/"], a[href*="/cee/"]',
                    "title_re": _USF_TITLE_RE,
                    "email": 'a[href^="mailto:"]',
                    "name_strip": r"(?i)^Dr\.\s*|,.*$",
                },
                "field_filter": {"selector": "p:has(strong) + p",
                                 "require_present": True,
                                 "include": r"professor|lecturer|instructor",
                                 "exclude": r"retired|emerit"},
                "ladder_filter": _LADDER,
            },
        },
        # Industrial & Management Systems Engineering (IMSE): name is an
        # <h5><strong>; the rank is the following <p>. Faculty-only + emailed.
        {
            "short": "IMSE",
            "name": "Department of Industrial and Management Systems Engineering",
            "majors": ["Industrial Engineering", "Systems Engineering",
                       "Engineering Management"],
            "directory_url": "https://www.usf.edu/engineering/imse/people/index.aspx",
            "scrape": {
                "url": "https://www.usf.edu/engineering/imse/people/index.aspx",
                "selectors": {
                    "card": "div.snippetImageGrid_item",
                    "name": "h5",
                    "link": "h5 a",
                    "title_re": _USF_TITLE_RE,
                    "email": 'a[href^="mailto:"]',
                    "name_strip": r",.*$",
                },
                "ladder_filter": _LADDER,
            },
        },
        # Biomedical Engineering (BME): name is a <p><a>; the roster is grouped by
        # h3 role headings (Core / Emeritus / Adjunct / Visiting / Affiliate /
        # Courtesy) where ONLY the Core block carries emails — the others are
        # name-only. Keep the Core section (its links + emails) and drop the rest.
        _grid(
            "BME", "Department of Medical Engineering",
            ["Biomedical Engineering", "Medical Engineering"],
            "https://www.usf.edu/engineering/bme/faculty-staff/index.aspx",
            name_sel='p a[href*="/faculty-staff/"]',
            section={"heading": "h3", "include": r"core"},
        ),
        # ================= College of Arts & Sciences ======================
        # Physics: scope to the core faculty table (Emeriti/Affiliated live in
        # collapsible div.snippetToggle_content tables, deeper than a direct child
        # of the mainContent well). Clean single research-area label in last cell.
        {
            "short": "PHYS",
            "name": "Department of Physics",
            "majors": ["Physics", "Applied Physics"],
            "directory_url": _PHYS_URL,
            "scrape": {
                "url": _PHYS_URL,
                "selectors": {
                    "card": "div.mainContent_well > table tr",
                    "name": 'a[href*="/people/faculty/"]',
                    "link": 'a[href*="/people/faculty/"]',
                    "title_re": _USF_TITLE_RE,
                    "research": "td:last-of-type",
                    "email": 'a[href^="mailto:"]',
                },
                "ladder_filter": _LADDER,
            },
        },
        # Chemistry: grid; roster mixes in lab managers / program directors (no
        # rank word), so gate on the h4+p title paragraph.
        _grid_h4(
            "CHEM", "Department of Chemistry",
            ["Chemistry", "Biochemistry"],
            f"{_AS}/chemistry/faculty/index.aspx",
            field_exclude=r"emerit|retired|adjunct",
        ),
        # Mathematics & Statistics: table; names inverted ("Last, First"). Keep
        # Permanent Faculty (the only ladder table with profile links besides
        # Adjunct); Visiting + Postdoc tables carry no links and drop by
        # construction.
        {
            "short": "MATH",
            "name": "Department of Mathematics and Statistics",
            "majors": ["Mathematics", "Statistics", "Applied Mathematics"],
            "directory_url": _MATH_URL,
            "scrape": {
                "url": _MATH_URL,
                "selectors": {
                    "card": "table tr",
                    "name": 'a[href*="/people/faculty/"]',
                    "link": 'a[href*="/people/faculty/"]',
                    "title_re": _USF_TITLE_RE,
                    "email": 'a[href^="mailto:"]',
                },
                "name_flip": True,
                "ladder_filter": {"require": r"professor|lecturer|instructor",
                                  "drop": r"adjunct|visiting|emerit"},
            },
        },
        # Biology is split across two departments; both are the "Biology" major.
        # Molecular Biosciences: grid with two card layouts — some name the person
        # in a profile-link <a>, most in the <a> that IS the mailto (its text is
        # the name). The union selector lands both; email comes from the mailto,
        # and the profile-enrich pass fills the few cards whose email lives only on
        # the profile page.
        _grid(
            "MBS", "Department of Molecular Biosciences",
            ["Biology", "Molecular Biology", "Cell Biology"],
            f"{_AS}/molecular-biosciences/directory/faculty/index.aspx",
            name_sel='p a[href*="/faculty/"], a[href^="mailto:"]',
            link_sel='a[href*="/faculty/"]', enrich=_CAS_EMAIL_ENRICH,
        ),
        # Integrative Biology: grid, name is an <h4><a>; roster groups Leadership /
        # Administrative / Faculty / Adjunct Instructors / Emeriti — drop the last
        # two via the ladder drop list.
        _grid(
            "IB", "Department of Integrative Biology",
            ["Biology", "Ecology", "Evolution", "Marine Biology"],
            f"{_AS}/ib/people/faculty/index.aspx",
            name_sel="h4 a", ladder=_LADDER_DROP,
        ),
        # History: grid, name is a <p><a>; research areas in a trailing <em>.
        # Groups Permanent / Visiting / Adjunct / Emeritus — ladder drop prunes.
        _grid(
            "HIST", "Department of History",
            ["History"],
            f"{_AS}/history/people/index.aspx",
            name_sel='p a[href*="/people/"]', link_sel='p a[href*="/people/"]',
            research="em", ladder=_LADDER_DROP,
        ),
        # Economics: table; name a <p><a>, rank an <em>, email a mailto. A
        # trailing name-only Affiliated/Emeriti roster (inverted names, no email,
        # no rank) is dropped by requiring the address.
        _table(
            "ECON", "Department of Economics",
            ["Economics"],
            f"{_AS}/economics/people/faculty/index.aspx",
            link_sub="/people/faculty/", ladder=_LADDER_DROP,
            field_filter=_REQUIRE_EMAIL,
        ),
        # Geosciences: table; names inverted, research areas in the 2nd cell.
        _table(
            "GEO", "School of Geosciences",
            ["Geology", "Environmental Science and Policy", "Geography"],
            f"{_AS}/geosciences/people/index.aspx",
            link_sub="/people/faculty/", name_flip=True,
            research="td:nth-of-type(2)", ladder=_LADDER_DROP,
            field_filter=_REQUIRE_EMAIL,
        ),
        # Communication: table; names inverted, rank in 2nd cell, research 3rd.
        _table(
            "COMM", "Department of Communication",
            ["Communication"],
            f"{_AS}/communication/people/faculty/index.aspx",
            link_sub="/people/faculty/", name_flip=True,
            research="td:nth-of-type(3)", ladder=_LADDER_DROP,
            field_filter=_REQUIRE_EMAIL,
        ),
        # School of Information: grid, name a <p><a>; groups Administration /
        # Faculty / Affiliate / Emeritus / Adjunct — drop non-home sections.
        _grid(
            "INFO", "School of Information",
            ["Information Technology", "Information Science", "Data Science"],
            f"{_AS}/information/people/index.aspx",
            name_sel='p a[href*="/people/"]', link_sel='p a[href*="/people/"]',
            section={"heading": "h2", "exclude": r"affiliate|emerit|adjunct"},
            ladder=_LADDER_DROP,
        ),
        # Political Science — School of Interdisciplinary Global Studies: grid,
        # name a <p><a>; the LISTING carries no email (address is on the profile
        # page only), so a profile-enrich pass lifts it. Drop the "In memoriam"
        # section.
        _grid(
            "SIGS", "School of Interdisciplinary Global Studies",
            ["Political Science", "International Studies", "Geography"],
            f"{_AS}/school-of-interdisciplinary-global-studies/people/faculty/index.aspx",
            name_sel='p a[href*="/people/faculty/"]',
            section={"heading": "h2", "exclude": r"memoriam"},
            ladder=_LADDER_DROP, enrich=_CAS_EMAIL_ENRICH,
        ),
        # Anthropology: table; names inverted, rank in 2nd cell, research areas in
        # the 3rd cell's <ul>. LISTING carries no email → profile-enrich.
        _table(
            "ANTH", "Department of Anthropology",
            ["Anthropology"],
            f"{_AS}/anthropology/people/index.aspx",
            link_sub="/people/", name_flip=True,
            research="td:nth-of-type(3)", ladder=_LADDER_DROP,
            enrich=_CAS_EMAIL_ENRICH,
        ),
        # ================= USF Health (health.usf.edu) =====================
        # College of Public Health: one combined roster (all departments) on the
        # server-rendered FacultyDirectory app. Rank + department in div.job-title;
        # gate to ladder/teaching faculty. Strip trailing credentials from names.
        {
            "short": "COPH",
            "name": "College of Public Health",
            "majors": ["Public Health", "Epidemiology", "Biostatistics",
                       "Environmental Health"],
            "directory_url": "https://health.usf.edu/publichealth/overviewcoph/faculty/",
            "scrape": {
                "url": "https://health.usf.edu/publichealth/overviewcoph/faculty/",
                "selectors": {
                    "card": "div.item",
                    "name": "span.gv-name",
                    "link": "a.gv-link",
                    "title": "div.job-title",
                    "email": "div.email a",
                    "name_strip": r",.*$",
                },
                "ladder_filter": _LADDER,
            },
        },
        # College of Nursing: one combined roster. Name split across .first/.last
        # (the .name container concatenates them); rank in .positions .primary.
        {
            "short": "NURS",
            "name": "College of Nursing",
            "majors": ["Nursing"],
            "directory_url": "https://health.usf.edu/nursing/faculty-staff/directory/",
            "scrape": {
                "url": "https://health.usf.edu/nursing/faculty-staff/directory/",
                "selectors": {
                    "card": "li.directory-person",
                    "name": "div.name",
                    "link": "a.directory-person-link",
                    "title": "div.positions .primary",
                    "email": "div.contact-email a",
                },
                "ladder_filter": _LADDER,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
