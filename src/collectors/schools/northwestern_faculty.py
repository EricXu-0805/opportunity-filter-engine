"""Northwestern University faculty config (via the faculty_graph engine).

Weinberg College of Arts & Sciences runs a shared "Cascade" CMS across nearly
all departments: a ``div.people-wrap`` card with name + profile link in
``h3 a``, rank in ``p.title``, and a public ``mailto:`` on the card, so records
land name + title + email in a single server-rendered listing pass (no headless
browser). Three departments use a different theme (Sociology's HTML table,
Molecular Biosciences' ``div.directory`` roster, the CIERA astrophysics center's
WordPress directory) — those carry their variant selectors inline.

McCormick School of Engineering (9 depts) uses its own ``.faculty`` card theme
(``.faculty-info`` name/rank + ``a.mail_link`` mailto). School of Communication
(5 depts) and the School of Education & Social Policy (one directory) serve a JS
``article`` card with no email on the listing, so they pair a rendered scrape with
a ``profile_enrich`` email pass (plain GET). Medill and Bienen have no scrapeable
listing at all (JS grid / performance table), so they use the ``sitemap`` source:
the site's sitemap enumerates every profile page, which is fetched (curl) for
name + rank + email. Feinberg basic sciences + Kellogg remain a follow-up.

Single source ("northwestern_faculty"); department rides each record's
``department``, ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Weinberg Cascade card theme.
_NW_SEL = {"card": "div.people-wrap", "name": "h3 a", "link": "h3 a",
           "title": "p.title", "email": "a[href^='mailto:']"}
# Drop Northwestern's large teaching track ("... of Instruction"), emeriti,
# lecturers, adjuncts, visiting, postdoctoral fellows, and staff; keep
# professorial ladder faculty (endowed chairs contain "Professor").
_NW_LADDER = {"require": r"\bprofessor\b",
              "drop": (r"\bemerit|instruction|\blecturer|\bvisiting|\badjunct"
                       r"|\bpostdoctoral|\bfellow\b|\bstaff\b")}
# Weinberg Cascade profiles keep research in a ``div#biography-content`` block
# under a "Research"/"Interests"/"Specializations" heading (case-sensitive
# soupsieve, so the uppercase Anthropology variant is listed explicitly); the
# body sometimes sits in an <h1> rather than <p>, so the combinator is ``+ *``.
# research_selector (prose, comma/semicolon-split downstream); env-gated
# (no ``always``) so it rides OFE_ENRICH_PROFILES + carry-forward persistence.
_NW_ENRICH = {
    "throttle": 0.3,
    "timeout": 8,
    "max_retries": 1,
    "research_selector": (
        '#biography-content h2:-soup-contains("Research") + *, '
        '#biography-content h3:-soup-contains("Research") + *, '
        '#biography-content h4:-soup-contains("Research") + *, '
        '#biography-content h5:-soup-contains("Research") + *, '
        '#biography-content h2:-soup-contains("RESEARCH AND TEACHING INTERESTS") + *, '
        '#biography-content h3:-soup-contains("RESEARCH AND TEACHING INTERESTS") + *, '
        '#biography-content h4:-soup-contains("RESEARCH AND TEACHING INTERESTS") + *, '
        '#biography-content h5:-soup-contains("RESEARCH AND TEACHING INTERESTS") + *, '
        '#biography-content h2:-soup-contains("Specializations") + *, '
        '#biography-content h3:-soup-contains("Specializations") + *, '
        '#biography-content h4:-soup-contains("Specializations") + *, '
        '#biography-content h5:-soup-contains("Specializations") + *, '
        '#biography-content h2:-soup-contains("Interests") + *, '
        '#biography-content h3:-soup-contains("Interests") + *, '
        '#biography-content h4:-soup-contains("Interests") + *, '
        '#biography-content h5:-soup-contains("Interests") + *'
    ),
}


def _nw(short: str, name: str, majors: list[str], url: str,
        link_filter: str | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": _NW_SEL, "ladder_filter": _NW_LADDER,
                    "profile_enrich": _NW_ENRICH}
    if link_filter:
        scrape["link_filter"] = link_filter
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# McCormick School of Engineering: shared theme distinct from Weinberg's — a
# ``.faculty`` card (name/link in ``.faculty-info h3 a``, rank in the first
# ``.faculty-info p``, public mailto in ``a.mail_link``) at
# mccormick.northwestern.edu/<slug>/people/faculty/ (ECE uses /people/faculty.html).
_MCC_SEL = {"card": ".faculty", "name": ".faculty-info h3 a",
            "link": ".faculty-info h3 a", "title": ".faculty-info p",
            "email": "a.mail_link[href^='mailto:']"}
_MCC_LADDER = {"require": r"\bprofessor\b",
               "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bcourtesy|instruction|\bstaff\b"}


def _mcc(short: str, name: str, majors: list[str], slug: str,
         path: str = "/people/faculty/index.html") -> dict:
    url = f"https://www.mccormick.northwestern.edu/{slug}{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _MCC_SEL, "ladder_filter": _MCC_LADDER}}


# School of Communication: each department serves a JS-rendered ``article`` card
# (name in ``h2``, profile link in the first ``a``, rank in ``p.title``) at
# communication.northwestern.edu/academics/<slug>/faculty.html. The LISTING has
# no email — but each ``/faculty/<name>.html`` profile carries a public mailto
# reachable by a plain GET, so a (gate-bypassing) ``profile_enrich`` pass lands
# the address without a per-profile headless render.
_SOC_SEL = {"card": "article", "name": "h2", "link": "a", "title": "p.title"}
_SOC_LADDER = {"require": r"\bprofessor\b",
               "drop": (r"\bemerit|\blecturer|\bvisiting|\badjunct|instruction"
                        r"|artist in residence|\bstaff\b|\bfellow\b|\bpostdoc")}
_SOC_ENRICH = {"always": True, "email_selector": "a[href^='mailto:']", "throttle": 0.15}


def _soc(short: str, name: str, majors: list[str], slug: str) -> dict:
    url = f"https://communication.northwestern.edu/academics/{slug}/faculty.html"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "render": True, "selectors": _SOC_SEL,
                       "ladder_filter": _SOC_LADDER, "profile_enrich": _SOC_ENRICH}}


SCHOOL: dict = {
    "school_slug": "northwestern",
    "source": "northwestern_faculty",
    "organization": "Northwestern University",
    "location": "Evanston, IL",
    "id_prefix": "northwestern",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Northwestern University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # --- Weinberg College of Arts & Sciences (shared Cascade theme) ---
        _nw("ANTH", "Department of Anthropology", ["Anthropology"],
            "https://anthropology.northwestern.edu/people/faculty/"),
        _nw("ARTH", "Department of Art History", ["Art History"],
            "https://arthistory.northwestern.edu/people/faculty/"),
        _nw("CHEM", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.northwestern.edu/people/faculty/"),
        _nw("CLASSICS", "Department of Classics", ["Classics", "Classical Studies"],
            "https://classics.northwestern.edu/people/faculty/"),
        _nw("ECON", "Department of Economics", ["Economics"],
            "https://economics.northwestern.edu/people/faculty/"),
        _nw("ENGL", "Department of English",
            ["English", "Literature", "Creative Writing"],
            "https://english.northwestern.edu/people/faculty/"),
        _nw("FRIT", "Department of French & Italian", ["French", "Italian"],
            "https://frenchanditalian.northwestern.edu/people/faculty/"),
        _nw("GSF", "Department of Gender & Sexuality Studies",
            ["Gender & Sexuality Studies"],
            "https://gendersexuality.northwestern.edu/people/faculty/core-faculty/index.html"),
        _nw("GERMAN", "Department of German", ["German", "German Studies"],
            "https://german.northwestern.edu/people/faculty/continuing/index.html"),
        _nw("HIST", "Department of History", ["History"],
            "https://history.northwestern.edu/people/faculty/"),
        _nw("LING", "Department of Linguistics", ["Linguistics"],
            "https://linguistics.northwestern.edu/people/core-faculty/"),
        _nw("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"],
            "https://www.math.northwestern.edu/people/faculty/"),
        _nw("NEURO", "Department of Neurobiology", ["Neurobiology", "Neuroscience"],
            "https://neurobiology.northwestern.edu/people/core-faculty/index.html"),
        _nw("PHIL", "Department of Philosophy", ["Philosophy"],
            "https://philosophy.northwestern.edu/people/continuing-faculty/index.html"),
        _nw("PHYS", "Department of Physics & Astronomy", ["Physics", "Astronomy"],
            "https://physics.northwestern.edu/people/faculty/core-faculty/index.html"),
        _nw("POLISCI", "Department of Political Science", ["Political Science"],
            "https://polisci.northwestern.edu/people/core-faculty/"),
        _nw("PSYCH", "Department of Psychology", ["Psychology"],
            "https://psychology.northwestern.edu/people/faculty/core/index.html"),
        _nw("RELIG", "Department of Religious Studies", ["Religious Studies"],
            "https://religious-studies.northwestern.edu/people/faculty/"),
        _nw("SLAVIC", "Department of Slavic Languages & Literatures",
            ["Slavic Languages & Literatures", "Russian"],
            "https://slavic.northwestern.edu/people/faculty/"),
        # Cross-listed affiliates carry an absolute foreign-subdomain profile link
        # + a "| Department of X" name suffix; a relative-only link_filter keeps
        # home faculty with clean names.
        _nw("SPANPORT", "Department of Spanish & Portuguese", ["Spanish", "Portuguese"],
            "https://spanish-portuguese.northwestern.edu/people/faculty/",
            link_filter=r"^(?!https?://)"),
        _nw("STAT", "Department of Statistics & Data Science",
            ["Statistics", "Data Science"],
            "https://statistics.northwestern.edu/people/faculty/"),
        _nw("EPS", "Department of Earth, Planetary & Environmental Sciences",
            ["Earth Science", "Environmental Sciences", "Planetary Science"],
            "https://deeps.northwestern.edu/our-people/faculty/index.html"),
        # --- variant themes ---
        {
            "short": "SOC", "name": "Department of Sociology", "majors": ["Sociology"],
            "directory_url": "https://sociology.northwestern.edu/people/faculty/",
            "scrape": {
                "url": "https://sociology.northwestern.edu/people/faculty/",
                "selectors": {
                    "card": "table#directory tbody tr",
                    "name": "td:nth-child(1) a", "link": "td:nth-child(1) a",
                    "title": "td:nth-child(2)",
                    "email": "td:nth-child(3) a[href^='mailto:']",
                },
                "ladder_filter": _NW_LADDER,
            },
        },
        {
            "short": "MOLBIO", "name": "Department of Molecular Biosciences",
            "majors": ["Molecular Biosciences", "Biochemistry", "Molecular Biology"],
            "directory_url": "https://molbiosci.northwestern.edu/people/core-faculty/index.html",
            # 'directory' card theme, no rank on the card; the page IS the
            # Core-Faculty roster so no ladder filter (title defaults to Professor).
            "scrape": {
                "url": "https://molbiosci.northwestern.edu/people/core-faculty/index.html",
                "selectors": {
                    "card": "div.directory", "name": "h3 a", "link": "h3 a",
                    "email": "a[href^='mailto:']",
                },
            },
        },
        {
            "short": "CIERA",
            "name": "Center for Interdisciplinary Exploration & Research in Astrophysics",
            "majors": ["Astronomy", "Astrophysics", "Physics"],
            "directory_url": "https://ciera.northwestern.edu/directory/",
            "scrape": {
                "url": "https://ciera.northwestern.edu/directory/",
                "selectors": {
                    "card": "div.people-wrap", "name": "h4 a", "link": "h4 a",
                    "title": "p[itemprop='jobTitle']",
                    "email": "a.email-link[href^='mailto:']",
                },
                # A WordPress center directory mixing grad students / postdocs /
                # staff and external-institution professors — strict drop keeps
                # Northwestern ladder professors.
                "ladder_filter": {
                    "require": r"\bprofessor\b",
                    "drop": (r"\bemerit|instruction|\bvisiting|\bpostdoctoral|postdoc"
                             r"|\bgraduate\b| at |\bscholar|\bfellow\b|adjunct"
                             r"|research assistant professor|\breader\b|specialist"
                             r"|scientist|director of operations|assistant director"
                             r"|,\s+(?:the\s+)?(?:university|northern|princeton"
                             r"|wake forest|illinois|mcgill|tata|national|adler"
                             r"|uc\b|mit\b|arizona|warwick|berkeley|chinese)"),
                },
            },
        },
        # --- McCormick School of Engineering (shared .faculty theme) ---
        _mcc("MCC-BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "biomedical"),
        _mcc("MCC-CHBE", "Department of Chemical & Biological Engineering",
             ["Chemical Engineering", "Biological Engineering"], "chemical-biological"),
        _mcc("MCC-CEE", "Department of Civil & Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "civil-environmental"),
        _mcc("MCC-CS", "Department of Computer Science",
             ["Computer Science"], "computer-science"),
        _mcc("MCC-ECE", "Department of Electrical & Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], "electrical-computer",
             path="/people/faculty.html"),
        _mcc("MCC-ESAM", "Department of Engineering Sciences & Applied Mathematics",
             ["Applied Mathematics"], "applied-math"),
        _mcc("MCC-IEMS", "Department of Industrial Engineering & Management Sciences",
             ["Industrial Engineering"], "industrial"),
        _mcc("MCC-MSE", "Department of Materials Science & Engineering",
             ["Materials Science"], "materials-science"),
        _mcc("MCC-ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"], "mechanical"),
        # --- School of Communication (article theme + profile_enrich email) ---
        _soc("COMM-CSD", "Department of Communication Sciences & Disorders",
             ["Communication Sciences & Disorders", "Speech-Language Pathology", "Audiology"],
             "communication-sciences-and-disorders"),
        _soc("COMM-CS", "Department of Communication Studies",
             ["Communication Studies", "Communication"], "communication-studies"),
        _soc("COMM-PS", "Department of Performance Studies",
             ["Performance Studies"], "performance-studies"),
        _soc("COMM-RTVF", "Department of Radio/Television/Film",
             ["Radio/Television/Film", "Film", "Media Arts"], "radio-television-film"),
        _soc("COMM-THEA", "Department of Theatre",
             ["Theatre", "Drama"], "theatre"),
        # --- School of Education & Social Policy (one Cascade directory) ---
        # Same theme as Communication but rank in ``div.title``; all programs
        # (Human Development & Social Policy, Learning Sciences, Higher Education,
        # Learning & Organizational Change) share one /people/faculty/ listing, so
        # it rides as a single school-level entry. Email via profile_enrich (GET).
        {
            "short": "SESP", "name": "School of Education and Social Policy",
            "majors": ["Education", "Social Policy", "Human Development",
                       "Learning Sciences", "Learning & Organizational Change"],
            "directory_url": "https://www.sesp.northwestern.edu/people/faculty/index.html",
            "scrape": {
                "url": "https://www.sesp.northwestern.edu/people/faculty/index.html",
                "render": True,
                "selectors": {"card": "article", "name": "h2", "link": "a",
                              "title": "div.title"},
                "ladder_filter": _SOC_LADDER,
                "profile_enrich": _SOC_ENRICH,
            },
        },
        # --- Medill School of Journalism (sitemap-enumerated profiles) ---
        # The directory is a JS grid with no scrapeable listing, but the sitemap
        # enumerates every /directory/faculty/<slug>.html profile (Cascade CMS,
        # curl-able: h1 name, a title class, public mailto). No render needed.
        {
            "short": "MEDILL",
            "name": "Medill School of Journalism, Media, Integrated Marketing Communications",
            "majors": ["Journalism", "Integrated Marketing Communications", "Media"],
            "directory_url": "https://www.medill.northwestern.edu/directory/faculty/index.html",
            "sitemap": {
                "sitemaps": ["https://www.medill.northwestern.edu/sitemap.xml"],
                "include": r"/directory/faculty/", "exclude": r"/index\.html$",
                "render": False,
                "selectors": {"name": "h1", "title": "[class*=title]",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff\b"},
                "cap": 200,
            },
        },
        # --- Pritzker School of Law (list-page-harvested profiles) ---
        # No XML sitemap, but /faculty/fulltime/ renders all full-time faculty as
        # /faculty/profiles/<slug>/ links; profiles are curl-able (h1 name,
        # p.mb-0 rank, public mailto). Harvest links from the listing, scrape each.
        {
            "short": "LAW", "name": "Pritzker School of Law",
            "majors": ["Law", "Legal Studies"],
            "directory_url": "https://www.law.northwestern.edu/faculty/fulltime/",
            "sitemap": {
                "list_pages": ["https://www.law.northwestern.edu/faculty/fulltime/"],
                "list_render": True,
                "include": r"/faculty/profiles/[^/]+/$",
                "render": False,
                "selectors": {"name": "h1", "title": "p.mb-0",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\bvisiting|\blecturer\b|\badjunct"},
                "cap": 200,
            },
        },
        # --- Bienen School of Music (sitemap-enumerated profiles) ---
        # /faculty/profile/<slug> pages (curl-able: h1 name, p.faculty-title rank,
        # public mailto). Keeps professorial faculty (incl. performance professors),
        # drops emeriti / lecturers / adjuncts.
        {
            "short": "BIENEN", "name": "Bienen School of Music",
            "majors": ["Music", "Music Performance", "Composition", "Musicology",
                       "Music Theory", "Music Education", "Jazz Studies"],
            "directory_url": "https://www.music.northwestern.edu/faculty",
            "sitemap": {
                "sitemaps": ["https://www.music.northwestern.edu/sitemap.xml"],
                "include": r"/faculty/profile/",
                "render": False,
                "selectors": {"name": "h1", "title": "p.faculty-title",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff\b"},
                "cap": 200,
            },
        },
        # --- Kellogg School of Management (JSON API harvest, static seed) ---
        # The faculty directory is an ASP.NET app backed by a clean JSON API
        # (/api/facultylisting) returning name + title (rank + area) + profile URL
        # for all ~363 faculty. Harvested once to a static seed; json_dir file +
        # ladder keeps the professoriate (drops adjuncts/emeriti/lecturers/visiting).
        # No email on the listing → name + rank + link. Regenerate: kellogg_harvest.py.
        {
            "short": "KELLOGG", "name": "Kellogg School of Management",
            "majors": ["Management", "Finance", "Marketing", "Accounting",
                       "Managerial Economics", "Operations", "Strategy",
                       "Management & Organizations"],
            "directory_url": "https://www.kellogg.northwestern.edu/academics-research/faculty-directory/",
            "json_dir": {
                "file": "data/faculty_seeds/nu_kellogg.json",
                "name_fields": ["name"], "title_field": "title",
                "email_field": "email", "link_field": "url",
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\badjunct|\bemerit|\blecturer|\bvisiting"},
            },
        },
        # --- Feinberg School of Medicine (harvested academic professoriate, seed) ---
        # feinberg.northwestern.edu/faculty-profiles enumerates 5009 profiles via
        # its sitemap (az/profile.html?xid=N, curl-able). A one-time harvest kept the
        # ~1490 with an academic Professor title (dropping instructors/residents/
        # fellows/lecturers/emeriti), rank + specialty from the .masthead-wrapper.
        # Loaded via json_dir file; profiles carry only a generic dept contact, so
        # name + rank + specialty, no personal email. Regenerate: feinberg_harvest.py.
        {
            "short": "FEINBERG", "name": "Feinberg School of Medicine",
            "majors": ["Medicine", "Neuroscience", "Cell & Developmental Biology",
                       "Pharmacology", "Physiology", "Microbiology-Immunology",
                       "Biochemistry", "Cancer Biology", "Preventive Medicine"],
            "directory_url": "https://www.feinberg.northwestern.edu/faculty-profiles/",
            "json_dir": {
                "file": "data/faculty_seeds/nu_feinberg.json",
                "name_fields": ["name"], "title_field": "title",
                "email_field": "email", "link_field": "url",
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
