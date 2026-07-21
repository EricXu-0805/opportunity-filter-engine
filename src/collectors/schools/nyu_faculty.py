"""New York University faculty config (via the faculty_graph engine).

NYU is not one platform — it is several independent ecosystems, each on its
own CMS. This module covers the ones that expose a clean, uniform,
server-rendered faculty listing (all live-verified 2026-07-19); the many
hand-authored legacy A&S department pages are documented as DEFERRED below.
No WAF blocks any covered host and nothing needs render mode.

Selector families
=================

* ``tandon`` — the NYU Tandon School of Engineering directory
  (engineering.nyu.edu, Drupal 10). Every department publishes a
  ``/academics/departments/<dept>/people`` page of identical
  ``article.node--type-profile`` cards: the name in ``.field--name-title``,
  the academic rank in ``.field--name-field-title`` (note the ``-field-``
  infix — the class WITHOUT it is the name), and the profile link in
  ``a.card-img-link`` (``/faculty/<slug>``). No email or research on the
  card and the profile pages expose no mailto, so Tandon records ship
  title-only (OpenAlex fills topics centrally). ``ladder_filter`` keeps
  professor/lecturer/instructor rows (Industry/Research/Global professors
  included) and drops emeriti. Ten departments; because NYU cross-lists
  affiliated faculty across department rosters, the engine's per-school
  url/id dedup collapses the overlap into one record per person.

* ``courant`` — the Courant Institute (Computer Science + Mathematics), a
  bespoke Django CMS shared by cs.nyu.edu and math.nyu.edu:
    - CS: ``ul.people-listing li`` cards, name ``p.name a``, rank
      ``p.title``. The ``/type/22/`` view is the Tenure-Track & Contract
      core roster (drops the emeriti/adjunct/visiting/affiliated buckets).
      The listing email is spaced-obfuscated ("ba2008 at nyu.edu") which the
      engine's ``_clean_email`` does not fold, so CS is title-only.
    - Math: ``div.people-link`` cards (``figure.people`` photo grid), name
      ``h2.name``, rank the first ``div.people-description > div``. No link
      or email on the card (records fall back to the directory URL); the
      ``Courant Instructor`` postdocs are kept as instructors, emeriti
      dropped.

* ``as_dir`` — the modern NYU Arts & Science "faculty directory bio"
  component (as.nyu.edu AEM), a clean ``div.filtered-items-item`` card with
  ``a.facultydirectorybio-person__name``, a ``span…__position`` rank and an
  inline ``span…__email a[mailto]``. Only two A&S departments have migrated
  to it so far: Psychology and the Center for Neural Science. The rank gate
  keeps professor/lecturer/instructor and drops emeriti (adjunct/clinical
  professors are kept — real mentoring faculty).

* ``as_flex`` — the legacy A&S hand-authored bio layout (Physics), a
  photo/text ``div[style*=flex]`` row with an ``<h3>`` name, the rank as a
  bare text node (recovered by ``title_re``) and the profile link. The page
  interleaves Department / Visiting / Associated / NYU Abu Dhabi / NYU
  Shanghai / Emeritus / In Memoriam sections, so a ``section_filter`` on the
  ``<h2>`` keeps only "Department Faculty". Listing carries no email; the
  env-gated profile pass backfills it from the profile page's mailto.

* ``steinhardt`` — the NYU Steinhardt School of Culture, Education, and Human
  Development directory (steinhardt.nyu.edu, Drupal). One page renders all
  ~320 faculty as ``div.teaser`` cards with the name
  (``.teaser__title-link``), rank (``.teaser__subtitle``) and an inline
  mailto (``a.teaser__link``). The department exposed-filter is client-side
  only (no per-card department attribute, no server/AJAX filter), so
  Steinhardt lands as ONE school-level department entry; the rank gate keeps
  professor/lecturer/instructor/artist and drops emeriti.

* ``as_book`` / ``as_cols_h2`` / ``as_cols_link`` — the three hand-authored
  legacy A&S department layouts, bespoke selectors per family (defined just
  above ``SCHOOL``; see their block comments). ``as_book`` (chemistry,
  history, sociology, complit, german, italian, soca, econ, french) has a
  clean ``div.book-box`` card with a real rank element and inline mailto.
  ``as_cols_h2`` (english, anthropology, ir) is a
  ``div.columns-body`` grid with an ``h2.theme__head--medium`` name + inline
  mailto and the rank recovered from free text by ``title_re``.
  ``as_cols_link`` (biology, linguistics, philosophy, politics, music) is a
  grid whose name IS the profile link; the email is inline only for music and
  is otherwise backfilled by the env-gated profile enrich. All three ladder
  out emeriti (``title_re`` captures the "Emerit*" marker so the normalize
  gate can drop it) and harvest inline "Research Interests:" text.

* ``stern`` — the Stern School of Business directory (stern.nyu.edu Drupal), a
  server-rendered ``div.…shadow-share`` tile grid paginated 20/page at
  ``?page=N`` (~25 pages). Name ``h2 a[/faculty/bio/]``, rank
  ``p.italic``, inline mailto. Ladder keeps professor/lecturer/instructor
  (adjunct/clinical practitioners kept as real mentors), drops emeriti.

* ``wagner`` — the Wagner Graduate School of Public Service directory
  (wagner.nyu.edu Drupal views), ``div.views-row`` cards (``h2`` name,
  ``.views-field-field-person-position`` rank, image profile link), paginated
  24/page at ``?page=N``. No inline email. Ladder drops adjunct/visiting/
  emeriti (Wagner lists a large part-time/practitioner tail).

* ``silver`` — the Silver School of Social Work Our Faculty page
  (socialwork.nyu.edu AEM), ``div.c--faculty-card`` cards (``h3 a`` name with a
  "Read More about " screen-reader prefix stripped, ``.f--professional-title``
  rank). See DEFERRED — only the core ~10 render server-side.

Single source ("nyu_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

Deferred (2026-07-20 recon)
===========================
* Silver School of Social Work FULL roster — the AEM ``faculty-search`` widget
  server-renders only its first ~10 core faculty (confirmed identical under
  headless render); the remaining full-time faculty load only after a
  client-side search interaction with no discoverable JSON endpoint. The
  covered ``SILVER`` entry ships that core slice; the tail is deferred.
* Hellenic Studies (as.nyu.edu/departments/hellenic) — only ~4 real faculty,
  and the bios embed ``h2.theme__head--medium`` sub-section headers ("Areas of
  Specialty", "Areas of Research") INSIDE the same ``columns-body`` article as
  the name, so the as_cols_h2 card selector harvests those headers as phantom
  people. Not worth a Hellenic-only guard for four names; deferred.
* Steinhardt sub-department split — the school directory's per-department
  filter is client-side only (no per-card department attribute, no server/AJAX
  department filter), so Steinhardt stays ONE school-level entry rather than
  split into its sub-departments.
* Small A&S area-studies programs with no standalone ``/people/faculty.html``
  roster at the probed path (art history, classics, CEMS, DHSS, drama lit,
  East Asian studies, environmental studies, Hebrew & Judaic studies, Irish
  studies, MEIS, metropolitan studies, museum studies, religious studies,
  Russian & Slavic studies, Spanish, urban studies, XE) — most are housed
  within a parent department's roster or list faculty only as cross-links;
  no clean per-program card structure to scrape.
* Center for Data Science (cds.nyu.edu) — 403 WAF on the directory.
* Law, Tisch, Gallatin, Global Public Health, School of Professional Studies,
  Dentistry, NYU Grossman School of Medicine (clinical scale) — separate
  platforms, not probed this session.
* NYU Abu Dhabi / NYU Shanghai portal campuses — out of scope for the
  New York, NY campus.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- shared ladder gates ---------------------------------------------------
# Keep professorial + teaching ranks; drop emeriti wherever a listing mixes
# them in. Adjunct/clinical/industry/research professors are kept (real
# mentoring faculty); postdocs/staff fail the "professor|lecturer|instructor"
# requirement.
_KEEP = r"professor|lecturer|instructor"
_KEEP_ARTS = r"professor|lecturer|instructor|artist"
_DROP = r"emerit"
_LADDER = {"require": _KEEP, "drop": _DROP}
_LADDER_ARTS = {"require": _KEEP_ARTS, "drop": _DROP}
_DROP_ONLY = {"drop": _DROP}


# ---- Tandon (engineering.nyu.edu Drupal profile cards) ---------------------
_TANDON_SELECTORS = {
    "card": "article.node--type-profile",
    "name": ".field--name-title",
    "link": "a[href*='/faculty/']",
    "title": ".field--name-field-title",
}
_TANDON_BASE = "https://engineering.nyu.edu/academics/departments"


def _tandon(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Tandon department served by the shared /people profile-card view.

    ``slug`` is the department machine name in the /people path (it differs
    from the department landing slug for Civil & Urban)."""
    url = f"{_TANDON_BASE}/{slug}/people"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _TANDON_SELECTORS,
                       "ladder_filter": _LADDER}}


