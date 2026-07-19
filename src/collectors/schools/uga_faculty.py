"""University of Georgia faculty config (via the faculty_graph engine).

UGA's directories span six markup families, all verified live 2026-07-18
(engine-parsed against saved HTML; counts are post-ladder):

* Statewide-Drupal "views-row" theme — 31 Franklin College departments plus
  Warnell (32 units). Cards carry name/title/email inline (plain mailto,
  85-100% coverage); no pagination anywhere, no WAF. Research areas live only
  on profile pages (``div.field_research_areas`` taxonomy links and/or a
  labelled "Research Areas:"/"Research Interests:" ``div.field``) — recovered
  by the monthly OFE_ENRICH_PROFILES pass. Plant Biology is the one dept whose
  LISTING has zero emails (profile-only); Philosophy embeds interests in the
  title after "--" (captured via ``research_re_text``, trimmed via
  ``title_strip_after``).

* WordPress Isotope/MixItUp portal grids — Engineering (one page, per-school
  wrapper classes + a trailing catch-all for the ~10 unclassed deans/joint
  appointments; email/URL dedup assigns dupes to their school first), SPIA
  (3 depts), Public Health (5 units; Epidemiology & Biostatistics is ONE
  merged department at UGA), Ecology, Social Work, Environment & Design,
  Pharmacy (2 depts via wrapper class; SHOUTING names retitled via
  ``name_title_case``), and Vet Med (7 depts; no emails on the 1243-card
  page — profile sidebar cf-link, monthly pass). All emails on these grids
  are Cloudflare-obfuscated (``__cf_email__``/``email-protection`` hrefs) —
  the engine's ``_decode_cfemail`` reads them at listing tier.

* CAES people-search (schema.org Person microdata) — 9 academic departments,
  one page each. Rosters interleave Ph.D. students / staff / county extension
  personnel, so these use the require-professor gate ("Professor and Extension
  Coordinator" is a real land-grant professor — no ``extension`` drop here).

* Hugo (College of Education) — 9 dept pages, ``section.list-of-people``
  role-grouped; the ``h2`` section gate keeps only "Faculty". Emails exist
  only on people.coe.uga.edu profiles as a REVERSED data-user/data-domain
  cloak — decoded by the engine's ``_decode_reversed_email``.

* Bespoke WordPress — Lamar Dodd Art (accordion ``article.profile`` with
  taxonomy classes, path pagination ``/page/N/``, plaintext emails in the
  toggle panel), Grady (single faculty-staff archive, emails on profiles),
  FACS (hCard ``li.vcard`` with an ``<em>`` role tag → ``field_filter``),
  Law (Drupal views TABLE, rank as bare text between ``<br>`` →
  ``title_html_re``; the host serves an incomplete TLS chain → ``insecure``).

* Terry College of Business — the whole site 403s behind a bot-classifier +
  Cloudflare managed challenge, but its WordPress REST API is open:
  ``/wp-json/wp/v2/directory?employee-type=4&group=<dept>`` with plain email
  and rank in the ACF block (``acf_fields`` + the wp-path ladder gate).

Single source ("uga_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (from the 2026-07-18 recon):
* Institute of Bioinformatics, Institute for AI faculty-fellows, WGS
  affiliate roster — all cross-listed rosters duplicating home-dept faculty.
* CAES non-departmental groups (county extension districts, USDA units,
  research centers) — not academic departments.
* Terry non-department groups (MBA programs, career centers, institutes).
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Statewide-Drupal "views-row" theme (Franklin + Warnell) ---------------
_UGA_SELECTORS = {
    "card": "div.views-row",
    "name": ".views-field-field-last-name a.util-delink h2",
    "link": ".views-field-field-last-name a.util-delink",
    "title": ".views-field-field-job-title .field-content",
    "email": ".views-field-field-email a[href^='mailto:']",
}

# Listing titles carry the full noise spectrum (emeritus/adjunct/lecturer/
# "Academic Professional"/"Limited-Term"/research-scientist ranks); admin
# add-ons like "Director of Graduate Studies" ride a professor title and pass.
_UGA_LADDER = {
    "drop": r"emerit|adjunct|visiting|postdoc|part-\s?time|\binstructor\b|"
            r"lecturer|courtesy|academic professional|research scientist|"
            r"limited.term|\bretired\b|\bspecialist\b",
}

# Require-gate for rosters that interleave students/staff/extension personnel
# with clean titles on every row (CAES, Grady, Pharmacy, Law).
_PROF_LADDER = {"require": r"\bprofessor\b",
                "drop": r"emerit|adjunct|visiting|courtesy|part-\s?time"}

# Profile pass for the statewide-Drupal theme: taxonomy research chips
# (atomic keywords) with the labelled prose block as fallback; the personal
# mailto sits in div.field_email ahead of the shared dept inbox (-web@).
_UGA_PROFILE = {
    "email_selector": "div.field_email a[href^='mailto:']",
    "email_drop": r"^[^@]*$|-web@|webmaster@",
    "research_items_selector": "div.field_research_areas a",
    "research_selector": "div.field:has(> .field-above:-soup-contains('Research'))",
    "throttle": 0.2,
}


def _fr(short: str, name: str, majors: list[str], host: str,
        path: str = "/directory/faculty", *, ladder: dict | None = None,
        selectors: dict | None = None, enrich: dict | None = None) -> dict:
    """A department on the statewide-Drupal views-row theme."""
    url = f"https://{host}{path}"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": selectors or _UGA_SELECTORS,
                       "ladder_filter": ladder or _UGA_LADDER,
                       "profile_enrich": enrich or _UGA_PROFILE}}


# ---- WordPress Isotope/MixItUp portal grids ---------------------------------
def _eng(short: str, name: str, majors: list[str], school_class: str) -> dict:
    """One College of Engineering school off the single Isotope directory."""
    card = f"div.element-item.portal_item.faculty{school_class}"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://engineering.uga.edu/directory/",
            "scrape": {"url": "https://engineering.uga.edu/directory/",
                       "selectors": {"card": card,
                                     "name": "p.team_member_title a",
                                     "link": "p.team_member_title a",
                                     "title": "p.job_title",
                                     "email": "p.email a",
                                     "name_strip": r",\s*(?:Ph\.?D|D\.?Sc|Sc\.?D|P\.?E)\.?.*$"},
                       "ladder_filter": _UGA_LADDER}}


def _spia(short: str, name: str, majors: list[str], dept_class: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://spia.uga.edu/directory/faculty/",
            "scrape": {"url": "https://spia.uga.edu/directory/faculty/",
                       "selectors": {"card": f"div.portal_item.element-item.{dept_class}",
                                     "name": "p.bio_title a",
                                     "link": "p.bio_title a",
                                     "title": "span.title",
                                     "email": "p.email_address a"},
                       "ladder_filter": _UGA_LADDER,
                       # Profile keeps "Areas of Expertise"/"Research
                       # Interests" accordions (div.expList → div.exp_content).
                       "profile_enrich": {
                           "research_selector": "div.expList div.exp_content",
                           "throttle": 0.2}}}


def _cph(short: str, name: str, majors: list[str], dept_class: str) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://publichealth.uga.edu/directory/faculty/",
            "scrape": {"url": "https://publichealth.uga.edu/directory/faculty/",
                       "selectors": {"card": f"div.element-item.bio-wrap.{dept_class}",
                                     "name": "p.h5_title a",
                                     "link": "p.h5_title a",
                                     "title": "span.title",
                                     "email": "span.email-address a"},
                       "ladder_filter": _UGA_LADDER,
                       "profile_enrich": {
                           "research_selector": "div.exp-content",
                           "throttle": 0.2}}}


def _vet(short: str, name: str, majors: list[str], dept_class: str) -> dict:
    """One Vet Med department off the single 1243-card college directory.

    No emails at listing tier — the profile sidebar carries one cf-encoded
    email-protection link; recovered by the monthly per-profile pass.
    """
    url = "https://vet.uga.edu/about-us/college-directory/search-faculty-staff/"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": f"div.element-item.faculty.{dept_class}",
                                     "name": "p.portal_title",
                                     "link": "a",
                                     "title": "p.designation_tax.tax_title"},
                       "ladder_filter": _UGA_LADDER,
                       "profile_enrich": {
                           "email_selector": "div.sidebar_person a[href*='email-protection']",
                           "email_drop": r"^[^@]*$",
                           "throttle": 0.2}}}


# ---- CAES people-search (schema.org Person microdata) -----------------------
def _caes(short: str, name: str, majors: list[str], dept_id: int,
          slug: str) -> dict:
    url = (f"https://www.caes.uga.edu/about/personnel/people-search/"
           f"department/{dept_id}/{slug}.html")
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "div.person",
                                     "name": "a.name",
                                     "link": "a.name",
                                     "title": "span.job-description",
                                     "email": ".contact-info a[href^='mailto:']"},
                       "ladder_filter": _PROF_LADDER}}


# ---- College of Education (Hugo, role-grouped sections) ----------------------
def _coe(short: str, name: str, majors: list[str], slug: str) -> dict:
    url = f"https://coe.uga.edu/directory/{slug}"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "section.list-of-people div.person",
                                     "name": "a", "link": "a",
                                     "title": "div.affiliation"},
                       "section_filter": {"heading": "h2", "include": r"^faculty$"},
                       "ladder_filter": _UGA_LADDER,
                       # Emails exist ONLY on people.coe.uga.edu profiles, as a
                       # reversed data-user/data-domain cloak the engine decodes.
                       "profile_enrich": {
                           "email_selector": "span.cloaked-e-mail",
                           "email_drop": r"^[^@]*$",
                           "research_html_re":
                               r"Areas of Expertise\s*</h3>\s*</header>(.*?)</section",
                           "throttle": 0.2}}}


# ---- FACS (hCard with an <em> role tag) -------------------------------------
def _fcs(short: str, name: str, majors: list[str], dept_no: int) -> dict:
    url = f"https://www.fcs.uga.edu/people/dept/{dept_no}"
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "li.vcard",
                                     "name": "p.fn a", "link": "p.fn a",
                                     "title": "p.title strong",
                                     "email": "a.email[href^='mailto:']"},
                       # The em role tag separates Faculty from Staff/Students/
                       # Emeriti/Extension Agents — titles alone can't.
                       "field_filter": {"selector": "p > em",
                                        "include": r"^faculty$",
                                        "exclude": r"adjunct|emerit|graduate|extension|staff"},
                       "ladder_filter": _UGA_LADDER,
                       "profile_enrich": {
                           "research_html_re":
                               r"<h2[^>]*>\s*Areas of Expertise\s*</h2>(.*?)(?:<h2|</div)",
                           "throttle": 0.2}}}


# ---- Terry College of Business (open WP REST API behind a walled site) ------
def _terry(short: str, name: str, majors: list[str], group_id: int) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": "https://www.terry.uga.edu/directory/",
            "api": {"type": "wp", "base": "https://www.terry.uga.edu",
                    "post_type": "directory",
                    "query": f"&employee-type=4&group={group_id}",
                    # A person double-tagged faculty+emeritus is dropped.
                    "category_exclude": {"employee-type": [6]},
                    "acf_fields": {"title": "job_titles.0.position.title",
                                   "email": "email"},
                    "ladder_filter": _UGA_LADDER}}


SCHOOL: dict = {
    "school_slug": "uga",
    "source": "uga_faculty",
    "organization": "University of Georgia",
    "location": "Athens, GA",
    "id_prefix": "uga",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Georgia) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Franklin College: sciences -------------------------------------
        _fr("CS", "School of Computing",
            ["Computer Science", "Data Science", "Artificial Intelligence"],
            "www.cs.uga.edu"),
        _fr("CHEM", "Department of Chemistry", ["Chemistry"], "www.chem.uga.edu"),
        _fr("PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astronomy"], "www.physast.uga.edu"),
        _fr("MATH", "Department of Mathematics", ["Mathematics"],
            "www.math.uga.edu"),
        _fr("STAT", "Department of Statistics", ["Statistics", "Data Science"],
            "www.stat.uga.edu"),
        _fr("MARS", "Department of Marine Sciences",
            ["Marine Sciences", "Oceanography"], "www.marsci.uga.edu"),
        _fr("GENE", "Department of Genetics", ["Genetics", "Genomics"],
            "www.genetics.uga.edu"),
        _fr("MIBO", "Department of Microbiology", ["Microbiology"],
            "mib.uga.edu"),
        # Cellular Biology's /directory/faculty 302s to /directory (which IS
        # the faculty list — 32 rows, all faculty ranks).
        _fr("CBIO", "Department of Cellular Biology",
            ["Cellular Biology", "Biology"], "cellbio.uga.edu", "/directory"),
        # Plant Biology's listing carries no emails at all — profile-only.
        _fr("PBIO", "Department of Plant Biology",
            ["Plant Biology", "Botany"], "www.plantbio.uga.edu"),
        _fr("BMB", "Department of Biochemistry and Molecular Biology",
            ["Biochemistry and Molecular Biology"], "bmb.uga.edu"),
        _fr("PSYC", "Department of Psychology", ["Psychology"],
            "psychology.uga.edu"),
        _fr("GEOG", "Department of Geography",
            ["Geography", "Geographic Information Science"],
            "geography.uga.edu"),
        # Host is geology.uga.edu (gly.uga.edu is DNS mail-only).
        _fr("GEOL", "Department of Geology", ["Geology", "Earth Sciences"],
            "geology.uga.edu"),
        # ---- Franklin College: social sciences ------------------------------
        _fr("ANTH", "Department of Anthropology", ["Anthropology"],
            "anthropology.uga.edu"),
        _fr("SOCI", "Department of Sociology", ["Sociology", "Criminology"],
            "sociology.uga.edu"),
        _fr("COMM", "Department of Communication Studies",
            ["Communication Studies"], "comm.uga.edu"),
        _fr("LING", "Department of Linguistics", ["Linguistics"],
            "linguistics.uga.edu"),
        # ---- Franklin College: humanities ------------------------------------
        _fr("HIST", "Department of History", ["History"], "history.uga.edu"),
        _fr("ENGL", "Department of English", ["English", "Creative Writing"],
            "english.uga.edu"),
        # Titles are UPPERCASE with interests appended after "--" — trim the
        # tail from the rank and keep it as the research line.
        _fr("PHIL", "Department of Philosophy", ["Philosophy"], "phil.uga.edu",
            selectors={**_UGA_SELECTORS,
                       "title_strip_after": r"\s*--",
                       "research_re_text": r"--\s*(.{4,200})$"}),
        _fr("RELI", "Department of Religion", ["Religion"], "religion.uga.edu"),
        # classics.uga.edu redirects to the clas.franklin host.
        _fr("CLAS", "Department of Classics", ["Classics"],
            "clas.franklin.uga.edu"),
        _fr("CMLT", "Department of Comparative Literature and Intercultural Studies",
            ["Comparative Literature"], "cmlt.uga.edu"),
        _fr("ROML", "Department of Romance Languages",
            ["Romance Languages", "Spanish", "French"], "rom.uga.edu"),
        _fr("GRSL", "Department of Germanic and Slavic Studies",
            ["German", "Russian"], "gsstudies.uga.edu"),
        # ---- Franklin College: fine and performing arts ----------------------
        _fr("THEA", "Department of Theatre and Film Studies",
            ["Theatre", "Film Studies"], "drama.uga.edu"),
        _fr("MUSI", "Hugh Hodgson School of Music",
            ["Music", "Music Education"], "music.uga.edu"),
        _fr("DANC", "Department of Dance", ["Dance"], "dance.uga.edu"),
        # Lamar Dodd is WordPress: an accordion of article.profile cards whose
        # position-regular-faculty taxonomy class IS the ladder roster; email
        # is plaintext inside the button's toggle panel; 11 /page/N/ pages.
        {
            "short": "ART", "name": "Lamar Dodd School of Art",
            "majors": ["Studio Art", "Art History", "Art Education"],
            "directory_url": "https://art.uga.edu/directory/",
            "scrape": {
                "url": "https://art.uga.edu/directory/",
                "selectors": {"card": "article.profile.position-regular-faculty",
                              "name": "button h2",
                              "link": "a[href*='/profile/']",
                              "title": "button p",
                              "email": "div[id^='course-toggle-'] p:-soup-contains('@')"},
                # start=2: /page/1/ canonical-redirects back to page 1 — the
                # duplicate yields no fresh cards and would abort the walk.
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 11},
                "ladder_filter": {"drop": _UGA_LADDER["drop"] + r"|affiliate"},
                # ~24% of panels omit the address; the profile page keeps a
                # real mailto plus a "Research Focus" section.
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|info@|admissions@",
                    "throttle": 0.25,
                },
            },
        },
        # ---- Franklin College: interdisciplinary (cross-listed-heavy; kept
        # after the home departments so email/URL dedup assigns people there) --
        _fr("AFAM", "Institute for African American Studies",
            ["African American Studies"], "afam.uga.edu"),
        _fr("WGS", "Institute for Women's, Gender, and Sexuality Studies",
            ["Women's Studies"], "wgs.uga.edu", "/directory/core-faculty"),
        # ---- College of Engineering (one Isotope page, per-school classes) ---
        _eng("ECAM", "School of Environmental, Civil, Agricultural and Mechanical Engineering",
             ["Civil Engineering", "Mechanical Engineering",
              "Agricultural Engineering", "Environmental Engineering"],
             ".school-of-environmental-civil-agricultural-and-mechanical-engineering"),
        _eng("ECE", "School of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             ".school-of-electrical-and-computer-engineering"),
        _eng("CMBE", "School of Chemical, Materials and Biomedical Engineering",
             ["Chemical Engineering", "Biomedical Engineering",
              "Materials Science and Engineering"],
             ".school-of-chemical-materials-and-biomedical-engineering"),
        # Catch-all for the ~10 faculty with no school class (deans/joint
        # appointments) — listed last so the schools win the dedup.
        _eng("ENGR", "College of Engineering", ["Engineering"], ""),
        # ---- Warnell School of Forestry and Natural Resources ----------------
        _fr("WARNELL", "Warnell School of Forestry and Natural Resources",
            ["Forestry", "Wildlife", "Natural Resources", "Fisheries"],
            "warnell.uga.edu"),
        # ---- Odum School of Ecology ------------------------------------------
        {
            "short": "ECOL", "name": "Odum School of Ecology",
            "majors": ["Ecology", "Environmental Science"],
            "directory_url": "https://ecology.uga.edu/directory/",
            "scrape": {
                "url": "https://ecology.uga.edu/directory/",
                # The MixItUp grid classes its 217 cards by role — courtesy/
                # adjunct/emeritus faculty carry their own classes.
                "selectors": {
                    "card": ("div.portal-item.faculty:not(.courtesy-faculty)"
                             ":not(.adjunct-faculty):not(.emeritus-faculty)"),
                    "name": ".bio-info h5 a", "link": ".bio-info h5 a",
                    "title": "span.title", "email": "span.email-address a"},
                "ladder_filter": _UGA_LADDER,
                "profile_enrich": {
                    "research_selector": "div.exp-content",
                    "throttle": 0.2},
            },
        },
        # ---- School of Public and International Affairs ----------------------
        _spia("POLS", "Department of Political Science", ["Political Science"],
              "department-of-political-science"),
        _spia("PADP", "Department of Public Administration and Policy",
              ["Public Administration", "Public Policy"],
              "department-of-public-administration-and-policy"),
        _spia("INTL", "Department of International Affairs",
              ["International Affairs"], "department-of-international-affairs"),
        # ---- College of Public Health ----------------------------------------
        _cph("EPIB", "Department of Epidemiology and Biostatistics",
             ["Epidemiology", "Biostatistics"], "epidemiology-biostatistics"),
        _cph("EHS", "Department of Environmental Health Science",
             ["Environmental Health"], "environmental-health-science"),
        _cph("HPM", "Department of Health Policy and Management",
             ["Health Policy", "Health Administration"],
             "health-policy-management"),
        _cph("HPB", "Department of Health Promotion and Behavior",
             ["Health Promotion", "Public Health"], "health-promotion-behavior"),
        _cph("GERO", "Institute of Gerontology", ["Gerontology"],
             "institute-of-gerontology"),
        # ---- CAES (per-dept people-search; require-professor gates the
        # student/staff/extension interleave) ----------------------------------
        _caes("AAEC", "Department of Agricultural and Applied Economics",
              ["Agricultural Economics", "Applied Economics"],
              2, "Agricultural%20&%20Applied%20Economics"),
        _caes("ALEC", "Department of Agricultural Leadership, Education and Communication",
              ["Agricultural Education", "Agricultural Communication"],
              4, "Agricultural%20Leadership,%20Education%20&%20Communication"),
        _caes("ADS", "Department of Animal and Dairy Science",
              ["Animal Science", "Dairy Science"], 6, "Animal%20&%20Dairy%20Science"),
        _caes("CSS", "Department of Crop and Soil Sciences",
              ["Agronomy", "Soil Science"], 43, "Crop%20&%20Soil%20Sciences"),
        _caes("ENTO", "Department of Entomology", ["Entomology"],
              49, "Entomology"),
        _caes("FST", "Department of Food Science and Technology",
              ["Food Science"], 57, "Food%20Science%20&%20Technology"),
        _caes("HORT", "Department of Horticulture", ["Horticulture"],
              66, "Horticulture"),
        _caes("PLPA", "Department of Plant Pathology", ["Plant Pathology"],
              85, "Plant%20Pathology"),
        _caes("POUL", "Department of Poultry Science", ["Poultry Science"],
              87, "Poultry%20Science"),
        # ---- Mary Frances Early College of Education (Hugo) -------------------
        _coe("EPSY", "Department of Educational Psychology",
             ["Educational Psychology"], "educational-psychology"),
        _coe("KINS", "Department of Kinesiology",
             ["Kinesiology", "Exercise Science"], "kinesiology"),
        _coe("CSSE", "Department of Communication Sciences and Special Education",
             ["Communication Sciences and Disorders", "Special Education"],
             "communication-sciences-and-special-education"),
        _coe("CHDS", "Department of Counseling and Human Development Services",
             ["Counseling"], "counseling-and-human-development-services"),
        _coe("ETAP", "Department of Educational Theory and Practice",
             ["Education"], "educational-theory-and-practice"),
        _coe("LLED", "Department of Language and Literacy Education",
             ["Language Education", "Literacy Education"],
             "language-and-literacy-education"),
        _coe("LEAP", "Department of Lifelong Education, Administration and Policy",
             ["Educational Administration"],
             "lifelong-education-administration-and-policy"),
        _coe("MSSE", "Department of Mathematics, Science, and Social Studies Education",
             ["Mathematics Education", "Science Education"],
             "math-science-and-social-studies-education"),
        _coe("WEIT", "Department of Workforce Education and Instructional Technology",
             ["Workforce Education", "Instructional Technology"],
             "workforce-education-and-instructional-technology"),
        # ---- College of Family and Consumer Sciences (hCard) ------------------
        _fcs("FHCE", "Department of Financial Planning, Housing and Consumer Economics",
             ["Financial Planning", "Consumer Economics"], 1),
        _fcs("NUTR", "Department of Nutritional Sciences",
             ["Nutritional Sciences", "Dietetics"], 2),
        _fcs("HDFS", "Department of Human Development and Family Science",
             ["Human Development and Family Science"], 3),
        _fcs("TMI", "Department of Textiles, Merchandising and Interiors",
             ["Fashion Merchandising", "Interior Design"], 4),
        # ---- Grady College of Journalism and Mass Communication --------------
        {
            "short": "GRADY",
            "name": "Grady College of Journalism and Mass Communication",
            "majors": ["Journalism", "Advertising", "Public Relations",
                       "Entertainment and Media Studies"],
            "directory_url": "https://grady.uga.edu/faculty-staff/",
            "scrape": {
                "url": "https://grady.uga.edu/faculty-staff/",
                # One archive of 168 people (faculty + staff + PhD students) —
                # the require-professor gate is the roster; emails and the
                # "Research Interests and Activities" block live on profiles.
                "selectors": {"card": "div.archive-faculty__post",
                              "name": "h3.archive-faculty__post__title",
                              "link": "a.wp-block-button__link-a",
                              "title": "p.archive-faculty__post__position"},
                "ladder_filter": _PROF_LADDER,
                "profile_enrich": {
                    "email_selector": "div.single-faculty__contact a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|grady@",
                    "research_html_re":
                        r"Research Interests and Activities</h3>(.*?)(?:<h3|</div)",
                    "throttle": 0.2},
            },
        },
        # ---- School of Social Work --------------------------------------------
        {
            "short": "SSW", "name": "School of Social Work",
            "majors": ["Social Work"],
            "directory_url": "https://ssw.uga.edu/about/directory/",
            "scrape": {
                "url": "https://ssw.uga.edu/about/directory/",
                # full-time-faculty is its own wrapper class (42 of 150 cards);
                # part-time instructors/staff/PhD students carry other classes.
                "selectors": {"card": "div.element-item.full-time-faculty",
                              "name": "h6.tm_title a", "link": "h6.tm_title a",
                              "title": "p.job_title",
                              "email": "div.table_row.tm_email a"},
                "ladder_filter": _UGA_LADDER,
            },
        },
        # ---- College of Pharmacy ----------------------------------------------
        {
            "short": "PBS", "name": "Department of Pharmaceutical and Biomedical Sciences",
            "majors": ["Pharmaceutical Sciences", "Pharmacy"],
            "directory_url": "https://rx.uga.edu/faculty-staff/directory/",
            "scrape": {
                "url": "https://rx.uga.edu/faculty-staff/directory/",
                "selectors": {"card": "div.element-item.pharmaceutical-and-biomedical-sciences",
                              "name": "p.h6_heading.post_title a",
                              "link": "p.h6_heading.post_title a",
                              "title": "span.title", "email": "span.email-address",
                              "name_strip": r",\s*(?:Ph\.?D|Pharm\.?D|M\.?S|M\.?B\.?A|B\.?S|R\.?Ph|J\.?D|M\.?P\.?H)\.?.*$",
                              "name_title_case": True},
                "ladder_filter": _PROF_LADDER,
                "profile_enrich": {
                    "research_html_re":
                        r"<strong>\s*Research Areas\s*</strong>\s*:?(.*?)</p>",
                    "throttle": 0.2},
            },
        },
        {
            "short": "CAP", "name": "Department of Clinical and Administrative Pharmacy",
            "majors": ["Pharmacy", "Clinical Pharmacy"],
            "directory_url": "https://rx.uga.edu/faculty-staff/directory/",
            "scrape": {
                "url": "https://rx.uga.edu/faculty-staff/directory/",
                "selectors": {"card": "div.element-item.clinical-and-administrative-pharmacy",
                              "name": "p.h6_heading.post_title a",
                              "link": "p.h6_heading.post_title a",
                              "title": "span.title", "email": "span.email-address",
                              "name_strip": r",\s*(?:Ph\.?D|Pharm\.?D|M\.?S|M\.?B\.?A|B\.?S|R\.?Ph|J\.?D|M\.?P\.?H)\.?.*$",
                              "name_title_case": True},
                "ladder_filter": _PROF_LADDER,
                "profile_enrich": {
                    "research_html_re":
                        r"<strong>\s*Research Areas\s*</strong>\s*:?(.*?)</p>",
                    "throttle": 0.2},
            },
        },
        # ---- College of Veterinary Medicine (one page, per-dept classes) ------
        _vet("VETID", "Department of Infectious Diseases",
             ["Microbiology", "Immunology"], "infectious-diseases-2"),
        _vet("VETPP", "Department of Physiology and Pharmacology",
             ["Physiology", "Pharmacology"], "physiology-and-pharmacology"),
        _vet("VETPATH", "Department of Pathology", ["Pathology"], "pathology"),
        _vet("VETBIO", "Department of Biomedical Sciences",
             ["Biomedical Sciences"], "biomedical-sciences"),
        _vet("VETSAM", "Department of Small Animal Medicine and Surgery",
             ["Veterinary Medicine"], "small-animal-medicine-surgery"),
        _vet("VETLAM", "Department of Large Animal Medicine",
             ["Veterinary Medicine"], "large-animal-medicine"),
        _vet("VETPH", "Department of Population Health",
             ["Veterinary Medicine", "Public Health"], "population-health-2"),
        # ---- School of Law (Drupal views table, 5 pages, lax TLS chain) -------
        {
            "short": "LAW", "name": "School of Law", "majors": ["Law"],
            "directory_url": "https://www.law.uga.edu/faculty-directory",
            "scrape": {
                "url": "https://www.law.uga.edu/faculty-directory",
                # The host serves an incomplete TLS chain (missing InCommon
                # intermediate) — a verifying GET dies with a cert error.
                "insecure": True,
                "selectors": {"card": "table tr:has(td.views-field-title)",
                              "name": "td.views-field-title > a[href^='/profile/']",
                              "link": "td.views-field-title > a[href^='/profile/']",
                              # Rank is bare text between the name link and the
                              # mailto — no element of its own.
                              "title_html_re": r"</a>\s*<br\s*/?>\s*(.*?)<br",
                              "email": "a[href^='mailto:']"},
                "paginate": {"param": "page", "start": 1, "max": 5},
                # 87/137 rows are emeriti/adjuncts/instructors/librarians —
                # the require gate is the roster.
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"emerit|adjunct|visiting|\binstructor\b|"
                                          r"librarian|part-\s?time|lecturer|of practice"},
            },
        },
        # ---- College of Environment and Design ---------------------------------
        {
            "short": "CED", "name": "College of Environment and Design",
            "majors": ["Landscape Architecture", "Historic Preservation",
                       "Urban Planning"],
            "directory_url": "https://ced.uga.edu/about/people/",
            "scrape": {
                "url": "https://ced.uga.edu/about/people/",
                # Retirees outnumber active faculty here (32 vs 29) but carry
                # their own retired-emeritus-faculty class — scope to .faculty.
                "selectors": {"card": "div.element-item.faculty",
                              "name": "p.team_member_title a",
                              "link": "p.team_member_title a",
                              "title": "p.job_title", "email": "p.email a"},
                "ladder_filter": _UGA_LADDER,
            },
        },
        # ---- Terry College of Business (WP REST API; site itself is walled) ---
        _terry("ACCT", "J.M. Tull School of Accounting", ["Accounting"], 141),
        _terry("ECON", "Department of Economics", ["Economics"], 120),
        _terry("FINA", "Department of Banking and Finance", ["Finance"], 127),
        _terry("ILSRE", "Department of Insurance, Legal Studies and Real Estate",
               ["Risk Management and Insurance", "Real Estate"], 695),
        _terry("MGMT", "Department of Management", ["Management"], 131),
        _terry("MIS", "Department of Management Information Systems",
               ["Management Information Systems"], 124),
        _terry("MARK", "Department of Marketing", ["Marketing"], 135),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
