"""Georgia Tech faculty config (via the faculty_graph engine).

Scrape-first, like UW — UIUC-parity coverage across all six colleges, each via a
department's faculty-only filter URL (verified to yield real ladder faculty, not
staff/affiliates). Most schools are a gatech.edu Drupal directory with a faculty
filter exposed as a query param; the exceptions are noted inline.

  * **College of Computing** — a Drupal ``card-block`` grid: CS (paginated), plus
    Interactive Computing and Computational Science & Engineering.
  * **College of Engineering** — Aerospace, Biomedical (the Coulter GT/Emory
    dept, ``BME Primary Faculty`` filter), Industrial & Systems, Mechanical, plus
    the already-shipped ECE / Civil / Materials / Chemical & Biomolecular.
  * **College of Sciences** — Chemistry, Mathematics, Biological Sciences, Earth
    & Atmospheric Sciences, Physics, Psychology.
  * **Scheller College of Business** — one authoritative ``directory/index.json``
    feed (a ``json_dir`` source), split into its eight academic areas and
    ladder-filtered (drops PhD students / lecturers / emeritus).
  * **College of Design** — Architecture, Building Construction, City & Regional
    Planning, Industrial Design, Music.
  * **Ivan Allen College of Liberal Arts** — Economics, History & Sociology,
    International Affairs, Literature Media & Communication, Public Policy, and
    Modern Languages.

Single source ("gatech_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown" (per-prof openness).
"""

from __future__ import annotations

from .. import faculty_graph


# Scheller College of Business ships its whole roster as one authoritative JSON
# feed; each academic area filters that feed and ladder-filters the titles.
def _scheller(short: str, name: str, majors: list[str], area: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://www.scheller.gatech.edu/directory/",
            "json_dir": {
                "url": "https://www.scheller.gatech.edu/directory/index.json",
                "filter_field": "academic", "filter_value": area,
                "status_field": "status", "status_value": "Faculty",
                "ladder_filter": {"drop": r"emerit|lecturer|of the practice"
                                          r"|academic professional|visiting|instructor|adjunct"}}}


