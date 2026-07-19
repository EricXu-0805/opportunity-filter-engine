"""Penn State University Park faculty config (via the faculty_graph engine).

Eight server-rendered markup families, live-verified 2026-07-18 (no WAF at a
plain Chrome UA anywhere except the College of Education — see deferred):

* Eberly College of Science central Drupal people view (``science.psu.edu/
  people`` faceted by ``person_type=47`` = Faculty + ``department=``;
  ``items_per_page=200`` covers every dept on one page). The richest listing
  on campus: mailto email AND clean comma-separated research-interest tags on
  the cards themselves — no profile pass needed. Some emeriti keep type 47,
  so a title drop-regex prunes them; joint appointments (a BMB/Physics
  professor listed under both facets) collapse via the engine's URL dedupe.

* College of Engineering shared ``.aspx`` template (``www.<dept>.psu.edu/
  department/faculty-list.aspx``; EECS hosts both CSE and EE lists under
  ``/departments/``, Acoustics uses ``/people/faculty.aspx``). Emeritus/
  adjunct/affiliate rosters live on separate pages, so the faculty list is
  pre-gated. Cards carry mailto emails; profiles (``directory-detail-g.aspx
  ?q=<netid>``) keep a clean semicolon-separated research list in
  ``#idDetail_lbl_Research`` → profile_enrich.

* College of Earth & Mineral Sciences Drupal tables (matse/eme/geosc/geog/
  met ``.psu.edu``) — tenure-line facets (``?tid_1=106``) or dedicated
  tenure-line pages. One merged ``<td>`` holds name-link, title, department,
  office, phone, and mailto as ``<br>``-separated TEXT, so the rank is
  extracted with ``title_re`` (misses fall back to "Professor" — safe: the
  pages are tenure-line-only by construction; the regex does catch the
  "Emeritus -" stragglers so the ladder gate can drop them). Geography's
  table uniquely carries an "Expertise:" keyword list per row →
  ``research_re_text``. One listing email has a typo (``whb2@psu,.edu``) —
  the email selector's ``:not([href*=','])`` guard skips it rather than ship
  a corrupt address. Profiles keep clean research tags in
  ``.field--name-field-research-interests .field__item`` → profile_enrich.

* Shared "directory-card" CMS (IST, Bellisario Communications, Arts &
  Architecture): one server-rendered page per college, name/title/mailto per
  card (``ul.directory-title-list li``), deans/staff mixed in → require-gate.
  IST profiles expose Pure fingerprint concepts (``span.pure-concept``) →
  profile_enrich; Arts/Bellisario profile research is unverified → email-only.

* College of Health & Human Development ``staff-item`` teasers
  (``hhd.psu.edu/<dept>/contact/faculty-staff``): faculty and staff mixed on
  one page, email as plain text on the card; title require-gate separates.
  Profile research is NOT structured (checked) — no research enrich.

* College of the Liberal Arts per-department WordPress REST
  (``*.la.psu.edu/wp-json/wp/v2/people`` — English uses the ``directory``
  CPT), filtered by the per-site ``classifications`` Faculty term id
  (psych 10 / econ 41 / polisci 15 / sociology tenure-track 20 / english 26;
  grads, postdocs, and staff are separate terms = the ladder gate). Keywords
  come from each site's research-area taxonomy (``program-areas`` /
  ``research-areas`` / ``areas-of-concentration`` / ``specializations``);
  emails live only on profile pages → dept-level profile_enrich.

* Smeal College of Business PHP directory (``directory.smeal.psu.edu/faculty/
  ?dept=<slug>`` per department; the root page shows letter A only). Cards
  are "Last, First" + mailto but NO academic title, and staff ride the same
  listing — so the ladder gate can only run after an always-on per-profile
  title pass (``p.dir-titles`` + ``ladder_recheck``; ~234 extra fetches per
  deep run, the recon-documented N+1 cost of this family). Profile research
  is prose — not scraped.

* College of Agricultural Sciences Plone mega-page (``agsci.psu.edu/
  directory/faculty``: 471 bios, 1.5 MB, one URL) with name, full title
  list, mailto, AND a clean "Areas of Expertise" ``<ul>`` per person on the
  listing itself. Emeriti and extension staff share the page → require-gate
  on the full title ``<ul>`` (the professor rank is often the second ``<li>``).

* College of Nursing WordPress (``www.nursing.psu.edu/directory/``): role
  facets ride the card class list (keep class token ``faculty``); no listing
  email. Profiles carry a labelled Research Interests bullet list
  (``h5 ~ ul li``) and a mailto → profile_enrich.

Single source ("psu_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (from the 2026-07-18 recon):
* College of Education (ed.psu.edu) — Cloudflare interactive challenge
  (HTTP 403, ``cf-mitigated: challenge``) on every curl variant; needs a
  headless-browser pass.
* Penn State College of Medicine (Hershey) — separate campus and OpenAlex
  org, clinician-heavy; out of scope for the University Park pass.
* Penn State Law / Dickinson Law — separate law-school sites, not probed.
* Liberal Arts remaining depts (History, Philosophy, CAS, German, French,
  Spanish/Italian/Portuguese, Anthropology, AAAS, CAMS, Asian Studies, WGSS,
  Labor & Employment Relations) — same WP family but the per-site Faculty
  classification term ids are unmapped (history's classifications endpoint
  404s; the anthropology subdomain doesn't resolve); mechanical per-site
  mapping next pass.
* EMS non-tenure-line facets (``tid_1=107`` / research-teaching directory
  pages) — only the recon-verified tenure-line rosters are wired.
* Ag Sciences per-department sites (ento/animalscience/foodscience/…) —
  redundant: the central directory carries all 471 bios with departments.
* Applied Research Laboratory — defense lab, no public faculty directory
  relevant to undergrad matching.
* Huck Institutes of the Life Sciences — intercollege institute; faculty are
  cross-listed in home departments already covered.
* HHD + Smeal profile research — prose/unstructured (no clean list to
  scrape); research for those colleges comes from the OpenAlex pass.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Eberly College of Science central people view -------------------------
_EBERLY_SELECTORS = {
    "card": "div.faculty-card",
    "name": ".views-field-field-name a",
    "link": ".views-field-field-name a",
    "title": ".views-field-field-staff-title .field-content",
    "email": ".views-field-field-email a[href^='mailto:']",
    # Clean comma-separated research tags on the listing card itself.
    "research": ".views-field-field-res .field-content",
}

# person_type=47 is already the Faculty facet, but some emeriti keep it.
_LADDER = {"drop": r"emerit|visiting"}


def _eberly(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    url = (f"https://science.psu.edu/people?person_type=47&department={dept_id}"
           f"&unit=All&items_per_page=200")
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _EBERLY_SELECTORS,
                       "ladder_filter": _LADDER}}


# ---- College of Engineering shared .aspx template --------------------------
_ENGR_SELECTORS = {
    "card": "div.results-individual-revised",
    "name": "p.name a",
    "link": "p.name a",
    "title": "p:nth-of-type(2)",
    "email": "a[href^='mailto:']",
}

# faculty-list.aspx excludes emeritus/adjunct/affiliate (separate pages).
_LADDER_ENGR = {"drop": r"emerit|adjunct|affiliate|visiting"}

# Profile keeps "Research Areas:" as a clean semicolon list in a stable span;
# the first profile mailto is the person, the second is webmaster@engr.
_ENGR_ENRICH = {
    "research_selector": "#idDetail_lbl_Research",
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^[^@]*$|webmaster@",
    "throttle": 0.2,
}


def _engr(short: str, name: str, majors: list[str], host: str,
          path: str = "/department/faculty-list.aspx") -> dict:
    url = f"https://www.{host}.psu.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _ENGR_SELECTORS,
                       "ladder_filter": _LADDER_ENGR,
                       "profile_enrich": _ENGR_ENRICH}}


# ---- College of Earth & Mineral Sciences Drupal tables ---------------------
# One merged <td> holds "Name<br>Title<br>Department<br>Office<br>Phone<br>
# email" as text, so the rank comes out via title_re: capture from the first
# rank/role word up to a stop token (department-name variants, an email, a
# room number, geog's "Expertise:", or end). "Emeritus - Atherton Professor"
# rows keep the Emeritus marker in the capture so the ladder drop fires.
_EMS_TITLE_RE = (
    r"\b("
    r"(?:Emerit\w+\s*[-–]\s*)?"
    r"(?:Department Head|Head of Department"
    r"|(?:Associate|Assistant|Interim) (?:Department )?Head[\w ,()&/-]*?"
    r"|Undergraduate Program Chair[\w ,]*?"
    # Rank-modifier whitelist (NOT a generic capitalized-word prefix — that
    # would eat the person's name, which precedes the rank in the same text).
    r"|(?:(?:Evan Pugh|Atherton|University|Distinguished|Associate|Assistant"
    r"|Interim|Teaching|Research|Clinical|Visiting|Senior|Emerit\w+) )*"
    r"(?:Professor|Lecturer)(?:[ -]Emerit\w+)?"
    r"(?: (?:of|in|and) [\w &,()'/-]+?)*)"
    r")"
    r"(?=\s*(?:;|John and Willie|John A\. Dutton|Department of|College of"
    r"|School of|Institute|Expertise:|[\w.+-]+@[\w.-]+|\d)|\s*$)"
)

_EMS_SELECTORS = {
    "card": "tr",
    "name": "td.views-field-field-directory-last-name a[href*='/directory/']",
    "link": "td.views-field-field-directory-last-name a[href*='/directory/']",
    "title_re": _EMS_TITLE_RE,
    # :not guard: one met.psu.edu listing address is typo'd "whb2@psu,.edu" —
    # better no email than a corrupt one.
    "email": "td a[href^='mailto:']:not([href*=','])",
}

# Profiles carry clean research-interest tags (one .field__item per area).
_EMS_ENRICH = {
    "research_items_selector": ".field--name-field-research-interests .field__item",
    "email_selector": "a[href^='mailto:']",
    "email_drop": r"^[^@]*$|,",
    "throttle": 0.2,
}


def _ems(short: str, name: str, majors: list[str], url: str,
         research_re_text: str | None = None) -> dict:
    selectors = dict(_EMS_SELECTORS)
    if research_re_text:
        selectors["research_re_text"] = research_re_text
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": selectors,
                       "ladder_filter": _LADDER,
                       "profile_enrich": _EMS_ENRICH}}


# ---- Shared "directory-card" CMS (IST / Bellisario / Arts & Architecture) --
_DIRCARD_SELECTORS = {
    "card": "div.directory-card",
    "name": ".directory-details h3 a",
    "link": ".directory-details h3 a",
    "title": "ul.directory-title-list li",
    "email": ".directory-details a[href^='mailto:']",
}

# These pages mix deans/advisers (Bellisario), part-time adjunct instructors
# (IST), affiliated professors (cross-listed from their home college, which
# already ships them), and staff into the Faculty facet — full require+drop.
_LADDER_TITLED = {"require": r"\bprofessor\b|\blecturer\b",
                  "drop": r"emerit|adjunct|visiting|affiliat"}


def _dircard(short: str, name: str, majors: list[str], url: str,
             enrich: dict | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": _DIRCARD_SELECTORS,
                    "ladder_filter": _LADDER_TITLED}
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


# ---- College of Health & Human Development staff-item teasers --------------
_HHD_SELECTORS = {
    "card": "div.staff-item.teaser",
    "name": ".staff-item__info__name a span",
    "link": ".staff-item__info__name a",
    "title": ".staff-item__info__titles",
    "email": ".staff-item__info__email",
}


def _hhd(short: str, name: str, majors: list[str], slug: str) -> dict:
    url = f"https://hhd.psu.edu/{slug}/contact/faculty-staff"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _HHD_SELECTORS,
                       "ladder_filter": _LADDER_TITLED}}


# ---- College of the Liberal Arts WordPress REST ----------------------------
def _la(short: str, name: str, majors: list[str], base: str, faculty_term: int,
        kw_tax: str, kw_drop: list[str] | None = None,
        post_type: str = "people") -> dict:
    url = f"{base}/wp-json/wp/v2/{post_type}?classifications={faculty_term}&per_page=100"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "api": {
            "type": "wp",
            "base": base,
            "post_type": post_type,
            # Server-side trim (grads/staff are other terms) + authoritative
            # include filter on the returned taxonomy field.
            "query": f"&classifications={faculty_term}",
            "category_include": {"classifications": [faculty_term]},
            "keyword_tax": [kw_tax],
            "keyword_drop": kw_drop or [],
        },
        # Emails live only on profile pages (first mailto = the person).
        "profile_enrich": {
            "email_selector": "a[href^='mailto:']",
            "email_drop": r"^[^@]*$",
            "throttle": 0.2,
        },
    }


# ---- Smeal College of Business PHP directory -------------------------------
# No academic title on the listing and staff share it, so the ladder gate
# runs AFTER an always-on per-profile title pass (p.dir-titles).
_SMEAL_ENRICH = {
    "always": True,
    "title_selector": "p.dir-titles",
    "throttle": 0.15,
    "ladder_recheck": {"require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
                       "drop": r"emerit|visiting"},
}


def _smeal(short: str, name: str, majors: list[str], dept: str) -> dict:
    url = f"https://directory.smeal.psu.edu/faculty/?dept={dept}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "div.media-body",
                                     "name": "strong.media-heading a",
                                     "link": "strong.media-heading a",
                                     "email": "a[href^='mailto:']"},
                       "name_flip": True,
                       "profile_enrich": _SMEAL_ENRICH}}


SCHOOL: dict = {
    "school_slug": "psu",
    "source": "psu_faculty",
    "organization": "Penn State University Park",
    "location": "University Park, PA",
    "id_prefix": "psu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Penn State University Park) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Eberly College of Science --------------------------------------
        _eberly("PHYS", "Department of Physics", ["Physics"], 16),
        _eberly("ASTRO", "Department of Astronomy and Astrophysics",
                ["Astronomy and Astrophysics", "Physics"], 11),
        _eberly("BMB", "Department of Biochemistry and Molecular Biology",
                ["Biochemistry and Molecular Biology", "Biology"], 12),
        _eberly("BIO", "Department of Biology", ["Biology"], 13),
        _eberly("CHEM", "Department of Chemistry", ["Chemistry"], 14),
        _eberly("MATH", "Department of Mathematics", ["Mathematics"], 15),
        _eberly("STAT", "Department of Statistics", ["Statistics", "Data Sciences"], 17),
        # ---- College of Engineering -----------------------------------------
        _engr("CSE", "Department of Computer Science and Engineering (School of EECS)",
              ["Computer Science", "Computer Engineering", "Data Sciences"],
              "eecs", path="/departments/cse-faculty-list.aspx"),
        _engr("EE", "Department of Electrical Engineering (School of EECS)",
              ["Electrical Engineering", "Computer Engineering"],
              "eecs", path="/departments/ee-faculty-list.aspx"),
        _engr("ME", "Department of Mechanical Engineering", ["Mechanical Engineering"], "me"),
        _engr("BME", "Department of Biomedical Engineering", ["Biomedical Engineering"], "bme"),
        _engr("AERSP", "Department of Aerospace Engineering", ["Aerospace Engineering"], "aero"),
        _engr("CHE", "Department of Chemical Engineering", ["Chemical Engineering"], "che"),
        _engr("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"], "cee"),
        _engr("ESM", "Department of Engineering Science and Mechanics",
              ["Engineering Science", "Mechanical Engineering"], "esm"),
        _engr("NUCE", "Ken and Mary Alice Lindquist Department of Nuclear Engineering",
              ["Nuclear Engineering"], "nuce"),
        _engr("AE", "Department of Architectural Engineering", ["Architectural Engineering"], "ae"),
        _engr("IME", "Department of Industrial and Manufacturing Engineering",
              ["Industrial Engineering"], "ime"),
        _engr("SEDI", "School of Engineering Design and Innovation",
              ["Engineering Design", "Mechanical Engineering"], "sedi"),
        _engr("ACS", "Graduate Program in Acoustics", ["Acoustics", "Mechanical Engineering"],
              "acs", path="/people/faculty.aspx"),
        # ---- College of Earth and Mineral Sciences --------------------------
        _ems("MATSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "https://www.matse.psu.edu/about/who-we-are/directory?tid_1=106"),
        _ems("EME", "John and Willie Leone Family Department of Energy and Mineral Engineering",
             ["Petroleum and Natural Gas Engineering", "Energy Engineering",
              "Energy Business and Finance"],
             "https://www.eme.psu.edu/directory/faculty"),
        _ems("GEOSC", "Department of Geosciences", ["Geosciences"],
             "https://www.geosc.psu.edu/about/who-we-are/directory?tid_1=106"),
        _ems("GEOG", "Department of Geography", ["Geography"],
             "https://www.geog.psu.edu/about/our-people/tenure-line-directory",
             research_re_text=r"Expertise:\s*(.+?)\s*$"),
        _ems("METEO", "Department of Meteorology and Atmospheric Science",
             ["Meteorology and Atmospheric Science"],
             "https://www.met.psu.edu/people/directory/tenure-line-faculty"),
        # ---- IST / Communications / Arts & Architecture ---------------------
        _dircard("IST", "College of Information Sciences and Technology",
                 ["Information Sciences and Technology", "Data Sciences",
                  "Cybersecurity Analytics and Operations",
                  "Human-Centered Design and Development"],
                 "https://ist.psu.edu/about/directory/faculty",
                 enrich={"research_items_selector": ".pure-expertise-list .pure-concept",
                         "email_selector": ".directory-details a[href^='mailto:']",
                         "email_drop": r"^[^@]*$",
                         "throttle": 0.2}),
        _dircard("COMM", "Donald P. Bellisario College of Communications",
                 ["Journalism", "Advertising/Public Relations", "Film Production",
                  "Telecommunications and Media Industries"],
                 "https://bellisario.psu.edu/people/faculty"),
        _dircard("AA", "College of Arts and Architecture",
                 ["Architecture", "Landscape Architecture", "Graphic Design",
                  "Music", "Theatre", "Art History"],
                 "https://arts.psu.edu/directory/faculty"),
        # ---- Smeal College of Business --------------------------------------
        _smeal("ACCTG", "Department of Accounting (Smeal)", ["Accounting"], "acctg"),
        _smeal("FIN", "Department of Finance (Smeal)", ["Finance"], "finance"),
        _smeal("MGMT", "Department of Management and Organization (Smeal)",
               ["Management"], "mgmt"),
        _smeal("MKTG", "Department of Marketing (Smeal)", ["Marketing"], "mktg"),
        _smeal("SCIS", "Department of Supply Chain and Information Systems (Smeal)",
               ["Supply Chain and Information Systems"], "scis"),
        _smeal("RM", "Department of Risk Management (Smeal)", ["Risk Management"], "rm"),
        _smeal("BIRES", "Borrelli Institute for Real Estate Studies (Smeal)",
               ["Real Estate"], "BIRES"),
        # ---- College of Agricultural Sciences (central bio directory) -------
        {
            "short": "AG", "name": "College of Agricultural Sciences",
            "majors": ["Animal Science", "Food Science", "Plant Science",
                       "Forest Ecosystem Management", "Agribusiness Management",
                       "Agricultural and Biological Engineering",
                       "Veterinary and Biomedical Sciences"],
            "directory_url": "https://agsci.psu.edu/directory/faculty",
            "scrape": {
                "url": "https://agsci.psu.edu/directory/faculty",
                "selectors": {
                    "card": "div.container.border-bottom.bio",
                    "name": "div.vcard h2 a",
                    "link": "div.vcard h2 a",
                    # The professor rank is often the SECOND <li> (admin roles
                    # first) — gate on the whole title list.
                    "title": "ul.title.jobTitle",
                    "email": "ul.list-bio-contact a[href^='mailto:']",
                    # The "Areas of Expertise" list here is free-text prose
                    # ("Extension and advisory systems for developing countries"),
                    # not clean topical tags — leave keywords to the OpenAlex
                    # enrichment pass rather than poison them with sentences.
                },
                "ladder_filter": _LADDER_TITLED,
            },
        },
        # ---- College of Health and Human Development ------------------------
        _hhd("BBH", "Department of Biobehavioral Health", ["Biobehavioral Health"], "bbh"),
        _hhd("CSD", "Department of Communication Sciences and Disorders",
             ["Communication Sciences and Disorders"], "csd"),
        _hhd("HDFS", "Department of Human Development and Family Studies",
             ["Human Development and Family Studies"], "hdfs"),
        _hhd("HPA", "Department of Health Policy and Administration",
             ["Health Policy and Administration"], "hpa"),
        _hhd("KINES", "Department of Kinesiology", ["Kinesiology"], "kines"),
        _hhd("NUTR", "Department of Nutritional Sciences", ["Nutritional Sciences"],
             "nutrition"),
        _hhd("RPTM", "Department of Recreation, Park, and Tourism Management",
             ["Recreation, Park, and Tourism Management"], "rptm"),
        _hhd("SHM", "School of Hospitality Management", ["Hospitality Management"], "shm"),
        # ---- College of the Liberal Arts ------------------------------------
        _la("PSYCH", "Department of Psychology", ["Psychology"],
            "https://psych.la.psu.edu", 10, "program-areas",
            kw_drop=["classification-subpage", "Clinical Faculty",
                     "Research Faculty", "Teaching", "Teaching Faculty"]),
        _la("ECON", "Department of Economics", ["Economics"],
            "https://econ.la.psu.edu", 41, "research-areas",
            kw_drop=["Teaching Faculty - Publications", "Teaching Faculty - Research"]),
        _la("PLSC", "Department of Political Science", ["Political Science"],
            "https://polisci.la.psu.edu", 15, "research-areas"),
        _la("SOC", "Department of Sociology and Criminology",
            ["Sociology", "Criminology"],
            "https://sociology.la.psu.edu", 20, "areas-of-concentration"),
        _la("ENGL", "Department of English", ["English"],
            "https://english.la.psu.edu", 26, "specializations",
            post_type="directory"),
        # ---- Ross and Carol Nese College of Nursing -------------------------
        {
            "short": "NURS", "name": "Ross and Carol Nese College of Nursing",
            "majors": ["Nursing"],
            "directory_url": "https://www.nursing.psu.edu/directory/",
            "scrape": {
                "url": "https://www.nursing.psu.edu/directory/",
                # Role facets ride the card class list; keep 'faculty' cards
                # (staff/emeritus tokens mark the others).
                "selectors": {"card": "div.faculty-member.faculty",
                              "name": "h2", "link": "a", "title": "h3"},
                "ladder_filter": _LADDER_TITLED,
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "research_items_selector":
                        "h5:-soup-contains('Research Interests') ~ ul li",
                    "throttle": 0.2,
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
