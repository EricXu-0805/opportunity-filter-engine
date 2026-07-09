"""Johns Hopkins University faculty config (via the faculty_graph engine).

The Krieger School of Arts & Sciences serves its entire faculty from one
Cloudflare-walled TablePress table (``#tablepress-54`` at
krieger.jhu.edu/people/faculty-directory/) — Name / Department / Title / public
email, ~836 rows, every row emailed. A headless Chromium session clears the
Cloudflare challenge and the DataTables JS API returns all rows; the engine's
``krieger_table`` source (``faculty_graph._fetch_krieger_table``) fetches the
table once and slices it per department. Records land name + rank + email + dept
(no research keywords on the table — like Duke Trinity / UCSD bare link-lists).

Whiting School of Engineering departments are NOT in that table — most run a
shared Cloudflare-walled WordPress ``.entity`` card theme (name + rank + public
email on the listing), wired via the ``_wse`` helper below; Biomedical
Engineering carries its own ``.zn-*`` theme inline. Carey Business School has no
scrapeable listing (JS grid behind Cloudflare) so it uses the ``sitemap`` source
(sitemap enumerates every profile; each is rendered for name + rank + email).
School of Medicine + Bloomberg Public Health remain a follow-up.

Single source ("jhu_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# The KSAS directory mixes ladder faculty with lecturers, research scientists,
# and emeriti — keep any professorial rank (incl. Research/Teaching Professor),
# drop the rest.
_KT_LADDER = {"require": r"\bprof",
              "drop": (r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff|scientist"
                       r"|scholar|instructor|postdoc|\bfellow")}


def _kt(short: str, name: str, majors: list[str], department: str) -> dict:
    """One KSAS department, sliced from the shared Krieger directory table by its
    exact Department-column string."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": faculty_graph._KRIEGER_URL,
            "krieger_table": {"department": department, "ladder_filter": _KT_LADDER}}


# Whiting School of Engineering department sites run a shared WordPress "entity"
# card theme: name + profile link in ``.entity_name a``, rank in ``.entity_title``,
# and a public ``mailto:`` on the listing itself — so a single render pass lands
# name + title + email (no per-profile enrichment). Each dept lives at
# engineering.jhu.edu/<slug>/faculty/ (Computer Science on its own cs.jhu.edu
# subdomain). All are Cloudflare-walled, so ``render`` clears the challenge.
_WSE_SEL = {"card": ".entity", "name": ".entity_name a", "link": ".entity_name a",
            "title": ".entity_title", "email": "a[href^='mailto:']"}
_WSE_LADDER = {"require": r"\bprofessor\b",
               "drop": (r"\bemerit|\blecturer|\bresearch scientist|\bteaching prof"
                        r"|\badjunct|\bvisiting|\bstaff\b|\bpostdoc|\bfellow\b")}


