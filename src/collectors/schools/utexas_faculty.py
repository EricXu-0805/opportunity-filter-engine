"""UT Austin faculty config (via the faculty_graph engine).

UT Austin's departments run separate CMSes; this engine covers each via the
cleanest source it exposes:

  * **Computer Science** + **ECE** — server-rendered Drupal "Views" grids (CS
    carries research groups inline → fully keyworded; ECE name + position).
  * **Cockrell School engineering** (ChemE, Aerospace, Civil/Arch/Env, BME) —
    one WordPress ``person`` post type per department, filtered to the
    ``cockrell_person_type`` "Faculty" term AND the ``cockrell_person_job_type``
    "Tenure-Track" term (drops emeritus/research/teaching/adjunct), keyworded
    from the ``cockrell_person_research_area`` taxonomy.
  * **College of Natural Sciences** (Physics, Chemistry, Math) — the CNS
    directory is a JS client over a public Algolia index; queried directly,
    filtered to tenure-track and de-emeritus'd, keyworded from
    ``areas_of_research``.
  * **Mechanical Engineering** — a server-rendered Joomla directory
    (``div.facdata``), title-filtered to ladder ranks, with public emails.

Deferred: Physics is JS only via Algolia (covered); no department remains on the
headless path.

Single source ("utexas_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph


# Cockrell School WordPress: faculty = a `person` post type filtered to the
# Faculty type AND the Tenure-Track job-type term (ids verified live per dept),
# keyworded from the research-area taxonomy.
def _cockrell(short: str, name: str, majors: list[str], base: str,
              type_id: int, tt_id: int) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": f"{base}/faculty",
            "api": {"type": "wp", "base": base, "post_type": "person",
                    "category_include": {"cockrell_person_type": [type_id],
                                         "cockrell_person_job_type": [tt_id]},
                    "keyword_tax": ["cockrell_person_research_area"]}}


# UT Austin College of Natural Sciences shared Algolia directory index.
_CNS_ALGOLIA = {"app_id": "R1M3WN6NBD",
                "api_key": "1323cc0cdac884501409d31207bb2d4b",
                "index": "directory_LIVE", "drop_title_re": r"emerit"}


def _cns(short: str, name: str, majors: list[str], dept: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://cns.utexas.edu/directory",
            "algolia": {**_CNS_ALGOLIA,
                        "filters": f'department:"{dept}" AND '
                                   'position_type:"1-Tenure-Track/Tenured Faculty"'}}


# College of Liberal Arts shared JSON:API (a Vue SPA per dept; one division facet
# each). Ladder-filter to tenure-track/teaching faculty (require a professor
# title, drop emeritus/lecturer/adjunct/research-track/cross-listed affiliates).
_COLA_BASE = "https://webeditor.la.utexas.edu/api/v2"
_COLA_DROP = (r"emerit|adjunct|lecturer|visiting|of practice|of the practice|"
              r"research (professor|scientist|associate|fellow)|research fellow|"
              r"postdoc|of instruction|clinical|affiliat")


def _cola(short: str, name: str, majors: list[str], division: str) -> dict:
    home = f"https://liberalarts.utexas.edu/{division}/faculty"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": f"{home}/",
            "cola": {"base": _COLA_BASE, "division": division,
                     "profile_base": home,
                     "ladder_filter": {"require": "profess", "drop": _COLA_DROP}}}


SCHOOL: dict = {
    "school_slug": "utexas",
    "source": "utexas_faculty",
    "organization": "The University of Texas at Austin",
    "location": "Austin, TX",
    "id_prefix": "utexas",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UT Austin) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CS",
            "name": "Department of Computer Science",
            "majors": ["Computer Science", "Computer Engineering", "Data Science"],
            "directory_url": "https://www.cs.utexas.edu/people",
            "scrape": {
                "url": "https://www.cs.utexas.edu/people",
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-contact-faculty",
                    "research": ".views-field-field-research-groups",
                },
            },
        },
        {
            "short": "ECE",
            "name": "Chandra Family Department of Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering"],
            "directory_url": "https://ece.utexas.edu/people/faculty",
            "scrape": {
                "url": "https://ece.utexas.edu/people/faculty",
                "selectors": {
                    "card": ".facentry",
                    "name": ".views-field-title a",
                    "link": ".views-field-title a",
                    "title": ".views-field-field-faculty-position",
                },
            },
        },
        _cockrell("CHEME", "McKetta Department of Chemical Engineering",
                  ["Chemical Engineering"], "https://che.utexas.edu", 218, 226),
        _cockrell("AERO", "Department of Aerospace Engineering & Engineering Mechanics",
                  ["Aerospace Engineering", "Engineering Mechanics"],
                  "https://www.ae.utexas.edu", 3012, 3015),
        _cockrell("CAEE", "Department of Civil, Architectural & Environmental Engineering",
                  ["Civil Engineering", "Architectural Engineering", "Environmental Engineering"],
                  "https://www.caee.utexas.edu", 45, 180),
        _cockrell("BME", "Department of Biomedical Engineering",
                  ["Biomedical Engineering"], "https://bme.utexas.edu", 569, 571),
        _cns("PHYSICS", "Department of Physics", ["Physics"], "Physics"),
        _cns("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"], "Chemistry"),
        _cns("MATH", "Department of Mathematics", ["Mathematics"], "Mathematics"),
        # Remaining College of Natural Sciences departments — same shared Algolia
        # directory index, one ``department`` facet each, tenure-track-filtered.
        _cns("ASTRO", "Department of Astronomy", ["Astronomy", "Astrophysics"],
             "Astronomy"),
        _cns("MOLBIO", "Department of Molecular Biosciences",
             ["Molecular Biology", "Biochemistry", "Microbiology"],
             "Molecular Biosciences"),
        _cns("NEURO", "Department of Neuroscience", ["Neuroscience"], "Neuroscience"),
        _cns("INTBIO", "Department of Integrative Biology",
             ["Biology", "Ecology", "Evolutionary Biology"], "Integrative Biology"),
        _cns("MARINE", "Department of Marine Science",
             ["Marine Science", "Marine Biology"], "Marine Science"),
        _cns("SDS", "Department of Statistics & Data Sciences",
             ["Statistics", "Data Science"], "Statistics and Data Sciences"),
        _cns("HDFS", "Department of Human Development & Family Sciences",
             ["Human Development and Family Sciences", "Human Development"],
             "Human Development & Family Sciences"),
        _cns("NUTR", "Department of Nutritional Sciences",
             ["Nutrition", "Nutritional Sciences"], "Nutritional Sciences"),
        _cns("ISCHOOL", "School of Information",
             ["Information Studies", "Informatics", "Information Science",
              "Data Science"], "Information"),
        {
            "short": "ME",
            "name": "Walker Department of Mechanical Engineering",
            "majors": ["Mechanical Engineering"],
            "directory_url": "https://www.me.utexas.edu/people/faculty-directory",
            "scrape": {
                "url": "https://www.me.utexas.edu/people/faculty-directory",
                "selectors": {"card": "div.facdata", "name": "h2",
                              "link": "p.h6-style a", "title": "p.facpos",
                              "email": "a.email"},
                "ladder_filter": {"drop": r"emerit|adjunct|research (professor|scientist)"
                                          r"|practice|instruction|lecturer|visiting"},
            },
        },
        # --- College of Liberal Arts (shared JSON:API; one division each) ---
        _cola("GOV", "Department of Government", ['Government', 'Political Science', 'International Relations and Global Studies'], "government"),
        _cola("ECO", "Department of Economics", ['Economics'], "economics"),
        _cola("ANTH", "Department of Anthropology", ['Anthropology'], "anthropology"),
        _cola("PSY", "Department of Psychology", ['Psychology'], "psychology"),
        _cola("SOC", "Department of Sociology", ['Sociology'], "sociology"),
        _cola("GEO", "Department of Geography & the Environment", ['Geography', 'Geographical Sciences', 'Environmental Science', 'Sustainability Studies'], "geography"),
        _cola("ENGLISH", "Department of English", ['English', 'Creative Writing', 'Rhetoric and Writing'], "english"),
        _cola("HISTORY", "Department of History", ['History'], "history"),
        _cola("PHILOSOPHY", "Department of Philosophy", ['Philosophy'], "philosophy"),
        _cola("LINGUISTICS", "Department of Linguistics", ['Linguistics'], "linguistics"),
        _cola("CLASSICS", "Department of Classics", ['Classics', 'Classical Languages', 'Classical Civilization'], "classics"),
        _cola("RS", "Department of Religious Studies", ['Religious Studies'], "rs"),
        _cola("FRIT", "Department of French & Italian", ['French', 'Italian', 'French Studies', 'Italian Studies'], "frenchitalian"),
        _cola("GERMANIC", "Department of Germanic Studies", ['German', 'Germanic Studies', 'Scandinavian Studies'], "germanic"),
        _cola("SPANPORT", "Department of Spanish & Portuguese", ['Spanish', 'Portuguese', 'Latin American Studies'], "spanish"),
        _cola("SLAVIC", "Department of Slavic & Eurasian Studies", ['Russian', 'Slavic Languages', 'Russian, East European & Eurasian Studies'], "slavic"),
        _cola("ASIAN", "Department of Asian Studies", ['Asian Studies', 'Asian Cultures and Languages', 'Chinese', 'Japanese', 'Hindi/Urdu'], "asianstudies"),
        _cola("MES", "Department of Middle Eastern Studies", ['Middle Eastern Studies', 'Arabic', 'Hebrew', 'Persian', 'Turkish'], "mes"),
        # --- Other colleges (per-department directories, live-scraped) ---
        {'short': 'ACC',
         'name': 'Department of Accounting',
         'majors': ['Accounting'],
         'directory_url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
         'scrape': {'url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
                    'selectors': {'card': 'a.utm-faculty__item',
                                  'name': '.utm-faculty__name',
                                  'link': ':self',
                                  'title': '.utm-faculty__title'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|instruction|of '
                                              'practice|clinical|academic staff|visiting'},
                    'field_filter': {'selector': '.utm-faculty__department',
                                     'include': '^Accounting$'}}},
        {'short': 'FIN',
         'name': 'Department of Finance',
         'majors': ['Finance'],
         'directory_url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
         'scrape': {'url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
                    'selectors': {'card': 'a.utm-faculty__item',
                                  'name': '.utm-faculty__name',
                                  'link': ':self',
                                  'title': '.utm-faculty__title'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|instruction|of '
                                              'practice|clinical|academic staff|visiting'},
                    'field_filter': {'selector': '.utm-faculty__department', 'include': '^Finance$'}}},
        {'short': 'IROM',
         'name': 'Department of Information, Risk & Operations Management',
         'majors': ['Management Information Systems',
                    'Operations Management',
                    'Business Analytics',
                    'Information Systems'],
         'directory_url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
         'scrape': {'url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
                    'selectors': {'card': 'a.utm-faculty__item',
                                  'name': '.utm-faculty__name',
                                  'link': ':self',
                                  'title': '.utm-faculty__title'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|instruction|of '
                                              'practice|clinical|academic staff|visiting'},
                    'field_filter': {'selector': '.utm-faculty__department',
                                     'include': '^Information, Risk, and Operations Management$'}}},
        {'short': 'MGMT',
         'name': 'Department of Management',
         'majors': ['Management', 'Business Administration'],
         'directory_url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
         'scrape': {'url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
                    'selectors': {'card': 'a.utm-faculty__item',
                                  'name': '.utm-faculty__name',
                                  'link': ':self',
                                  'title': '.utm-faculty__title'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|instruction|of '
                                              'practice|clinical|academic staff|visiting'},
                    'field_filter': {'selector': '.utm-faculty__department',
                                     'include': '^Management$'}}},
        {'short': 'MKT',
         'name': 'Department of Marketing',
         'majors': ['Marketing'],
         'directory_url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
         'scrape': {'url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
                    'selectors': {'card': 'a.utm-faculty__item',
                                  'name': '.utm-faculty__name',
                                  'link': ':self',
                                  'title': '.utm-faculty__title'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|instruction|of '
                                              'practice|clinical|academic staff|visiting'},
                    'field_filter': {'selector': '.utm-faculty__department', 'include': '^Marketing$'}}},
        {'short': 'BGS',
         'name': 'Department of Business, Government & Society',
         'majors': ['Business', 'Business Administration'],
         'directory_url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
         'scrape': {'url': 'https://www.mccombs.utexas.edu/faculty-and-research/faculty-directory/',
                    'selectors': {'card': 'a.utm-faculty__item',
                                  'name': '.utm-faculty__name',
                                  'link': ':self',
                                  'title': '.utm-faculty__title'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|instruction|of '
                                              'practice|clinical|academic staff|visiting'},
                    'field_filter': {'selector': '.utm-faculty__department',
                                     'include': '^Business, Government, and Society$'}}},
        {'short': 'ADV',
         'name': 'Stan Richards School of Advertising & Public Relations',
         'majors': ['Advertising', 'Public Relations'],
         'directory_url': 'https://advertising.utexas.edu/faculty',
         'scrape': {'url': 'https://advertising.utexas.edu/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': '.faculty-view-name',
                                  'link': '.views-field-field-headshot-faculty-bio a',
                                  'title': '.views-field-field-position-faculty-bio'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|practice|instruction'}}},
        {'short': 'COMMSTUD',
         'name': 'Department of Communication Studies',
         'majors': ['Communication Studies', 'Communication and Leadership', 'Human Relations'],
         'directory_url': 'https://commstudies.utexas.edu/faculty',
         'scrape': {'url': 'https://commstudies.utexas.edu/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': '.faculty-view-name',
                                  'link': '.views-field-field-headshot-faculty-bio a',
                                  'title': '.views-field-field-position-faculty-bio'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|practice|instruction'}}},
        {'short': 'JOUR',
         'name': 'School of Journalism and Media',
         'majors': ['Journalism', 'Journalism and Media'],
         'directory_url': 'https://journalism.utexas.edu/faculty',
         'scrape': {'url': 'https://journalism.utexas.edu/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': '.faculty-view-name',
                                  'link': '.views-field-field-headshot-faculty-bio a',
                                  'title': '.views-field-field-position-faculty-bio'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|practice|instruction'}}},
        {'short': 'RTF',
         'name': 'Department of Radio-Television-Film',
         'majors': ['Radio-Television-Film', 'Media Production', 'Media Studies', 'Screenwriting'],
         'directory_url': 'https://rtf.utexas.edu/faculty',
         'scrape': {'url': 'https://rtf.utexas.edu/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': '.faculty-view-name',
                                  'link': '.views-field-field-headshot-faculty-bio a',
                                  'title': '.views-field-field-position-faculty-bio'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|practice|instruction'}}},
        {'short': 'SLHS',
         'name': 'Department of Speech, Language, and Hearing Sciences',
         'majors': ['Communication Sciences and Disorders',
                    'Speech-Language Pathology',
                    'Audiology',
                    'Speech, Language, and Hearing Sciences'],
         'directory_url': 'https://slhs.utexas.edu/faculty',
         'scrape': {'url': 'https://slhs.utexas.edu/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': '.faculty-view-name',
                                  'link': '.views-field-field-headshot-faculty-bio a',
                                  'title': '.views-field-field-position-faculty-bio'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|practice|instruction'}}},
        {'short': 'ART',
         'name': 'Department of Art & Art History',
         'majors': ['Studio Art', 'Art History', 'Art Education', 'Visual Art Studies', 'Design'],
         'directory_url': 'https://art.utexas.edu/people/faculty',
         'scrape': {'url': 'https://art.utexas.edu/people/faculty?field_cofaprof_profile_groups_target_id=1',
                    'selectors': {'card': 'div.views-row',
                                  'name': 'h3.cofaprof__title a',
                                  'link': 'h3.cofaprof__title a',
                                  'title': '.cofaprof__designation .field__item',
                                  'email': '.cofaprof__email_address a'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|of practice|affiliat|adjunct|visiting'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 6}}},
        {'short': 'MUSIC',
         'name': 'Sarah and Ernest Butler School of Music',
         'majors': ['Music',
                    'Music Performance',
                    'Composition',
                    'Musicology',
                    'Music Theory',
                    'Music Education',
                    'Jazz'],
         'directory_url': 'https://music.utexas.edu/about/people/faculty',
         'scrape': {'url': 'https://music.utexas.edu/about/people/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': 'h3.cofaprof__title a',
                                  'link': 'h3.cofaprof__title a',
                                  'title': '.cofaprof__designation .field__item',
                                  'email': '.cofaprof__email_address a'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|of practice|affiliat|adjunct|visiting'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 6}}},
        {'short': 'TD',
         'name': 'Department of Theatre & Dance',
         'majors': ['Theatre and Dance',
                    'Theatre Studies',
                    'Dance',
                    'Acting',
                    'Playwriting and Directing',
                    'Design and Technology',
                    'Performance as Public Practice'],
         'directory_url': 'https://theatredance.utexas.edu/about/directory/faculty',
         'scrape': {'url': 'https://theatredance.utexas.edu/about/directory/faculty',
                    'selectors': {'card': 'div.views-row',
                                  'name': 'h3.cofaprof__title a',
                                  'link': 'h3.cofaprof__title a',
                                  'title': '.cofaprof__designation .field__item',
                                  'email': '.cofaprof__email_address a'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|of practice|affiliat|adjunct|visiting'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 8}}},
        {'short': 'DESIGN',
         'name': 'School of Design and Creative Technologies — Design',
         'majors': ['Design', 'Visual Design', 'Product Design', 'Communication Design'],
         'directory_url': 'https://designcreativetech.utexas.edu/design-faculty',
         'scrape': {'url': 'https://designcreativetech.utexas.edu/design-faculty',
                    'selectors': {'card': '.cofaprof__profile-item',
                                  'name': 'h3.title a',
                                  'link': 'h3.title a',
                                  'title': '.cofaprof__designation .field__item'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|lecturer|adjunct|visiting'}}},
        {'short': 'AET',
         'name': 'School of Design and Creative Technologies — Arts and Entertainment Technologies',
         'majors': ['Arts and Entertainment Technologies', 'Game Development', 'Immersive Media'],
         'directory_url': 'https://designcreativetech.utexas.edu/aet-faculty',
         'scrape': {'url': 'https://designcreativetech.utexas.edu/aet-faculty',
                    'selectors': {'card': '.cofaprof__profile-item',
                                  'name': 'h3.title a',
                                  'link': 'h3.title a',
                                  'title': '.cofaprof__designation .field__item'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|lecturer|adjunct|visiting'}}},
        {'short': 'CI',
         'name': 'Department of Curriculum & Instruction',
         'majors': ['Curriculum and Instruction',
                    'STEM Education',
                    'Bilingual/Bicultural Education',
                    'Language and Literacy Studies',
                    'Cultural Studies in Education'],
         'directory_url': 'https://education.utexas.edu/research/find-faculty/',
         'scrape': {'url': 'https://education.utexas.edu/research/find-faculty/',
                    'selectors': {'card': 'div.faculty-container',
                                  'name': 'a.headline-link',
                                  'link': 'a.headline-link',
                                  'title': 'div.faculty-title'},
                    'field_filter': {'selector': 'div.faculty-title',
                                     'include': 'Department of Curriculum and Instruction'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|research (professor|scientist|associate '
                                              'professor|assistant '
                                              'professor)|clinical|postdoc|^(?:program |senior '
                                              '|associate )?director\\b|faculty specialist|program '
                                              'specialist'}}},
        {'short': 'ELP',
         'name': 'Department of Educational Leadership & Policy',
         'majors': ['Educational Leadership and Policy',
                    'Higher Education Leadership',
                    'Education Policy and Planning',
                    'Cooperative Superintendency / K-12 Educational Leadership'],
         'directory_url': 'https://education.utexas.edu/research/find-faculty/',
         'scrape': {'url': 'https://education.utexas.edu/research/find-faculty/',
                    'selectors': {'card': 'div.faculty-container',
                                  'name': 'a.headline-link',
                                  'link': 'a.headline-link',
                                  'title': 'div.faculty-title'},
                    'field_filter': {'selector': 'div.faculty-title',
                                     'include': 'Educational Leadership and Policy'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|research (professor|scientist|associate '
                                              'professor|assistant '
                                              'professor)|clinical|postdoc|^(?:program |senior '
                                              '|associate )?director\\b|faculty specialist|program '
                                              'specialist'}}},
        {'short': 'EDP',
         'name': 'Department of Educational Psychology',
         'majors': ['Educational Psychology',
                    'Counseling Psychology',
                    'School Psychology',
                    'Counselor Education',
                    'Human Development, Culture, and Learning Sciences',
                    'Quantitative Methods'],
         'directory_url': 'https://education.utexas.edu/research/find-faculty/',
         'scrape': {'url': 'https://education.utexas.edu/research/find-faculty/',
                    'selectors': {'card': 'div.faculty-container',
                                  'name': 'a.headline-link',
                                  'link': 'a.headline-link',
                                  'title': 'div.faculty-title'},
                    'field_filter': {'selector': 'div.faculty-title',
                                     'include': 'Department of Educational Psychology'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|research (professor|scientist|associate '
                                              'professor|assistant '
                                              'professor)|clinical|postdoc|^(?:program |senior '
                                              '|associate )?director\\b|faculty specialist|program '
                                              'specialist'}}},
        {'short': 'KHE',
         'name': 'Department of Kinesiology & Health Education',
         'majors': ['Kinesiology',
                    'Health Education',
                    'Health Promotion and Behavioral Science',
                    'Exercise Science',
                    'Sport Management',
                    'Physical Culture and Sport Studies'],
         'directory_url': 'https://education.utexas.edu/research/find-faculty/',
         'scrape': {'url': 'https://education.utexas.edu/research/find-faculty/',
                    'selectors': {'card': 'div.faculty-container',
                                  'name': 'a.headline-link',
                                  'link': 'a.headline-link',
                                  'title': 'div.faculty-title'},
                    'field_filter': {'selector': 'div.faculty-title',
                                     'include': 'Department of Kinesiology and Health Education'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|research (professor|scientist|associate '
                                              'professor|assistant '
                                              'professor)|clinical|postdoc|^(?:program |senior '
                                              '|associate )?director\\b|faculty specialist|program '
                                              'specialist'}}},
        {'short': 'SPED',
         'name': 'Department of Special Education',
         'majors': ['Special Education',
                    'Autism and Developmental Disabilities',
                    'Early Childhood Special Education',
                    'High-Incidence Disabilities and Behavior Disorders',
                    'Multicultural Special Education',
                    'Deaf and Hard of Hearing'],
         'directory_url': 'https://education.utexas.edu/research/find-faculty/',
         'scrape': {'url': 'https://education.utexas.edu/research/find-faculty/',
                    'selectors': {'card': 'div.faculty-container',
                                  'name': 'a.headline-link',
                                  'link': 'a.headline-link',
                                  'title': 'div.faculty-title'},
                    'field_filter': {'selector': 'div.faculty-title',
                                     'include': 'Department of Special Education'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|of '
                                              'instruction|research (professor|scientist|associate '
                                              'professor|assistant '
                                              'professor)|clinical|postdoc|^(?:program |senior '
                                              '|associate )?director\\b|faculty specialist|program '
                                              'specialist'}}},
        {'short': 'SOA',
         'name': 'School of Architecture',
         'majors': ['Architecture',
                    'Interior Design',
                    'Landscape Architecture',
                    'Urban Design',
                    'Community and Regional Planning',
                    'Urban Studies'],
         'directory_url': 'https://soa.utexas.edu/faculty',
         'scrape': {'url': 'https://soa.utexas.edu/faculty',
                    'selectors': {'card': '.soaprof__list',
                                  'name': 'h3.soaprof__title a',
                                  'link': 'h3.soaprof__title a',
                                  'title': '.soaprof__designation'},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|visiting|of practice|research '
                                              'professor|fellow|instructor'}}},
        {'short': 'LBJ',
         'name': 'LBJ School of Public Affairs',
         'majors': ['Public Affairs',
                    'Public Policy',
                    'Global Policy Studies',
                    'Master of Public Affairs',
                    'Master of Global Policy Studies'],
         'directory_url': 'https://lbj.utexas.edu/faculty',
         'scrape': {'url': 'https://lbj.utexas.edu/faculty',
                    'selectors': {'card': 'div.faculty-caption',
                                  'name': 'h4 a',
                                  'link': 'h4 a',
                                  'title': 'span em'},
                    'ladder_filter': {'drop': 'emerit|adjunct|visiting|lecturer|of practice|of '
                                              'instruction|research '
                                              '(professor|scientist)|practice|^director|^interim '
                                              'dean|^assistant dean|^associate dean|^executive '
                                              'director|senior fellow'},
                    'paginate': {'param': 'page', 'start': 1, 'max': 4}}},
        {'short': 'MEDCHEM',
         'name': 'Division of Chemical Biology & Medicinal Chemistry',
         'majors': ['Medicinal Chemistry', 'Pharmaceutical Sciences', 'Chemistry'],
         'directory_url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/medicinal-chemistry/faculty-staff',
         'scrape': {'url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/medicinal-chemistry/faculty-staff',
                    'selectors': {'card': 'div.pharm__list',
                                  'name': 'h3.pharm__title a',
                                  'link': 'h3.pharm__title a',
                                  'title': '.pharm__designation'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|adjunct|courtesy|of practice|research (assistant '
                                              '|associate |full )?prof|research '
                                              'scientist|visiting|lecturer'}}},
        {'short': 'HOP',
         'name': 'Division of Health Outcomes',
         'majors': ['Health Outcomes', 'Pharmacy', 'Pharmaceutical Sciences'],
         'directory_url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/health-outcomes/faculty-staff',
         'scrape': {'url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/health-outcomes/faculty-staff',
                    'selectors': {'card': 'div.pharm__list',
                                  'name': 'h3.pharm__title a',
                                  'link': 'h3.pharm__title a',
                                  'title': '.pharm__designation'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|adjunct|courtesy|of practice|research (assistant '
                                              '|associate |full )?prof|research '
                                              'scientist|visiting|lecturer'}}},
        {'short': 'MPDD',
         'name': 'Division of Molecular Pharmaceutics & Drug Delivery',
         'majors': ['Pharmaceutical Sciences', 'Molecular Pharmaceutics', 'Drug Delivery'],
         'directory_url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/molecular-pharmaceutics/faculty-staff',
         'scrape': {'url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/molecular-pharmaceutics/faculty-staff',
                    'selectors': {'card': 'div.pharm__list',
                                  'name': 'h3.pharm__title a',
                                  'link': 'h3.pharm__title a',
                                  'title': '.pharm__designation'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|adjunct|courtesy|of practice|research (assistant '
                                              '|associate |full )?prof|research '
                                              'scientist|visiting|lecturer'}}},
        {'short': 'PHTOX',
         'name': 'Division of Pharmacology & Toxicology',
         'majors': ['Pharmacology', 'Toxicology', 'Pharmaceutical Sciences'],
         'directory_url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/pharmacology-toxicology/faculty-staff',
         'scrape': {'url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/pharmacology-toxicology/faculty-staff',
                    'selectors': {'card': 'div.pharm__list',
                                  'name': 'h3.pharm__title a',
                                  'link': 'h3.pharm__title a',
                                  'title': '.pharm__designation'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|adjunct|courtesy|of practice|research (assistant '
                                              '|associate |full )?prof|research '
                                              'scientist|visiting|lecturer'}}},
        {'short': 'PTS',
         'name': 'Division of Pharmacotherapy & Translational Sciences',
         'majors': ['Pharmacy', 'Pharmacotherapy', 'Translational Sciences'],
         'directory_url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/pharmacotherapy/faculty-staff',
         'scrape': {'url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/pharmacotherapy/faculty-staff',
                    'selectors': {'card': 'div.pharm__list',
                                  'name': 'h3.pharm__title a',
                                  'link': 'h3.pharm__title a',
                                  'title': '.pharm__designation'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|adjunct|courtesy|of practice|research (assistant '
                                              '|associate |full )?prof|research '
                                              'scientist|visiting|lecturer'}}},
        {'short': 'PHRP',
         'name': 'Division of Pharmacy Practice',
         'majors': ['Pharmacy', 'Pharmacy Practice'],
         'directory_url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/pharmacy-practice/faculty-staff',
         'scrape': {'url': 'https://pharmacy.utexas.edu/research-practice/college-divisions/pharmacy-practice/faculty-staff',
                    'selectors': {'card': 'div.pharm__list',
                                  'name': 'h3.pharm__title a',
                                  'link': 'h3.pharm__title a',
                                  'title': '.pharm__designation'},
                    'ladder_filter': {'require': 'profess',
                                      'drop': 'emerit|adjunct|courtesy|of practice|research (assistant '
                                              '|associate |full )?prof|research '
                                              'scientist|visiting|lecturer'}}},
        {'short': 'NURS',
         'name': 'School of Nursing',
         'majors': ['Nursing'],
         'directory_url': 'https://nursing.utexas.edu/faculty/search',
         'scrape': {'url': 'https://nursing.utexas.edu/faculty/search',
                    'selectors': {'card': 'div.views-row',
                                  'name': 'h3.utprof__title a',
                                  'link': 'h3.utprof__title a',
                                  'title': '.utprof__designation',
                                  'research': '.field--name-field-nurs-faculty-expertise '
                                              '.field__items'},
                    'ladder_filter': {'drop': 'emerit|adjunct|visiting|honoris|honoraris|professor of '
                                              '(?:the )?practice|research professor|clinical '
                                              'instructor|^instructor|assistant '
                                              'instructor|instructors|faculty '
                                              'associate|lieutenant|colonel'}}},
        {'short': 'SW',
         'name': 'Steve Hicks School of Social Work',
         'majors': ['Social Work', 'Bachelor of Social Work', 'Master of Social Work'],
         'directory_url': 'https://socialwork.utexas.edu/academics/faculty/',
         'scrape': {'url': 'https://socialwork.utexas.edu/academics/faculty/',
                    'selectors': {'card': 'div.item-content-area',
                                  'name': 'h3.link-title a',
                                  'link': 'h3.link-title a',
                                  'title': 'h4.sub-title'}}},
        {'short': 'LAW',
         'name': 'School of Law',
         'majors': ['Law', 'Juris Doctor', 'Master of Laws'],
         'directory_url': 'https://law.utexas.edu/faculty/directory/',
         'scrape': {'url': 'https://law.utexas.edu/faculty/directory/',
                    'selectors': {'card': 'div.faculty-card',
                                  'name': '.faculty-name h2 a',
                                  'link': '.faculty-name h2 a',
                                  'title': 'ul.faculty-titles',
                                  'research_items': '.faculty-specialties ul li',
                                  'email': ".faculty-contact a[href^='mailto:']"},
                    'ladder_filter': {'require': 'profess|research chair|dean, school of law',
                                      'drop': 'emerit|adjunct|lecturer|visiting|clinical|of '
                                              'instruction|of practice|specialist|executive '
                                              'director|assistant director|assistant dean|associate '
                                              'dean for information|^director|library'}}},
        {'short': 'PGE',
         'name': 'Hildebrand Department of Petroleum & Geosystems Engineering',
         'majors': ['Petroleum Engineering', 'Geosystems Engineering'],
         'directory_url': 'https://www.pge.utexas.edu/faculty-staff/faculty-directory/',
         'scrape': {'url': 'https://www.pge.utexas.edu/faculty-staff/faculty-directory/',
                    'selectors': {'card': 'li.wp-block-post.faculty-and-staff',
                                  'name': 'h3',
                                  'link': 'a.kb-advanced-image-link',
                                  'title': 'p.title',
                                  'email': "a[href^='mailto:']"},
                    'ladder_filter': {'drop': 'emerit|adjunct|lecturer|of practice|of '
                                              'instruction|research '
                                              '(professor|scientist|associate)|visiting'}}},
    ],
}


# --- Research-area enrichment -----------------------------------------------
# Each directory's research markup was found by per-directory recon and
# re-verified live through the engine (nav links sit outside these scoped
# selectors). Computer Science renders its research-group taxonomy on the listing
# card (card-level ``research_items``); everyone else keeps it only on the profile
# page, reached by a gated (OFE_ENRICH_PROFILES=1), throttled per-profile pass —
# taxonomy-link fields use ``research_items_selector``, labelled blocks use
# ``research_html_re`` (the engine splits <br>-separated areas, e.g. ME).
# Deferred (stay broad): mccombs business (research is JS/JSON-loaded), education
# / advertising / comm-studies / pharmacy / art (prose-only or no field).
_THROTTLE = 1.5
_CARD_RESEARCH_ITEMS = {
    "CS": "div.views-field-field-research-groups .field-content a",
}
_PROFILE_ENRICH = {
    "ECE": {"research_items_selector": ".field--name-field-research-areas .field__item a"},
    "ME": {"research_html_re": r'<p class="dept-resarea-p">(.*?)</p>'},
    "SOA": {"research_items_selector": "div.utsoa-gray li"},
    "LBJ": {"research_items_selector": "div.field--name-field-research-areas div.field__item"},
    "TD": {"research_html_re": r'<summary[^>]*>\s*Areas of Expertise\s*</summary>\s*<p[^>]*>(.*?)</p>'},
    "SW": {"research_html_re": r'<h3[^>]*>\s*Professional Interests\s*</h3>\s*<p[^>]*>(.*?)</p>'},
    "SLHS": {"research_items_selector": "div.field--name-field-expertise-faculty-bio .field__item"},
    "RTF": {"research_items_selector": "div.field--name-field-expertise-faculty-bio div.field__item"},
    "JOUR": {"research_items_selector": ".field--name-field-expertise-faculty-bio .field__item"},
    "COMMSTUD": {"research_items_selector": ".field--name-field-expertise-faculty-bio .field__item"},
    "PGE": {"research_html_re": r"<strong>\s*Research Areas\s*(?:<br\s*/?>)?\s*</strong>(.*?)</p>"},
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
