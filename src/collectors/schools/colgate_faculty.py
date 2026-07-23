"""Colgate University faculty config (via the faculty_graph engine).

Colgate is a highly selective US liberal-arts college (~3,000 undergraduates,
no graduate/professional schools) in Hamilton, NY, organized into four academic
divisions — Natural Sciences & Mathematics, Social Sciences, Arts & Humanities,
and University Studies. There is NO per-department faculty roster page: every
department landing page (``colgate.edu/academics/departments-programs/...``) is
a marketing shell, and all people are served from ONE college-wide Drupal
directory View at ``colgate.edu/about/directory`` whose exposed filter form
takes a ``directory_units`` term id (the department/program) and a
``directory_roles`` facet (``faculty``). So a single scrape family covers the
whole college — one shared selector set, one URL per department that differs
only by the numeric unit id.

Markup family (live-verified 2026-07-23, all plain HTTP 200s, no WAF, no render
mode): the results are a stacked ``table.directory__results`` whose every
``tbody tr`` is one person. The name + profile link is the ``.h3 a`` cell (an
``/about/directory/<slug>`` profile); the rank is a bare text node in the same
cell (no wrapping element), so it is recovered with ``title_re`` over the row
text and trimmed of the trailing email/phone/role columns with
``title_strip_after``; the public email, when exposed, is the
``a[href^='mailto:']`` in the contact column. The View pages 25 rows at a time
(``&page=1`` etc.), so query-mode pagination is enabled for the larger
departments (e.g. Economics has 33).

The ``directory_roles=faculty`` facet already removes staff and students, but
it still returns emeriti, visiting appointments, and non-teaching laboratory
instructors, so the ``ladder_filter`` keeps only professorial + lecturer ranks
and drops emeriti/visiting; laboratory instructors carry neither "professor"
nor "lecturer" and so fail the require gate. Colgate professors are frequently
cross-listed onto an interdisciplinary program and their home department (a
biologist also under Environmental Studies or Global Public Health); the core
departments are listed FIRST and the University-Studies programs after, and the
engine's per-school url/email dedup collapses each cross-listed professor to a
single record attributed to a home department.

Single source ("colgate_faculty"); department rides each record, ids namespaced
by department short-code. Audience "unknown". Emails are inline for only part of
the directory (many professors expose only the profile link), so email coverage
is partial; no profile-enrichment pass is configured (topics come from
OpenAlex, and profile enrich is env-gated off in CI anyway).
"""

from __future__ import annotations

from .. import faculty_graph

_DIR = "https://www.colgate.edu/about/directory"

# Shared selectors for the college-wide Drupal directory View (stacked table).
# The rank is a bare text node in the name cell, so it is recovered from the row
# text via ``title_re`` (capturing any leading Visiting/Assistant/... modifiers
# so the ladder gate can see them) and trimmed of the trailing email / phone /
# "Faculty" role columns via ``title_strip_after``.
_SELECTORS = {
    "card": "table.directory__results tbody tr",
    "name": ".h3 a",
    "link": ".h3 a",
    "title_re": (
        r"((?:Visiting |Adjunct |Interim |Acting |Distinguished |Senior |"
        r"Associate |Assistant |University |Research |Clinical |Laboratory |"
        r"Endowed |Family )*"
        r"(?:Professor|Lecturer|Instructor|Artist[- ]in[- ]Residence)[^;]*)"
    ),
    # Cut everything from the first email / phone / trailing role-column word.
    "title_strip_after": r"\s+(?:[\w.+-]+@|\(?\d{3}\)?[\s.-]?\d|Faculty\b|Staff\b)",
    "email": "a[href^='mailto:']",
}

# Keep professorial + lecturer ranks; drop emeriti and visiting appointments.
# Non-teaching laboratory instructors carry no professor/lecturer rank and so
# fail the require gate.
_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|visiting"}

# The directory pages 25 rows at a time; a handful of departments exceed that.
_PAGINATE = {"param": "page", "start": 1, "max": 4}


def _dept(short: str, name: str, majors: list[str], unit: int) -> dict:
    """A Colgate department/program served by the shared directory View."""
    url = f"{_DIR}?directory_units={unit}&directory_roles=faculty"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _SELECTORS,
            "ladder_filter": _LADDER,
            "paginate": _PAGINATE,
        },
    }


