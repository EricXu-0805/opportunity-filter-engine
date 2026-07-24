"""University of Cincinnati faculty config (via the faculty_graph engine).

Full university-wide coverage across six colleges. Three markup families:

* **Shared UC AEM "contact" people card (the workhorse).** Arts & Sciences
  (artsci.uc.edu), Engineering & Applied Science (ceas.uc.edu), DAAP
  (daap.uc.edu), and CECH (cech.uc.edu) all run the same webcentral/eprof AEM
  component: each person is a ``div.contact-item`` with an ``h3.name`` (a trailing
  ``<span>,</span>`` the ``name_strip`` regex removes), a rank in ``h4.title``
  (CEAS/DAAP/CECH skin) or ``span.title`` (A&S natural-sciences skin), a
  ``p.email > a`` plain ``mailto:``, and an ``a.btn-red`` →
  ``researchdirectory.uc.edu/p/<username>`` profile link. A SECOND skin,
  ``div.contact-card``, holds only the Emeritus / Postdoc / Research-Associate /
  staff roster (doubled desktop+mobile copies), so the card selector is
  deliberately ``div.contact-item`` ONLY. Records land name + title + email in
  one pass (~99% email, no per-profile crawl). The ``field_filter``
  (``require_present`` + ``include`` professor|lecturer) is ESSENTIAL: these
  listings mix in graduate assistants, postdocs, research associates, department
  staff, and adjunct instructors, and UC lists its EMERITI with a *blank* title
  cell — a plain ``ladder_filter`` would default those to "Professor" and inject
  them, so ``require_present`` reads the title element directly and drops the
  title-less card. ``include`` keeps only Professor / Lecturer ranks (ladder +
  Educator-track + research + endowed-chair rows carrying "Professor"); the
  engine's own ``_RETIRED_TITLE_RE`` drops the labelled "Professor Emeritus".

* **Carl H. Lindner College of Business — AEM prose blocks.** business.uc.edu
  renders each person NOT as a card but as one ``<div class="component text">
  <p>`` block: a bold profile link (``b a``) whose text carries credentials the
  ``name_strip`` trims ("Nan Zhou, PhD" → "Nan Zhou"), the rank as loose
  ``<br>``-separated text (recovered with ``title_re``), and a ``mailto:``.
  People are grouped under ``<h2>`` section headings — "Department Head",
  "Faculty", "Part-Time Faculty", "Emeriti" — so a ``section_filter`` keeps only
  the first two (dropping the adjunct part-timers and emeriti), and a
  ``ladder_filter`` additionally drops any postdoctoral fellow whose "Faculty"-
  section row would otherwise default to "Professor". Active endowed-chair rows
  with no rank word ("Endowed Chairholder") correctly default to "Professor" and
  stay. Six departments; ~99% email.

* **College of Nursing — server-rendered HTML tables.** nursing.uc.edu publishes
  its roster as ``table.table-striped`` grids (Name / Title / plaintext-Email
  columns) grouped by administrative office. The card is the ``<tr>``; the name
  cell carries heavy clinical credentials the ``name_strip`` trims ("Alicia
  Ribar, PhD, APRN, FNP-BC" → "Alicia Ribar"); the email is plaintext in the
  third cell (``_clean_email`` reads it). A ``ladder_filter`` (require
  professor|lecturer) keeps the ranked faculty scattered across the office tables
  and drops the deans, coordinators, advisors, and other staff.

Neuroscience is a cross-listed A&S program with no dedicated reachable roster
(its faculty-staff.html is a bare landing page) — DROPPED; the "Neuroscience"
major rides Psychology + Biological Sciences instead. Geography, and the A&S
humanities/social-science departments outside the catalog (History, Philosophy,
Anthropology, Journalism, Africana, Women's/Gender studies), are out of the
catalog's college/major scope and left unwired. UC Economics is housed in the
Lindner business college, so it is wired there (covering the A&S "Economics"
major). DAAP publishes only a single college-wide directory (no per-school
roster), so it is wired as one college-level department across its five majors.

Single source ("cincinnati_faculty"); department rides each record, ids
namespaced by department short-code.

Live-verified 2026-07-24 (deep=True, listing scrape, kept-after-gate / email):
CS 41/41, ECE 30/30, ME 36/36, Aerospace 15/15, BME 49/46, ChemE 25/25,
Civil 27/27, Physics 30/30, Chemistry 31/31, Math 72/72, Biology 26/26,
Geosciences 18/18, Psychology 43/43, Sociology 22/22, Communication 50/50,
Political Science 32/32, Environment & Sustainability 47/47, English 67/67,
DAAP 98/98, Criminal Justice 20/20, Education 72/72, Human Services 38/38,
Information Technology 42/42, Accounting 14/14, Economics 8/8, Finance 19/18,
Management 25/25, Marketing 19/19, OBAIS 33/33, Nursing 39/39.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Shared UC AEM contact-item people card ---------------------------------
# One selector set spans every college skin: CEAS/DAAP/CECH keep the rank in
# ``h4.title``, A&S natural-sciences in ``span.title`` (beside a ``span.department``
# sibling the selector avoids). The ``h3.name`` wraps a trailing ``<span>,</span>``
# that ``name_strip`` removes. The card selector is ``div.contact-item`` ONLY — the
# ``div.contact-card`` skin holds just the emeriti/postdoc/staff roster (doubled).
_SEL = {
    "card": "div.contact-item",
    "name": "h3.name",
    "name_strip": r"\s*,\s*$",
    "link": "a.btn-red[href*='researchdirectory.uc.edu/p/']",
    "title": "h4.title, span.title",
    "email": "p.email a[href^='mailto:']",
}
# Keep Professors (ladder + Educator-track + research + endowed-chair rows
# carrying "Professor") and Lecturers; drop grad students, postdocs, research
# associates, staff, adjunct instructors, and title-less emeriti cards. A
# field_filter (not ladder_filter) with require_present is REQUIRED so UC's
# title-less emeriti cards can't default to "Professor" and inject themselves.
_FIELD = {
    "selector": "h4.title, span.title",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UC contact-item people component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


# ---- Lindner College of Business: AEM prose blocks --------------------------
# Each person is one ``<div class="component text"><p>`` block: a bold profile
# link (name + credentials), the rank as loose <br>-separated text, a mailto.
_BIZ_SEL = {
    "card": "div.component.text p",
    "name": "b a",
    "link": "b a",
    # Trim academic/professional post-nominals after the name ("Nan Zhou, PhD",
    # "Mark Bell, MBA, CPA") — UC business names carry them universally.
    "name_strip": (r"(?i),\s*(?:ph\.?d|cpa|mba|m\.?b\.?a|m\.?s\.?|macc|cfa|j\.?d"
                   r"|dba|cma|cfp|cia|md|esq|ed\.?d|cisa|cissp|cism|pmp|do)\b.*$"),
    "email": "a[href^='mailto:']",
    # Rank is loose text between <br> tags with no element of its own; capture the
    # professor/lecturer/educator rank (or a postdoctoral role, so the ladder gate
    # below can drop it). An active endowed-chair row with no rank word matches
    # nothing here and correctly defaults to "Professor".
    "title_re": (r"(?i)\b((?:Assistant |Associate |Visiting |Adjunct |Clinical "
                 r"|Field Service |Research )*(?:Professor|Lecturer|Instructor"
                 r"|Educator)|Postdoctoral(?:\s+[\w-]+){0,3})"),
}
# People are grouped under <h2> role headings: keep "Department Head" + "Faculty",
# drop the "Part-Time Faculty" (adjuncts) and "Emeriti" sections.
_BIZ_SECTION = {"heading": "h2", "exclude": r"emerit|part-time"}
# Belt-and-suspenders on the extracted rank: drop the lone postdoctoral fellow
# that would otherwise default to "Professor" inside the Faculty section.
_BIZ_LADDER = {"require": r"professor|lecturer|educator",
               "drop": r"emerit|adjunct|visiting|part-time|postdoc"}
_BIZ = "https://business.uc.edu/faculty-research"


def _biz(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A Lindner department on the shared AEM prose-block faculty page."""
    url = f"{_BIZ}/{slug}/faculty.html"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _BIZ_SEL,
                   "section_filter": _BIZ_SECTION, "ladder_filter": _BIZ_LADDER},
    }


