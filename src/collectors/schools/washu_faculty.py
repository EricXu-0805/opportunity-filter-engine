"""Washington University in St. Louis faculty config (via the faculty_graph engine).

WashU is mid-rebrand (wustl.edu -> washu.edu; med-school basic-science depts
still live natively on *.wustl.edu) but everything wired here is served
server-rendered to a plain desktop-UA request — no WAF, no render mode. Five
markup families, all selectors live-verified 2026-07-18:

* McKelvey School of Engineering: ONE static page (engineering.washu.edu/
  faculty/) holds all ~180 engineering faculty; each ``article.faculty-
  directory__teaser`` is tagged ``data-shortdept`` (cse/bme/mems/ese/eece), so
  a department is just an attribute-filtered card selector over the same page.
  Ladder gate keeps tenure-track only (recon call): drops the 20 Senior
  Lecturers / 12 Lecturers / 10 Teaching Professors / 11 Professors of
  Practice / 6 Research Assistant Professors, and "Dean" alone. No usable
  research text: the clean topics ride a ``data-degree`` ATTRIBUTE as
  underscore_joined_tokens ("neural_engineering neuroimaging"), which no
  engine selector/regex path can split into keywords (an attribute-token
  transform would be a new engine feature), and profiles are prose taglines —
  so records land unkeyworded (OpenAlex backfills). Profile pages carry one
  clean personal mailto -> gated email enrich.

* Arts & Sciences shared Drupal theme (26 depts on ``<dept>.washu.edu/people``;
  jimes uses ``/faculty-staff``): the role facet ``?cat=88`` ("Faculty" /
  "Academic Faculty") gates out staff/grads/postdocs/emeriti server-side. The
  page renders the SAME people twice (a Grid tab and a List tab); the List tab
  (``div#List article.faculty-post``) is the one wired because it carries the
  personal mailto ON the listing — no profile pass needed. 24 people/page,
  "Load more" is ``&page=N`` (0-indexed, so the engine's start=1 follow-up is
  the second page). NOTE: the recon's per-dept estimates counted BOTH tabs, so
  healthy parsed counts sit at ~50% of the recon numbers (verified: single-page
  depts like Anthropology parse 23 vs "46 est"). Research on cards/profiles is
  prose-only — no research selectors (comma-splitting bios is poison).

* Sam Fox School of Design & Visual Arts: ``div.faculty-directory__entry``
  cards, 24/page, ``?page=N`` (1-indexed; base page IS page 1, so paginate
  starts at 2). Faculty-only listing (staff/students are separate tabs);
  lecturers kept (an art school's studio faculty). Profiles carry one clean
  mailto -> gated email enrich; no clean research anywhere (exhibition lists).

* Med-school basic science on *.wustl.edu WordPress ("washu-ppi" people
  plugin; Genetics / Neuroscience / Cell Biology & Physiology / Developmental
  Biology): one-page faculty listing at ``/people-page/faculty/`` with the
  personal mailto CLEAN ON THE CARD (``li.washu-ppi-email``) — the profile
  mailto is percent-hex obfuscated, so no profile pass. Names carry ", PhD"
  (engine strips credentials).

* WordPress REST (Brown School + School of Law): both rosters are enumerated
  via ``/wp-json/wp/v2/<type>`` (the public HTML pages JS-filter or only
  feature ~15 cards). Brown: post type ``faculty``, 67 records, all four
  facultytype terms are real faculty (TT 38 / research 7 / practice 10 /
  teaching 11); the ``researchtype`` taxonomy exists but is empty on every
  person, so research comes from the gated profile pass ("Areas of Focus"
  <br>-separated block). Law: post type ``person`` filtered to people-category
  12 (Resident & Visiting Faculty, 92 records, one page — the REST API
  occasionally 403s rapid repeat calls, so the single-call category filter
  matters). Neither REST payload carries a rank -> titles default to
  "Professor"; Law's gated profile pass reads the real rank from the first
  ``h2.wp-block-kadence-advancedheading`` under the name.

Faculty emails are @wustl.edu even where the web domain is washu.edu.
Single source ("washu_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (and why):
* Olin Business School (~127 core faculty): the ONLY enumeration is a PHP
  JSON feed (``/_common/files/php/views/faculty/faculty-results.php``) whose
  card HTML rides key "Results" — the engine's ``ajax_html`` source reads only
  the Drupal "data" key, and ``olin.washu.edu/faculty`` 404s to a plain GET
  (JS shell), sitemap carries no profile URLs. Profiles themselves are rich
  (rank, clean comma-separated "Area of Expertise", personal mailto) — a tiny
  engine extension (configurable ajax_html JSON key) unlocks the school.
* McKelvey Division of Engineering Education (8): all teaching-track — the
  tenure-track ladder gate yields zero by design.
* School of Medicine clinical departments (Medicine, Surgery, Pediatrics, …):
  thousands of clinicians across many division sites, low undergrad-research
  relevance (recon scope call).
* Pathology & Immunology: roster fragmented across per-division sub-pages;
  needs per-division enumeration (med-scale).
* DBBS umbrella roster: cross-listed aggregator that would duplicate the
  per-department washu-ppi lists wired above.
* Biochemistry & Molecular Biophysics / Molecular Microbiology / Physiology:
  different sites.wustl.edu template or unreachable (000) at recon time —
  re-probe next pass.
* School of Public Health (publichealth.washu.edu): 403 to the desktop UA at
  recon time (newly launched school) — retry with adjusted headers next pass.
* German / Slavic / Comparative Literature / Film & Media (A&S): standalone
  subdomains don't resolve; likely merged into RLL/AMCS/EALC — verify slugs.
* Statistics & Data Science / datascience.washu.edu: institute aggregator of
  faculty already counted under Math/CSE — dedupe risk, skipped.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- McKelvey School of Engineering (one page, data-shortdept cards) -------
_MCK_URL = "https://engineering.washu.edu/faculty/"

# Tenure-track only (recon call): the directory mixes 50+ teaching-track
# titles into the same card grid; "Dean" alone also fails the require.
_MCK_LADDER = {
    "require": r"\bprofessor\b",
    "drop": (r"emerit|visiting|adjunct|lecturer|instructor|teaching professor"
             r"|of practice|research assistant professor"),
}

# Profiles carry exactly one clean personal mailto (setton@wustl.edu).
_MCK_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^[^@]*$",
    "throttle": 0.2,
}


def _mck(short: str, code: str, name: str, majors: list[str]) -> dict:
    """One McKelvey department = an attribute-filtered slice of the one page."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": _MCK_URL,
            "scrape": {"url": _MCK_URL,
                       "selectors": {
                           "card": f"article.faculty-directory__teaser[data-shortdept~='{code}']",
                           "name": "h3.faculty-directory__teaser-name",
                           "link": "a.faculty-directory__teaser-container",
                           "title": "p.faculty-directory__teaser-title",
                       },
                       "ladder_filter": _MCK_LADDER,
                       "profile_enrich": _MCK_ENRICH}}


