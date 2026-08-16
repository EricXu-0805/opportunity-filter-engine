"""Carleton College faculty config (via the faculty_graph engine).

Carleton is a top-10 US liberal arts college (~2,000 undergraduates, no
graduate school) in Northfield, Minnesota, with a national reputation in the
sciences and undergraduate research. Every academic department and program
publishes a faculty listing on the college-wide WordPress CMS at
``carleton.edu/<dept>/faculty/`` (a few depts use ``/faculty-staff/`` or
``/people/`` — resolved per entry). There is NO single college-wide faculty
directory that lists ranks, so a single scrape source with per-dept URLs covers
the whole college. Live-verified 2026-07-21 (all pages plain HTTP 200, no WAF,
no render mode).

Two markup generations coexist on the shared CMS, and ONE combined selector set
covers both (each person card only ever belongs to one generation, so the
comma-joined selectors resolve unambiguously per card):

* Newer template (``faculty-staff--*``): each person is a
  ``section.faculty-staff--members div.faculty-staff--item`` card — the name is
  the ``div.faculty-staff--name`` text (with a trailing "Bio" profile link and,
  for alumni, a class year like "’06" that ``name_strip`` removes),
  ``a.bio-link`` is the profile link (``/directory/<username>/``),
  ``div.faculty-staff--title`` carries the <br>-separated rank(s), and
  ``a.email-address`` the public ``mailto:``.
* Older template (``facStaff*``): ``div.facStaff`` cards with
  ``div.facStaffName`` (name + "Bio" link), ``div.facStaffTitle`` rank, and
  ``a.emailAddress`` email — the same information under camelCase class names.

Both are fully server-rendered and expose inline emails for most faculty, so
records ship with ``contact_email`` where published; topical enrichment comes
from OpenAlex (no env-gated profile pass — Carleton profile pages carry only a
free-prose bio, no structured research block).

Because these are "Faculty & Staff" pages, each list mixes teaching faculty
with lab managers, coordinators, technicians, research/educational associates,
and department administrators (whose titles carry no "professor"/"lecturer"/
"instructor"), plus emeriti and visiting appointments. The ladder filter keeps
professorial + lecturer + instructor ranks (the last covers Carleton's applied
-music lesson instructors and language associates) and drops emeriti, retirees,
visiting, adjunct, and postdoctoral appointments. Carleton professors are heavily
cross-listed onto interdisciplinary programs (Environmental Studies, the area
studies, Gender/Women's/Sexuality Studies, Cognitive Science, ...); the core
academic departments are listed FIRST so a cross-listed professor attributes to
a home department, and the engine's per-school url/email dedup collapses the
duplicates.

Single source ("carleton_faculty"); department rides each record's
``department``, ids namespaced by short-code. Audience "unknown".

Deferred: the pre-engineering (3-2 dual-degree) program and Interdisciplinary
Studies have no home faculty roster of their own (their contributors already
land via their home departments).
"""

from __future__ import annotations

from .. import faculty_graph

# Combined person-card selector spanning both CMS generations. Each card
# belongs to exactly one generation, so ``select_one`` inside a card resolves
# to that generation's element.
_SELECTORS = {
    "card": "section.faculty-staff--members div.faculty-staff--item, div.facStaff",
    "name": "div.faculty-staff--name, div.facStaffName",
    "link": "a.bio-link, div.facStaffName a",
    "title": "div.faculty-staff--title, div.facStaffTitle",
    "email": "a.email-address, a.emailAddress",
    # Names carry a trailing "Bio" profile-link label and, for alumni, an
    # apostrophe-year ("Rika Anderson ’06 Bio"); strip both, leaving names with
    # a legitimate apostrophe (O'Connell) untouched.
    "name_strip": r"\s*[’'][0-9]{2}(?=\s|$)|\s*Bio\s*$",
}

# Keep professorial + lecturer + instructor ranks; drop emeriti, visiting,
# adjunct, and postdoctoral appointments as well as the staff (lab manager /
# coordinator / technician / administrative assistant / research associate)
# whose titles carry none of the ladder words.
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
    "drop": r"emerit|retir|\bvisiting\b|\badjunct\b|postdoc",
}


# The listing carries no research. 276 of 294 people link to their own
# /directory/<netid>/ page; the remaining 18 carry the department listing URL
# their card sat on, which profile_url_re refuses so they are not "verified"
# against a roster.
_ENRICH = {
    "research_label_re": faculty_graph.RESEARCH_LABEL_RE,
    "profile_url_re": r"https://www\.carleton\.edu/directory/",
    "throttle": 0.15,
}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty") -> dict:
    """A Carleton department on the shared faculty-listing CMS template."""
    url = f"https://www.carleton.edu/{slug}/{path}/"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {"url": url, "selectors": _SELECTORS, "ladder_filter": _LADDER,
                   "profile_enrich": _ENRICH},
    }


