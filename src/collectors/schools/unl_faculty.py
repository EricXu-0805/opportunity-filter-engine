"""University of Nebraska-Lincoln faculty config (via the faculty_graph engine).

Campus-wide coverage: 46 departments across seven colleges — Engineering,
Arts & Sciences, Agricultural Sciences & Natural Resources, Business, Education
& Human Sciences, Journalism & Mass Communications, and Law. Live-verified
2026-07-24 through the proxy; every shipped department is majority-emailed.

THREE SOURCE FAMILIES
---------------------
1. ``_teaser`` (43 depts) — the campus-wide UNLcms "person teaser" component.
   Whatever the host (department subdomain, a college subdirectory, or the
   engineering CMS) the markup is byte-identical, so one selector set covers
   almost the whole university. One card is
   ``div.unlcms-teaser-person`` (it carries ``data-uid`` = netid = email
   local-part). Inside it:

   * ``a.dcf-card-link[itemprop="name"]`` whose own anchor text is whitespace —
     the display name sits in an inner ``<span>``, so the name selector targets
     ``… span``; the anchor itself is the ``/person/<slug>/`` profile link,
     RELATIVE to each host and resolved by the engine's ``urljoin`` against that
     department's own listing URL;
   * ``span[itemprop="jobTitle"]`` with the rank (the reliable gate field);
   * ``span.organization-unit`` with the person's home academic unit — the field
     that lets the one 194-card College of Business page split into its seven
     real departments;
   * a plain ``mailto:`` inside the card ``<address>`` — no Cloudflare / hex /
     base64 obfuscation anywhere on any UNL page, so email coverage is 90-100%
     wherever the listing exposes an address.

   The card is the ``div``, NOT the enclosing ``li[itemtype*=schema.org/Person]``:
   UNLcms also ships an ABBREVIATED teaser (``div.unlcms-abbr-teaser-person``)
   that renders name + rank and NO ``<address>``. Both variants sit in an
   identical ``li``, so an ``li`` card selector silently mixes email-less rows
   into a mixed page. Keying on the full-teaser class is exact — verified
   identical kept/emailed counts to the old ``li`` selector on all ten original
   departments, while cleanly excluding the abbreviated rosters.

2. ``_snr`` (1 dept) — the School of Natural Resources runs a legacy ASP.NET
   directory (``directory.aspx``) with its own markup: a
   ``section.partner[data-category=…]`` card whose ``data-category`` attribute IS
   the role gate (faculty 113 / staff 78 / graduatestudent 82). Name in
   ``h3.dcf-regular``, role text in ``div.info p``, plain ``mailto``.

3. ``_law`` (1 dept) — the College of Law paints its roster client-side (a bare
   shell statically; 0 cards, 0 mailto), so it needs ``scrape["render"]=True``.
   Rendered, it exposes 50 "Last, First" cards with rank in ``p.dcf-subhead``
   and a real ``mailto`` — the only UNL department that needs headless.

QUALITY GATE
------------
Teaser departments use ``field_filter`` (NOT ``ladder_filter``) so a title-less
staff card can't fall through the engine's default-to-"Professor":
``require_present`` reads ``span[itemprop='jobTitle']`` directly and drops the
card when the rank is absent/blank, then ``include`` keeps only Professor /
Lecturer / Instructor ranks (endowed-chair and professor-of-practice titles
still contain "Professor"). This matters — the directories interleave ladder
faculty with a large block of non-teaching staff, emeriti, advisors, grants
coordinators and grad students: Biological Sciences lists 150 cards of which 30
are faculty, Philosophy 48 of which 8, Business 194 of which 114. Emeriti that
carry the word "Professor" are additionally dropped by the engine's own
retired-title guard.

The seven College of Business departments all read the SAME college directory
page and separate on ``span.organization-unit`` via ``field_filter``, so the
rank gate moves to ``ladder_filter`` there (safe: all 194 cards on that page
carry a ``jobTitle``, so nothing defaults to "Professor"). ``MNGT`` anchors its
unit regex (``^management$``) so it does not swallow "Supply Chain Management &
Analytics"; ``ACCT`` tolerates the live page's "Acountancy" typo.

SNR gates on the card's ``data-category="faculty"`` plus a ``field_filter``
``exclude`` for emeriti / post-docs / visiting scholars, rather than a
professor-rank ``include``: SNR lists its ladder faculty under research-specialty
titles ("Physiological Plant Ecologist | Interim Dean", "Climate Scientist |
State Climatologist"), so a rank regex would drop 61 of its 70 real faculty.

DROPPED (all live-checked; each is a coverage gap, not an oversight)
-------------------------------------------------------------------
Email-less abbreviated-teaser rosters — real faculty, but the listing renders
NO ``<address>``, so every record would be a name-only stub. Recoverable only by
a per-profile enrichment pass (phase 2):

* Hixson-Lied College of Fine and Performing Arts — all four schools (Art/Art
  History & Design ~45, Glenn Korff Music ~68, Johnny Carson Theatre & Film ~42,
  Carson Center for Emerging Media Arts ~18) plus the college directory.
* College of Architecture (``architecture.unl.edu/people/college-directory/``) —
  ~86 abbreviated faculty; its only full teasers are 36 advisory-council members.
* Agricultural Economics (~38) and Plant Pathology (~31), both CASNR.
* School of Veterinary Medicine and Biomedical Sciences (~33).

Affiliate-only rosters — every person's ``organization-unit`` is another
department (the unit has no own-line faculty), so they are already covered at
their home department and would only steal attribution:

* Ethnic Studies (16 kept, home units History/Psychology/English/MLL/Sociology).
* Women's and Gender Studies (4 kept, all joint appointments).

``sociology.unl.edu`` is a dead host (TLS handshake reset over any client, HTTP
502 on :80) — the department is shipped from its live alias ``soc.unl.edu``.

Single source ("unl_faculty"); department rides each record, ids namespaced by
department short-code. The engine's intra-batch dedup keys on contact_email and
profile URL, so the leadership featured-card duplicate some departments render,
and the genuine joint appointments the interdisciplinary rosters repeat, each
land once.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UNLcms full person teaser — identical markup on every UNL host.
_SEL = {
    "card": "div.unlcms-teaser-person",
    "name": 'a.dcf-card-link[itemprop="name"] span',
    "link": 'a.dcf-card-link[itemprop="name"]',
    "title": 'span[itemprop="jobTitle"]',
    "email": 'address a[href^="mailto:"]',
}

# Keep Professors (ladder + of-practice + research + endowed-chair) and any
# Lecturer / Instructor; drop the staff, advisors, and grad students the
# directories mix in. require_present makes a rank-less card fail outright
# instead of inheriting the engine's default "Professor".
_FIELD = {
    "selector": 'span[itemprop="jobTitle"]',
    "require_present": True,
    "include": r"professor|lecturer|instructor",
}

_BUSINESS_DIR = "https://business.unl.edu/about/faculty-and-staff-directory/"


# Research lives only on the /person/<slug>/ profile (relative link already in
# the card). Chips win where a heading is followed by a <ul> (Engineering/A&S:
# "Research Areas"/"Areas of Research and Professional Interest"/"EXPERTISE"/
# "Areas of Expertise"; Law uses a taxonomy <section> of <a>); a comma <p> line
# is the fallback (STAT/EAS/CHEM/ENGL). Bio-div scope keeps figure/publication
# <ul>s out. No profile pass exists today → always:true (weekly enrich is gated).
_BIO = 'div.unlcms-grid-person-detail-bio :is(h2,h3,h4,h5,h6)'
_UNL_ENRICH = {
    "always": True, "throttle": 0.2,
    "research_items_selector": (
        f'{_BIO}:-soup-contains("Research Areas") + ul li, '
        f'{_BIO}:-soup-contains("Areas of Research and Professional Interest") + ul li, '
        f'{_BIO}:-soup-contains("EXPERTISE") + ul li, '
        f'{_BIO}:-soup-contains("Areas of Expertise") + ul li, '
        ':is(h2,h3,h4,h5,h6):-soup-contains("Areas of Expertise") + section a'),
    "research_selector": (
        f'{_BIO}:-soup-contains("Research Interests") + p, '
        f'{_BIO}:-soup-contains("Areas of Expertise") + p, '
        f'{_BIO}:-soup-contains("Expertise Areas") + p, '
        f'{_BIO}:-soup-contains("Areas of Interest") + p'),
}


def _teaser(short: str, name: str, majors: list[str], url: str) -> dict:
    """A UNL department on the shared unlcms-teaser-person component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD,
                   "profile_enrich": _UNL_ENRICH},
    }