# ---- Arts & Science modern "faculty directory bio" component ---------------
_AS_DIR_SELECTORS = {
    "card": "div.filtered-items-item",
    "name": "a.facultydirectorybio-person__name",
    "link": "a.facultydirectorybio-person__name",
    "title": "span.facultydirectorybio-person__position",
    "email": "span.facultydirectorybio-person__email a[href^='mailto:']",
}


def _as_dir(short: str, name: str, majors: list[str], slug: str) -> dict:
    """An A&S department on the modern filtered-items-item directory."""
    url = f"https://as.nyu.edu/departments/{slug}/people/faculty.html"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_DIR_SELECTORS,
                       "ladder_filter": _LADDER}}


# ---- Physics: legacy A&S hand-authored flex bio rows -----------------------
# Rank is a bare text node after the <h3> name ("Associate Professor of
# Physics", immediately followed by "Personal Homepage"/"Lab Homepage" link
# text in the same run of text). Capture the rank word + its leading
# modifiers only — anchored to real rank modifiers so the preceding name is
# never swallowed and the trailing homepage link text is never absorbed.
_AS_TITLE_RE = (
    r"((?:(?:University |Global |Distinguished |Silver |Collegiate |Clinical "
    r"|Research |Associate |Assistant |Visiting |Adjunct )*)"
    r"(?:Professor|Lecturer|Instructor)"
    r"(?:\s+(?:of|in)\s+Physics)?)"
)
_PHYS_SELECTORS = {
    "card": "div[style*='display: flex']:has(h3)",
    "name": "h3",
    "link": "a[href*='/faculty/']",
    "title_re": _AS_TITLE_RE,
}
# The AEM profile page (/content/nyu-as/as/faculty/<slug>.html) carries a
# clean personal mailto — the env-gated pass backfills it.
_AS_ENRICH = {"email_selector": "a[href^='mailto:']", "throttle": 0.3}


