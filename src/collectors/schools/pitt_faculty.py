"""University of Pittsburgh faculty config (via the faculty_graph engine).

Three markup families, all live-verified 2026-07-19:

* **Drupal 'views-row' (CS, Physics & Astronomy).** ``div.views-row`` cards with
  the name in ``.views-field-title`` and the rank on the listing (CS:
  ``.views-field-field-title``; Physics: a nested ``.field-position``). The email
  is written by an inline ``<script>`` that sets ``innerHTML`` to a mailto whose
  every character is a *decimal HTML entity* (``&#109;&#97;…``) — BeautifulSoup
  keeps that script text raw (the visible field is empty) and the engine's
  text/href email path never html-unescapes it, so there is **no usable listing
  email** for either dept. CS's profile page hides the personal address behind
  the same obfuscation (its only plain mailto is the ``computer.science@pitt.edu``
  dept inbox), so CS ships email-less; its profiles do carry a clean
  ``.field-research-interests`` bullet list, recovered by the gated profile pass.
  Physics profiles DO publish a plain personal mailto (plus the ``dept@phyast``
  inbox, dropped), so the gated pass backfills Physics emails. CS's front rows are
  social-link utility cells (no ``.views-field-title``) — auto-skipped by the name
  guard. Physics' one listing mixes emeritus/adjunct/secondary/research-staff, so
  a title ``ladder_filter`` keeps only ladder + research-professor ranks.

* **engineering.pitt.edu WordPress grids (ECE, MEMS, BME).** One shared card set
  (``.l-grid--faculty-archive .l-grid-item`` → ``h4.h5`` name, ``.bio-info .title``
  rank, card ``a`` → ``/people/faculty/<slug>/`` profile). Each page stacks several
  role grids under sibling ``h2`` headings (Chair / Faculty / Primary Faculty vs
  Secondary Faculty / Research Faculty / Adjunct / Emeritus) — a ``section_filter``
  keeps only the home-department ladder (BME's 174 Secondary cross-listings and the
  adjunct/emeritus grids drop). Headshots are base64-inlined (pages run 5–18 MB) but
  a plain fetch reads them fine. Email + rank live on the profile; research is only
  prose/publication text (no clean tag block), so the gated pass backfills the
  personal mailto only (``mailto://addr`` double-slash form) — topics come from
  OpenAlex.

* **'pitt_25' thin Drupal (Chemistry).** ``div.views-row`` cards carrying only a
  name + ``/people/<slug>`` link (paginated), everything else on the profile. The
  clean 36-name roster is faculty-only; the gated pass reads the personal mailto
  (dropping the ``chemhelp@`` inbox) and, where present, the
  ``field--name-field-research-interests`` bullet list. Records default to
  "Professor" (no listing rank) — acceptable because the listing carries no
  non-faculty.

Single source ("pitt_faculty"); department rides each record, ids namespaced by
department short-code. Emails/research land via the gated OFE_ENRICH_PROFILES pass
(the listings alone give clean name + rank + department for every dept but
Chemistry, which is name + link).

Dietrich School of Arts & Sciences expansion (added 2026-07-26, all
live-verified, no WAF/render). Almost every Dietrich department runs the SAME
Drupal "person" view as CS/Physics above (twentytwenty + pitt_25 skins emit
identical card markup), so three thin helpers cover the college:
* ``_d1`` — Family 1: the ``.views-field-field-email`` mailto is present on the
  LISTING (Communication, Economics, French & Italian, HPS, Hispanic, History
  of Art, Biological Sciences, Psychology), so email lands without a profile
  pass. Some use an exposed ``?type=`` / ``?person_type=`` faculty-only view;
  the rest an ``h3`` ``section_filter`` (Dietrich headings are h3, not the
  engineering h2).
* ``_d2`` — Family 2: listing email is empty/entity-obfuscated (like CS), so the
  personal mailto + any research bullet list ride the gated profile pass
  (Africana, Anthropology, Math, German, History, Sociology, Studio Arts, Film &
  Media, GSWS, Linguistics, Music, Urban Studies, plus the h3-sectioned English,
  Neuroscience, Political Science, Theatre, Philosophy, and the iSchool/SCI).
* ``_nt`` — Family 3: a thin ``node-teaser`` template (Classics, East Asian,
  Geology, Religious Studies, Slavic, plus SPIA and the Law School) with only a
  name + profile link; rank defaults to "Professor" (the URL pre-filters to
  faculty) and the email rides the profile pass.
Plus the three remaining Swanson School of Engineering departments (Chemical &
Petroleum, Civil & Environmental, Industrial) on the existing WordPress grid.

Deferred:
* **Statistics** (stat.pitt.edu/people/faculty, same pitt_25 theme) — the
  "faculty" view is misconfigured to list PhD students and staff alongside the
  real faculty (ID-style ``nis220@pitt.edu`` addresses, no rank), and the
  profiles carry no reliable rank field (most real professors lack the
  "Appointments" section that one or two have), so there is no signal to filter
  the non-faculty out. No cleaner faculty-only URL exists (all probed 404).
  Dropped rather than ship a roster padded with students.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Drupal 'views-row' family (CS, Physics) -------------------------------
_VIEWS_CARD = "div.views-row"
_VIEWS_NAME = ".views-field-title .field-content"
_VIEWS_LINK = ".views-field-field-person-img a[href]"

# Physics ladder: keep tenure/teaching + research-PROFESSOR ranks; drop emeritus,
# adjunct, secondary (cross-listed home elsewhere), part-time, lab instructors,
# and bare research staff (research assistant/associate/scientist NOT "…Professor").
_PHYS_LADDER = {
    "drop": (r"emerit|adjunct|\bsecondary\b|part-?time|lab instructor"
             r"|research (?:associate|assistant|scientist)(?!\s+professor)"),
}
# CS lists full-time faculty only; drop the lone visiting appointment (+ any emeritus).
_CS_LADDER = {"drop": r"visiting|emerit"}

# CS profiles keep a clean "Specific Research Interests" bullet list; the personal
# email stays entity-obfuscated on the profile too, so enrich = research only.
_CS_ENRICH = {
    "research_items_selector": ".field-research-interests ul li",
    "throttle": 0.2,
}
# Physics profiles publish a plain personal mailto (+ the dept inbox, dropped).
_PHYS_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^dept@|@phyast\.pitt\.edu$",
    "throttle": 0.2,
}

# ---- engineering.pitt.edu WordPress grids (ECE, MEMS, BME) -----------------
_ENG_SELECTORS = {
    "card": ".l-grid--faculty-archive .l-grid-item",
    "name": "h4.h5",
    "link": "a",
    "title": ".bio-info .title",
}
# Keep only the home-department ladder grid; the role heading is the sibling h2
# ("Chair" / "Interim Chair" / "Faculty" / "Primary Faculty"). "Secondary Faculty",
# "Research Faculty", "Adjunct …", and any "… Emeritus" grid are excluded.
_ENG_SECTION = {"heading": "h2",
                "include": r"^(?:(?:interim )?chair|(?:primary )?faculty)$"}
# Email on the profile is a personal mailto (double-slash "mailto://addr" form the
# engine's regex still recovers); drop obvious shared inboxes. No clean research block.
_ENG_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^(?:info|webmaster|contact|department|dept|engineering)@",
    "throttle": 0.2,
}

# ---- 'pitt_25' thin Drupal (Chemistry) -------------------------------------
_CHEM_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^chemhelp@|^help@",
    "research_items_selector": ".field--name-field-research-interests .field__item li",
    "throttle": 0.2,
}

# ---- Dietrich views-fields shared across the Arts & Sciences departments ----
# Every Dietrich department runs the same Drupal "person" view (twentytwenty or
# the newer pitt_25 skin — identical card markup): the name+profile link is the
# ``.views-field-title`` anchor, the rank is ``.views-field-field-title``, and
# many listings ALSO expose a plain mailto in ``.views-field-field-email`` (no
# profile pass needed). Section headings are ``<h3>`` here (engineering used h2).
_D_CARD = "div.views-row"
_D_NAME = ".views-field-title .field-content"
_D_LINK = ".views-field-title a[href]"
_D_TITLE = ".views-field-field-title .field-content"
_D_EMAIL = ".views-field-field-email a[href^='mailto:']"

# Two interchangeable skins carry the name differently: most depts wrap it in
# ``.views-field-title .field-content`` (skin A), a few (History of Art, the
# iSchool) put it directly in the ``.views-field-title`` anchor with a trailing
# "»" (skin B). ``skin_b=True`` on the helpers swaps to the anchor selector.
_D_NAME_B = ".views-field-title a"
_NAME_STRIP_ARROW = r"\s*»\s*$"

# Family 1 — email inline on the listing.
_D1_SEL = {"card": _D_CARD, "name": _D_NAME, "link": _D_LINK,
           "title": _D_TITLE, "email": _D_EMAIL}
# Family 2 — no usable listing email (empty/entity-obfuscated, like CS/Physics);
# the personal mailto + any research bullet list ride the gated profile pass.
_D2_SEL = {"card": _D_CARD, "name": _D_NAME, "link": _D_LINK, "title": _D_TITLE}
_DIETRICH_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    # Drop shared departmental inboxes (econ@, chemhelp@, info@, …); the personal
    # mailto is what the profile pass wants.
    "email_drop": (r"^(?:[a-z.]*(?:dept|help|info|contact|admin|office|advising"
                   r"|webmaster|inquir|questions|ask))@"),
    "research_items_selector": (".field-research-interests li, "
                                ".field--name-field-research-interests li"),
    "throttle": 0.2,
}

# ---- Family 3: Drupal "node-teaser" thin (Classics, DEALL, Geology, …) ------
# Small departments render each person as ``article.node--type-person`` with the
# name in the card's ``h2`` anchor and NOTHING else on the listing — rank
# defaults to "Professor" (the URL already pre-filters to faculty) and the email
# rides the profile pass. Two node-teaser skins put the name in ``h2.node__title
# a`` (Classics) or a bare ``h2 > a > span`` (SPIA, Law); ``h2 a`` matches both.
_NT_SEL = {"card": "article.node--type-person", "name": "h2 a", "link": "h2 a"}


def _d1(short, name, majors, url, section=None, skin_b=False):
    """A Dietrich department with inline listing email (Family 1)."""
    sel = dict(_D1_SEL)
    if skin_b:
        sel["name"] = _D_NAME_B
        sel["name_strip"] = _NAME_STRIP_ARROW
    scrape = {"url": url, "selectors": sel}
    if section:
        scrape["section_filter"] = {"heading": "h3", "include": section}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _d2(short, name, majors, url, section=None, skin_b=False):
    """A Dietrich department whose email/research ride the profile pass (Family 2)."""
    sel = dict(_D2_SEL)
    if skin_b:
        sel["name"] = _D_NAME_B
        sel["name_strip"] = _NAME_STRIP_ARROW
    scrape = {"url": url, "selectors": sel, "profile_enrich": _DIETRICH_ENRICH}
    if section:
        scrape["section_filter"] = {"heading": "h3", "include": section}
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _nt(short, name, majors, url):
    """A node-teaser department (Family 3): name+link only, rest via profile."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _NT_SEL,
                       "profile_enrich": _DIETRICH_ENRICH}}