SCHOOL: dict = {
    "school_slug": "gatech",
    "source": "gatech_faculty",
    "organization": "Georgia Institute of Technology",
    "location": "Atlanta, GA",
    "id_prefix": "gatech",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Georgia Tech) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "College of Computing",
            "majors": ["Computer Science", "Computer Engineering", "Computational Media", "Cybersecurity"],
            "directory_url": "https://www.cc.gatech.edu/people/faculty",
            "scrape": {
                "url": "https://www.cc.gatech.edu/people/faculty",
                "selectors": {
                    "card": ".card-block",
                    "name": ".card-block__title a",
                    "link": ".card-block__title a",
                    "title": ".card-block__subtitle",
                },
                "paginate": {"param": "page", "start": 1, "max": 22},
                # The CoC listing carries name/title only; each profile keeps a
                # "<strong>Research Areas:</strong> A; B; C</p>" block (gated
                # per-profile enrich, OFE_ENRICH_PROFILES=1). Profiles without the
                # block stay broad — no prose-scraping, no junk.
                "profile_enrich": {
                    "research_html_re": r"Research Areas?:?\s*</strong>(.*?)</p>",
                },
            },
        },
        {
            "short": "CHEM",
            "name": "School of Chemistry and Biochemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://chemistry.gatech.edu/faculty/academic-faculty-PI",
            "scrape": {
                "url": "https://chemistry.gatech.edu/faculty/academic-faculty-PI",
                "selectors": {"card": "div.person", "name": "h3",
                              "link": "a[href*='/people/']"},
            },
        },
        {
            "short": "MATH",
            "name": "School of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics"],
            "directory_url": "https://math.gatech.edu/people?field_job_type_tid=11",
            "scrape": {
                "url": "https://math.gatech.edu/people?field_job_type_tid=11",
                "selectors": {"card": "tr", "name": "td a", "link": "td a"},
            },
            # The per-profile pages carry no research field, but a dedicated
            # aggregator page lists each professor's areas keyed by /people/<slug>.
            "research_join": {
                "url": "https://math.gatech.edu/faculty-research-interests",
                "item_re": r'<li><a href="[^"]*/people/(?P<key>[^"]+)"[^>]*>'
                           r"(?P<name>[^<]+)</a>\s*(?:&nbsp;)*\s*&mdash;\s*"
                           r"(?:&nbsp;)*\s*(?P<areas>[^<]+)</li>",
                "key": "slug",
            },
        },
        {
            "short": "MSE",
            "name": "School of Materials Science and Engineering",
            "majors": ["Materials Science and Engineering", "Materials Science"],
            "directory_url": "https://www.mse.gatech.edu/people?field_personnel_group_value_1=1FTE",
            "scrape": {
                "url": "https://www.mse.gatech.edu/people?field_personnel_group_value_1=1FTE",
                "selectors": {"card": ".views-row", "name": "a[href*='/people/']",
                              "link": "a[href*='/people/']", "email": "a[href^='mailto:']"},
            },
        },
        {
            "short": "ECE",
            "name": "School of Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://ece.gatech.edu/directory?field_person_groups_target_id=2323",
            "scrape": {
                "url": "https://ece.gatech.edu/directory?field_person_groups_target_id=2323",
                "selectors": {"card": ".views-row", "name": "a[href^='/directory/']",
                              "link": "a[href^='/directory/']",
                              "name_strip": r"^Learn more about\s+"},
                "ladder_filter": {"drop": r"emerit|adjunct|affiliat|of the practice"
                                          r"|academic professional|research (scientist|engineer)"},
                "paginate": {"param": "page", "start": 1, "max": 8},
            },
        },
        {
            "short": "CEE",
            "name": "School of Civil & Environmental Engineering",
            "majors": ["Civil Engineering", "Environmental Engineering"],
            "directory_url": "https://ce.gatech.edu/people?field_person_faculty_type_target_id=58",
            "scrape": {
                "url": "https://ce.gatech.edu/people?field_person_faculty_type_target_id=58",
                "selectors": {"card": ".views-row", "name": "a[href*='/directory/person/']",
                              "link": "a[href*='/directory/person/']",
                              "name_strip": r"^Learn more about\s+"},
                "ladder_filter": {"drop": r"emerit|adjunct|affiliat|of the practice"
                                          r"|academic professional|research (scientist|engineer)"},
                "paginate": {"param": "page", "start": 1, "max": 8},
            },
        },
        {
            "short": "CHBE",
            "name": "School of Chemical & Biomolecular Engineering",
            "majors": ["Chemical Engineering", "Biomolecular Engineering"],
            "directory_url": "https://chbe.gatech.edu/directory1?field_person_category_target_id=1",
            "scrape": {
                "url": "https://chbe.gatech.edu/directory1?field_person_category_target_id=1",
                "selectors": {"card": ".views-row", "name": "a.dir_link",
                              "link": "a.dir_link",
                              "title": ".field--name-field-person-job-title-s-"},
                "ladder_filter": {"drop": r"emerit|adjunct|affiliat|of the practice"
                                          r"|academic professional"},
            },
        },
        # --- Full-school coverage (CoC/Engineering/Sciences extras, Design, Liberal Arts) ---
        {'short': 'IC',
         'name': 'School of Interactive Computing',
         'majors': ['Computer Science', 'Computational Media', 'Human-Computer Interaction'],
         'directory_url': 'https://ic.gatech.edu/people/faculty',
         'scrape': {'url': 'https://ic.gatech.edu/people/faculty',
                    'selectors': {'card': '.card-block',
                                  'name': '.card-block__title a',
                                  'link': '.card-block__title a',
                                  'title': '.card-block__subtitle'},
                    'ladder_filter': {'drop': 'emerit|in memoriam|of the practice|principal '
                                              'research|research '
                                              '(scientist|associate|engineer)|^lecturer|, '
                                              'lecturer|^research associate'}}},
        {'short': 'CSE',
         'name': 'School of Computational Science and Engineering',
         'majors': ['Computational Science and Engineering', 'Computer Science'],
         'directory_url': 'https://cse.gatech.edu/people/faculty',
         'scrape': {'url': 'https://cse.gatech.edu/people/faculty',
                    'selectors': {'card': '.card-block',
                                  'name': '.card-block__title a',
                                  'link': '.card-block__title a',
                                  'title': '.card-block__subtitle'},
                    'ladder_filter': {'drop': 'emerit|in memoriam|of the practice|principal '
                                              'research|research '
                                              '(scientist|associate|engineer)|^lecturer|, '
                                              'lecturer|^research associate'}}},
        {'short': 'AE',
         'name': 'Daniel Guggenheim School of Aerospace Engineering',
         'majors': ['Aerospace Engineering'],
         'directory_url': 'https://ae.gatech.edu/people?tid=1',
         'scrape': {'url': 'https://ae.gatech.edu/people?tid=1',
                    'selectors': {'card': '.node--type-dir-person',
                                  'name': 'a.dir_link',
                                  'link': 'a.dir_link',
                                  'title': '.field--name-field-person-job-title-s-'},
                    'ladder_filter': {'drop': 'emerit|adjunct|affiliat|courtesy|of the practice|academic '
                                              'professional|research '
                                              '(scientist|engineer)|post.?doc|lecturer|instructor'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 8}}},
        {'short': 'BME',
         'name': 'Wallace H. Coulter Department of Biomedical Engineering',
         'majors': ['Biomedical Engineering'],
         'directory_url': 'https://bme.gatech.edu/our-people/our-faculty?field_faculty_type=BME%20Primary%20Faculty',
         'scrape': {'url': 'https://bme.gatech.edu/our-people/our-faculty?field_faculty_type=BME%20Primary%20Faculty',
                    'selectors': {'card': '.node-teaser-bios',
                                  'name': '.node-field-title',
                                  'link': "a[href^='/bio/']",
                                  'title': '.field-position'},
                    'ladder_filter': {'drop': 'emerit|adjunct|affiliat|courtesy|lecturer|of the '
                                              'practice|academic professional|research '
                                              '(scientist|engineer)|post.?doc|instructor'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 8}}},
        {'short': 'ISYE',
         'name': 'H. Milton Stewart School of Industrial & Systems Engineering',
         'majors': ['Industrial Engineering', 'Industrial and Systems Engineering'],
         'directory_url': 'https://www.isye.gatech.edu/people/faculty?classification=27',
         'scrape': {'url': 'https://www.isye.gatech.edu/people/faculty?classification=27',
                    'selectors': {'card': '.card',
                                  'name': '.person-name a',
                                  'link': '.person-name a',
                                  'title': '.person-type'},
                    'ladder_filter': {'drop': 'emerit|adjunct|affiliat|courtesy|of practice|of the '
                                              'practice|academic professional|research '
                                              '(scientist|engineer)|post.?doc|lecturer'}}},
        {'short': 'ME',
         'name': 'George W. Woodruff School of Mechanical Engineering',
         'majors': ['Mechanical Engineering', 'Nuclear and Radiological Engineering'],
         'directory_url': 'https://me.gatech.edu/faculty',
         'scrape': {'url': 'https://me.gatech.edu/faculty',
                    'selectors': {'card': '.faculty__user-wrapper',
                                  'name': '.faculty-name a',
                                  'link': '.faculty-name a',
                                  'title': '.faculty-title'},
                    'link_filter': '/faculty/',
                    'ladder_filter': {'drop': 'emerit|adjunct|affiliat|courtesy|lecturer|of the '
                                              'practice|of practice|academic professional|research '
                                              '(scientist|engineer|faculty|professor)|helluva|coordinator|^staff$'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 13}}},
        {'short': 'BIOSCI',
         'name': 'School of Biological Sciences',
         'majors': ['Biology', 'Biochemistry', 'Neuroscience'],
         'directory_url': 'https://biosciences.gatech.edu/people?field_job_category_tid=19',
         'scrape': {'url': 'https://biosciences.gatech.edu/people?field_job_category_tid=19',
                    'selectors': {'card': '.people ul.grid li',
                                  'name': 'span.name a',
                                  'link': 'span.name a',
                                  'title': 'span.title'},
                    'ladder_filter': {'drop': '\\bemerit|\\badjunct|\\baffiliat|of the practice|academic '
                                              'professional|\\blecturer\\b|academic adviser'}}},
        {'short': 'EAS',
         'name': 'School of Earth and Atmospheric Sciences',
         'majors': ['Earth and Atmospheric Sciences',
                    'Atmospheric and Oceanic Sciences',
                    'Solid Earth and Planetary Sciences'],
         'directory_url': 'https://eas.gatech.edu/people?field_gtppl_roles_value=academic_faculty',
         'scrape': {'url': 'https://eas.gatech.edu/people?field_gtppl_roles_value=academic_faculty',
                    'selectors': {'card': 'div.gtppl-directory-person',
                                  'name': 'h3',
                                  'link': "a[href^='/people/']",
                                  'title': 'p.person-title'},
                    'ladder_filter': {'drop': '\\bemerit|\\badjunct|\\baffiliat|of the practice|academic '
                                              'professional|\\blecturer\\b'}}},
        {'short': 'PHYS',
         'name': 'School of Physics',
         'majors': ['Physics', 'Applied Physics'],
         'directory_url': 'https://physics.gatech.edu/people?rid=4',
         'scrape': {'url': 'https://physics.gatech.edu/people?rid=4',
                    'selectors': {'card': '.people ul.grid li',
                                  'name': 'h3.p-name a',
                                  'link': 'h3.p-name a'}}},
        {'short': 'PSYCH',
         'name': 'School of Psychology',
         'majors': ['Psychology'],
         'directory_url': 'https://psychology.gatech.edu/people/all-faculty',
         'scrape': {'url': 'https://psychology.gatech.edu/people/all-faculty',
                    'selectors': {'card': 'table.views-table tbody tr',
                                  'name': 'td a',
                                  'link': 'td a',
                                  'research': 'td.views-field-field-research-interests',
                                  'email': 'td.views-field-field-email'}}},
        {'short': 'ARCH',
         'name': 'School of Architecture',
         'majors': ['Architecture'],
         'directory_url': 'https://arch.gatech.edu/people',
         'scrape': {'url': 'https://arch.gatech.edu/people',
                    'selectors': {'card': '.profile-card',
                                  'name': 'h3',
                                  'link': '.card-link a',
                                  'title': '.card-text p'},
                    'ladder_filter': {'require': '\\bprofessor\\b',
                                      'drop': 'emerit|adjunct|lecturer|instructor|of (the '
                                              ')?practice|visiting|critic|fellow|ph\\.?d '
                                              '(candidate|student)|\\bcandidate\\b|postdoc|research '
                                              '(scientist|engineer|associate)'}}},
        {'short': 'BC',
         'name': 'School of Building Construction',
         'majors': ['Building Construction'],
         'directory_url': 'https://bc.gatech.edu/people',
         'scrape': {'url': 'https://bc.gatech.edu/people',
                    'selectors': {'card': '.profile-card',
                                  'name': 'h3',
                                  'link': '.card-link a',
                                  'title': '.card-text p'},
                    'ladder_filter': {'require': '\\bprofessor\\b',
                                      'drop': 'emerit|adjunct|lecturer|instructor|of (the '
                                              ')?practice|visiting|critic|fellow|ph\\.?d '
                                              '(candidate|student)|\\bcandidate\\b|postdoc|research '
                                              '(scientist|engineer|associate)'}}},
        {'short': 'CRP',
         'name': 'School of City & Regional Planning',
         'majors': ['City and Regional Planning'],
         'directory_url': 'https://planning.gatech.edu/people',
         'scrape': {'url': 'https://planning.gatech.edu/people',
                    'selectors': {'card': '.profile-card',
                                  'name': 'h3',
                                  'link': '.card-link a',
                                  'title': '.card-text p'},
                    'ladder_filter': {'require': '\\bprofessor\\b',
                                      'drop': 'emerit|adjunct|lecturer|instructor|of (the '
                                              ')?practice|visiting|critic|fellow|ph\\.?d '
                                              '(candidate|student)|\\bcandidate\\b|postdoc|research '
                                              '(scientist|engineer|associate)'}}},
        {'short': 'ID',
         'name': 'School of Industrial Design',
         'majors': ['Industrial Design'],
         'directory_url': 'https://id.gatech.edu/people',
         'scrape': {'url': 'https://id.gatech.edu/people',
                    'selectors': {'card': '.profile-card',
                                  'name': 'h3',
                                  'link': '.card-link a',
                                  'title': '.card-text p'},
                    'ladder_filter': {'require': '\\bprofessor\\b',
                                      'drop': 'emerit|adjunct|lecturer|instructor|of (the '
                                              ')?practice|visiting|critic|fellow|ph\\.?d '
                                              '(candidate|student)|\\bcandidate\\b|postdoc|research '
                                              '(scientist|engineer|associate)'}}},
        {'short': 'MUSIC',
         'name': 'School of Music',
         'majors': ['Music Technology'],
         'directory_url': 'https://music.gatech.edu/people',
         'scrape': {'url': 'https://music.gatech.edu/people',
                    'selectors': {'card': '.profile-card',
                                  'name': 'h3',
                                  'link': '.card-link a',
                                  'title': '.card-text p'},
                    'ladder_filter': {'require': '\\bprofessor\\b',
                                      'drop': 'emerit|adjunct|lecturer|instructor|of (the '
                                              ')?practice|visiting|critic|fellow|ph\\.?d '
                                              '(candidate|student)|\\bcandidate\\b|postdoc|research '
                                              '(scientist|engineer|associate)'}}},
        {'short': 'ECON',
         'name': 'School of Economics',
         'majors': ['Economics', 'Global Economics and Modern Languages'],
         'directory_url': 'https://econ.gatech.edu/people/faculty',
         'scrape': {'url': 'https://econ.gatech.edu/people/faculty',
                    'selectors': {'card': 'li.iacPersonEntry',
                                  'name': 'span.iacPersonName',
                                  'link': "a[href*='/people/person/']",
                                  'title': 'p.iacPersonTitle',
                                  'research_items': 'ul.iacPersonMainInterests li'},
                    'ladder_filter': {'require': 'prof(?:essor)?',
                                      'drop': 'emerit|adjunct|lecturer|of the practice|academic '
                                              'professional|postdoc|visiting|affiliat|retired|research '
                                              '(scientist|associate|engineer)|\\bresearcher\\b|part-time'}}},
        {'short': 'HSOC',
         'name': 'School of History and Sociology',
         'majors': ['History Technology and Society', 'History', 'Sociology'],
         'directory_url': 'https://hsoc.gatech.edu/people/faculty',
         'scrape': {'url': 'https://hsoc.gatech.edu/people/faculty',
                    'selectors': {'card': 'li.iacPersonEntry',
                                  'name': 'span.iacPersonName',
                                  'link': "a[href*='/people/person/']",
                                  'title': 'p.iacPersonTitle'},
                    'ladder_filter': {'require': 'prof(?:essor)?',
                                      'drop': 'emerit|adjunct|lecturer|of the practice|academic '
                                              'professional|postdoc|visiting|affiliat|retired|research '
                                              '(scientist|associate|engineer)|\\bresearcher\\b|part-time'}}},
        {'short': 'INTA',
         'name': 'Sam Nunn School of International Affairs',
         'majors': ['International Affairs',
                    'Global Economics and Modern Languages',
                    'International Affairs and Modern Languages'],
         'directory_url': 'https://inta.gatech.edu/people/faculty',
         'scrape': {'url': 'https://inta.gatech.edu/people/faculty',
                    'selectors': {'card': 'li.iacPersonEntry',
                                  'name': 'span.iacPersonName',
                                  'link': "a[href*='/people/person/']",
                                  'title': 'p.iacPersonTitle'},
                    'ladder_filter': {'require': 'prof(?:essor)?',
                                      'drop': 'emerit|adjunct|lecturer|of the practice|academic '
                                              'professional|postdoc|visiting|affiliat|retired|research '
                                              '(scientist|associate|engineer)|\\bresearcher\\b|part-time'}}},
        {'short': 'LMC',
         'name': 'School of Literature, Media, and Communication',
         'majors': ['Literature Media and Communication', 'Computational Media'],
         'directory_url': 'https://lmc.gatech.edu/people/faculty',
         'scrape': {'url': 'https://lmc.gatech.edu/people/faculty',
                    'selectors': {'card': 'li.iacPersonEntry',
                                  'name': 'span.iacPersonName',
                                  'link': "a[href*='/people/person/']",
                                  'title': 'p.iacPersonTitle'},
                    'ladder_filter': {'require': 'prof(?:essor)?',
                                      'drop': 'emerit|adjunct|lecturer|of the practice|academic '
                                              'professional|postdoc|visiting|affiliat|retired|research '
                                              '(scientist|associate|engineer)|\\bresearcher\\b|part-time'}}},
        {'short': 'SPP',
         'name': 'School of Public Policy',
         'majors': ['Public Policy'],
         'directory_url': 'https://spp.gatech.edu/people/faculty',
         'scrape': {'url': 'https://spp.gatech.edu/people/faculty',
                    'selectors': {'card': 'li.iacPersonEntry',
                                  'name': 'span.iacPersonName',
                                  'link': "a[href*='/people/person/']",
                                  'title': 'p.iacPersonTitle'},
                    'ladder_filter': {'require': 'prof(?:essor)?',
                                      'drop': 'emerit|adjunct|lecturer|of the practice|academic '
                                              'professional|postdoc|visiting|affiliat|retired|research '
                                              '(scientist|associate|engineer)|\\bresearcher\\b|part-time'}}},
        {'short': 'MODLANG',
         'name': 'School of Modern Languages',
         'majors': ['Applied Languages and Intercultural Studies',
                    'Global Economics and Modern Languages',
                    'International Affairs and Modern Languages'],
         'directory_url': 'https://modlangs.gatech.edu/people/faculty',
         'scrape': {'url': 'https://modlangs.gatech.edu/people/faculty',
                    'selectors': {'card': 'li.iacPersonEntry',
                                  'name': 'span.iacPersonName',
                                  'link': "a[href*='/people/person/']",
                                  'title': 'p.iacPersonTitle'},
                    'ladder_filter': {'require': 'prof(?:essor)?',
                                      'drop': 'emerit|adjunct|lecturer|of the practice|academic '
                                              'professional|postdoc|visiting|affiliat|retired|research '
                                              '(scientist|associate|engineer)|\\bresearcher\\b|part-time'}}},
        # --- Scheller College of Business (json_dir feed, per academic area) ---
        _scheller('ACCT', 'Accounting (Scheller College of Business)', ['Accounting', 'Business Administration'], 'Accounting'),
        _scheller('FIN', 'Finance (Scheller College of Business)', ['Finance', 'Business Administration'], 'Finance'),
        _scheller('ITM', 'Information Technology Management (Scheller College of Business)', ['Information Technology Management', 'Business Administration', 'Business Analytics'], 'IT Management'),
        _scheller('LAWETH', 'Law & Ethics (Scheller College of Business)', ['Business Administration'], 'Law and Ethics'),
        _scheller('MKTG', 'Marketing (Scheller College of Business)', ['Marketing', 'Business Administration'], 'Marketing'),
        _scheller('OM', 'Operations Management (Scheller College of Business)', ['Operations Management', 'Business Administration', 'Supply Chain Engineering'], 'Operations Management'),
        _scheller('OB', 'Organizational Behavior (Scheller College of Business)', ['Business Administration', 'Leadership and Organizational Change'], 'Organizational Behavior'),
        _scheller('STRAT', 'Strategy & Innovation (Scheller College of Business)', ['Business Administration', 'Strategy and Innovation'], 'Strategy and Innovation'),
    ],
}