# ---- Steinhardt (steinhardt.nyu.edu Drupal teaser directory) ---------------
_STEIN_SELECTORS = {
    "card": "div.teaser:has(a.teaser__title-link)",
    "name": "a.teaser__title-link",
    "link": "a.teaser__title-link",
    "title": ".teaser__subtitle",
    "email": "a.teaser__link[href^='mailto:']",
}


# ---- Legacy A&S hand-authored department pages -----------------------------
# The AEM Arts & Science department sites publish their rosters in three
# distinct hand-authored layouts (all live-verified 2026-07-20). A shared
# rank regex + research regex serve every one; each family gets its own card
# selectors below.
#
# ``title_re`` runs over the card's rendered TEXT (faculty_graph §3.3) and
# ``group(1)`` replaces the default "Professor". It captures the rank word
# with its leading modifiers AND a trailing "Emerit*" so the normalize gate
# (and the ladder ``drop``) can strip emeriti whose only rank marker is inline
# free text. Leading "Emeritus/Emerita" is also allowed as a modifier so
# "Emeritus Professor" is captured (and dropped) too.
_AS_TITLE_RE_GEN = (
    r"((?:(?:Emeritus |Emerita |University |Global |Distinguished |Julius Silver "
    r"|Silver |Collegiate |Clinical |Research |Associate |Assistant |Visiting "
    r"|Adjunct |Acting |Senior |Language |Master )*)"
    r"(?:Professor|Lecturer|Instructor)(?:\s+Emerit\w+)?)"
)
# Inline "Research Interests: a, b, c" free text (over rendered TEXT).
_AS_RESEARCH_RE = r"Research Interests\s*:?\s*(.{3,300})"

# Family 1 — "book-box" cards: a clean <h2 class=book-box__title> name, a
# <div class=book-box__author> rank, an inline mailto and a "View Profile"
# /faculty/ link. Rank is a real element so no title_re needed; the ladder
# gate reads it directly. (chemistry, history, sociology, complit, german,
# italian, soca, econ, french)
_AS_BOOK_SEL = {
    "card": "div.book-box",
    "name": "h2.book-box__title",
    "link": "a[href*='/faculty/'], a[href*='/directory']",
    "title": "div.book-box__author",
    "email": "a[href^='mailto:']",
}

