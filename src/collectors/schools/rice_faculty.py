"""Rice University faculty config (via the faculty_graph engine).

Rice runs every department site on one shared Drupal 10 platform (theme
``adm_rice``). Faculty rosters are NOT in the server HTML — each page ships an
empty ``<div class="js-profiles" data-tags="...">`` shell that a shared theme
script fills client-side from ONE central JSON endpoint:

    GET https://web-api2.rice.edu/profiles/search?tag=<TAGS>&netid=
    -> {"data": [{fname, lname, title, profile_url, img_url}, ...]}

The theme comma-joins each page's ``data-tags`` (``"Faculty, Computer Science"``
-> ``tag=Faculty,Computer Science``). So one engine source — the ``json_dir``
live-endpoint fetch with ``name_fields=[fname,lname]`` — covers the whole
university; only the per-department ``tag`` differs. Each dept's exact
``data-tags`` was harvested from its live page and the resulting API count
verified (e.g. CS 46, Physics 52, Economics 33). No email/keywords in the
listing JSON; the profile page (profiles.rice.edu/faculty/<slug>) carries them,
recovered later by the profile-enrichment pass.

Single source ("rice_faculty"); department rides each record's ``department``,
ids namespaced by short-code. Audience "unknown".

The prior 406 "deferred" tail was resolved by harvesting the exact ``data-tags``
(the API bypasses the rate-limited HTML page): Psychological Sciences
("Psychology, Faculty"), Modern & Classical Languages ("mclc"), Kinesiology
("kinesiology"), Earth-Environmental-Planetary ("Earth Environmental and
Planetary Sciences, Faculty"), Art History ("art_history, Faculty"), Asian
Studies ("Asian Studies Faculty" — single tag, no comma), Sport Management
("Sport Management, Faculty") — all now wired. Architecture is the one
static-HTML outlier (``div.faculty-member`` scrape).

Also covered outside the shared platform: Visual & Dramatic Arts (on the
web-api2 endpoint, tag ``VADA, Faculty``) and the Jones Graduate School of
Business (its own Sitecore site ``business.rice.edu/faculty`` — static
``article.cc--profile-card-vertical`` cards, paginated ``?page=N``, ROT13-
obfuscated emails so title-only, ladder-filtered to drop pure staff/deans).

Still deferred: Shepherd School of Music (bespoke hand-authored "text-columns"
page — bare ``<a href="/faculty/slug">Name</a>`` under instrument headings, no
card wrapper / no js-profiles / no title element; needs a self-anchor scrape).
"""

from __future__ import annotations

from urllib.parse import quote

from .. import faculty_graph

_API = "https://web-api2.rice.edu/profiles/search"


def _rice(short: str, name: str, majors: list[str], directory_url: str, data_tags: str) -> dict:
    """A Rice department served by the shared web-api2 profiles endpoint.

    ``data_tags`` is the verbatim ``data-tags`` attribute from the dept's live
    faculty page; the theme comma-joins it into the API ``tag`` param.
    """
    tag = ",".join(part.strip() for part in data_tags.split(","))
    url = f"{_API}?tag={quote(tag)}&netid="
    return {"short": short, "name": name, "majors": majors, "directory_url": directory_url,
            "json_dir": {"url": url, "records_key": "data",
                         "name_fields": ["fname", "lname"],
                         "title_field": "title", "link_field": "profile_url"}}


# School of Architecture is the one static-HTML outlier (not the js-profiles API).
_ARCH_SELECTORS = {
    "card": "div.faculty-member",
    "name": ".faculty-info h4 a",
    "link": ".faculty-info h4 a",
    "title": ".job-title",
    "email": "a[href^='mailto:']",
}


