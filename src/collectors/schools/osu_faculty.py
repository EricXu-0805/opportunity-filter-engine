"""Ohio State University faculty config (via the faculty_graph engine).

OSU's directories are server-rendered (no WAF; plain GETs with polite throttle)
across seven markup families, verified live 2026-07-17:

* College of Engineering shared Drupal (``osu_kinetic`` theme, coe_person
  nodes) on ``<dept>.osu.edu/directory/faculty`` (BME uses
  ``/directory/department-faculty``): ``div.grid-item-link-wrapper`` cards with
  "Last, First" names (``name_flip``), rank in the appointments block, the
  email as plain text on the listing, and Drupal ``?page=N`` pagination.
  Ladder gate = the faculty category page path PLUS a ``field_filter`` on the
  per-card directory-categories tags (drops Emeritus/Courtesy/Adjunct/Staff/
  Researcher cards cross-listed onto the faculty page) PLUS the title regex.
  Profiles keep clean expertise topics one-``<p>``-each under an "Expertise"
  heading (``div.content-body.field-expertise p``).

* Arts & Sciences shared Drupal (``asc_bux`` theme, 21 dept subdomains): the
  ``/people/faculty`` URL is a JS-hydrated empty shell, but **``/people``
  (no facet) server-renders the ENTIRE roster** — faculty + grads + staff
  (+ alumni on geography, 968 rows) as ``div.people-row`` cards, single page.
  There is no usable server-side role facet, so the ladder gate is the title
  regex over the first ``bux-person__details`` line (every row has one —
  verified 0 detail-less rows on physics/geography). Emails ride the listing
  as real mailtos. Profiles keep a clean "Areas of Expertise" tag list
  (``div.user-profile__areas-of-expertise ul li``).

* Fisher College of Business: server-rendered BUX directory with a working
  ``?type=faculty_member`` facet + ``&page=N`` (25/page). Titles like
  "Interim Executive Director" survive the facet, so the title regex still
  gates. Research areas are NOT server-rendered on profiles (directory-facet
  only) — treated as unavailable; the OpenAlex pass fills topics.

* CFAES legacy Drupal whole-unit people TABLE at ``/our-people`` (fabe 222 /
  ansci 207 / fst 148 rows, one page): ``tr.odd/tr.even`` rows, name link in
  the first cell ("Last, First" → ``name_flip``), title in the second, email
  as plain text (sometimes email+phone; the engine extracts the address) in
  the fourth. Title regex is the only gate — the table mixes everyone from
  postdocs to office staff. Profiles keep a labeled "Research Area(s)" item
  list (``div.field-name-field-research-areas .field-item``).

* John Glenn College of Public Affairs: single ``/faculty`` page of
  ``article.person-teaser`` cards with email on the listing; profiles keep a
  semicolon-separated "Expertise" line (``div.person__specialization p``).

* Health-science BUX colleges (CPH ``/people?role=1`` Core-Faculty facet,
  Nursing ``/faculty-and-staff?field_role_value=faculty`` — the facet still
  includes "Faculty Emeritus", title-regexed out —, Pharmacy ``/directory``
  with no facet at all): server-rendered ``div.bux-person`` cards, the rank in
  ``bux-person__details``, emails on the listing, ``?page=N`` (10-12/page).
  CPH profiles keep a labeled "Research interests" keyword block; Nursing/
  Pharmacy profiles carry none.

* Knowlton School (COE): ``/directory?field_employee_type_target_id=88``
  server facet (88 = faculty, 89 = staff), ``article.directory-item`` cards,
  16/page. No email/research on the listing; profile enrich recovers the
  mailto (= ``<slug>@osu.edu``).

* College of Social Work WordPress: single ``/our-faculty/`` page,
  ``div.col-6`` cards ("Last, First, PhD" → credential ``name_strip`` then
  ``name_flip``), email on the listing; profiles are prose bios (no research
  list — unusable).

* College of Optometry: single ``/directory`` page of ``views-row`` rows;
  faculty rows are identified by their ``/directory/faculty/`` link prefix
  (``link_filter``; staff/grad rows link elsewhere). Email is a real mailto
  on the listing.

Single source ("osu_faculty"); department rides each record, ids namespaced by
department short-code. OSU emails are slug-derivable (``/people/<name.N>`` ⇒
``<name.N>@osu.edu``) and personal locals always carry the dot-number, so the
enrich passes drop any digit-less ``@osu.edu`` mailto (a departmental inbox).

Deferred (from the 2026-07-17 recon):

* College of Medicine (medicine.osu.edu incl. Wexner basic-science depts) —
  thousands-of-clinicians enterprise; needs its own scoping decision.
* College of Education and Human Ecology (ehe.osu.edu) — directories are
  JS-rendered (server HTML is nav only).
* Moritz College of Law — listing server-renders 1898 rows but names+emails
  only; the faculty-type facet is JS-applied, so gating would need ~1900
  per-profile fetches.
* College of Veterinary Medicine — custom tailwind markup with no card/role
  structure; large clinical unit, needs bespoke selector work.
* College of Dentistry — no server-rendered directory found.
* CFAES redesigned depts (SENR, Entomology, AEDE, Horticulture & Crop
  Science) — new CFAES bux theme faculty pages are JS-rendered (0 person
  nodes server-side).
* School of Health and Rehabilitation Sciences — not probed (College of
  Medicine sub-school).
* Regional campuses (Lima/Mansfield/Marion/Newark/Wooster) — not probed;
  some regional faculty already appear in Columbus dept directories.
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + clinical/teaching ranks; drop emeriti/adjunct/visiting/courtesy.
# (Grad students and staff never match the require side.)
_LADDER = {"require": r"\bprofessor\b|\blecturer\b",
           "drop": r"emerit|adjunct|visiting|courtesy"}
# Colleges whose teaching ranks are titled "Instructor" (CFAES, Nursing, CSW).
# Deliberately NO bare "chair" here: the CFAES tables carry staff rows like
# "Administrative Associate Assistant to the Chair".
_LADDER_TEACH = {"require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
                 "drop": r"emerit|adjunct|visiting|courtesy"}
# COE appointment names for endowed positions omit the word "Professor"
# ("The Donald D. Glower Chair in Engineering", "Ohio Research Scholar in
# Materials", "College of Engineering Innovation Scholar") — real senior
# faculty, so chair/scholar join the require side. Safe here because the
# faculty-category page + category filter already exclude staff/postdocs.
_LADDER_COE = {"require": r"\bprofessor\b|\blecturer\b|\bchair\b|\bscholar\b",
               "drop": r"emerit|adjunct|visiting|courtesy"}
# Glenn subtitles for endowed positions likewise ("Ambassador Milton A. and
# Roslyn Z. Wolf Chair in Public and International Affairs").
_LADDER_GLENN = {"require": r"\bprofessor\b|\blecturer\b|\binstructor\b|\bchair\b",
                 "drop": r"emerit|adjunct|visiting|courtesy"}

# A personal OSU address is <last>.<N>@osu.edu — always digit-carrying. A
# digit-less @osu.edu local is a departmental inbox (physics@, chem-biochem@),
# never a person's address.
_DEPT_INBOX_DROP = r"^[^@]*$|^[^@0-9]+@osu\.edu$"

# ---- College of Engineering shared Drupal (osu_kinetic / coe_person) --------
_COE_SELECTORS = {
    "card": "div.grid-item-link-wrapper",
    "name": "h2.directory-grid-name",
    "link": "a.grid-item-link",
    "title": "div.field-block-node-coe-person-field-appointments div.appointment-name",
    "email": "div.directory-grid-email",
}

# The /directory/faculty page cross-lists Emeritus/Courtesy/Adjunct cards; the
# per-card category tags separate them where the title alone can't.
_COE_CAT_FILTER = {
    "selector": "div.field-block-node-coe-person-field-directory-categories",
    "exclude": r"emerit|courtesy|adjunct|staff|researcher",
}

_COE_ENRICH = {
    "research_items_selector": "div.content-body.field-expertise p",
    "email_selector": "a[href^='mailto:']",
    "email_drop": _DEPT_INBOX_DROP,
    "throttle": 0.2,
}


def _coe(short: str, name: str, majors: list[str], subdomain: str,
         path: str = "/directory/faculty", pages: int = 8) -> dict:
    """A College of Engineering department on the shared coe_person theme."""
    url = f"https://{subdomain}.osu.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _COE_SELECTORS, "name_flip": True,
                       "paginate": {"param": "page", "start": 1, "max": pages},
                       "ladder_filter": _LADDER_COE, "field_filter": _COE_CAT_FILTER,
                       "profile_enrich": _COE_ENRICH}}


# ---- Arts & Sciences shared Drupal (asc_bux people directory) ---------------
_ASC_SELECTORS = {
    "card": "div.people-row",
    "name": "div.bux-person__name a",
    "link": "div.bux-person__name a",
    # Names are "First Last" (never inverted); strip an honorific prefix
    # ("Dr. Steven MacEachern" on psychology) and the comma-led credential
    # tail ("Noel Mayo, D.F.A. (Hon.)").
    "name_strip": r"^Dr\.?\s+|\s*,\s*[A-Z].*$",
    "title": "div.bux-person__details",
    "email": "div.bux-person__contact a[href^='mailto:']",
}

_ASC_ENRICH = {
    "research_items_selector": "div.user-profile__areas-of-expertise ul li",
    "email_selector": "a[href^='mailto:']",
    "email_drop": _DEPT_INBOX_DROP,
    "throttle": 0.2,
}


def _asc(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    """An Arts & Sciences department on the asc_bux theme.

    ``/people`` (NOT ``/people/faculty``, which is a JS shell) server-renders
    the whole roster on one page; the ladder gate does the faculty cut.
    """
    url = f"https://{subdomain}.osu.edu/people"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _ASC_SELECTORS,
                       # Single-page roster today; the paginate block is a cheap
                       # safeguard (a no-fresh page stops the walk immediately).
                       "paginate": {"param": "page", "start": 1, "max": 4},
                       "ladder_filter": _LADDER,
                       "profile_enrich": _ASC_ENRICH}}


# ---- CFAES legacy Drupal whole-unit people table ----------------------------
_CFAES_SELECTORS = {
    "card": "tr.odd, tr.even",
    "name": "td:nth-of-type(1)",
    "link": "td:nth-of-type(1) a",
    "title": "td:nth-of-type(2)",
    "email": "td:nth-of-type(4)",
}

_CFAES_ENRICH = {
    "research_items_selector": "div.field-name-field-research-areas .field-item",
    "email_selector": "a[href^='mailto:']",
    "email_drop": _DEPT_INBOX_DROP,
    "throttle": 0.2,
}


def _cfaes(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    """A CFAES department on the legacy cfaesbase people table."""
    url = f"https://{subdomain}.osu.edu/our-people"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CFAES_SELECTORS, "name_flip": True,
                       "ladder_filter": _LADDER_TEACH,
                       "profile_enrich": _CFAES_ENRICH}}


# ---- Health-science BUX colleges (CPH / Nursing / Pharmacy) -----------------
_BUX_SELECTORS = {
    "card": "div.bux-person",
    "name": "div.bux-person__name a",
    "link": "div.bux-person__name a",
    # Names are "First Last" (never inverted); strip an honorific prefix
    # ("Dr. Taner Pirim") and the comma-led credential tail, which on the
    # nursing roster carries tokens the engine's credential regex can't reach
    # ("Liz Arthur, PhD, APRN-CNP, AOCNP®").
    "name_strip": r"^Dr\.?\s+|\s*,\s*[A-Z].*$",
    "title": "div.bux-person__details",
    "email": "a[href^='mailto:']",
}


def _bux(short: str, name: str, majors: list[str], url: str, pages: int,
         ladder: dict, enrich: dict | None = None) -> dict:
    """A server-rendered BUX card directory (health colleges + Fisher)."""
    scrape: dict = {"url": url, "selectors": _BUX_SELECTORS,
                    "paginate": {"param": "page", "start": 1, "max": pages},
                    "ladder_filter": ladder}
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "osu",
    "source": "osu_faculty",
    "organization": "Ohio State University",
    "location": "Columbus, OH",
    "id_prefix": "osu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Ohio State University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering ----------------------------------------
        _coe("CSE", "Computer Science and Engineering",
             ["Computer Science and Engineering", "Computer Science"], "cse"),
        _coe("ECE", "Electrical and Computer Engineering",
             ["Electrical and Computer Engineering", "Electrical Engineering",
              "Computer Engineering"], "ece"),
        _coe("MAE", "Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], "mae"),
        _coe("BME", "Biomedical Engineering", ["Biomedical Engineering"], "bme",
             path="/directory/department-faculty"),
        _coe("MSE", "Materials Science and Engineering",
             ["Materials Science and Engineering", "Welding Engineering"], "mse"),
        _coe("CBE", "Chemical and Biomolecular Engineering",
             ["Chemical Engineering"], "cbe"),
        _coe("ISE", "Integrated Systems Engineering",
             ["Industrial and Systems Engineering"], "ise"),
        _coe("CEG", "Civil, Environmental and Geodetic Engineering",
             ["Civil Engineering", "Environmental Engineering"], "ceg"),
        _coe("AVN", "Center for Aviation Studies", ["Aviation"], "aviation"),
        _coe("EED", "Department of Engineering Education",
             ["Engineering", "Engineering Education"], "eed"),
        {
            "short": "KNOW",
            "name": "Knowlton School (Architecture, Landscape Architecture, City Planning)",
            "majors": ["Architecture", "Landscape Architecture", "City and Regional Planning"],
            "directory_url": "https://knowlton.osu.edu/directory?field_employee_type_target_id=88",
            "scrape": {
                "url": "https://knowlton.osu.edu/directory?field_employee_type_target_id=88",
                "selectors": {"card": "article.directory-item",
                              "name": "h3.directory-grid-name a",
                              "link": "h3.directory-grid-name a",
                              "title": "div.person-appointments"},
                "paginate": {"param": "page", "start": 1, "max": 5},
                "ladder_filter": _LADDER,
                # No email/research on the listing; the profile mailto is the
                # slug-derived personal address.
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": _DEPT_INBOX_DROP,
                                   "throttle": 0.2},
            },
        },
        # ---- College of Arts and Sciences ----------------------------------
        _asc("PHYS", "Department of Physics", ["Physics", "Engineering Physics"], "physics"),
        _asc("CHEM", "Department of Chemistry and Biochemistry",
             ["Chemistry", "Biochemistry"], "chemistry"),
        _asc("MATH", "Department of Mathematics", ["Mathematics"], "math"),
        _asc("STAT", "Department of Statistics", ["Statistics", "Data Analytics"], "stat"),
        _asc("PSYCH", "Department of Psychology", ["Psychology"], "psychology"),
        _asc("ECON", "Department of Economics", ["Economics"], "economics"),
        _asc("ASTRO", "Department of Astronomy", ["Astronomy and Astrophysics"], "astronomy"),
        _asc("MOLGEN", "Department of Molecular Genetics",
             ["Molecular Genetics", "Biology"], "molgen"),
        _asc("MICRO", "Department of Microbiology", ["Microbiology"], "microbiology"),
        _asc("EARTH", "School of Earth Sciences", ["Earth Sciences", "Geology"],
             "earthsciences"),
        _asc("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _asc("POLISCI", "Department of Political Science", ["Political Science"], "polisci"),
        _asc("EEOB", "Department of Evolution, Ecology and Organismal Biology",
             ["Biology", "Evolution and Ecology"], "eeob"),
        _asc("LING", "Department of Linguistics", ["Linguistics"], "linguistics"),
        _asc("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _asc("GEOG", "Department of Geography", ["Geography"], "geography"),
        _asc("HIST", "Department of History", ["History"], "history"),
        _asc("ENGL", "Department of English", ["English"], "english"),
        _asc("DESIGN", "Department of Design", ["Design"], "design"),
        _asc("COMM", "School of Communication", ["Communication"], "comm"),
        _asc("MUSIC", "School of Music", ["Music"], "music"),
        # ---- Fisher College of Business ------------------------------------
        _bux("FISHER", "Fisher College of Business",
             ["Business", "Finance", "Accounting", "Marketing",
              "Logistics Management", "Operations Management", "Information Systems"],
             "https://fisher.osu.edu/directory?type=faculty_member", 12, _LADDER),
        # ---- CFAES ----------------------------------------------------------
        _cfaes("FABE", "Department of Food, Agricultural and Biological Engineering",
               ["Food, Agricultural and Biological Engineering", "Agricultural Engineering"],
               "fabe"),
        _cfaes("ANSCI", "Department of Animal Sciences", ["Animal Sciences"], "ansci"),
        _cfaes("FST", "Department of Food Science and Technology",
               ["Food Science and Technology"], "fst"),
        _cfaes("PLPATH", "Department of Plant Pathology",
               ["Plant Pathology", "Plant Health Management"], "plantpath"),
        # ---- Health-science colleges ----------------------------------------
        _bux("CPH", "College of Public Health",
             ["Public Health", "Environmental Public Health"],
             "https://cph.osu.edu/people?role=1", 8, _LADDER,
             enrich={"research_html_re": r"Research interests</h2>\s*<div[^>]*>(.*?)</div>",
                     "throttle": 0.2}),
        _bux("NURS", "College of Nursing", ["Nursing", "Health Sciences"],
             "https://nursing.osu.edu/faculty-and-staff?field_role_value=faculty", 10,
             _LADDER_TEACH),
        _bux("PHARM", "College of Pharmacy", ["Pharmaceutical Sciences", "Pharmacy"],
             "https://pharmacy.osu.edu/directory", 8, _LADDER),
        # ---- College of Social Work -----------------------------------------
        {
            "short": "CSW", "name": "College of Social Work", "majors": ["Social Work"],
            "directory_url": "https://csw.osu.edu/our-faculty/",
            "scrape": {
                "url": "https://csw.osu.edu/our-faculty/",
                "selectors": {
                    "card": "div.col-6",
                    "name": "h2.h5",
                    # "Anderson-Butcher, Dawn, PhD" — cut the credential run so
                    # one comma remains and name_flip can un-invert it.
                    "name_strip": (r"(?:\s*,\s*(?:(?i:Ph\.?\s?D|Ed\.?\s?D|D\.?S\.?W|M\.?S\.?W"
                                   r"|M\.?P\.?H|J\.?\s?D|M\.?\s?D|M\.?\s?A|M\.?\s?S|Psy\.?\s?D)"
                                   r"|[A-Z]{2,}[A-Za-z.()-]*)\.?)+\s*$"),
                    "title": "p.h6",
                    "link": "a",
                    "email": "a.faculty-email[href^='mailto:']",
                },
                "name_flip": True,
                "ladder_filter": _LADDER_TEACH,
            },
        },
        # ---- John Glenn College of Public Affairs ---------------------------
        {
            "short": "GLENN", "name": "John Glenn College of Public Affairs",
            "majors": ["Public Policy Analysis", "Public Management, Leadership, and Policy"],
            "directory_url": "https://glenn.osu.edu/faculty",
            "scrape": {
                "url": "https://glenn.osu.edu/faculty",
                "selectors": {"card": "article.person-teaser",
                              "name": "h3.person-teaser__title a span",
                              "link": "h3.person-teaser__title a",
                              "title": "div.person-teaser__subtitle",
                              "email": "div.person-teaser__contact-email a[href^='mailto:']"},
                "ladder_filter": _LADDER_GLENN,
                # Profile "Expertise" is a clean semicolon-separated line.
                "profile_enrich": {"research_selector": "div.person__specialization p",
                                   "throttle": 0.2},
            },
        },
        # ---- College of Optometry -------------------------------------------
        {
            "short": "OPTOM", "name": "College of Optometry",
            "majors": ["Optometry", "Health Sciences"],
            "directory_url": "https://optometry.osu.edu/directory",
            "scrape": {
                "url": "https://optometry.osu.edu/directory",
                "selectors": {"card": "div.view-directory div.views-row",
                              "name": "div.views-field-title a",
                              "link": "div.views-field-title a",
                              "title": "div.views-field-field-person-title",
                              "email": "div.views-field-field-person-email a[href^='mailto:']"},
                # Faculty rows link /directory/faculty/; staff and grad rows
                # link /directory/staff/ and /directory/graduate-students/.
                "link_filter": r"/directory/faculty/",
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