# Family 2 — "columns" grid with an <h2 class=theme__head--medium> name and an
# inline mailto; the rank lives in a <h4> or bare <p> (recovered by title_re).
# (english, anthropology, ir, hellenic)
_AS_COLS_H2_SEL = {
    "card": "div.columns-body article.generic-content:has(h2.theme__head--medium)",
    "name": "h2.theme__head--medium",
    "link": "a[href*='/faculty/'], a[href*='/directory']",
    "title_re": _AS_TITLE_RE_GEN,
    "email": "a[href^='mailto:']",
    "research_re_text": _AS_RESEARCH_RE,
}

# Family 3 — "columns" grid whose name IS the profile link (a bold <a> to a
# /faculty/ or /directory. profile); rank (when present) is bare inline text
# recovered by title_re, and email is either an inline mailto (music) or only
# on the profile page (biology/linguistics/philosophy/politics — the env-gated
# enrich backfills it centrally). (biology, linguistics, philosophy, politics,
# music)
_AS_COLS_LINK_SEL = {
    "card": "div.columns-body article.generic-content:has(a[href*='/faculty/'], a[href*='/directory'])",
    "name": "a[href*='/faculty/'], a[href*='/directory']",
    "link": "a[href*='/faculty/'], a[href*='/directory']",
    "title_re": _AS_TITLE_RE_GEN,
    "email": "a[href^='mailto:']",
    "research_re_text": _AS_RESEARCH_RE,
}


def _as_book(short: str, name: str, majors: list[str], url: str) -> dict:
    """A legacy A&S department on the book-box card layout."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_BOOK_SEL,
                       "ladder_filter": _LADDER}}


def _as_cols_h2(short: str, name: str, majors: list[str], url: str) -> dict:
    """A legacy A&S department on the columns/h2-name layout."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_COLS_H2_SEL,
                       "ladder_filter": _LADDER}}


