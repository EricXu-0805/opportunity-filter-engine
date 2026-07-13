"""Dartmouth College faculty config (via the faculty_graph engine).

Dartmouth's directories are all server-rendered (no WAF, no JS grids) across
five markup families, verified live 2026-07-12:

* Arts & Sciences shared Drupal "profile-card" theme (37 depts/programs on
  ``<dept>.dartmouth.edu``). Cards are ``.views-row .profile-card`` with the
  name/profile link on ``a.profile-card__name``, the rank on
  ``.profile-card__appointments p``, and a role tag (``a.profile-card__tag``:
  Faculty / Staff / Emeriti / Graduate Students / …). Affiliates carry clean
  professor titles from their home departments, so the ladder gate here is the
  TAG, not the title (``field_filter`` on the tag element). Emails are not on
  the listing OR behind a mailto — profiles keep them as plain text in the
  first ``.field--field-hb-number`` (email, then phone/office/Hinman Box), so
  the enrich pass reads that field and ``email_drop``s anything that isn't
  address-shaped. Verified live: Anthropology 15, Economics 40, English 35.

* Legacy Drupal "node-person" theme (Physics & Astronomy, Earth Sciences).
  One page grouped by lowercase ``h2`` role headings — ``section_filter`` on
  ``^faculty$`` keeps the 30/15 ladder rosters. Profiles expose a real mailto
  (``.pane-node-field-ldap-email``) and clean expertise spans.

* Math's hand-rolled PHP directory (``people-select.php?list=permanent``) —
  the only listing WITH emails. The name has no wrapper element, so the name
  selector takes the whole ``div.text`` and ``name_strip`` cuts the title tail.

* Thayer School of Engineering: one page, 161 ``div.profile-box`` grouped
  under ``h2`` "Core (85)" / "Lecturer (22)" / Adjunct / Emeriti headings.

* Tuck School of Business: 99 static ``div.faculty-card`` with a
  ``data-faculty-role`` attribute — the card selector keeps ``"tuck"`` (71
  core) and drops visiting.

* Geisel School of Medicine: the Faculty Expertise Database is server-rendered
  behind a fully-parameterized GET; six basic-science departments are wired
  (clinical departments deferred). No emails anywhere on Geisel results.

Single source ("dartmouth_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred: Geisel clinical departments (Medicine, Surgery, …— same DB, huge
and clinician-heavy), Guarini (no faculty directory — draws from other
schools' rosters). Physiology & Neurobiology was probed and dropped: its DB
roster is 7 emeriti (the department merged into Molecular and Systems
Biology), so the ladder gate correctly yields zero.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Arts & Sciences shared Drupal "profile-card" theme --------------------
_AS_SELECTORS = {
    "card": ".views-row .profile-card",
    "name": "a.profile-card__name",
    "link": "a.profile-card__name",
    "title": ".profile-card__appointments p",
}

# Ladder gate by role TAG (affiliates/emeriti/staff/grads have their own tags;
# titles alone can't separate an affiliate's home-dept professorship).
_AS_TAG_FILTER = {
    "selector": "a.profile-card__tag",
    "include": r"^(?:core\s+)?faculty$|^(?:department\s+)?chair$|^joint\s+(?:appointments|titles)\b",
}

# Profile pages keep the email as PLAIN TEXT in the first contact field
# (email, then office/Hinman Box) — drop anything that isn't address-shaped.
# No research_selector here: A&S profile bodies are BIOS, not research
# summaries — comma-split bio prose ("A native of Switzerland and Italy")
# poisons the keyword list. Research topics come from the OpenAlex pass.
_AS_ENRICH = {
    "email_selector": ".field--field-hb-number",
    "email_drop": r"^[^@]*$|department@|@office\.",
    "throttle": 0.15,
}

# ---- Legacy Drupal "node-person" theme (physics, earthsciences) ------------
_NP_SELECTORS = {
    "card": "article.node-person",
    "name": ".content h3 a",
    "link": ".content h3 a",
    "title": ".content ul.field-items li.field-item",
}

_NP_SECTION = {"heading": "h2", "include": r"^faculty$"}

_NP_ENRICH = {
    "email_selector": ".pane-node-field-ldap-email a[href^='mailto:']",
    "email_drop": r"^[^@]*$|department@",
    "research_items_selector": ".people-expertise span:not(.spacer)",
    "throttle": 0.15,
}

# Keep ladder faculty; drop emeriti stragglers (in-memoriam etc.).
_LADDER = {"drop": r"emerit"}

# Full require-gate for rosters where the section/tag can't do the work
# (Geisel DB rows mix Instructors and Emeritus Professors into one table).
_LADDER_STRICT = {"require": r"\bprofessor\b|\blecturer\b", "drop": r"emerit|adjunct|visiting"}


def _as(short: str, name: str, majors: list[str], subdomain: str,
        path: str = "/people") -> dict:
    """An Arts & Sciences department on the shared profile-card theme."""
    url = f"https://{subdomain}.dartmouth.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_SELECTORS,
                       "ladder_filter": _LADDER, "field_filter": _AS_TAG_FILTER,
                       "profile_enrich": _AS_ENRICH}}


def _np(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    """A legacy node-person department (physics, earthsciences)."""
    url = f"https://{subdomain}.dartmouth.edu/people"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _NP_SELECTORS,
                       "section_filter": _NP_SECTION, "ladder_filter": _LADDER,
                       "profile_enrich": _NP_ENRICH}}


def _geisel(short: str, dept: str, majors: list[str]) -> dict:
    """A Geisel School of Medicine department via the Faculty Expertise DB.

    The search endpoint 200s with an error page unless EVERY GET param is
    present — keep the full canonical param set.
    """
    from urllib.parse import quote_plus
    url = ("https://geiselmed.dartmouth.edu/faculty/facultydb/search/"
           "?search_fields=Department&search_op=AND&sort_field=Name_Last"
           f"&sort_order=ASC&exact=1&search_query={quote_plus(dept)}&search=Search")
    return {"short": short, "name": f"Department of {dept} (Geisel)", "majors": majors,
            "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "table.faculty_results td",
                                     "name": "h4 a", "link": "h4 a", "title": "p"},
                       "ladder_filter": _LADDER_STRICT}}


SCHOOL: dict = {
    "school_slug": "dartmouth",
    "source": "dartmouth_faculty",
    "organization": "Dartmouth College",
    "location": "Hanover, NH",
    "id_prefix": "dartmouth",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Dartmouth College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Arts & Sciences: Arts and Humanities -------------------------
        _as("ARTH", "Department of Art History", ["Art History"], "arthistory"),
        _as("SART", "Department of Studio Art", ["Studio Art"], "studioart", path="/people/people"),
        _as("CLAS", "Department of Classics", ["Classics"], "classics"),
        _as("COLT", "Program in Comparative Literature", ["Comparative Literature"], "complit"),
        _as("ENGL", "Department of English and Creative Writing",
            ["English", "Creative Writing"], "english"),
        _as("FILM", "Department of Film and Media Studies", ["Film and Media Studies"],
            "film-media"),
        _as("FRIT", "Department of French and Italian", ["French", "Italian"], "frandit"),
        _as("GERM", "Department of German Studies", ["German Studies"], "german",
            path="/people/faculty-staff"),
        _as("MUS", "Department of Music", ["Music"], "music", path="/people/people"),
        _as("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),
        _as("REL", "Department of Religion", ["Religion"], "religion"),
        _as("SPAN", "Department of Spanish and Portuguese", ["Spanish"], "spanport"),
        _as("THEA", "Department of Theater", ["Theater"], "theater", path="/people/people"),
        _as("WRIT", "Institute for Writing and Rhetoric", ["English"], "writing"),
        # ---- Arts & Sciences: Sciences -------------------------------------
        _as("BIOL", "Department of Biological Sciences", ["Biological Sciences", "Biology"],
            "biology"),
        _as("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry",
            path="/people/people"),
        _as("CS", "Department of Computer Science", ["Computer Science"], "web.cs"),
        _np("EARS", "Department of Earth and Planetary Sciences",
            ["Earth Sciences", "Geology"], "earthsciences"),
        _as("ENVS", "Environmental Studies Program", ["Environmental Studies"], "envs"),
        _np("PHYS", "Department of Physics and Astronomy", ["Physics", "Astronomy"],
            "physics"),
        _as("PBS", "Department of Psychological and Brain Sciences",
            ["Psychological and Brain Sciences", "Neuroscience", "Psychology"], "pbs"),
        # ---- Arts & Sciences: Social Sciences ------------------------------
        _as("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _as("ECON", "Department of Economics", ["Economics"], "economics"),
        _as("EDUC", "Department of Education", ["Education"], "educ"),
        _as("GEOG", "Department of Geography", ["Geography"], "geography"),
        _as("GOVT", "Department of Government", ["Government", "Political Science"], "govt"),
        _as("HIST", "Department of History", ["History"], "history"),
        _as("QSS", "Program in Quantitative Social Science",
            ["Quantitative Social Science"], "qss", path="/people/people"),
        _as("SOCY", "Department of Sociology", ["Sociology"], "sociology"),
        # ---- Arts & Sciences: Interdisciplinary ----------------------------
        _as("AAAS", "Department of African and African American Studies",
            ["African and African American Studies"], "aaas"),
        _as("ASCL", "Department of Asian Societies, Cultures, and Languages",
            ["Asian Societies, Cultures, and Languages"], "ascl"),
        _as("COGS", "Program in Cognitive Science", ["Cognitive Science"],
            "cognitive-science"),
        _as("EEER", "Program in East European, Eurasian, and Russian Studies",
            ["Russian"], "eeer"),
        _as("JWST", "Program in Jewish Studies", ["Religion"], "jewish",
            path="/people/people"),
        _as("LALACS", "Department of Latin American, Latino, and Caribbean Studies",
            ["Latin American, Latino and Caribbean Studies"], "lalacs"),
        _as("LING", "Program in Linguistics", ["Linguistics"], "linguistics"),
        _as("MES", "Program in Middle Eastern Studies", ["Middle Eastern Studies"], "mes"),
        _as("NAIS", "Department of Native American and Indigenous Studies",
            ["Native American and Indigenous Studies"], "native-american"),
        _as("WGSS", "Program in Women's, Gender, and Sexuality Studies",
            ["Women's, Gender, and Sexuality Studies"], "wgs"),
        # ---- Mathematics (custom PHP; the one listing WITH emails) ---------
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://math.dartmouth.edu/people/people-select.php?list=permanent",
            "scrape": {
                "url": "https://math.dartmouth.edu/people/people-select.php?list=permanent",
                "selectors": {
                    "card": "div.flex-container",
                    # The name is a bare text node in div.text — take the div and
                    # cut everything from the rank onward.
                    "name": "div.text",
                    "name_strip": r"\s+(?:(?:Assistant|Associate|Research|Adjunct|Visiting)\s+)?(?:Professor|Instructor).*$|\s+(?:Senior\s+)?Lecturer.*$|\s+(?:John\s+Wesley\s+Young|Byrne).*$",
                    "title": "div.text ul li:first-child",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        },
        # ---- Thayer School of Engineering ----------------------------------
        {
            "short": "ENGS", "name": "Thayer School of Engineering",
            "majors": ["Engineering Sciences", "Biomedical Engineering"],
            "directory_url": "https://engineering.dartmouth.edu/community/faculty",
            "scrape": {
                "url": "https://engineering.dartmouth.edu/community/faculty",
                "selectors": {"card": "div.profile-box", "name": "h3", "link": "a",
                              "title": "div.position p"},
                # h2 groups: "Core (85)" / "Lecturer (22)" / Adjunct / Emeriti.
                "section_filter": {"heading": "h2", "include": r"^(?:core|lecturer)\b"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": ".faculty-contacts a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "research_html_re": r"Research Interests</h3>\s*<p>(.*?)</p>",
                    "throttle": 0.15,
                },
            },
        },
        # ---- Tuck School of Business ----------------------------------------
        {
            "short": "TUCK", "name": "Tuck School of Business",
            "majors": ["Business", "Economics"],
            "directory_url": "https://tuck.dartmouth.edu/faculty/faculty-directory",
            "scrape": {
                "url": "https://tuck.dartmouth.edu/faculty/faculty-directory",
                # data-faculty-role="tuck" = core faculty; "visiting" dropped here.
                "selectors": {"card": "div.faculty-card[data-faculty-role='tuck']",
                              "name": "p.faculty-name a.faculty-link--name",
                              "link": "p.faculty-name a.faculty-link--name",
                              "title": "p.faculty-position"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "research_html_re": r"Areas of Expertise</h3>\s*<p>(.*?)</p>",
                    "throttle": 0.15,
                },
            },
        },
        # ---- Geisel School of Medicine (basic-science departments) ---------
        _geisel("GMICRO", "Microbiology and Immunology",
                ["Biological Sciences", "Microbiology"]),
        _geisel("GBCHEM", "Biochemistry and Cell Biology",
                ["Biological Sciences", "Biochemistry"]),
        _geisel("GMSB", "Molecular and Systems Biology", ["Biological Sciences"]),
        _geisel("GBMDS", "Biomedical Data Science",
                ["Biomedical Data Science", "Data Science"]),
        _geisel("GEPI", "Epidemiology", ["Epidemiology", "Public Health"]),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
