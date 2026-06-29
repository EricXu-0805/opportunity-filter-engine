"""Stanford University faculty config (via the faculty_graph engine).

Scrape-first, like UW/GT — UIUC-parity coverage across all seven schools, each
on a server-rendered directory (Stanford Profiles' CAP API is auth-gated, so we
scrape the dept pages directly):

  * **School of Engineering** depts share a "stanford-person" node template
    (``.node.stanford-person.node-title`` → ``h3 a``) — name + profile link
    only. EE is a server-rendered "orglist" Views grid (paginated, keyworded by
    research area); ICME's advising-faculty page is link-filtered to its core PIs.
  * **Humanities & Sciences** depts render a "Views" grid of ``div.hb-card``
    whose ``.views-field-field-hs-person-research`` lists each research area as
    its own taxonomy link — so the sciences land fully keyworded at UIUC parity;
    Psychology's page is section-filtered to the Regular ladder (drops the
    emeriti + courtesy sections).
  * **Doerr Sustainability, Education, Medicine basic-science** depts each use
    their own server-rendered grid; **Law** is a WordPress REST ``person`` type.

GSB is left out (its directory WAFs the scraper with a 403); the CAP-only
Genetics / Earth-Science / FGSS pages and the curated-only Religious Studies /
AAAS pages likewise stay deferred.

Single source ("stanford_faculty"); department rides each record's
``department``, ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Shared Stanford School of Engineering "stanford-person" directory selectors.
_SU_PERSON = {
    "card": ".node.stanford-person.node-title",
    "name": "h3 a",
    "link": "h3 a",
}

# Humanities & Sciences "Views" grid: research areas are per-area taxonomy links.
_HS_RESEARCH = ".views-field-field-hs-person-research a"


def _su(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, "selectors": _SU_PERSON}}


def _hb(short: str, name: str, majors: list[str], url: str, *,
        card: str = "div.hb-card", name_sel: str = ".views-field-title a",
        ladder_filter: dict | None = None) -> dict:
    scrape = {"url": url, "selectors": {
        "card": card, "name": name_sel, "link": name_sel,
        "title": ".views-field-field-hs-person-title",
        "research_items": _HS_RESEARCH,
    }}
    if ladder_filter:
        scrape["ladder_filter"] = ladder_filter
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "stanford",
    "source": "stanford_faculty",
    "organization": "Stanford University",
    "location": "Stanford, CA",
    "id_prefix": "stanford",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Stanford University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        _su("ME", "Department of Mechanical Engineering",
            ["Mechanical Engineering"], "https://me.stanford.edu/people/faculty"),
        _su("BIOE", "Department of Bioengineering",
            ["Bioengineering"], "https://bioengineering.stanford.edu/people/faculty"),
        _su("AA", "Department of Aeronautics & Astronautics",
            ["Aeronautics & Astronautics", "Aerospace Engineering"], "https://aa.stanford.edu/people/faculty"),
        _su("MSE", "Department of Materials Science & Engineering",
            ["Materials Science & Engineering"], "https://mse.stanford.edu/people/faculty"),
        _su("CHEME", "Department of Chemical Engineering",
            ["Chemical Engineering"], "https://cheme.stanford.edu/people/faculty"),
        _su("CEE", "Department of Civil & Environmental Engineering",
            ["Civil Engineering", "Environmental Engineering"],
            "https://cee.stanford.edu/people/faculty"),
        {"short": "CS", "name": "Department of Computer Science",
         "majors": ["Computer Science"],
         "directory_url": "https://www.cs.stanford.edu/people/faculty",
         "scrape": {"url": "https://www.cs.stanford.edu/people/faculty",
                    "selectors": {"card": "article.su-card", "name": "a", "link": "a"}}},
        _hb("PHYSICS", "Department of Physics", ["Physics"],
            "https://physics.stanford.edu/people/faculty"),
        _hb("STATS", "Department of Statistics", ["Statistics", "Data Science"],
            "https://statistics.stanford.edu/people/faculty",
            name_sel=".hb-card__title h3 a"),
        _hb("CHEM", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.stanford.edu/people/faculty", card="div.hb-table-row",
            name_sel="a[href*='/people/']"),
        _hb("MATH", "Department of Mathematics", ["Mathematics"],
            "https://mathematics.stanford.edu/people/faculty-lecturers",
            ladder_filter={"require": r"professor", "drop": r"emerit|adjunct|lecturer|teaching"}),
        # --- Full-school coverage (Engineering extras, H&S, Doerr, GSE, Law, Medicine) ---
        {'short': 'EE',
         'name': 'Department of Electrical Engineering',
         'majors': ['Electrical Engineering'],
         'directory_url': 'https://ee.stanford.edu/people/faculty',
         'scrape': {'url': 'https://ee.stanford.edu/people/faculty',
                    'selectors': {'card': '.orglist__row',
                                  'name': '.orglist__display-name a',
                                  'link': '.orglist__display-name a',
                                  'title': '.orglist__person-title',
                                  'research_items': '.orglist__area-link'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|teaching|visiting|acting|courtesy'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 14}}},
        {'short': 'MSANDE',
         'name': 'Department of Management Science & Engineering',
         'majors': ['Management Science & Engineering'],
         'directory_url': 'https://msande.stanford.edu/people/faculty',
         'scrape': {'url': 'https://msande.stanford.edu/people/faculty',
                    'selectors': {'card': '.node.stanford-person.node-title',
                                  'name': 'h3 a',
                                  'link': 'h3 a'}}},
        {'short': 'ICME',
         'name': 'Institute for Computational & Mathematical Engineering',
         'majors': ['Computational & Mathematical Engineering'],
         'directory_url': 'https://icme.stanford.edu/icme-advising-faculty',
         'scrape': {'url': 'https://icme.stanford.edu/icme-advising-faculty',
                    'selectors': {'card': 'article.su-card', 'name': 'a', 'link': 'a'},
                    'link_filter': 'profiles\\.stanford\\.edu'}},
        {'short': 'ECON',
         'name': 'Department of Economics',
         'majors': ['Economics'],
         'directory_url': 'https://economics.stanford.edu/people/faculty',
         'scrape': {'url': 'https://economics.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a'}}},
        {'short': 'POLISCI',
         'name': 'Department of Political Science',
         'majors': ['Political Science'],
         'directory_url': 'https://politicalscience.stanford.edu/people/faculty',
         'scrape': {'url': 'https://politicalscience.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title h3',
                                  'link': '.hb-card__title h3 a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research_items': '.views-field-field-hs-person-research a',
                                  'email': '.views-field-field-hs-person-email a'},
                    'ladder_filter': {'drop': 'emerit'}}},
        {'short': 'SOC',
         'name': 'Department of Sociology',
         'majors': ['Sociology'],
         'directory_url': 'https://sociology.stanford.edu/people/faculty',
         'scrape': {'url': 'https://sociology.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title h2',
                                  'link': '.hb-card__title h2 a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research': '.views-field-custm-area-s-of-specialization '
                                              '.field-content',
                                  'email': '.views-field-field-hs-person-email a'},
                    'ladder_filter': {'drop': 'emerit'}}},
        {'short': 'PSYCH',
         'name': 'Department of Psychology',
         'majors': ['Psychology'],
         'directory_url': 'https://psychology.stanford.edu/people/faculty',
         'scrape': {'url': 'https://psychology.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a',
                                  'research_items': '.views-field-field-hs-person-research a'},
                    'section_filter': {'include': '^Regular$', 'heading': 'h2'}}},
        {'short': 'ANTHRO',
         'name': 'Department of Anthropology',
         'majors': ['Anthropology'],
         'directory_url': 'https://anthropology.stanford.edu/people/faculty',
         'scrape': {'url': 'https://anthropology.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title h3',
                                  'link': '.hb-card__title h3 a',
                                  'title': '.views-field-custm-faculty-type .field-content',
                                  'research_items': '.views-field-field-hs-person-research a'},
                    'ladder_filter': {'drop': 'emerit|lecturer|teaching|adjunct'}}},
        {'short': 'LING',
         'name': 'Department of Linguistics',
         'majors': ['Linguistics'],
         'directory_url': 'https://linguistics.stanford.edu/people/faculty',
         'scrape': {'url': 'https://linguistics.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title h3',
                                  'link': '.hb-card__title h3 a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research_items': '.views-field-field-hs-person-research a',
                                  'email': '.views-field-field-hs-person-email a'},
                    'section_filter': {'include': '^Core Faculty$', 'heading': 'h2'}}},
        {'short': 'COMM',
         'name': 'Department of Communication',
         'majors': ['Communication'],
         'directory_url': 'https://comm.stanford.edu/people/faculty',
         'scrape': {'url': 'https://comm.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.su-wysiwyg-text',
                                  'name': 'h2',
                                  'link': 'a.su-button',
                                  'title': 'p',
                                  'email': "a[href^='mailto:']",
                                  'title_strip_after': '\\b(?:Director|Vice '
                                                       'Provost|\\d{3}[.\\-]|McClatchy|Rm\\.|www\\.|http|[a-z]+\\d*@)'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|lecturer|visiting|practice|professional|in '
                                              'residence|teaching|adjunct|courtesy'}}},
        {'short': 'ENGLISH',
         'name': 'Department of English',
         'majors': ['English'],
         'directory_url': 'https://english.stanford.edu/people/faculty',
         'scrape': {'url': 'https://english.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title a',
                                  'link': '.hb-card__title a',
                                  'research_items': '.views-field-field-hs-person-research a'}}},
        {'short': 'HISTORY',
         'name': 'Department of History',
         'majors': ['History'],
         'directory_url': 'https://history.stanford.edu/people/faculty',
         'scrape': {'url': 'https://history.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a',
                                  'research_items': '.views-field-field-hs-person-research a'}}},
        {'short': 'PHIL',
         'name': 'Department of Philosophy',
         'majors': ['Philosophy'],
         'directory_url': 'https://philosophy.stanford.edu/people/faculty',
         'scrape': {'url': 'https://philosophy.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title a',
                                  'link': '.hb-card__title a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research_items': '.views-field-field-hs-person-research a'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|emerita|\\blecturer\\b|\\(teaching\\)|adjunct|visiting '
                                              'professor|postdoc|fellow|professor of '
                                              'psychology|professor of political science|professor of '
                                              'education|dean of the school|hammond professor of '
                                              'french'}}},
        {'short': 'CLASSICS',
         'name': 'Department of Classics',
         'majors': ['Classics'],
         'directory_url': 'https://classics.stanford.edu/people/faculty',
         'scrape': {'url': 'https://classics.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research_items': '.views-field-field-hs-person-research a'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|lecturer|\\(teaching\\)|adjunct|visiting '
                                              'professor|postdoc|college fellow|research fellow|research '
                                              'scholar|specialist|\\bmanager\\b|coordinator|director of '
                                              'finance|administration|operations'}}},
        {'short': 'EALC',
         'name': 'Department of East Asian Languages and Cultures',
         'majors': ['East Asian Languages and Cultures'],
         'directory_url': 'https://ealc.stanford.edu/people/faculty',
         'scrape': {'url': 'https://ealc.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title a',
                                  'link': '.hb-card__title a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research_items': '.views-field-field-hs-person-research a'},
                    'ladder_filter': {'drop': 'emerit|lecturer|adjunct|visiting|postdoc|recalled'}}},
        {'short': 'FRENCHITAL',
         'name': 'Department of French & Italian',
         'majors': ['French', 'Italian'],
         'directory_url': 'https://dlcl.stanford.edu/people/faculty',
         'scrape': {'url': 'https://dlcl.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card:has(.views-field-custm-department-s- '
                                          "a[href*='french-and-italian'])",
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a'}}},
        {'short': 'COMPLIT',
         'name': 'Department of Comparative Literature',
         'majors': ['Comparative Literature'],
         'directory_url': 'https://dlcl.stanford.edu/people/faculty',
         'scrape': {'url': 'https://dlcl.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card:has(.views-field-custm-department-s- '
                                          "a[href*='comparative-literature'])",
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a'}}},
        {'short': 'GERMAN',
         'name': 'Department of German Studies',
         'majors': ['German Studies'],
         'directory_url': 'https://dlcl.stanford.edu/people/faculty',
         'scrape': {'url': 'https://dlcl.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card:has(.views-field-custm-department-s- '
                                          "a[href*='german-studies'])",
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a'}}},
        {'short': 'SLAVIC',
         'name': 'Department of Slavic Languages & Literatures',
         'majors': ['Slavic Languages and Literatures'],
         'directory_url': 'https://dlcl.stanford.edu/people/faculty',
         'scrape': {'url': 'https://dlcl.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card:has(.views-field-custm-department-s- '
                                          "a[href*='slavic'])",
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a'}}},
        {'short': 'IBERLAC',
         'name': 'Department of Iberian & Latin American Cultures',
         'majors': ['Iberian and Latin American Cultures'],
         'directory_url': 'https://dlcl.stanford.edu/people/faculty',
         'scrape': {'url': 'https://dlcl.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card:has(.views-field-custm-department-s- '
                                          "a[href*='iberian-and-latin-american'])",
                                  'name': '.views-field-title a',
                                  'link': '.views-field-title a'}}},
        {'short': 'ART',
         'name': 'Department of Art & Art History',
         'majors': ['Art History', 'Art Practice', 'Film and Media Studies'],
         'directory_url': 'https://art.stanford.edu/people/faculty',
         'scrape': {'url': 'https://art.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': 'h3 a',
                                  'link': 'h3 a',
                                  'title': '.views-field-field-hs-person-title',
                                  'research_items': '.views-field-field-hs-person-research a'},
                    'ladder_filter': {'require': 'professor', 'drop': 'emerit|visiting|^lecturer'}}},
        {'short': 'MUSIC',
         'name': 'Department of Music',
         'majors': ['Music', 'Music, Science and Technology'],
         'directory_url': 'https://music.stanford.edu/people/people/faculty',
         'scrape': {'url': 'https://music.stanford.edu/people/people/faculty',
                    'selectors': {'card': 'div.hb-table-row',
                                  'name': 'h3 a',
                                  'link': 'h3 a',
                                  'title': '.views-field-custm-pers-dept-title',
                                  'research_items': '.views-field-field-hs-person-research-1 a'},
                    'ladder_filter': {'require': 'professor',
                                      'drop': 'emerit|adjunct|lecturer|visiting|artist in residence|by '
                                              'courtesy|collaborative'}}},
        {'short': 'TAPS',
         'name': 'Department of Theater & Performance Studies',
         'majors': ['Theater and Performance Studies'],
         'directory_url': 'https://taps.stanford.edu/people/professors/',
         'scrape': {'url': 'https://taps.stanford.edu/people/professors/',
                    'selectors': {'card': 'h4.qodef-e-title-holder',
                                  'name': '.qodef-e-title',
                                  'link': '.qodef-e-title',
                                  'name_strip': '\\s*\\|.*$'},
                    'section_filter': {'include': '^professors$', 'heading': 'h1'}}},
        {'short': 'BIOLOGY',
         'name': 'Department of Biology',
         'majors': ['Biology'],
         'directory_url': 'https://biology.stanford.edu/people/faculty',
         'scrape': {'url': 'https://biology.stanford.edu/people/faculty',
                    'selectors': {'card': 'div.hb-card',
                                  'name': '.hb-card__title a',
                                  'link': '.hb-card__title a',
                                  'research': '.views-field-field-hs-person-interests .field-content',
                                  'research_items': '.hb-categories a'}}},
        {'short': 'APPHYS',
         'name': 'Department of Applied Physics',
         'majors': ['Applied Physics', 'Physics'],
         'directory_url': 'https://appliedphysics.stanford.edu/people/faculty',
         'scrape': {'url': 'https://appliedphysics.stanford.edu/people/faculty',
                    'selectors': {'card': '.views-row',
                                  'name': '.views-field-view-profile a',
                                  'link': '.views-field-view-profile a'},
                    'section_filter': {'include': '^faculty$', 'heading': 'h2'}}},
        {'short': 'ESYS',
         'name': 'Department of Earth System Science',
         'majors': ['Earth Systems', 'Earth System Science'],
         'directory_url': 'https://earthsystemscience.stanford.edu/faculty/faculty',
         'scrape': {'url': 'https://earthsystemscience.stanford.edu/faculty/faculty',
                    'selectors': {'card': 'ul.su-list-unstyled.grid-container-4 > li',
                                  'name': '.views-field-title h2',
                                  'link': '.views-field-title a',
                                  'title': '.views-field-su-person-full-title'}}},
        {'short': 'ESOS',
         'name': 'Department of Environmental Social Sciences',
         'majors': ['Environmental Social Sciences', 'Earth Systems'],
         'directory_url': 'https://esos.stanford.edu/people',
         'scrape': {'url': 'https://esos.stanford.edu/people',
                    'selectors': {'card': 'ul.su-list-unstyled.grid-container-4 > li',
                                  'name': '.views-field-title h2',
                                  'link': '.views-field-title a',
                                  'title': '.views-field-su-person-full-title'},
                    'name_flip': True}},
        {'short': 'ESE',
         'name': 'Department of Energy Science & Engineering',
         'majors': ['Energy Science & Engineering', 'Energy Resources Engineering'],
         'directory_url': 'https://ese.stanford.edu/people',
         'scrape': {'url': 'https://ese.stanford.edu/people',
                    'selectors': {'card': "a[href*='profiles.stanford.edu']",
                                  'name': ':self',
                                  'link': ':self'},
                    'section_filter': {'include': '^faculty$', 'heading': 'h2'}}},
        {'short': 'EPS',
         'name': 'Department of Earth & Planetary Sciences',
         'majors': ['Earth Systems', 'Geological Sciences', 'Earth & Planetary Sciences'],
         'directory_url': 'https://epsci.stanford.edu/people/faculty',
         'scrape': {'url': 'https://epsci.stanford.edu/people/faculty',
                    'selectors': {'card': 'ul.su-list-unstyled.grid-container-4 > li',
                                  'name': '.views-field-title h2',
                                  'link': '.views-field-title a',
                                  'title': '.views-field-su-person-full-title'}}},
        {'short': 'OCEANS',
         'name': 'Department of Oceans',
         'majors': ['Earth Systems', 'Oceans'],
         'directory_url': 'https://oceans.stanford.edu/people/oceans-department-0/faculty',
         'scrape': {'url': 'https://oceans.stanford.edu/people/oceans-department-0/faculty',
                    'selectors': {'card': 'ul.su-list-unstyled.grid-container-4 > li',
                                  'name': '.views-field-title h2',
                                  'link': '.views-field-title a',
                                  'title': '.views-field-su-person-full-title'}}},
        {'short': 'GEOPHYSICS',
         'name': 'Department of Geophysics',
         'majors': ['Geophysics'],
         'directory_url': 'https://geophysics.stanford.edu/people/people/people/faculty/faculty',
         'scrape': {'url': 'https://geophysics.stanford.edu/people/people/people/faculty/faculty',
                    'selectors': {'card': 'ul.su-list-unstyled.grid-container-4 > li',
                                  'name': '.views-field-title h2',
                                  'link': '.views-field-title a',
                                  'title': '.views-field-su-person-full-title'}}},
        {'short': 'EDUC',
         'name': 'Graduate School of Education',
         'majors': ['Education'],
         'directory_url': 'https://ed.stanford.edu/faculty/profiles',
         'scrape': {'url': 'https://ed.stanford.edu/faculty/profiles',
                    'selectors': {'card': 'article.node--type-faculty',
                                  'name': '.content-title a',
                                  'link': '.content-title a',
                                  'title': '.content-subtitle'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|emerita|courtesy|adjunct|lecturer|practice|\\(research\\)|\\(teaching\\)'}}},
        {'short': 'LAW',
         'name': 'Stanford Law School',
         'majors': ['Law', 'Juris Doctor'],
         'directory_url': 'https://law.stanford.edu/directory/?tax_and_terms=1067',
         'api': {'type': 'wp',
                 'base': 'https://law.stanford.edu',
                 'post_type': 'person',
                 'category_include': {'person_role': [1067]},
                 'category_exclude': {'person_role': [1080]},
                 'keyword_tax': ['expertise'],
                 'keyword_drop': ['Food & Drug Administration']}},
        {'short': 'BIOCHEM',
         'name': 'Department of Biochemistry',
         'majors': ['Biochemistry'],
         'directory_url': 'https://biochemistry.stanford.edu/people/faculty',
         'scrape': {'url': 'https://biochemistry.stanford.edu/people/faculty',
                    'selectors': {'card': '.node.stanford-person.node-title',
                                  'name': 'h3 a',
                                  'link': 'h3 a'}}},
        {'short': 'MCP',
         'name': 'Department of Molecular & Cellular Physiology',
         'majors': ['Molecular & Cellular Physiology', 'Physiology'],
         'directory_url': 'https://mcp.stanford.edu/people/mcp-faculty',
         'scrape': {'url': 'https://mcp.stanford.edu/people/mcp-faculty',
                    'selectors': {'card': '.node.stanford-person.node-title',
                                  'name': 'h3 a',
                                  'link': 'h3 a'}}},
        {'short': 'NEURO',
         'name': 'Department of Neurobiology',
         'majors': ['Neurobiology', 'Biology'],
         'directory_url': 'https://neurobiology.stanford.edu/who-we-are/faculty.html',
         'scrape': {'url': 'https://neurobiology.stanford.edu/who-we-are/faculty.html',
                    'selectors': {'card': '.accordion_content1 div.row',
                                  'name': 'h2.feature-box-main-heading',
                                  'link': "a[href*='/profiles/']",
                                  'title': "a[href*='/profiles/']"}}},
        {'short': 'DEVBIO',
         'name': 'Department of Developmental Biology',
         'majors': ['Developmental Biology', 'Biology'],
         'directory_url': 'https://devbio.stanford.edu/faculty',
         'scrape': {'url': 'https://devbio.stanford.edu/faculty',
                    'selectors': {'card': '.slide', 'name': '.image-slide-title', 'link': 'a'}}},
        {'short': 'STRUCTBIO',
         'name': 'Department of Structural Biology',
         'majors': ['Structural Biology', 'Biophysics'],
         'directory_url': 'https://med.stanford.edu/structuralbio/faculty.html',
         'scrape': {'url': 'https://med.stanford.edu/structuralbio/faculty.html',
                    'selectors': {'card': '#main_panel_builder_panel_0_tabs_content_1 '
                                          'div.adaptiveimage.text-image',
                                  'name': "b a[href*='profiles.stanford.edu/']",
                                  'link': "b a[href*='profiles.stanford.edu/']"}}},
        {'short': 'MICROIMMUNO',
         'name': 'Department of Microbiology & Immunology',
         'majors': ['Microbiology & Immunology', 'Immunology'],
         'directory_url': 'https://med.stanford.edu/microimmuno/faculty.html',
         'scrape': {'url': 'https://med.stanford.edu/microimmuno/faculty.html',
                    'selectors': {'card': 'div.text-image.section',
                                  'name': 'b',
                                  'name_strip': '\\s*\\([^)]*\\)\\s*$',
                                  'link': "a[href*='/profiles/']",
                                  'title': 'b'},
                    'ladder_filter': {'drop': 'emeritus|emerita'}}},
    ],
}


# --- Research-area enrichment -----------------------------------------------
# Each extractor was found by per-template recon and re-verified live through the
# engine. Stanford is harder than peers: its big engineering/science block (ME,
# BioE, MSE, Biochem, CEE, AeroAstro, MS&E, ChemE, MCP) plus CS / ICME / DevBio /
# ESE / Comm / StructBio publish only PROSE bios on-site and no CAP keywords, so
# they stay broad — better broad than fragments. What IS clean:
#   * Physics renders its Hb-theme research taxonomy on the listing CARD.
#   * Education keeps a labelled "Research interests" block on the profile.
#   * Economics + the DLCL languages (Comp Lit, French&Italian) + Applied Physics
#     expose a per-person research-taxonomy field on the profile.
#   * The Earth-sciences departments (ESS, E-SOS, Geological, Oceans, Geophysics)
#     are prose on-site but link to a central Stanford CAP profile whose JSON API
#     carries a clean curated ``keywords`` field — harvested via the gated two-hop
#     ``cap_keywords`` pass.
# (MicroImmuno/Neuro were dropped: their only per-person field is MeSH-style
# publication tags — too noisy to ship as research areas.)
_THROTTLE = 1.5
_CARD_RESEARCH_ITEMS = {
    "PHYSICS": ".views-field-field-hs-person-research ul li a",
}
_PROFILE_ENRICH = {
    "EDUC": {"research_html_re": r'<h2[^>]*>\s*Research interests\s*</h2>\s*<div[^>]*>(.*?)</div>'},
    "ECON": {"research_items_selector": ".field-hs-person-research a"},
    "COMPLIT": {"research_items_selector": "div.views-field-custm-research-interest-s- li > a"},
    "FRENCHITAL": {"research_items_selector": "div.views-field-custm-research-interest-s- li > a"},
    "APPHYS": {"research_items_selector": ".field-research-areas div div"},
    "ESYS": {"cap_keywords": True},
    "ESOS": {"cap_keywords": True},
    "EPS": {"cap_keywords": True},
    "OCEANS": {"cap_keywords": True},
    "GEOPHYSICS": {"cap_keywords": True},
}
for _dept in SCHOOL["departments"]:
    _short = _dept["short"]
    if not _dept.get("scrape"):
        continue
    _ci = _CARD_RESEARCH_ITEMS.get(_short)
    if _ci:
        _dept["scrape"]["selectors"] = {
            **_dept["scrape"].get("selectors", {}), "research_items": _ci}
    _enr = _PROFILE_ENRICH.get(_short)
    if _enr:
        _dept["scrape"].setdefault("profile_enrich", {**_enr, "throttle": _THROTTLE})


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