# Per-profile research enrichment (gated by OFE_ENRICH_PROFILES): each professor's
# own profile page keeps a labelled research block the directory listing omits, on
# a department-specific subdomain with department-specific markup. Each regex was
# verified live through the engine (clean keywords, 0 DQ junk). Departments absent
# here have no clean per-profile source (prose-only bios, a tag-separated taxonomy
# the [;,] split can't atomise, or no research field) and stay broad rather than
# ship fragments. College of Computing carries its own profile_enrich inline.
_PROFILE_ENRICH_RES = {
    "CHEM": r"Research Keywords\s*</h5>(.*?)</div>",
    "CEE": r'field_person_research_area">(.*?)</div>\s*<div class="block',
    "IC": r"Research Areas:?\s*</strong>\s*(?:</?br\s*/?>)?\s*(.*?)\s*</p>",
    "CSE": r"<strong>Research Areas?:?</strong>(.*?)</p>",
    "ME": r"Research Area:\s*(?:</strong>)?(.*?)</h5>",
    "BIOSCI": r'views-label-field-research-interests">.*?<div class="field-content">(.*?)</div>',
    "PSYCH": r"Research Interests\s*</h3>\s*<p>(.*?)</p>",
    "ARCH": r"<h4[^>]*>(?:<[^>]+>|&nbsp;|\s)*Keywords(?:<[^>]+>|&nbsp;|\s)*</h4>\s*<p>(.*?)</p>",
    "CRP": r"<(?:strong|h4)>Specialization Area:.*?</(?:strong|h4)>(?:\s*<[^>]+>)*\s*(.*?)\s*</(?:p|h4)>",
}
for _dept in SCHOOL["departments"]:
    _enrich_re = _PROFILE_ENRICH_RES.get(_dept["short"])
    if _enrich_re and _dept.get("scrape"):
        _dept["scrape"].setdefault("profile_enrich", {"research_html_re": _enrich_re})

# Same idea, but for profiles whose research field is a clean list of taxonomy
# links / chips rather than free text: one keyword per matched element (commas
# inside a chip stay folded, never atomised into fragments). Each selector was
# verified live through the engine. ISyE keeps a labelled "Expertise" list; MSE a
# coarse materials-class taxonomy (field-research-area chips); SPP an "Areas of
# Expertise" list on the iac person template (its listing card omits it).
_PROFILE_ENRICH_ITEMS = {
    "ISYE": "div.ieuser-expertise ul li",
    "MSE": "div.field--name-field-research-area a[href^='/research-area/']",
    "SPP": "ul.iacPersonExpertiseView li",
}
for _dept in SCHOOL["departments"]:
    _enrich_sel = _PROFILE_ENRICH_ITEMS.get(_dept["short"])
    if _enrich_sel and _dept.get("scrape"):
        _dept["scrape"].setdefault(
            "profile_enrich", {"research_items_selector": _enrich_sel})


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