def _wse(short: str, name: str, majors: list[str], url: str) -> dict:
    """One Whiting dept, scraped from its ``.entity`` faculty listing (render)."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "render": True, "selectors": _WSE_SEL,
                       "ladder_filter": _WSE_LADDER}}


SCHOOL: dict = {
    "school_slug": "jhu",
    "source": "jhu_faculty",
    "organization": "Johns Hopkins University",
    "location": "Baltimore, MD",
    "id_prefix": "jhu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Johns Hopkins University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # --- Krieger School of Arts & Sciences (shared directory table) ---
        _kt("BIO", "Department of Biology", ["Biology"], "Biology"),
        _kt("CHEM", "Department of Chemistry", ["Chemistry"], "Chemistry"),
        _kt("PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astronomy"], "Physics and Astronomy"),
        _kt("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"], "Mathematics"),
        _kt("BIOPHYS", "Thomas C. Jenkins Department of Biophysics",
            ["Biophysics"], "Biophysics"),
        _kt("COGSCI", "Department of Cognitive Science",
            ["Cognitive Science"], "Cognitive Science"),
        _kt("EPS", "Department of Earth and Planetary Sciences",
            ["Earth Sciences", "Planetary Science"], "Earth and Planetary Science"),
        _kt("ECON", "Department of Economics", ["Economics"], "Economics"),
        _kt("ENGL", "Department of English", ["English", "Literature"], "English"),
        _kt("HIST", "Department of History", ["History"], "History"),
        _kt("HART", "Department of History of Art",
            ["History of Art", "Art History"], "History of Art"),
        _kt("HOS", "Department of History of Science and Technology",
            ["History of Science"], "History of Science"),
        _kt("PHIL", "Department of Philosophy", ["Philosophy"], "Philosophy"),
        _kt("POLS", "Department of Political Science",
            ["Political Science"], "Political Science"),
        _kt("PBS", "Department of Psychological and Brain Sciences",
            ["Psychology", "Neuroscience"], "Psychological and Brain Sciences"),
        _kt("SOC", "Department of Sociology", ["Sociology"], "Sociology"),
        _kt("ANTH", "Department of Anthropology", ["Anthropology"], "Anthropology"),
        _kt("CLAS", "Department of Classics", ["Classics"], "Classics"),
        _kt("NES", "Department of Near Eastern Studies",
            ["Near Eastern Studies"], "Near Eastern Studies"),
        _kt("MLL", "Department of Modern Languages and Literatures",
            ["German", "French", "Italian", "Spanish"],
            "Modern Languages and Literatures"),
        _kt("WRIT", "The Writing Seminars",
            ["Creative Writing", "Writing Seminars"], "Writing Seminars"),
        _kt("NEURO", "Solomon H. Snyder Department of Neuroscience",
            ["Neuroscience"], "Neuroscience"),
        # --- Whiting School of Engineering (shared .entity theme, render) ---
        _wse("WSE-CS", "Department of Computer Science", ["Computer Science"],
             "https://www.cs.jhu.edu/faculty/"),
        _wse("WSE-ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://engineering.jhu.edu/ece/faculty/"),
        _wse("WSE-MSE", "Department of Materials Science and Engineering",
             ["Materials Science"], "https://engineering.jhu.edu/materials/faculty/"),
        _wse("WSE-AMS", "Department of Applied Mathematics and Statistics",
             ["Applied Mathematics", "Statistics"],
             "https://engineering.jhu.edu/ams/faculty/"),
        _wse("WSE-CEE", "Department of Civil and Systems Engineering",
             ["Civil Engineering", "Systems Engineering"],
             "https://engineering.jhu.edu/civil/faculty/"),
        _wse("WSE-EHE", "Department of Environmental Health and Engineering",
             ["Environmental Engineering", "Environmental Health"],
             "https://engineering.jhu.edu/ehe/faculty/"),
        _wse("WSE-CHEMBE", "Department of Chemical and Biomolecular Engineering",
             ["Chemical Engineering", "Biomolecular Engineering"],
             "https://engineering.jhu.edu/chembe/faculty/"),
        _wse("WSE-ME", "Department of Mechanical Engineering",
             ["Mechanical Engineering"],
             "https://engineering.jhu.edu/mechanical-engineering/faculty/"),
        # Biomedical Engineering runs its own ``.zn-*`` theme on a more aggressively
        # Cloudflare-walled subdomain (bme.jhu.edu) — a longer render settle lets the
        # challenge clear before the first card check.
        {
            "short": "WSE-BME", "name": "Department of Biomedical Engineering",
            "majors": ["Biomedical Engineering"],
            "directory_url": "https://www.bme.jhu.edu/faculty/",
            "scrape": {
                "url": "https://www.bme.jhu.edu/faculty/",
                "render": True, "render_settle": 8000,
                "selectors": {
                    "card": ".zn-faculty-profile", "name": "a.zn-faculty-link",
                    "link": "a.zn-faculty-link", "title": ".zn-position",
                    "email": "a.zn-faculty-email[href^='mailto:']",
                },
                "ladder_filter": _WSE_LADDER,
            },
        },
        # --- Carey Business School (sitemap-enumerated profiles) ---
        # The directory is a JS grid behind Cloudflare with no scrapeable listing,
        # but the sitemap enumerates every /faculty/faculty-directory/<slug> profile.
        # Profiles are Cloudflare-walled (render): h1 name, p.fac-subhead rank,
        # public mailto. Keeps professorial faculty (incl. Professor of Practice).
        {
            "short": "CAREY", "name": "Carey Business School",
            "majors": ["Business Administration", "Finance", "Marketing",
                       "Management", "Business Analytics", "Health Care Management"],
            "directory_url": "https://carey.jhu.edu/faculty/faculty-directory",
            "sitemap": {
                "sitemaps": ["https://carey.jhu.edu/sitemap.xml"],
                "include": r"/faculty/faculty-directory/[^/]+$",
                "render": True,
                "selectors": {"name": "h1", "title": "p.fac-subhead",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff\b"},
                "cap": 320,
            },
        },
        # --- School of Education (paginated card listing + profile_enrich) ---
        # /directory/ paginates at /directory/page/N/ (8 pages); each card has
        # name (h2.card_bio_name) + rank (p.card_bio_title) + profile link, so a
        # rendered paginated scrape lands name+rank and profile_enrich (render)
        # recovers the email the listing omits.
        {
            "short": "SOE", "name": "School of Education",
            "majors": ["Education", "Teaching", "Educational Leadership",
                       "Counseling", "Special Education"],
            "directory_url": "https://education.jhu.edu/directory/",
            "scrape": {
                "url": "https://education.jhu.edu/directory/",
                "render": True, "render_settle": 9000,
                "selectors": {"card": "div.card_bio_header", "name": "h2.card_bio_name",
                              "link": "a.card_bio_name_link", "title": "p.card_bio_title"},
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 8},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\blecturer|\badjunct|\bvisiting|\bstaff\b"},
                "profile_enrich": {"always": True, "render": True,
                                   "email_selector": "a[href^='mailto:']"},
            },
        },
        # --- Bloomberg School of Public Health (sitemap, Turnstile, capped) ---
        # publichealth.jhu.edu is Cloudflare-Turnstile-walled; its sitemap pages
        # 6-7 enumerate ~2000 /faculty/<id>/<slug> profiles. Each renders (long
        # settle clears Turnstile on the CI datacenter IP): h1 name, ``h1 + div``
        # rank (drops emeriti), public mailto. Capped for refresh-time sanity —
        # the professorial subset that fits the cap, not the full 2000.
        {
            "short": "BSPH", "name": "Bloomberg School of Public Health",
            "majors": ["Public Health", "Epidemiology", "Biostatistics",
                       "Environmental Health", "Health Policy", "Mental Health",
                       "International Health", "Molecular Microbiology"],
            "directory_url": "https://publichealth.jhu.edu/faculty/directory/list",
            "sitemap": {
                "sitemap_pages": ("https://publichealth.jhu.edu/sitemap.xml?page={n}", 6, 7),
                "include": r"publichealth\.jhu\.edu/faculty/\d+/",
                "render": True, "render_settle": 9000,
                "selectors": {"name": "h1", "title": "h1 + div",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": (r"\bemerit|\badjunct|\bvisiting|\blecturer"
                                           r"|scientist|scholar|\bfellow\b")},
                "cap": 300,
            },
        },
        # --- School of Medicine (harvested academic professoriate, static seed) ---
        # profiles.hopkinsmedicine.org lists 8601 clinical providers (curl-able, no
        # Turnstile). A one-time local harvest kept the ~2905 with an academic
        # "Professor" title (dropping residents/fellows/clinical-instructors/DNPs)
        # and committed them to a seed JSON. Loaded via json_dir file (no re-render
        # each refresh). Clinical profiles carry no public email → name+rank only;
        # specialty rides the title. See scripts/harvest for regeneration.
        {
            "short": "SOM", "name": "School of Medicine",
            "majors": ["Medicine", "Neuroscience", "Cell Biology", "Pharmacology",
                       "Physiology", "Biological Chemistry", "Immunology",
                       "Molecular Biology and Genetics", "Oncology", "Public Health"],
            "directory_url": "https://profiles.hopkinsmedicine.org/",
            "json_dir": {
                "file": "data/faculty_seeds/jhu_som.json",
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