SCHOOL: dict = {
    "school_slug": "carleton",
    "source": "carleton_faculty",
    "organization": "Carleton College",
    "location": "Northfield, MN",
    "id_prefix": "carleton",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Carleton College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics (listed first so cross-listed
        #      professors attribute to a home science department) -------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),
        _dept("BCHM", "Biochemistry Program", ["Biochemistry"], "biochemistry"),
        _dept("PHAS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics-astronomy"),
        _dept("MATH", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "math"),
        _dept("CS", "Department of Computer Science", ["Computer Science"],
              "computer-science"),
        _dept("GEOL", "Department of Geology", ["Geology"], "geology"),
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),
        _dept("NEUR", "Program in Neuroscience", ["Neuroscience"], "neuroscience"),
        _dept("COGS", "Program in Cognitive Science", ["Cognitive Science"],
              "cognitive-science"),
        _dept("ENTS", "Program in Environmental Studies",
              ["Environmental Studies"], "environmental-studies"),
        # ---- Social Sciences -----------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),
        _dept("POSC", "Department of Political Science and International Relations",
              ["Political Science", "International Relations"],
              "political-science", "faculty-staff"),
        _dept("SOAN", "Department of Sociology and Anthropology",
              ["Sociology", "Anthropology"], "sociology-anthropology"),
        _dept("EDUC", "Educational Studies Program", ["Educational Studies"],
              "educational-studies"),
        _dept("PPOL", "Public Policy Program", ["Public Policy"], "public-policy"),
        _dept("ARCN", "Program in Archaeology", ["Archaeology"], "archaeology"),
        # ---- Humanities ----------------------------------------------------
        _dept("ENGL", "Department of English", ["English", "Creative Writing"],
              "english"),
        _dept("HIST", "Department of History", ["History"], "history"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy",
              "people"),
        _dept("RELG", "Department of Religion", ["Religion"], "religion"),
        _dept("CLAS", "Department of Classics", ["Classics", "Greek", "Latin"],
              "classics"),
        _dept("LING", "Program in Linguistics", ["Linguistics"], "linguistics"),
        # ---- Arts ----------------------------------------------------------
        _dept("ARTH", "Department of Art and Art History",
              ["Studio Art", "Art History"], "art"),
        _dept("MUSC", "Department of Music", ["Music"], "music"),
        _dept("THEA", "Department of Theater and Dance", ["Theater", "Dance"],
              "theater-dance"),
        _dept("CAMS", "Program in Cinema and Media Studies",
              ["Cinema and Media Studies"], "cinema-media-studies", "faculty-staff"),
        # ---- Languages & Literatures ---------------------------------------
        _dept("FREN", "Department of French and Francophone Studies",
              ["French", "Francophone Studies"], "french"),
        _dept("SPAN", "Department of Spanish", ["Spanish"], "spanish"),
        _dept("GERM", "Department of German", ["German"], "german"),
        _dept("RUSS", "Department of Russian", ["Russian"], "russian"),
        _dept("ARBC", "Arabic", ["Arabic"], "arabic"),
        _dept("HEBR", "Hebrew", ["Hebrew"], "hebrew"),
        _dept("ASLN", "Asian Languages and Literatures",
              ["Chinese", "Japanese"], "asian-languages"),
        _dept("MELG", "Middle Eastern Languages", ["Middle Eastern Languages"],
              "middle-eastern-languages"),
        # ---- Interdisciplinary / Area Studies programs (listed after the
        #      home departments so cross-listed professors attribute upstream)
        _dept("AFAM", "Program in Africana Studies", ["Africana Studies"],
              "africana-studies"),
        _dept("AMST", "Program in American Studies", ["American Studies"],
              "american-studies"),
        _dept("ASST", "Program in Asian Studies", ["Asian Studies"],
              "asian-studies"),
        _dept("CCST", "Program in Cross-Cultural Studies",
              ["Cross-Cultural Studies"], "cross-cultural-studies", "faculty-staff"),
        _dept("DAH", "Program in Digital Arts and Humanities",
              ["Digital Arts and Humanities"], "digital-arts-humanities",
              "faculty-staff"),
        _dept("EUST", "Program in European Studies", ["European Studies"],
              "european-studies"),
        _dept("JUDA", "Program in Judaic Studies", ["Judaic Studies"],
              "judaic-studies"),
        _dept("LTAM", "Program in Latin American Studies",
              ["Latin American Studies"], "latin-american-studies"),
        _dept("MARS", "Program in Medieval and Renaissance Studies",
              ["Medieval and Renaissance Studies"], "medieval-renaissance-studies"),
        _dept("MEST", "Program in Middle East Studies", ["Middle East Studies"],
              "middle-east-studies"),
        _dept("GWSS", "Program in Gender, Women's, and Sexuality Studies",
              ["Gender, Women's, and Sexuality Studies"],
              "gender-womens-sexuality-studies"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