# ---- Arts & Sciences shared Drupal theme (List tab, emails on listing) -----
_AS_SELECTORS = {
    "card": "div#List article.faculty-post",
    "name": "h3.name a",
    # A few cards paste a zero-width space into the name ("​Kristin Van
    # Engen") — strip it so pi_name stays a clean person name.
    "name_strip": r"[\u200b\u200e\ufeff]",
    "link": "h3.name a",
    "title": "ul.depts li",
    "email": "ul.contact a[href^='mailto:']",
}

# ?cat=88 already gates the roles server-side; drop emeriti stragglers.
_LADDER_LIGHT = {"drop": r"emerit"}


def _as(short: str, name: str, majors: list[str], subdomain: str,
        path: str = "/people") -> dict:
    """An Arts & Sciences department on the shared ?cat=88 faculty facet."""
    url = f"https://{subdomain}.washu.edu{path}?cat=88"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _AS_SELECTORS,
                       "ladder_filter": _LADDER_LIGHT,
                       "paginate": {"param": "page", "start": 1, "max": 6}}}


# ---- Med-school basic science ("washu-ppi" WordPress people plugin) --------
_PPI_SELECTORS = {
    "card": "div.washu-ppi-card.ppi-people-card",
    "name": "h2.washu-ppi-name",
    "link": "a.washu-ppi-card-link",
    "title": "p.washu-ppi-description",
    # The listing mailto is clean; the PROFILE mailto is hex-obfuscated.
    "email": "li.washu-ppi-email a[href^='mailto:']",
}


