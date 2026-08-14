"""Yale University faculty config (via the faculty_graph engine).

Yale department sites span three server-rendered YaleSites generations, all
scrapeable with one selector set each (verified live 2026-07-17):

  * **OLD** (Drupal 7 ``view-people`` striped table): rows are
    ``table.views-table tr`` with the name link (``a.username`` →
    ``/people/<slug>``), the rank, the public ``mailto:`` and the office all
    inside the ``views-field-name`` cell, plus a per-dept research column
    (``views-field-field-field-of-study`` and friends). Physics, English,
    History, EEB, MB&B and most other legacy A&S sites.
  * **NEW teaser** (YaleSites Drupal 10 ``node-teaser--person`` article cards,
    paginated ``?page=N``): Economics only so far.
  * **DLC** (YaleSites "directory listing card" profile collection):
    ``li.directory-listing-card`` with heading-link (``/profile/<slug>``),
    subheading rank and an inline ``mailto:`` link. Math, Chemistry, MCDB,
    Statistics & Data Science, Philosophy and the other migrated sites.

Mixed listings (``/people`` pages that interleave staff and students with
faculty) are gated by ``field_filter`` on the cell/subheading text — a card
must carry a professor/lecturer/lector rank to land — with emeriti excluded.
``title_re`` recovers the display rank from the OLD template's unstructured
name cell (falls back to "Professor"; the gated profile pass refines).

SEAS (engineering.yale.edu, concrete5 "Worx" theme) is a Vue directory over a
POST JSON endpoint — the ``ajax {type: "worx"}`` block hits it directly, one
department term id per SEAS department (ids from the page's inline
``departmentsList``), titled records included.

Single source ("yale_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

Deferred (tracked for a later pass): School of Public Health + School of
Nursing + Jackson School (client-rendered directories, no public JSON found),
School of the Environment (JS directory), School of Architecture (names are
bare text nodes between divs — no selectable name element) and Divinity
(/faculty is a nav page of reference-cards, no people listing), Yale School
of Medicine (clinical scale, like other schools' deferred medical tails), and
the Law School.
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + teaching faculty (Yale language departments appoint "Lectors");
# drop emeriti wherever they share a listing.
_KEEP = r"professor|lecturer|lector|instructor"
_DROP = r"emerit"

# OLD YaleSites (Drupal 7) striped people table. The name cell holds name +
# rank + email as <br>-separated text, so the rank is regex-recovered and the
# field_filter drops the staff/student rows of mixed /people listings.
_OLD_SELECTORS = {
    "card": ".view-people table.views-table tr",
    "name": "td.views-field-name a.username",
    "link": "td.views-field-name a.username",
    "email": "a[href^='mailto:']",
    "research": "td[class*='field-of-study']",
    "title_re": (
        r"\b((?:[A-Z][A-Za-z.'’&-]+\s+){0,5}"
        r"(?:Professor|Lecturer|Lector|Instructor)"
        r"(?:\s+(?:of|in)\s+[A-Za-z,&\- ]{3,60})?)"
    ),
}

# NEW YaleSites teaser cards (Economics), paginated.
_NEW_SELECTORS = {
    "card": "article.node-teaser--person",
    "name": ".node-teaser__heading a",
    "link": ".node-teaser__heading a",
    "title": ".node-teaser__professional-title",
}

# YaleSites "directory listing card" collections. Heading text may append
# credentials ("Jeffrey Brock, Ph.D.") — name_strip recovers the clean name.
_DLC_SELECTORS = {
    "card": "li.directory-listing-card",
    "name": ".directory-listing-card__heading-link",
    "link": ".directory-listing-card__heading-link",
    "title": ".directory-listing-card__subheading",
    "email": "a[href^='mailto:']",
    "name_strip": r",\s*(?:Ph\.?\s?D\.?|D\.?Phil\.?|M\.?D\.?|J\.?D\.?|Dr\.?\s?rer).*$",
}

_FIELD_OLD = {"selector": "td.views-field-name", "include": _KEEP, "exclude": _DROP}
_FIELD_DLC = {"selector": ".directory-listing-card__subheading",
              "include": _KEEP, "exclude": _DROP}

# Profile-pass research capture for OLD (Drupal 7) profiles. The listing carries
# no research for most departments, but each /people/<slug> profile exposes the
# department's structured research field. Target ONLY the discrete labelled
# blocks — field-of-study ("Research Areas: …"), field-s-of-interest ("Fields of
# interest: …; …"), field-specialization ("Specialization: …") — whose text is a
# short comma/semicolon list of areas (the engine's label strip + downstream
# _RESEARCH_LABEL_RE clean the leading label). The universal field-bio block is
# deliberately EXCLUDED: it is a biography paragraph that comma-splits into
# sentence fragments. Bio-only departments simply no-op (no keywords, no noise).
_OLD_ENRICH = {
    "research_selector": (
        "div.field-name-field-field-of-study, "
        "div.field-name-field-field-s-of-interest, "
        "div.field-name-field-specialization, "
        "div.field-name-field-primary-field-of-interest"
    ),
    "throttle": 0.3,
    "timeout": 8,
    "max_retries": 1,
}

# DLC profiles publish research as either a "Research Interests" <ul> chip list
# or an "Areas of Interest" delimited <p>; env-gated research-only per-profile
# pass (chips win over the line when present).
_DLC_ENRICH = {
    "research_items_selector": 'h2:-soup-contains("Research Interests") + ul li',
    "research_selector": 'h2:-soup-contains("Areas of Interest") + p',
    "throttle": 0.3, "timeout": 8, "max_retries": 1,
}


def _old(short: str, name: str, majors: list[str], host: str, path: str,
         filtered: bool = False) -> dict:
    """A department on the OLD (Drupal 7) people table. ``filtered`` gates a
    mixed all-people listing down to professor/lecturer/lector rows."""
    url = f"https://{host}.yale.edu/{path}"
    scrape = {"url": url, "selectors": _OLD_SELECTORS, "profile_enrich": _OLD_ENRICH}
    if filtered:
        scrape["field_filter"] = _FIELD_OLD
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _dlc(short: str, name: str, majors: list[str], host: str, path: str,
         filtered: bool = True) -> dict:
    """A department on the DLC profile-collection template. Most DLC listings
    are /people pages that mix staff in, so the rank gate defaults on."""
    url = f"https://{host}.yale.edu/{path}"
    scrape = {"url": url, "selectors": _DLC_SELECTORS, "profile_enrich": _DLC_ENRICH}
    if filtered:
        scrape["field_filter"] = _FIELD_DLC
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


_WORX_ENDPOINT = ("https://engineering.yale.edu/research-and-faculty/"
                  "faculty-directory/load_faculty/172")


def _seas(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    """A SEAS department served by the shared Worx load_faculty endpoint."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://seas.yale.edu/faculty-research/faculty-directory",
            "ajax": {"type": "worx", "endpoint": _WORX_ENDPOINT,
                     "department": dept_id,
                     "referer": "https://seas.yale.edu/faculty-research/faculty-directory",
                     "ladder_filter": {"require": _KEEP, "drop": _DROP}},
            # The engineering.yale.edu profile page's only mailto: is the
            # person's own address (verified on /faculty-directory/james-aspnes).
            "profile_enrich": {"email_selector": "a[href^='mailto:']",
                               "throttle": 0.5}}