def _business(short: str, name: str, majors: list[str], unit_re: str) -> dict:
    """One College of Business department, split off the shared college page."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": _BUSINESS_DIR,
        "scrape": {
            "url": _BUSINESS_DIR,
            "selectors": _SEL,
            "field_filter": {"selector": "span.organization-unit",
                             "require_present": True, "include": unit_re},
            "ladder_filter": {"require": r"professor|lecturer|instructor"},
            "profile_enrich": _UNL_ENRICH,
        },
    }


SCHOOL: dict = {
    "school_slug": "unl",
    "source": "unl_faculty",
    "organization": "University of Nebraska-Lincoln",
    "location": "Lincoln, NE",
    "id_prefix": "unl",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Nebraska-Lincoln) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering ---------------------------------------
        _teaser("CSE", "School of Computing",
                ["Computer Science", "Computer Engineering", "Software Engineering",
                 "Data Science"],
                "https://computing.unl.edu/directory/"),
        _teaser("ECE", "Department of Electrical and Computer Engineering",
                ["Electrical Engineering", "Computer Engineering"],
                "https://engineering.unl.edu/ece/about/faculty-staff/"),
        _teaser("MME", "Department of Mechanical and Materials Engineering",
                ["Mechanical Engineering", "Materials Engineering", "Materials Science"],
                "https://engineering.unl.edu/mme/about/faculty-staff/"),
        _teaser("CEE", "Department of Civil and Environmental Engineering",
                ["Civil Engineering", "Environmental Engineering"],
                "https://engineering.unl.edu/civil/about/faculty-staff/"),
        _teaser("CHME", "Department of Chemical and Biomolecular Engineering",
                ["Chemical Engineering", "Biomolecular Engineering"],
                "https://engineering.unl.edu/chme/about/faculty-staff/"),
        _teaser("BSE", "Department of Biological Systems Engineering",
                ["Biological Systems Engineering", "Agricultural Engineering",
                 "Biomedical Engineering"],
                "https://bse.unl.edu/our-people/faculty-directory/"),
        _teaser("DURH", "Durham School of Architectural Engineering and Construction",
                ["Architectural Engineering", "Construction Management",
                 "Construction Engineering"],
                "https://durhamschool.unl.edu/about/directory/"),
        # ---- College of Arts & Sciences -----------------------------------
        _teaser("PHYS", "Department of Physics and Astronomy",
                ["Physics", "Astronomy", "Astrophysics"],
                "https://physics.unl.edu/about/directory/"),
        _teaser("CHEM", "Department of Chemistry",
                ["Chemistry", "Biochemistry"],
                "https://chem.unl.edu/research/faculty/"),
        _teaser("MATH", "Department of Mathematics",
                ["Mathematics", "Applied Mathematics"],
                "https://math.unl.edu/about/directory/"),
        _teaser("STAT", "Department of Statistics",
                ["Statistics", "Data Science"],
                "https://statistics.unl.edu/faculty/"),
        _teaser("BIOS", "School of Biological Sciences",
                ["Biological Sciences", "Biology", "Microbiology", "Genetics",
                 "Ecology"],
                "https://biosci.unl.edu/about/directory/"),
        _teaser("PSYC", "Department of Psychology",
                ["Psychology", "Neuroscience", "Cognitive Science"],
                "https://psychology.unl.edu/about/directory/"),
        _teaser("EAS", "Department of Earth and Atmospheric Sciences",
                ["Earth Sciences", "Geology", "Meteorology", "Climatology"],
                "https://eas.unl.edu/about/directory/"),
        _teaser("SGIS", "School of Global Integrative Studies",
                ["Anthropology", "Geography", "Global Studies",
                 "Community and Regional Planning"],
                "https://sgis.unl.edu/about/directory/"),
        _teaser("ENGL", "Department of English",
                ["English", "Creative Writing", "Film Studies"],
                "https://engl.unl.edu/faculty/"),
        _teaser("HIST", "Department of History",
                ["History"],
                "https://history.unl.edu/about/directory/"),
        _teaser("POLS", "Department of Political Science",
                ["Political Science", "International Relations"],
                "https://polisci.unl.edu/about/directory/"),
        _teaser("SOC", "Department of Sociology",
                ["Sociology", "Criminology"],
                "https://soc.unl.edu/about/directory/"),
        _teaser("PHIL", "Department of Philosophy",
                ["Philosophy"],
                "https://philosophy.unl.edu/about/directory/"),
        _teaser("MODL", "Department of Modern Languages and Literatures",
                ["Modern Languages", "Spanish", "French", "German", "Linguistics"],
                "https://modlang.unl.edu/about/directory/"),
        _teaser("CLAS", "Department of Classics and Religious Studies",
                ["Classics", "Religious Studies"],
                "https://classics.unl.edu/about/directory/"),
        _teaser("COMM", "Department of Communication Studies",
                ["Communication Studies"],
                "https://comm.unl.edu/about/directory/"),
        # ---- Agricultural Sciences & Natural Resources ---------------------
        _teaser("AGRO", "Department of Agronomy and Horticulture",
                ["Agronomy", "Horticulture", "Plant Science", "Soil Science"],
                "https://agronomy.unl.edu/our-people/faculty-directories/faculty/"),
        _teaser("ANSC", "Department of Animal Science",
                ["Animal Science", "Veterinary Science"],
                "https://animalscience.unl.edu/faculty/"),
        _teaser("FDST", "Department of Food Science and Technology",
                ["Food Science and Technology", "Food Science"],
                "https://foodscience.unl.edu/people/faculty/"),
        _teaser("ENTO", "Department of Entomology",
                ["Entomology", "Insect Science"],
                "https://entomology.unl.edu/faculty/"),
        _teaser("BIOC", "Department of Biochemistry",
                ["Biochemistry", "Molecular Biology"],
                "https://biochem.unl.edu/our-people/faculty/"),
        _teaser("ALEC", "Department of Agricultural Leadership, Education and Communication",
                ["Agricultural Education", "Agricultural Leadership",
                 "Agricultural Communication"],
                "https://alec.unl.edu/our-people/faculty/"),
        # ---- College of Business (one page, split on organization-unit) ----
        _business("MNGT", "Department of Management",
                  ["Management", "Entrepreneurship", "Human Resources"],
                  r"^management$"),
        _business("ACCT", "School of Accountancy",
                  ["Accounting", "Accountancy"],
                  r"ac+ountancy"),
        _business("ECON", "Department of Economics",
                  ["Economics"],
                  r"\beconomics\b"),
        _business("FINA", "Department of Finance",
                  ["Finance"],
                  r"\bfinance\b"),
        _business("MRKT", "Department of Marketing",
                  ["Marketing"],
                  r"\bmarketing\b"),
        _business("SCMA", "Department of Supply Chain Management and Analytics",
                  ["Supply Chain Management", "Business Analytics"],
                  r"supply chain"),
        _business("ACTS", "Actuarial Science Program",
                  ["Actuarial Science"],
                  r"actuarial science"),
        # ---- College of Education & Human Sciences -------------------------
        _teaser("CYAF", "Department of Child, Youth and Family Studies",
                ["Child Development", "Family Science", "Human Development"],
                "https://cehs.unl.edu/cyaf/meet-faculty-and-staff/"),
        _teaser("EDAD", "Department of Educational Administration",
                ["Educational Administration", "Higher Education Leadership"],
                "https://cehs.unl.edu/edad/about-edad/edad-community/"),
        _teaser("EDPS", "Department of Educational Psychology",
                ["Educational Psychology", "School Psychology",
                 "Counseling Psychology"],
                "https://cehs.unl.edu/edpsych/edps-faculty-and-staff/"),
        _teaser("NHS", "Department of Nutrition and Health Sciences",
                ["Nutrition", "Health Sciences", "Exercise Science"],
                "https://cehs.unl.edu/nhs/nhs-home/facultystaff/"),
        _teaser("SECD", "Department of Special Education and Communication Disorders",
                ["Special Education", "Communication Disorders",
                 "Speech-Language Pathology"],
                "https://cehs.unl.edu/secd/secd-faculty/"),
        _teaser("TLTE", "Department of Teaching, Learning and Teacher Education",
                ["Elementary Education", "Secondary Education", "Teacher Education"],
                "https://cehs.unl.edu/tlte/tlte-home/faculty-and-staff-directory/"),
        _teaser("TMFD", "Department of Textiles, Merchandising and Fashion Design",
                ["Textiles", "Merchandising", "Fashion Design"],
                "https://cehs.unl.edu/tmfd/tmfd-home/faculty-staff/"),
        # ---- College of Journalism & Mass Communications -------------------
        _teaser("JOMC", "College of Journalism and Mass Communications",
                ["Journalism", "Advertising and Public Relations", "Broadcasting",
                 "Sports Media and Communication"],
                "https://journalism.unl.edu/about-college/meet-team/"),
        # ---- School of Natural Resources (legacy ASP.NET directory) --------
        # data-category IS the role gate; the exclude prunes emeriti, post-docs
        # and visiting scholars that share the "faculty" category. No rank
        # include: SNR lists ladder faculty under research-specialty titles.
        {
            "short": "SNR", "name": "School of Natural Resources",
            "majors": ["Environmental Studies", "Fisheries and Wildlife",
                       "Natural Resources", "Water Science", "Applied Climate Science"],
            "directory_url": "https://snr.unl.edu/aboutus/who/people/directory.aspx",
            "scrape": {
                "url": "https://snr.unl.edu/aboutus/who/people/directory.aspx",
                "selectors": {
                    "card": 'section.partner[data-category="faculty"]',
                    "name": "h3.dcf-regular",
                    "link": 'a[href*="member.aspx"]',
                    "title": "div.info p",
                    "email": 'a[href^="mailto:"]',
                },
                "field_filter": {
                    "selector": "div.info p",
                    "require_present": True,
                    "exclude": (r"emerit|post-?doc|post[- ]doctoral|resesarch associate"
                                r"|visiting|graduate student"),
                },
            },
        },
        # ---- College of Law (client-rendered; needs headless) --------------
        {
            "short": "LAW", "name": "College of Law",
            "majors": ["Law", "Legal Studies"],
            "directory_url": "https://law.unl.edu/faculty-directory/",
            "scrape": {
                "url": "https://law.unl.edu/faculty-directory/",
                "render": True,
                "render_wait": "networkidle",
                "selectors": {
                    "card": "div.dcf-d-grid.dcf-grid-cols-12",
                    "name": "h4.dcf-regular",
                    "link": "a.dcf-txt-decor-none",
                    "title": "p.dcf-subhead",
                    "email": 'address a[href^="mailto:"]',
                },
                "name_flip": True,
                "field_filter": {
                    "selector": "p.dcf-subhead",
                    "require_present": True,
                    "include": r"professor|lecturer|instructor",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