def _ppi(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    """A School of Medicine basic-science department on the washu-ppi theme."""
    url = f"https://{subdomain}.wustl.edu/people-page/faculty/"
    return {"short": short, "name": f"Department of {name}", "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _PPI_SELECTORS,
                       "ladder_filter": _LADDER_LIGHT}}


SCHOOL: dict = {
    "school_slug": "washu",
    "source": "washu_faculty",
    "organization": "Washington University in St. Louis",
    "location": "St. Louis, MO",
    "id_prefix": "washu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Washington University in St. Louis) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- McKelvey School of Engineering --------------------------------
        _mck("CSE", "cse", "Computer Science & Engineering",
             ["Computer Science", "Computer Engineering", "Data Science"]),
        _mck("BME", "bme", "Biomedical Engineering", ["Biomedical Engineering"]),
        _mck("MEMS", "mems", "Mechanical Engineering & Materials Science",
             ["Mechanical Engineering", "Materials Science"]),
        _mck("ESE", "ese", "Electrical & Systems Engineering",
             ["Electrical Engineering", "Systems Science & Engineering"]),
        _mck("EECE", "eece", "Energy, Environmental & Chemical Engineering",
             ["Chemical Engineering", "Environmental Engineering"]),
        # ---- Arts & Sciences: Sciences -------------------------------------
        _as("PHYS", "Department of Physics", ["Physics"], "physics"),
        _as("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _as("MATH", "Department of Mathematics & Statistics",
            ["Mathematics", "Statistics"], "math"),
        _as("BIOL", "Department of Biology", ["Biology"], "biology"),
        _as("EEPS", "Department of Earth, Environmental & Planetary Sciences",
            ["Earth, Environmental & Planetary Sciences", "Geology"], "eeps"),
        # ---- Arts & Sciences: Social Sciences ------------------------------
        _as("ECON", "Department of Economics", ["Economics"], "economics"),
        _as("PBS", "Department of Psychological & Brain Sciences",
            ["Psychological & Brain Sciences", "Neuroscience", "Psychology"],
            "psych"),
        _as("ANTH", "Department of Anthropology", ["Anthropology"], "anthropology"),
        _as("POLSCI", "Department of Political Science", ["Political Science"],
            "polisci"),
        _as("SOC", "Department of Sociology", ["Sociology"], "sociology"),
        _as("EDUC", "Department of Education", ["Education"], "education"),
        # ---- Arts & Sciences: Humanities -----------------------------------
        _as("PHIL", "Department of Philosophy",
            ["Philosophy", "Philosophy-Neuroscience-Psychology (PNP)"],
            "philosophy"),
        _as("HIST", "Department of History", ["History"], "history"),
        _as("ENGL", "Department of English", ["English"], "english"),
        _as("CLAS", "Department of Classics", ["Classics"], "classics"),
        _as("LING", "Program in Linguistics", ["Linguistics"], "linguistics"),
        _as("MUSIC", "Department of Music", ["Music"], "music"),
        _as("RLL", "Department of Romance Languages & Literatures",
            ["French", "Spanish", "Italian"], "rll"),
        _as("EALC", "Department of East Asian Languages & Cultures",
            ["East Asian Languages & Cultures", "Chinese", "Japanese"], "ealc"),
        _as("AHA", "Department of Art History & Archaeology",
            ["Art History & Archaeology"], "arthistory"),
        _as("PAD", "Program in Performing Arts (Dance / Theater)",
            ["Dance", "Theater"], "pad"),
        # ---- Arts & Sciences: interdisciplinary (after home depts, so the
        # email-keyed joint-appointment dedup keeps the home-dept record) -----
        _as("WGSS", "Department of Women, Gender & Sexuality Studies",
            ["Women, Gender & Sexuality Studies"], "wgss"),
        _as("JIMES", "Department of Jewish, Islamic & Middle Eastern Studies",
            ["Jewish, Islamic & Middle Eastern Studies"], "jimes",
            path="/faculty-staff"),
        _as("AMCS", "Program in American Culture Studies",
            ["American Culture Studies"], "amcs"),
        _as("AFAS", "Department of African & African American Studies",
            ["African & African American Studies"], "afas"),
        _as("GLST", "Program in Global Studies", ["Global Studies"],
            "globalstudies"),
        # ---- Sam Fox School of Design & Visual Arts ------------------------
        {
            "short": "SAMFOX",
            "name": "Sam Fox School of Design & Visual Arts",
            "majors": ["Architecture", "Studio Art", "Communication Design",
                       "Fashion Design"],
            "directory_url": "https://samfoxschool.washu.edu/people/faculty",
            "scrape": {
                "url": "https://samfoxschool.washu.edu/people/faculty",
                "selectors": {"card": "div.faculty-directory__entry",
                              "name": "p.faculty-directory__name",
                              "link": "a",
                              "title": "p.faculty-directory__job-title"},
                "ladder_filter": {"drop": r"emerit|visiting"},
                # Base page IS page 1 — start the follow-ups at ?page=2.
                "paginate": {"param": "page", "start": 2, "max": 9},
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "email_drop": r"^[^@]*$",
                                   "throttle": 0.2},
            },
        },
        # ---- Brown School (WordPress REST) ---------------------------------
        {
            "short": "BROWN",
            "name": "Brown School (Social Work, Public Health & Social Policy)",
            "majors": ["Social Work", "Public Health", "Social Policy",
                       "Sociology"],
            "directory_url": "https://brownschool.washu.edu/faculty-research/",
            "api": {
                "type": "wp",
                "base": "https://brownschool.washu.edu",
                "post_type": "faculty",
            },
            # Dept-level enrich (the wp-api source has no scrape block):
            # personal mailto is the first on the profile; "Areas of Focus" is
            # a clean <br>-separated block.
            "profile_enrich": {
                "email_selector": "a[href^='mailto:']",
                "email_drop": r"^[^@]*$|brownschool@",
                "research_html_re": r"Areas of Focus</h2>\s*<p>(.*?)</p>",
                "throttle": 0.2,
            },
        },
        # ---- School of Law (WordPress REST) --------------------------------
        {
            "short": "LAW",
            "name": "School of Law",
            "majors": ["Law", "Political Science"],
            "directory_url": "https://law.washu.edu/faculty-staff-directory/",
            "api": {
                "type": "wp",
                "base": "https://law.washu.edu",
                "post_type": "person",
                # people-category 12 = Resident & Visiting Faculty (92, one
                # page — the REST API 403s rapid repeat calls, so keep it to
                # a single filtered request).
                "query": "&people-category=12",
                "category_include": {"people-category": [12]},
            },
            # REST carries no rank; the profile's first kadence heading under
            # the name is the real title ("Associate Professor of Law").
            "profile_enrich": {
                "title_selector": "h2.wp-block-kadence-advancedheading",
                "email_selector": "a[href^='mailto:']",
                "email_drop": r"^[^@]*$",
                "ladder_recheck": {"drop": r"emerit"},
                "throttle": 0.2,
            },
        },
        # ---- School of Medicine basic science (washu-ppi on wustl.edu) -----
        _ppi("GEN", "Genetics", ["Biology", "Genetics"], "genetics"),
        _ppi("NSC", "Neuroscience", ["Neuroscience", "Biology"], "neuroscience"),
        _ppi("CBP", "Cell Biology & Physiology", ["Biology"], "cellbiology"),
        _ppi("DEVBIO", "Developmental Biology", ["Biology"],
             "developmentalbiology"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
