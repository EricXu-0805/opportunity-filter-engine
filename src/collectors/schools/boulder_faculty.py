"""CU Boulder faculty config (via the faculty_graph engine).

One markup family for the whole campus: CU Experts (experts.colorado.edu), the
university's VIVO research-information system, server-renders every
department's roster on its ``/display/deptid_N`` page as role-grouped
``li.subclass`` sections. The anchored ``^faculty position$`` section gate
drops the sibling "faculty administrative position" / "other researchers and
staff" groups; the rank rides as loose text after the name anchor ("Evans,
John A</a>, Associate Professor"), captured by a last-comma ``title_re``
(names hold exactly one comma in "Last, First M" form) and ladder-gated —
Adjoint (CU's adjunct-equivalent), clinical, visiting, and attendant ranks
ride the same section. Endowed Chairs are real ladder faculty whose title
omits the word "professor", so the require-regex admits them explicitly.

Per-person profile pages are server-rendered too and carry clean research-area
taxonomy chips (``#individual-hasResearchArea``), a comma-delimited freetext
keyword line (fallback for the ~5% without chips), and the person's email —
the gated profile pass (OFE_ENRICH_PROFILES=1) fills all three; sampled
coverage was 15/16 chips, 16/16 emails (Jul 2026).

51 departments: every CU Experts "Academic Department" with a real roster
(Engineering + Arts & Sciences) plus the CMCI departments, Environmental
Design, Leeds, Education, Law, and Music. Skipped: Honors/Herbst/Writing &
Rhetoric/Humanities (teaching programs, not research departments) and
Robotics/Biomedical Engineering (1-2 rows each, all joint appointments whose
home-department listing already lands them — the school-wide profile-URL
dedup would collapse them anyway).

Single source ("boulder_faculty"); ids namespaced by department short-code.
Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_EXPERTS = "https://experts.colorado.edu/display/deptid_"

# "Endowed Chair" is a ladder rank here (Leeds/Music chairs whose title text
# never says "professor"); Adjoint is CU's adjunct-series name.
_LADDER = {
    "require": r"\bprofessor\b|\bendowed chair\b",
    "drop": r"\bemerit|\badjunct|\badjoint|\bvisiting|\bclinical|\battendant\b",
}

_SELECTORS = {
    "card": "li.subclass ul.subclass-property-list > li",
    "name": "a[href^='/display/fisid_']",
    "link": "a[href^='/display/fisid_']",
    # Rank is loose text after the name anchor; the name carries exactly one
    # comma ("Last, First M"), so the run after the LAST comma is the rank. A
    # rank-less row mis-captures the first name — and then fails the ladder
    # require-gate (1 of 2019 rows sampled).
    "title_re": r",\s*([^,]+)$",
}

_PROFILE_ENRICH = {
    "research_items_selector": "#individual-hasResearchArea li a",
    # ~5% of profiles have no taxonomy chips but do keep the freetext keyword
    # line ("unmanned aircraft systems, robotics, ..."); _clean_keywords
    # comma-splits the captured run.
    "research_html_re": (r'id="freetextKeyword-noRangeClass-List"[^>]*>'
                         r"\s*<li[^>]*>\s*([^<]{4,400})"),
    "email_selector": "#additional-emails a.email[href^='mailto:']",
    "throttle": 0.6,
}


def _dept(short: str, name: str, majors: list[str], deptid: int) -> dict:
    url = f"{_EXPERTS}{deptid}"
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": dict(_SELECTORS),
            "name_flip": True,
            "section_filter": {"include": r"^faculty position$", "heading": "h3"},
            "ladder_filter": _LADDER,
            "profile_enrich": dict(_PROFILE_ENRICH),
        },
    }


SCHOOL: dict = {
    "school_slug": "boulder",
    "source": "boulder_faculty",
    "organization": "University of Colorado Boulder",
    "location": "Boulder, CO",
    "id_prefix": "boulder",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (CU Boulder) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering and Applied Science ---------------------
        _dept("AERO", "Department of Aerospace Engineering Sciences",
              ["Aerospace Engineering"], 10318),
        _dept("CHBE", "Department of Chemical and Biological Engineering",
              ["Chemical Engineering", "Chemical and Biological Engineering"], 10324),
        _dept("CVEN", "Department of Civil, Environmental and Architectural Engineering",
              ["Civil Engineering", "Environmental Engineering",
               "Architectural Engineering"], 10331),
        _dept("CS", "Department of Computer Science",
              ["Computer Science"], 10344),
        _dept("ECEE", "Department of Electrical, Computer and Energy Engineering",
              ["Electrical Engineering", "Electrical and Computer Engineering"], 10334),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"], 10340),
        # ---- Natural sciences ------------------------------------------------
        _dept("APPM", "Department of Applied Mathematics",
              ["Applied Mathematics", "Statistics and Data Science"], 10159),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics"], 10176),
        _dept("PHYS", "Department of Physics",
              ["Physics", "Engineering Physics"], 10180),
        _dept("APS", "Department of Astrophysical and Planetary Sciences",
              ["Astronomy", "Astrophysics"], 10158),
        _dept("ATOC", "Department of Atmospheric and Oceanic Sciences",
              ["Atmospheric and Oceanic Sciences"], 10189),
        _dept("CHEM", "Department of Chemistry",
              ["Chemistry"], 10167),
        _dept("BCHM", "Department of Biochemistry",
              ["Biochemistry"], 10592),
        _dept("MCDB", "Department of Molecular, Cellular and Developmental Biology",
              ["Molecular, Cellular and Developmental Biology", "Neuroscience"], 10161),
        _dept("EBIO", "Department of Ecology and Evolutionary Biology",
              ["Ecology and Evolutionary Biology"], 10160),
        _dept("IPHY", "Department of Integrative Physiology",
              ["Integrative Physiology"], 10175),
        _dept("PSYC", "Department of Psychology and Neuroscience",
              ["Psychology", "Neuroscience"], 10190),
        _dept("GEOL", "Department of Geological Sciences",
              ["Geological Sciences", "Geology"], 10173),
        _dept("ENVS", "Department of Environmental Studies",
              ["Environmental Studies"], 10169),
        _dept("GEOG", "Department of Geography",
              ["Geography"], 10170),
        _dept("SLHS", "Department of Speech, Language, and Hearing Sciences",
              ["Speech, Language and Hearing Sciences"], 10216),
        # ---- Social sciences -------------------------------------------------
        _dept("ECON", "Department of Economics",
              ["Economics"], 10208),
        _dept("PSCI", "Department of Political Science",
              ["Political Science"], 10184),
        _dept("SOC", "Department of Sociology",
              ["Sociology"], 10219),
        _dept("ANTH", "Department of Anthropology",
              ["Anthropology"], 10206),
        _dept("LING", "Department of Linguistics",
              ["Linguistics"], 10214),
        _dept("COMM", "Department of Communication",
              ["Communication"], 10207),
        _dept("ETHN", "Department of Ethnic Studies",
              ["Ethnic Studies"], 10212),
        _dept("WGST", "Department of Women and Gender Studies",
              ["Women and Gender Studies"], 10220),
        # ---- Arts & humanities -----------------------------------------------
        _dept("HIST", "Department of History",
              ["History"], 10238),
        _dept("PHIL", "Department of Philosophy",
              ["Philosophy"], 10239),
        _dept("RLST", "Department of Religious Studies",
              ["Religious Studies"], 10241),
        _dept("ENGL", "Department of English",
              ["English", "Creative Writing"], 10231),
        _dept("CLAS", "Department of Classics",
              ["Classics"], 10228),
        _dept("FRIT", "Department of French and Italian",
              ["French", "Italian"], 10236),
        _dept("GSLL", "Department of Germanic and Slavic Languages and Literatures",
              ["German Studies", "Russian Studies"], 10237),
        _dept("SPAN", "Department of Spanish and Portuguese",
              ["Spanish", "Portuguese"], 10242),
        _dept("ALC", "Department of Asian Languages and Civilizations",
              ["Chinese", "Japanese", "Asian Studies"], 10230),
        _dept("AAH", "Department of Art and Art History",
              ["Art History", "Studio Arts"], 10234),
        _dept("CINE", "Department of Cinema Studies and Moving Image Arts",
              ["Cinema Studies"], 10233),
        _dept("THDN", "Department of Theatre and Dance",
              ["Theatre", "Dance"], 10243),
        # ---- CMCI + Environmental Design --------------------------------------
        _dept("INFO", "Department of Information Science",
              ["Information Science"], 11051),
        _dept("JRNL", "Department of Journalism",
              ["Journalism"], 11049),
        _dept("MDST", "Department of Media Studies",
              ["Media Studies"], 11050),
        _dept("APRD", "Department of Advertising, Public Relations and Media Design",
              ["Advertising", "Public Relations"], 11053),
        _dept("CMP", "Department of Critical Media Practices",
              ["Media Production"], 11052),
        _dept("ENVD", "Program in Environmental Design",
              ["Environmental Design", "Architecture"], 10988),
        # ---- Professional schools ---------------------------------------------
        _dept("BUS", "Leeds School of Business",
              ["Business Administration", "Finance", "Marketing",
               "Accounting", "Management"], 10255),
        _dept("EDUC", "School of Education",
              ["Education", "Elementary Education"], 10261),
        _dept("LAW", "School of Law",
              ["Political Science", "Philosophy"], 10352),
        _dept("MUS", "College of Music",
              ["Music", "Music Education"], 10362),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector.

    CU Experts displays mailto locals in inconsistent case ("Tin.Su@Colorado.EDU",
    "Merritt.turetsky@..."); colorado.edu delivery is case-insensitive, and a
    First.lowersurname local trips the corpus DQ caps-mash email heuristic —
    canonicalize to lowercase so every refresh emits the same passing form.
    """
    records = faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)
    for rec in records:
        if rec.get("contact_email"):
            rec["contact_email"] = rec["contact_email"].lower()
    return records


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