SCHOOL: dict = {
    "school_slug": "rice",
    "source": "rice_faculty",
    "organization": "Rice University",
    "location": "Houston, TX",
    "id_prefix": "rice",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Rice University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- George R. Brown School of Engineering & Computing -----------
        _rice("CS", "Department of Computer Science", ["Computer Science"],
              "https://csweb.rice.edu/people/faculty", "Faculty, Computer Science"),
        _rice("MECH", "Department of Mechanical Engineering", ["Mechanical Engineering"],
              "https://mech.rice.edu/people/faculty", "MECH - Faculty"),
        _rice("BIOE", "Department of Bioengineering", ["Bioengineering"],
              "https://bioengineering.rice.edu/people/faculty", "Bioengineering, Faculty"),
        _rice("CHBE", "Department of Chemical & Biomolecular Engineering",
              ["Chemical Engineering", "Biomolecular Engineering"],
              "https://chbe.rice.edu/people/faculty",
              "Chemical and Biomolecular Engineering, Faculty"),
        _rice("CEE", "Department of Civil & Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://cee.rice.edu/people/faculty", "Faculty, Civil and Environmental Engineering"),
        _rice("CMOR", "Computational Applied Mathematics & Operations Research",
              ["Computational & Applied Mathematics", "Operations Research"],
              "https://cmor.rice.edu/people/faculty", "CMOR - Faculty"),
        _rice("MSNE", "Department of Materials Science & Nanoengineering",
              ["Materials Science & NanoEngineering"],
              "https://msne.rice.edu/people/faculty",
              "Materials Science and Nanoengineering, Tenured"),
        _rice("STAT", "Department of Statistics", ["Statistics"],
              "https://statistics.rice.edu/people/faculty", "Statistics, Faculty"),
        # ---- Wiess School of Natural Sciences ----------------------------
        _rice("PHYA", "Department of Physics & Astronomy", ["Physics", "Astronomy"],
              "https://physics.rice.edu/core-faculty", "PHYA Core Faculty"),
        _rice("CHEM", "Department of Chemistry", ["Chemistry"],
              "https://chemistry.rice.edu/people/core-faculty", "chemistry, core faculty"),
        _rice("MATH", "Department of Mathematics", ["Mathematics"],
              "https://math.rice.edu/faculty", "mathematics, Faculty, Core Faculty"),
        _rice("BIOS", "Department of BioSciences", ["Biosciences", "Biology", "Ecology"],
              "https://biosciences.rice.edu/tenure-track-faculty", "Tenured faculty, Biosciences"),
        # ---- School of Social Sciences -----------------------------------
        _rice("ECON", "Department of Economics", ["Economics"],
              "https://economics.rice.edu/faculty", "Economics, Faculty"),
        _rice("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.rice.edu/faculty", "Anthropology, Faculty"),
        _rice("LING", "Department of Linguistics", ["Linguistics"],
              "https://linguistics.rice.edu/faculty", "Linguistics, Faculty"),
        _rice("POLI", "Department of Political Science", ["Political Science"],
              "https://politicalscience.rice.edu/faculty", "Political Science, Faculty"),
        _rice("SOCI", "Department of Sociology", ["Sociology"],
              "https://sociology.rice.edu/faculty", "Sociology, Faculty"),
        # ---- School of Humanities ----------------------------------------
        _rice("ENGL", "Department of English", ["English", "Creative Writing"],
              "https://english.rice.edu/faculty", "English, Core Faculty"),
        _rice("HIST", "Department of History", ["History"],
              "https://history.rice.edu/faculty", "History, Core Faculty"),
        _rice("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.rice.edu/faculty", "Philosophy, Core Faculty"),
        _rice("ECEP", "Department of Electrical & Computer Engineering",
              ["Electrical & Computer Engineering"],
              "https://eceweb.rice.edu/people/faculty", "ECE - Professor"),
        _rice("ECEA", "Department of Electrical & Computer Engineering",
              ["Electrical & Computer Engineering"],
              "https://eceweb.rice.edu/people/faculty", "ECE - Associate Professor"),
        _rice("ECEAP", "Department of Electrical & Computer Engineering",
              ["Electrical & Computer Engineering"],
              "https://eceweb.rice.edu/people/faculty", "ECE - Assistant Professor"),
        _rice("RELI", "Department of Religion", ["Religion", "Religious Studies"],
              "https://reli.rice.edu/faculty", "Religion, Core Faculty"),
        _rice("PSYC", "Department of Psychological Sciences",
              ["Psychology", "Psychological Sciences"],
              "https://psychology.rice.edu/people/faculty", "Psychology, Faculty"),
        _rice("MCLC", "Modern & Classical Languages, Literatures & Cultures",
              ["Modern Languages", "Classical Studies", "French", "German", "Spanish"],
              "https://mclc.rice.edu/people", "mclc"),
        _rice("KINE", "Department of Kinesiology", ["Kinesiology", "Sports Medicine"],
              "https://kinesiology.rice.edu/people/faculty", "kinesiology"),
        _rice("EEPS", "Department of Earth, Environmental & Planetary Sciences",
              ["Earth Science", "Environmental Science", "Planetary Science",
               "Geology", "Geophysics"],
              "https://earthscience.rice.edu/people",
              "Earth Environmental and Planetary Sciences, Faculty"),
        _rice("ARTH", "Department of Art History", ["Art History"],
              "https://arthistory.rice.edu/people", "art_history, Faculty"),
        _rice("ASIA", "Program in Transnational Asian Studies",
              ["Asian Studies", "Transnational Asian Studies"],
              "https://asianstudies.rice.edu/people", "Asian Studies Faculty"),
        _rice("SMGT", "Department of Sport Management",
              ["Sport Management", "Sport Analytics"],
              "https://sport.rice.edu/people", "Sport Management, Faculty"),
        _rice("VADA", "Department of Visual & Dramatic Arts",
              ["Art", "Film", "Theatre", "Visual Arts", "Studio Art"],
              "https://vada.rice.edu/people", "VADA, Faculty"),
        # Jones Graduate School of Business — its own Sitecore platform (NOT the
        # shared web-api2), static server-HTML profile cards, paginated ?page=N.
        # Email is ROT13-obfuscated (no mailto) so ships title-only; ladder-filter
        # drops pure staff/deans without a professorial rank.
        {"short": "JGSB", "name": "Jones Graduate School of Business",
         "majors": ["Business Administration", "Accounting", "Finance", "Marketing",
                    "Management", "Strategy", "Operations Management",
                    "Organizational Behavior", "Entrepreneurship"],
         "directory_url": "https://business.rice.edu/faculty",
         "scrape": {"url": "https://business.rice.edu/faculty",
                    "selectors": {"card": "article.cc--profile-card-vertical",
                                  "name": ".f--cta-title a", "link": ".f--cta-title a",
                                  "title": ".f--text", "email": "a[href^='mailto:']"},
                    "paginate": {"param": "page", "max": 8},
                    "ladder_filter": {"require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
                                      "drop": r"emerit"}}},
        # School of Architecture — static-HTML outlier (div.faculty-member cards).
        {"short": "ARCH", "name": "Rice School of Architecture",
         "majors": ["Architecture", "Architectural Studies"],
         "directory_url": "https://arch.rice.edu/people/faculty",
         "scrape": {"url": "https://arch.rice.edu/people/faculty",
                    "selectors": _ARCH_SELECTORS}},
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