SCHOOL: dict = {
    "school_slug": "yale",
    "source": "yale_faculty",
    "organization": "Yale University",
    "location": "New Haven, CT",
    "id_prefix": "yale",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Yale University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- FAS sciences -------------------------------------------------
        _old("PHYS", "Department of Physics", ["Physics", "Applied Physics"],
             "physics", "people/faculty"),
        _old("ASTR", "Department of Astronomy", ["Astronomy", "Astrophysics"],
             "astronomy", "people/faculty"),
        _old("EEB", "Department of Ecology & Evolutionary Biology",
             ["Ecology & Evolutionary Biology", "Biology"], "eeb", "people/faculty"),
        _old("MBB", "Department of Molecular Biophysics & Biochemistry",
             ["Molecular Biophysics & Biochemistry", "Biochemistry"],
             "mbb", "people/faculty"),
        _dlc("MCDB", "Department of Molecular, Cellular & Developmental Biology",
             ["Molecular, Cellular & Developmental Biology", "Biology"],
             "mcdb", "people"),
        _dlc("CHEM", "Department of Chemistry", ["Chemistry"], "chem", "people"),
        _dlc("EPS", "Department of Earth & Planetary Sciences",
             ["Earth & Planetary Sciences", "Geology"], "earth", "faculty"),
        _dlc("MATH", "Department of Mathematics", ["Mathematics"], "math", "people"),
        _dlc("SDS", "Department of Statistics & Data Science",
             ["Statistics & Data Science", "Data Science"], "statistics", "people"),
        _old("PSYC", "Department of Psychology",
             ["Psychology", "Neuroscience"], "psychology", "people/all",
             filtered=True),
        _dlc("CGSC", "Cognitive Science Program", ["Cognitive Science"],
             "cogsci", "people"),
        # ---- FAS social sciences -----------------------------------------
        # economics.yale.edu/people/faculty is the EGC shared view and its
        # pager meta-refreshes to egc.yale.edu — scrape the canonical host, whose
        # ?page=N pagination actually works (43 faculty over 3 pages).
        {"short": "ECON", "name": "Department of Economics", "majors": ["Economics"],
         "directory_url": "https://egc.yale.edu/people/faculty",
         "scrape": {"url": "https://egc.yale.edu/people/faculty",
                    "selectors": _NEW_SELECTORS,
                    "paginate": {"param": "page", "start": 1, "max": 8}}},
        _old("PLSC", "Department of Political Science", ["Political Science"],
             "politicalscience", "people", filtered=True),
        _dlc("SOCY", "Department of Sociology", ["Sociology"], "sociology", "faculty"),
        _old("ANTH", "Department of Anthropology", ["Anthropology"],
             "anthropology", "people", filtered=True),
        _old("HIST", "Department of History", ["History"],
             "history", "people", filtered=True),
        _old("HSHM", "Program in the History of Science, Medicine & Public Health",
             ["History of Science, Medicine & Public Health"], "hshm", "people/faculty"),
        _old("ERM", "Program in Ethnicity, Race & Migration",
             ["Ethnicity, Race & Migration"], "erm", "people/faculty"),
        _old("AFAM", "Department of African American Studies",
             ["African American Studies"], "afamstudies", "people", filtered=True),
        _old("AMST", "Department of American Studies", ["American Studies"],
             "americanstudies", "people", filtered=True),
        _old("WGSS", "Program in Women's, Gender & Sexuality Studies",
             ["Women's, Gender & Sexuality Studies"], "wgss", "people/faculty"),
        _old("ARCG", "Council on Archaeological Studies", ["Archaeological Studies"],
             "archaeology", "people/faculty"),
        # ---- FAS humanities ----------------------------------------------
        _old("ENGL", "Department of English", ["English"],
             "english", "people/faculty", filtered=True),
        _dlc("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy", "faculty"),
        _old("CLSS", "Department of Classics", ["Classics"], "classics", "faculty"),
        _dlc("CPLT", "Department of Comparative Literature",
             ["Comparative Literature"], "complit", "people"),
        _dlc("FREN", "Department of French", ["French"], "french", "people"),
        _dlc("ITAL", "Department of Italian Studies", ["Italian"], "italian", "people"),
        _old("SPAN", "Department of Spanish & Portuguese", ["Spanish", "Portuguese"],
             "span-port", "people/faculty"),
        _old("GMAN", "Department of Germanic Languages & Literatures",
             ["German Studies"], "german", "people/faculty"),
        _dlc("SLAV", "Department of Slavic Languages & Literatures",
             ["Russian", "Slavic Studies"], "slavic", "directory/faculty"),
        _old("EALL", "Department of East Asian Languages & Literatures",
             ["East Asian Languages & Literatures", "East Asian Studies"],
             "eall", "people/faculty"),
        _old("NELC", "Department of Near Eastern Languages & Civilizations",
             ["Near Eastern Languages & Civilizations"], "nelc", "people/faculty"),
        _dlc("LING", "Department of Linguistics", ["Linguistics"], "ling", "people"),
        _dlc("RLST", "Department of Religious Studies", ["Religious Studies"],
             "religiousstudies", "people"),
        _dlc("JDST", "Program in Judaic Studies", ["Jewish Studies"],
             "jewishstudies", "people"),
        _old("HSAR", "Department of the History of Art", ["History of Art"],
             "arthistory", "people/faculty"),
        _old("FILM", "Program in Film & Media Studies", ["Film & Media Studies"],
             "filmstudies", "people/faculty"),
        _old("MUS", "Department of Music (FAS)", ["Music"],
             "yalemusic", "people", filtered=True),
        _dlc("TAPS", "Program in Theater, Dance & Performance Studies",
             ["Theater & Performance Studies"], "tdps", "faculty"),
        _dlc("HUMS", "Program in Humanities", ["Humanities"], "humanities", "faculty"),
        _dlc("EMST", "Program in Early Modern Studies", ["Early Modern Studies"],
             "earlymodern", "people"),
        _old("MDVL", "Program in Medieval Studies", ["Medieval Studies"],
             "medieval", "people", filtered=True),
        # ---- SEAS (Worx JSON endpoint, one department term id each) -------
        _seas("CPSC", "Department of Computer Science", ["Computer Science"], 297),
        _seas("ECE", "Department of Electrical & Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"], 300),
        _seas("BENG", "Department of Biomedical Engineering",
              ["Biomedical Engineering"], 295),
        _seas("CEE", "Department of Chemical & Environmental Engineering",
              ["Chemical Engineering", "Environmental Engineering"], 296),
        _seas("MECH", "Department of Mechanical Engineering",
              ["Mechanical Engineering"], 299),
        _seas("MSE", "Department of Materials Science", ["Materials Science"], 396),
        _seas("APHY", "Department of Applied Physics", ["Applied Physics"], 287),
        _seas("ACM", "Program in Applied & Computational Mathematics",
              ["Applied Mathematics", "Computational Mathematics"], 408),
        # ---- Professional schools with open server-rendered directories ---
        {"short": "SOM", "name": "Yale School of Management",
         "majors": ["Management", "Economics", "Finance"],
         "directory_url": "https://som.yale.edu/faculty-research/faculty-directory",
         "scrape": {"url": "https://som.yale.edu/faculty-research/faculty-directory",
                    "selectors": {"card": "article.node-teaser--faculty",
                                  "name": ".node-teaser__heading a",
                                  "link": ".node-teaser__heading a",
                                  "title": ".node-teaser__professional-title"},
                    "paginate": {"param": "page", "start": 1, "max": 8},
                    "ladder_filter": {"require": _KEEP, "drop": _DROP}}},
        {"short": "YSM", "name": "Yale School of Music",
         "majors": ["Music", "Performance"],
         "directory_url": "https://music.yale.edu/faculty",
         "scrape": {"url": "https://music.yale.edu/faculty",
                    "selectors": {"card": "article.node--type-person",
                                  "name": "h2",
                                  "link": "a[href*='/people/']",
                                  "title": ".title-affiliations"},
                    "ladder_filter": {"require": r"professor|lecturer|lector|instructor|artist",
                                      "drop": _DROP}}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