# Swanson Industrial's chair grid is headed "Department Chair" (not bare
# "Chair"), so it needs a widened section include vs the shared _ENG_SECTION.
_ENG_SECTION_IE = {"heading": "h2",
                   "include": r"^(?:department chair|(?:interim )?chair|(?:primary )?faculty)$"}


def _eng(short, name, majors, url, section=None):
    """A Swanson School of Engineering department (WordPress grid)."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _ENG_SELECTORS,
                       "section_filter": section or _ENG_SECTION,
                       "profile_enrich": _ENG_ENRICH}}


SCHOOL: dict = {
    "school_slug": "pitt",
    "source": "pitt_faculty",
    "organization": "University of Pittsburgh",
    "location": "Pittsburgh, PA",
    "id_prefix": "pitt",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Pittsburgh) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Computing and Information ---------------------------
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": "https://www.cs.pitt.edu/people/full-time-faculty",
            "scrape": {
                "url": "https://www.cs.pitt.edu/people/full-time-faculty",
                "selectors": {
                    "card": _VIEWS_CARD,
                    "name": _VIEWS_NAME,
                    "link": _VIEWS_LINK,
                    "title": ".views-field-field-title .field-content",
                },
                "ladder_filter": _CS_LADDER,
                "profile_enrich": _CS_ENRICH,
            },
        },
        # ---- Swanson School of Engineering ---------------------------------
        {
            "short": "ECE",
            "name": "Department of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://www.engineering.pitt.edu/departments/electrical-computer/people/faculty/",
            "scrape": {
                "url": "https://www.engineering.pitt.edu/departments/electrical-computer/people/faculty/",
                "selectors": _ENG_SELECTORS,
                "section_filter": _ENG_SECTION,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        {
            "short": "MEMS",
            "name": "Department of Mechanical Engineering and Materials Science",
            "majors": ["Mechanical Engineering", "Materials Science and Engineering"],
            "directory_url": "https://www.engineering.pitt.edu/departments/mems/People/faculty/",
            "scrape": {
                "url": "https://www.engineering.pitt.edu/departments/mems/People/faculty/",
                "selectors": _ENG_SELECTORS,
                "section_filter": _ENG_SECTION,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        {
            "short": "BME", "name": "Department of Bioengineering",
            "majors": ["Bioengineering", "Biomedical Engineering"],
            "directory_url": "https://www.engineering.pitt.edu/departments/bioengineering/people/faculty/",
            "scrape": {
                "url": "https://www.engineering.pitt.edu/departments/bioengineering/people/faculty/",
                "selectors": _ENG_SELECTORS,
                "section_filter": _ENG_SECTION,
                "profile_enrich": _ENG_ENRICH,
            },
        },
        # ---- Kenneth P. Dietrich School of Arts and Sciences ---------------
        {
            "short": "PHYS", "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astronomy"],
            "directory_url": "https://www.physicsandastronomy.pitt.edu/people/faculty",
            "scrape": {
                "url": "https://www.physicsandastronomy.pitt.edu/people/faculty",
                "selectors": {
                    "card": _VIEWS_CARD,
                    "name": _VIEWS_NAME,
                    "link": _VIEWS_LINK,
                    "title": ".field-position",
                },
                "ladder_filter": _PHYS_LADDER,
                "profile_enrich": _PHYS_ENRICH,
            },
        },
        {
            "short": "CHEM", "name": "Department of Chemistry",
            "majors": ["Chemistry"],
            "directory_url": "https://www.chem.pitt.edu/people/faculty",
            "scrape": {
                "url": "https://www.chem.pitt.edu/people/faculty",
                "selectors": {
                    "card": _VIEWS_CARD,
                    "name": ".views-field-title .field-content a",
                    "link": ".views-field-title a[href]",
                },
                "paginate": {"param": "page", "start": 1, "max": 8},
                "profile_enrich": _CHEM_ENRICH,
            },
        },
        # ---- Dietrich A&S — Family 1 (views fields, email INLINE) -----------
        _d1("COMM", "Department of Communication", ["Communication"],
            "https://www.comm.pitt.edu/people",
            section=r"Research and Teaching Faculty"),
        _d1("ECON", "Department of Economics", ["Economics"],
            "https://www.econ.pitt.edu/people?type=1"),
        _d1("FRIT", "Department of French and Italian", ["French", "Italian"],
            "https://www.frenchanditalian.pitt.edu/people", section=r"All Faculty"),
        _d1("HPS", "Department of History and Philosophy of Science",
            ["History and Philosophy of Science"],
            "https://www.hps.pitt.edu/people", section=r"Primary Faculty"),
        _d1("HISP", "Department of Hispanic Languages and Literatures",
            ["Spanish", "Portuguese", "Hispanic Studies"],
            "https://www.spanport.pitt.edu/people?type=1"),
        _d1("HAA", "Department of History of Art and Architecture",
            ["History of Art and Architecture"],
            "https://www.haa.pitt.edu/people", section=r"^Faculty$", skin_b=True),
        _d1("BIOSC", "Department of Biological Sciences",
            ["Biological Sciences", "Biology"],
            "https://www.biology.pitt.edu/people?type=40"),
        _d1("BIOSCT", "Department of Biological Sciences",
            ["Biological Sciences", "Biology"],
            "https://www.biology.pitt.edu/people?type=53"),
        _d1("PSYC", "Department of Psychology", ["Psychology"],
            "https://www.psychology.pitt.edu/people?person_type=45"),
        # ---- Dietrich A&S — Family 2 (views fields, email via profile) ------
        _d2("AFRIC", "Department of Africana Studies", ["Africana Studies"],
            "https://www.africanastudies.pitt.edu/people/faculty"),
        _d2("ANTH", "Department of Anthropology", ["Anthropology"],
            "https://www.anthropology.pitt.edu/people/faculty"),
        _d2("MATH", "Department of Mathematics", ["Mathematics"],
            "https://www.mathematics.pitt.edu/people/faculty"),
        _d2("GERM", "Department of German", ["German"],
            "https://www.german.pitt.edu/people/faculty"),
        _d2("HIST", "Department of History", ["History"],
            "https://www.history.pitt.edu/people/faculty"),
        _d2("SOC", "Department of Sociology", ["Sociology"],
            "https://www.sociology.pitt.edu/people/faculty"),
        _d2("SART", "Department of Studio Arts", ["Studio Arts", "Art"],
            "https://www.studioarts.pitt.edu/people/faculty"),
        _d2("FMST", "Film and Media Studies Program", ["Film and Media Studies"],
            "https://www.filmandmedia.pitt.edu/people/primary-teaching-faculty"),
        _d2("GSWS", "Gender, Sexuality, and Women's Studies Program",
            ["Gender, Sexuality, and Women's Studies"],
            "https://www.wstudies.pitt.edu/people/core-faculty"),
        _d2("LING", "Department of Linguistics", ["Linguistics"],
            "https://www.linguistics.pitt.edu/people/core-linguistics-faculty"),
        _d2("MUSIC", "Department of Music", ["Music"],
            "https://www.music.pitt.edu/people/core-faculty"),
        _d2("URBST", "Urban Studies Program", ["Urban Studies"],
            "https://www.urbanstudies.pitt.edu/people/urban-studies-faculty"),
        # ---- Dietrich A&S — Family 2 with h3 section filter -----------------
        _d2("ENGL", "Department of English", ["English"],
            "https://www.english.pitt.edu/people",
            section=r"Tenure-Stream Faculty|Appointment-Stream Faculty"),
        _d2("NROSCI", "Department of Neuroscience", ["Neuroscience"],
            "https://www.neuroscience.pitt.edu/people/faculty",
            section=r"Faculty with Primary Appointments|Full-Time Teaching"),
        _d2("PS", "Department of Political Science", ["Political Science"],
            "https://www.polisci.pitt.edu/people",
            section=r"Political Science Faculty"),
        _d2("THEA", "Department of Theatre Arts", ["Theatre Arts"],
            "https://www.play.pitt.edu/people/theatre-arts-faculty"),
        _d2("PHIL", "Department of Philosophy", ["Philosophy"],
            "https://www.philosophy.pitt.edu/people", section=r"Primary Faculty"),
        # ---- Dietrich A&S — Family 3 (node-teaser, rank+email via profile) --
        _nt("CLAS", "Department of Classics", ["Classics"],
            "https://www.classics.pitt.edu/people/full-time-faculty"),
        _nt("DEALL", "Department of East Asian Languages and Literatures",
            ["East Asian Languages and Literatures"],
            "https://www.deall.pitt.edu/people/full-time-faculty"),
        _nt("GEOL", "Department of Geology and Environmental Science",
            ["Geology", "Environmental Science"],
            "https://www.geology.pitt.edu/people/faculty"),
        _nt("RELGST", "Department of Religious Studies", ["Religious Studies"],
            "https://www.religiousstudies.pitt.edu/people/faculty"),
        _nt("SLAV", "Department of Slavic Languages and Literatures",
            ["Slavic Languages and Literatures"],
            "https://www.slavic.pitt.edu/people/faculty"),
        # ---- Swanson School of Engineering — remaining departments ----------
        _eng("CHE", "Department of Chemical and Petroleum Engineering",
             ["Chemical Engineering", "Petroleum Engineering"],
             "https://www.engineering.pitt.edu/departments/chemical-petroleum/people/faculty/"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://www.engineering.pitt.edu/departments/civil-environmental/people/faculty/"),
        _eng("IE", "Department of Industrial Engineering", ["Industrial Engineering"],
             "https://www.engineering.pitt.edu/departments/industrial/people/faculty/",
             section=_ENG_SECTION_IE),
        # ---- Professional schools (same Drupal templates) ------------------
        _nt("SPIA", "Graduate School of Public and International Affairs",
            ["Public Affairs", "International Affairs", "Public Policy"],
            "https://www.spia.pitt.edu/people/faculty"),
        _nt("LAW", "School of Law", ["Law"],
            "https://www.law.pitt.edu/people/full-time-faculty"),
        _d2("SCI", "School of Computing and Information",
            ["Information Science", "Computing"],
            "https://www.sci.pitt.edu/people/faculty", skin_b=True),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