def _as_cols_link(short: str, name: str, majors: list[str], url: str) -> dict:
    """A legacy A&S department on the columns/name-is-the-link layout.

    Carries an env-gated ``profile_enrich`` so the central enrichment run can
    backfill the email (and any research) from each professor's profile."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_COLS_LINK_SEL,
                       "ladder_filter": _LADDER,
                       "profile_enrich": _AS_ENRICH}}


# ---- Stern School of Business (stern.nyu.edu Drupal, ?page= pagination) -----
# Every faculty card is a server-rendered <div class=…shadow-share…> tile with
# the name in <h2><a href=/faculty/bio/…>, the rank in <p class=…italic…>, an
# inline mailto and a Profile button. The listing paginates 20/page at
# ?page=N (page 0 is the base URL); ~25 pages cover the whole school.
_STERN_SEL = {
    "card": "div.shadow-share",
    "name": "h2 a[href*='/faculty/bio/']",
    "link": "h2 a[href*='/faculty/bio/']",
    "title": "p.italic",
    "email": "a[href^='mailto:']",
}

# ---- Wagner (wagner.nyu.edu Drupal views directory, ?page= pagination) ------
# The /community/faculty/directory view renders <div class=views-row> cards:
# name in <h2>, rank in .views-field-field-person-position, profile link in the
# image anchor. No inline email. 24/page.
_WAGNER_SEL = {
    "card": "div.views-row",
    "name": "h2",
    "link": "a[href*='/community/faculty/']",
    "title": ".views-field-field-person-position .field-content",
}

# ---- Silver School of Social Work (socialwork.nyu.edu AEM faculty cards) ----
# The Our Faculty page renders <div class=c--faculty-card> cards: name in
# <h3><a> (with a "Read More about " screen-reader prefix stripped by
# name_strip), rank in .f--professional-title. The AEM faculty-search widget
# only server-renders its first ~10 core faculty; the remainder require a
# client-side search interaction (see DEFERRED note).
_SILVER_SEL = {
    "card": "div.c--faculty-card",
    "name": "h3 a",
    "link": "h3 a",
    "title": ".f--professional-title",
    "name_strip": r"(?i)^\s*read more about\s+",
}


SCHOOL: dict = {
    "school_slug": "nyu",
    "source": "nyu_faculty",
    "organization": "New York University",
    "location": "New York, NY",
    "id_prefix": "nyu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (New York University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Tandon School of Engineering ---------------------------------
        _tandon("CSE", "Department of Computer Science and Engineering",
                ["Computer Science", "Computer Engineering"],
                "computer-science-and-engineering"),
        _tandon("ECE", "Department of Electrical and Computer Engineering",
                ["Electrical Engineering", "Computer Engineering"],
                "electrical-and-computer-engineering"),
        _tandon("MAE", "Department of Mechanical and Aerospace Engineering",
                ["Mechanical Engineering", "Aerospace Engineering"],
                "mechanical-and-aerospace-engineering"),
        _tandon("BME", "Department of Biomedical Engineering",
                ["Biomedical Engineering"], "biomedical-engineering"),
        _tandon("CUE", "Department of Civil and Urban Engineering",
                ["Civil Engineering", "Urban Engineering", "Environmental Engineering"],
                "civil-and-urban-engineering"),
        _tandon("CBE", "Department of Chemical and Biomolecular Engineering",
                ["Chemical Engineering", "Biomolecular Engineering"],
                "chemical-and-biomolecular-engineering"),
        _tandon("FRE", "Department of Finance and Risk Engineering",
                ["Financial Engineering", "Risk Engineering"],
                "finance-and-risk-engineering"),
        _tandon("APHY", "Department of Applied Physics",
                ["Applied Physics"], "applied-physics"),
        _tandon("TMI", "Department of Technology Management and Innovation",
                ["Technology Management", "Management of Technology"],
                "technology-management-and-innovation"),
        _tandon("TCS", "Department of Technology, Culture and Society",
                ["Integrated Digital Media", "Science and Technology Studies"],
                "technology-culture-and-society"),
        # ---- Courant Institute of Mathematical Sciences -------------------
        {"short": "CS", "name": "Department of Computer Science (Courant)",
         "majors": ["Computer Science", "Data Science"],
         "directory_url": "https://cs.nyu.edu/dynamic/people/faculty/",
         "scrape": {"url": "https://cs.nyu.edu/dynamic/people/faculty/type/22/",
                    "selectors": {"card": "ul.people-listing li",
                                  "name": "p.name a", "link": "p.name a",
                                  "title": "p.title"},
                    "ladder_filter": _LADDER}},
        {"short": "MATH", "name": "Department of Mathematics (Courant)",
         "majors": ["Mathematics", "Applied Mathematics"],
         "directory_url": "https://math.nyu.edu/dynamic/people/faculty/",
         "scrape": {"url": "https://math.nyu.edu/dynamic/people/faculty/",
                    "selectors": {"card": "div.people-link",
                                  "name": "h2.name", "link": "h2.name",
                                  "title": "div.people-description > div"},
                    "ladder_filter": _DROP_ONLY}},
        # ---- Faculty of Arts and Science ----------------------------------
        _as_dir("PSYCH", "Department of Psychology", ["Psychology"], "psychology"),
        _as_dir("CNS", "Center for Neural Science",
                ["Neural Science", "Neuroscience"], "cns"),
        {"short": "PHYS", "name": "Department of Physics", "majors": ["Physics"],
         "directory_url": "https://as.nyu.edu/departments/physics/people/faculty.html",
         "scrape": {"url": "https://as.nyu.edu/departments/physics/people/faculty.html",
                    "selectors": _PHYS_SELECTORS,
                    "section_filter": {"heading": "h2", "include": r"^department faculty$"},
                    "ladder_filter": _DROP_ONLY,
                    "profile_enrich": _AS_ENRICH}},
        # ---- Steinhardt School (one school-level entry) -------------------
        {"short": "STEIN",
         "name": "Steinhardt School of Culture, Education, and Human Development",
         "majors": ["Education", "Applied Psychology", "Media, Culture, and Communication",
                    "Music", "Art and Art Professions", "Nutrition and Food Studies",
                    "Physical Therapy", "Occupational Therapy",
                    "Communicative Sciences and Disorders", "Applied Statistics"],
         "directory_url": "https://steinhardt.nyu.edu/faculty",
         "scrape": {"url": "https://steinhardt.nyu.edu/faculty",
                    "selectors": _STEIN_SELECTORS,
                    "ladder_filter": _LADDER_ARTS}},
        # ---- Faculty of Arts and Science: legacy sciences -----------------
        _as_book("CHEM", "Department of Chemistry",
                 ["Chemistry", "Biochemistry"],
                 "https://as.nyu.edu/departments/chemistry/people/faculty.html"),
        _as_cols_link("BIO", "Department of Biology",
                      ["Biology", "Molecular and Cell Biology", "Neural Science"],
                      "https://as.nyu.edu/departments/biology/people/faculty.html"),
        # ---- Faculty of Arts and Science: humanities & social sciences ----
        _as_cols_h2("ENGL", "Department of English",
                    ["English", "Literature"],
                    "https://as.nyu.edu/departments/english/people/faculty.html"),
        _as_book("HIST", "Department of History", ["History"],
                 "https://as.nyu.edu/departments/history/people/faculty.html"),
        _as_cols_h2("ANTH", "Department of Anthropology", ["Anthropology"],
                    "https://as.nyu.edu/departments/anthropology/people/faculty.html"),
        _as_book("SOC", "Department of Sociology", ["Sociology"],
                 "https://as.nyu.edu/departments/sociology/people/faculty.html"),
        _as_cols_link("LING", "Department of Linguistics", ["Linguistics"],
                      "https://as.nyu.edu/departments/linguistics/people/faculty.html"),
        _as_cols_link("PHIL", "Department of Philosophy", ["Philosophy"],
                      "https://as.nyu.edu/departments/philosophy/directory/faculty.html"),
        _as_book("ECON", "Department of Economics", ["Economics"],
                 "https://as.nyu.edu/departments/econ/faculty.html"),
        _as_cols_link("POL", "Department of Politics",
                      ["Politics", "Political Science"],
                      "https://as.nyu.edu/departments/politics/directory/CoreFaculty.html"),
        _as_book("COMPLIT", "Department of Comparative Literature",
                 ["Comparative Literature"],
                 "https://as.nyu.edu/departments/complit/people/faculty.html"),
        _as_book("GERM", "Department of German", ["German"],
                 "https://as.nyu.edu/departments/german/people/faculty.html"),
        _as_book("ITAL", "Department of Italian Studies", ["Italian Studies"],
                 "https://as.nyu.edu/departments/italian/people/faculty.html"),
        _as_book("SCA", "Department of Social and Cultural Analysis",
                 ["Social and Cultural Analysis", "American Studies",
                  "Africana Studies", "Latino Studies",
                  "Gender and Sexuality Studies"],
                 "https://as.nyu.edu/departments/soca/people/faculty.html"),
        _as_cols_h2("IR", "International Relations Program",
                    ["International Relations"],
                    "https://as.nyu.edu/departments/ir/people/faculty.html"),
        _as_cols_link("MUS", "Department of Music", ["Music"],
                      "https://as.nyu.edu/departments/music/people/faculty.html"),
        _as_book("FREN", "Department of French Literature, Thought and Culture",
                 ["French Literature, Thought and Culture", "French"],
                 "https://as.nyu.edu/departments/french/people/Faculty.html"),
        # ---- Stern School of Business -------------------------------------
        {"short": "STERN", "name": "Leonard N. Stern School of Business",
         "majors": ["Business", "Finance", "Marketing", "Management",
                    "Accounting", "Economics", "Information Systems",
                    "Operations Management", "Business Analytics"],
         "directory_url": "https://www.stern.nyu.edu/faculty",
         "scrape": {"url": "https://www.stern.nyu.edu/faculty",
                    "selectors": _STERN_SEL,
                    "paginate": {"param": "page", "start": 1, "max": 26},
                    "ladder_filter": _LADDER}},
        # ---- Wagner Graduate School of Public Service ---------------------
        {"short": "WAG",
         "name": "Robert F. Wagner Graduate School of Public Service",
         "majors": ["Public Policy", "Public Administration", "Urban Planning",
                    "Health Policy and Management", "Public Service"],
         "directory_url": "https://wagner.nyu.edu/community/faculty/directory",
         "scrape": {"url": "https://wagner.nyu.edu/community/faculty/directory",
                    "selectors": _WAGNER_SEL,
                    "paginate": {"param": "page", "start": 1, "max": 15},
                    "ladder_filter": {"require": _KEEP,
                                      "drop": r"emerit|adjunct|visiting"}}},
        # ---- Silver School of Social Work (core faculty; search-gated) ----
        {"short": "SILVER", "name": "Silver School of Social Work",
         "majors": ["Social Work"],
         "directory_url": "https://socialwork.nyu.edu/nyusilver/en/home/faculty-and-research/our-faculty.html",
         "scrape": {"url": "https://socialwork.nyu.edu/nyusilver/en/home/faculty-and-research/our-faculty.html",
                    "selectors": _SILVER_SEL,
                    "ladder_filter": _LADDER}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