SCHOOL: dict = {
    "school_slug": "colgate",
    "source": "colgate_faculty",
    "organization": "Colgate University",
    "location": "Hamilton, NY",
    "id_prefix": "colgate",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Colgate University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics ------------------------------
        _dept("BIO", "Department of Biology", ["Biology"], 1471),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], 1484),
        _dept("CS", "Department of Computer Science", ["Computer Science"], 1481),
        _dept("GEOL", "Department of Earth and Environmental Geosciences",
              ["Earth and Environmental Geosciences", "Geology"], 3476),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], 1476),
        _dept("NEUR", "Neuroscience Program", ["Neuroscience"], 1528),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], 1490),
        _dept("PBS", "Department of Psychological and Brain Sciences",
              ["Psychological and Brain Sciences", "Psychology"], 1492),
        # ---- Social Sciences ---------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], 1502),
        _dept("EDUC", "Department of Educational Studies",
              ["Educational Studies"], 1512),
        _dept("GEOG", "Department of Geography", ["Geography"], 1466),
        _dept("HIST", "Department of History", ["History"], 1494),
        _dept("IR", "International Relations Program",
              ["International Relations"], 1496),
        _dept("POSC", "Department of Political Science",
              ["Political Science"], 1465),
        _dept("SOAN", "Department of Sociology and Anthropology",
              ["Sociology", "Anthropology"], 1488),
        # ---- Arts & Humanities -------------------------------------------
        _dept("ARTH", "Department of Art and Art History",
              ["Art", "Art History"], 3491),
        _dept("CLAS", "Department of Classics", ["Classics"], 1521),
        _dept("EALL", "Department of East Asian Languages and Literatures",
              ["East Asian Languages and Literatures"], 1506),
        _dept("ENGL", "Department of English and Creative Writing",
              ["English", "Creative Writing"], 1474),
        _dept("GERM", "Department of German", ["German"], 1470),
        _dept("MUS", "Department of Music", ["Music"], 1475),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], 1505),
        _dept("RELG", "Department of Religion", ["Religion"], 1477),
        _dept("ROML", "Department of Romance Languages and Literatures",
              ["French", "Spanish", "Italian"], 1504),
        _dept("THEA", "Department of Theater", ["Theater"], 1527),
        _dept("WRIT", "Department of Writing and Rhetoric",
              ["Writing and Rhetoric"], 1486),
        # ---- University Studies (interdisciplinary programs; cross-listed
        #      faculty dedup to a home department above) --------------------
        _dept("AFLAS", "Africana and Latin American Studies Program",
              ["Africana and Latin American Studies"], 1467),
        _dept("ASIA", "Asian Studies Program", ["Asian Studies"], 1495),
        _dept("ENST", "Environmental Studies Program",
              ["Environmental Studies"], 1468),
        _dept("FMST", "Film and Media Studies Program",
              ["Film and Media Studies"], 1499),
        _dept("GPEH", "Global Public and Environmental Health Program",
              ["Global Public and Environmental Health"], 3661),
        _dept("JWST", "Jewish Studies Program", ["Jewish Studies"], 1500),
        _dept("LGBTQ", "LGBTQ Studies Program", ["LGBTQ Studies"], 1487),
        _dept("LING", "Linguistics Program", ["Linguistics"], 1517),
        _dept("MARS", "Medieval and Renaissance Studies Program",
              ["Medieval and Renaissance Studies"], 1497),
        _dept("MEIS", "Middle Eastern Studies and Islamic Civilization Program",
              ["Middle Eastern Studies and Islamic Civilization"], 1509),
        _dept("MUSE", "Museum Studies Program", ["Museum Studies"], 3446),
        _dept("NAIS", "Native American and Indigenous Studies Program",
              ["Native American and Indigenous Studies"], 1478),
        _dept("PCON", "Peace and Conflict Studies Program",
              ["Peace and Conflict Studies"], 1503),
        _dept("REST", "Russian and Eurasian Studies Program",
              ["Russian and Eurasian Studies"], 3656),
        _dept("WGSS", "Women's, Gender, and Sexuality Studies Program",
              ["Women's, Gender, and Sexuality Studies"], 1469),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