# ---- College of Nursing: server-rendered HTML tables ------------------------
# Name / Title / plaintext-Email columns grouped by office; card is the <tr>.
_NURS_SEL = {
    "card": "table.table-striped tbody tr",
    "name": "td:nth-of-type(1)",
    "title": "td:nth-of-type(2)",
    "email": "td:nth-of-type(3)",
    # Clinical-nursing credentials trail the name ("Alicia Ribar, PhD, APRN,
    # FNP-BC, CNE") — trim from the first credential token.
    "name_strip": (r"(?i),\s*(?:ph\.?d|dnp|aprn|msn|bsn|rn|fnp[\w-]*|cne|md|apn"
                   r"|cnp|cns|ed\.?d|mba|do|faan|ccrn|np-c|whnp[\w-]*|pmhnp[\w-]*"
                   r"|acnp[\w-]*|ne-bc|cnl|phn).*$"),
}
_NURS_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|adjunct|visiting"}


def _nurs(short: str, name: str, majors: list[str], url: str) -> dict:
    """The nursing college roster on its shared table component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _NURS_SEL, "ladder_filter": _NURS_LADDER},
    }


_CEAS = "https://www.ceas.uc.edu/academics/departments"
_AS = "https://www.artsci.uc.edu"

SCHOOL: dict = {
    "school_slug": "cincinnati",
    "source": "cincinnati_faculty",
    "organization": "University of Cincinnati",
    "location": "Cincinnati, OH",
    "id_prefix": "cincinnati",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Cincinnati) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering & Applied Science (CEAS) --------------
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Data Science", "Cybersecurity"],
              f"{_CEAS}/computer-science/computer-science-people.html"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              f"{_CEAS}/electrical-computer-engineering/people.html"),
        _dept("ME", "Department of Mechanical and Materials Engineering",
              ["Mechanical Engineering", "Materials Science and Engineering"],
              f"{_CEAS}/mechanical-materials-engineering/People/"
              "mechanical-engineering-faculty.html"),
        _dept("AERO", "Department of Aerospace Engineering and Engineering Mechanics",
              ["Aerospace Engineering", "Engineering Mechanics"],
              f"{_CEAS}/aerospace-engineering-mechanics/people.html"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              f"{_CEAS}/biomedical-engineering/people.html"),
        _dept("CHEME", "Department of Chemical and Environmental Engineering",
              ["Chemical Engineering", "Environmental Engineering"],
              f"{_CEAS}/chemical-environmental-engineering/people.html"),
        _dept("CIVIL",
              "Department of Civil and Architectural Engineering and Construction Management",
              ["Civil Engineering", "Architectural Engineering",
               "Construction Management", "Environmental Engineering"],
              f"{_CEAS}/civil-architectural-engineering-construction-management/people.html"),
        # ---- College of Arts & Sciences (A&S) -----------------------------
        _dept("PHYS", "Department of Physics", ["Physics", "Astrophysics"],
              f"{_AS}/natural-sciences/physics/faculty-staff.html"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              f"{_AS}/natural-sciences/chemistry/faculty-and-staff-directory.html"),
        _dept("MATH", "Department of Mathematical Sciences",
              ["Mathematics", "Applied Mathematics", "Statistics"],
              f"{_AS}/natural-sciences/math/faculty-staff-students.html"),
        # Biology splits its ladder roster across two pages (no combined page):
        # tenure-track + educator-track, both the shared card, same display name.
        _dept("BIOL", "Department of Biological Sciences",
              ["Biological Sciences", "Neuroscience"],
              f"{_AS}/natural-sciences/biological-sciences/faculty-staff-students/tenure.html"),
        _dept("BIOLE", "Department of Biological Sciences",
              ["Biological Sciences", "Neuroscience"],
              f"{_AS}/natural-sciences/biological-sciences/faculty-staff-students/educator.html"),
        _dept("GEOL", "Department of Geosciences",
              ["Geology", "Earth Sciences", "Geography"],
              f"{_AS}/natural-sciences/geosciences/faculty.html"),
        _dept("PSYC", "Department of Psychology",
              ["Psychology", "Neuroscience"],
              f"{_AS}/natural-sciences/psychology/faculty-staff.html"),
        _dept("SOC", "Department of Sociology", ["Sociology"],
              f"{_AS}/social-sciences/sociology/faculty-staff-students.html"),
        _dept("COMM", "School of Communication, Film, and Media Studies",
              ["Communication"],
              f"{_AS}/social-sciences/communication-film-media/faculty-staff.html"),
        _dept("POLI", "School of Public and International Affairs",
              ["Political Science", "Public Administration", "International Affairs"],
              f"{_AS}/social-sciences/public-and-international-affairs/faculty-staff.html"),
        _dept("ENVS", "Department of Environment and Sustainability",
              ["Environmental Studies"],
              f"{_AS}/social-sciences/environment-and-sustainability/faculty-staff.html"),
        _dept("ENGL", "Department of English", ["English"],
              f"{_AS}/humanities/english/faculty-staff.html"),
        # ---- Carl H. Lindner College of Business (AEM prose blocks) -------
        _biz("ACCT", "Department of Accounting", ["Accounting"], "accounting"),
        _biz("ECON", "Department of Economics", ["Economics"], "economics"),
        _biz("FIN", "Department of Finance and Real Estate",
             ["Finance", "Real Estate"], "finance"),
        _biz("MGMT", "Department of Management",
             ["Management", "Entrepreneurship", "Operations Management"], "management"),
        _biz("MARK", "Department of Marketing", ["Marketing"], "marketing"),
        _biz("OBAIS",
             "Department of Operations, Business Analytics, and Information Systems",
             ["Information Systems", "Business Analytics", "Operations Management"],
             "obais"),
        # ---- College of Design, Architecture, Art & Planning (DAAP) -------
        # Only a single college-wide directory exists (no per-school roster).
        _dept("DAAP", "College of Design, Architecture, Art, and Planning",
              ["Architecture", "Industrial Design", "Communication Design",
               "Urban Planning", "Fine Arts", "Interior Design", "Fashion Design"],
              "https://daap.uc.edu/about/directory.html"),
        # ---- College of Education, Criminal Justice & Human Services ------
        _dept("CJ", "School of Criminal Justice", ["Criminal Justice"],
              "https://cech.uc.edu/schools/criminaljustice/employees.html"),
        _dept("EDUC", "School of Education",
              ["Early Childhood Education", "Education", "Special Education"],
              "https://cech.uc.edu/schools/education/faculty-and-staff.html"),
        _dept("HS", "School of Human Services",
              ["Sport Administration", "Health Promotion", "Human Services",
               "Substance Abuse Counseling"],
              "https://cech.uc.edu/schools/human-services/employees.html"),
        _dept("IT", "School of Information Technology",
              ["Information Technology", "Cybersecurity"],
              "https://cech.uc.edu/schools/it/people/people.html"),
        # ---- College of Nursing (HTML tables) -----------------------------
        _nurs("NURS", "College of Nursing", ["Nursing"],
              "https://nursing.uc.edu/about-us/faculty---staff-directory.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
