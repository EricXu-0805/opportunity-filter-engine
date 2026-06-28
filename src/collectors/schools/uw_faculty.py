"""University of Washington faculty config (via the faculty_graph engine).

Unlike Michigan (whose directories are Cloudflare-walled, so it ships a curated
hand-verified set), UW's department directories are server-rendered and
scrapable, so this config is scrape-first: each department carries a ``scrape``
block (directory URL + CSS selectors) and deep mode lands real, current faculty
live. No curated seed list to hand-maintain.

Two directory shapes on campus:
  * **ECE** uses the College-of-Engineering ``stafftemplate`` card, which exposes
    research interests + a mailto inline — so its faculty land fully keyworded
    in one pass (UIUC-level richness).
  * **The College of Arts & Sciences departments** (Physics, Chemistry,
    Mathematics, Astronomy, Economics, Linguistics, Geography, History,
    Political Science, Sociology, Philosophy, English, Anthropology)
    share a Drupal "Views" directory that lists name + job title + email but not
    research areas, so those faculty land as keyword-light cold-email targets
    (department majors drive matching; per-profile research enrichment is a
    deferred follow-up — the page interest sections are inconsistent across
    departments and risk nav-menu pollution, so accuracy comes first).

Departments behind a JS facultyfinder app (most of the College of Engineering)
or a client-rendered list (the Allen School) are intentionally omitted — a
stdlib scraper lands zero there; they need the headless-browser path.

Single source ("uw_faculty") across departments (the UIUC model); the
department rides each record's ``department`` field, ids namespaced by
department short-code. Audience "unknown" — cross-school openness is per-prof.
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Drupal "Views" directory selectors (UW College of Arts & Sciences).
_CAS_SELECTORS = {
    "card": "div.views-row",
    "name": ".views-field-title a",
    "link": ".views-field-title a",
    "title": ".views-field-field-job-title .field-content",
    "email": ".views-field-field-email a",
}


def _cas(short: str, name: str, majors: list[str], url: str) -> dict:
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _CAS_SELECTORS},
    }


# College of Engineering "facultyfinder" — a server-rendered table (the JS path
# is just a wrapper). ``?page_size=300`` returns all rows in one request; the
# name is inverted ("Last, First"), research areas are per-area list items, and
# courtesy appointments in other departments mean a whole-cell rank drop would
# over-prune, so we keep any "Professor" row and only drop emeriti.
def _ff(short: str, name: str, majors: list[str], host: str) -> dict:
    url = f"https://{host}/facultyfinder?page_size=300"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "name_flip": True,
                       "selectors": {"card": "table#results tbody tr",
                                     "name": "td:nth-child(2) b a",
                                     "link": "td:nth-child(2) b a",
                                     "title": "td:nth-child(3)",
                                     "email": "td:nth-child(2) a[href^='mailto:']",
                                     "research_items": "td:nth-child(4) li"},
                       "ladder_filter": {"require": r"professor", "drop": r"emerit"}}}


SCHOOL: dict = {
    "school_slug": "uw",
    "source": "uw_faculty",
    "organization": "University of Washington",
    "location": "Seattle, WA",
    "id_prefix": "uw",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Washington) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "ECE",
            "name": "Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering"],
            "directory_url": "https://www.ece.uw.edu/faculty/",
            "scrape": {
                "url": "https://www.ece.uw.edu/faculty/",
                "selectors": {
                    "card": ".stafftemplate--entry",
                    "name": ".stafftemplate--name a",
                    "link": ".stafftemplate--name a",
                    "title": ".stafftemplate--title",
                    "research": ".stafftemplate--interests",
                    "email": ".stafftemplate--email a",
                },
            },
        },
        _cas("PHYS", "Department of Physics",
             ["Physics", "Applied Physics", "Astrophysics"],
             "https://phys.washington.edu/people/faculty"),
        _cas("CHEM", "Department of Chemistry",
             ["Chemistry", "Biochemistry"],
             "https://chem.washington.edu/people/faculty"),
        _cas("MATH", "Department of Mathematics",
             ["Mathematics", "Applied Mathematics"],
             "https://math.washington.edu/people/faculty"),
        _cas("ASTR", "Department of Astronomy",
             ["Astronomy", "Astrophysics"],
             "https://astro.washington.edu/people/faculty"),
        _cas("ECON", "Department of Economics",
             ["Economics"],
             "https://econ.washington.edu/people/faculty"),
        _cas("LING", "Department of Linguistics",
             ["Linguistics"],
             "https://linguistics.washington.edu/people/faculty"),
        _cas("GEOG", "Department of Geography",
             ["Geography"],
             "https://geography.washington.edu/people/faculty"),
        _cas("HIST", "Department of History",
             ["History"],
             "https://history.washington.edu/people/faculty"),
        _cas("POLS", "Department of Political Science",
             ["Political Science"],
             "https://www.polisci.washington.edu/people/faculty"),
        _cas("SOC", "Department of Sociology",
             ["Sociology"],
             "https://soc.washington.edu/people/faculty"),
        _cas("PHIL", "Department of Philosophy",
             ["Philosophy"],
             "https://phil.washington.edu/people/faculty"),
        _cas("ENGL", "Department of English",
             ["English", "Literature", "Creative Writing"],
             "https://english.washington.edu/people/faculty"),
        _cas("ANTH", "Department of Anthropology",
             ["Anthropology"],
             "https://anthropology.washington.edu/people/faculty"),
        # College of Engineering (facultyfinder, keyworded + emailed).
        _ff("ME", "Department of Mechanical Engineering",
            ["Mechanical Engineering"], "www.me.washington.edu"),
        _ff("AA", "Department of Aeronautics & Astronautics",
            ["Aeronautics & Astronautics", "Aerospace Engineering"], "www.aa.washington.edu"),
        _ff("CHEME", "Department of Chemical Engineering",
            ["Chemical Engineering"], "www.cheme.washington.edu"),
        _ff("CEE", "Department of Civil & Environmental Engineering",
            ["Civil Engineering", "Environmental Engineering"], "www.ce.washington.edu"),
        _ff("MSE", "Department of Materials Science & Engineering",
            ["Materials Science & Engineering"], "www.mse.washington.edu"),
        # Bioengineering — WordPress (Avada) "Core Faculty" portfolio, keyworded.
        {
            "short": "BIOE",
            "name": "Department of Bioengineering",
            "majors": ["Bioengineering", "Biomedical Engineering"],
            "directory_url": "https://bioe.uw.edu/people/faculty/",
            "api": {"type": "wp", "base": "https://bioe.uw.edu",
                    "post_type": "avada_portfolio",
                    "category_include": {"portfolio_category": [170]},
                    "keyword_tax": ["portfolio_category"],
                    "keyword_drop": ["core faculty", "faculty", "adjunct",
                                     "affiliate", "emeritus", "joint"]},
        },
        # Biology — Drupal directory, title-filtered to ladder ranks.
        {
            "short": "BIOL",
            "name": "Department of Biology",
            "majors": ["Biology", "Molecular Biology", "Ecology"],
            "directory_url": "https://biology.washington.edu/people/faculty",
            "scrape": {
                "url": "https://biology.washington.edu/people/faculty",
                "selectors": {"card": "div.directory-item",
                              "name": "h2.directory-item__name a",
                              "link": "h2.directory-item__name a",
                              "title": "strong.directory-item__title",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"professor",
                                  "drop": r"emerit|adjunct|affiliat|teaching|acting|visiting"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
