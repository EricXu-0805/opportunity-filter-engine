"""UC Riverside faculty config (via the faculty_graph engine).

UCR runs one authoritative campus profile system — ``profiles.ucr.edu`` (an
Interfolio-style directory). Every department directory site is a JS-SPA shell
that embeds an iframe from it; the real roster is a single JSON API:

    GET https://profiles.ucr.edu/api/profile?acctStruct=<CODE>&affiliationFilter=Faculty

returning a flat array of people with ``name``, ``title``, ``email`` (100%
populated on every unit) and a clean controlled-vocabulary ``researchAreas``
string array. Rather than chase per-department curated ``groupId`` widgets (one
per dept, only discoverable by rendering each SPA), every department is keyed on
its stable **account-structure code** (``D#####`` department / ``ORG##`` school),
pulled once from ``profiles.ucr.edu/api/acctStruct`` (the full 557-node campus
org tree). So the single path here is the generic ``json_dir`` source pointed at
the profile API, one dept per acctStruct code — all field mappings identical.
Codes + counts live-verified 2026-07-24.

QUALITY GATE. ``affiliationFilter=Faculty`` is broad — especially in CNAS
agricultural departments it folds in postdocs, project scientists, station
specialists, PhD students and (crucially) a large pool of *title-less* transient
appointments (non-customized, no bio/research — clearly not ladder faculty). The
engine defaults a blank title to "Professor", which would silently pad those in.
So instead of a title ``ladder_filter`` (which runs *after* that default), a
``field_filters`` gate runs on the **raw** title: ``include=r"profess|lect"``
(keeps professors of every rank + lecturers/LECT-AY + teaching-track, drops
blank-title records and every non-professorial staff/researcher role) and
``exclude=r"emerit|adjunct|affiliate|visiting|retir"`` (drops emeriti, adjunct,
affiliate, visiting). Result: every department is ladder + teaching faculty only
and 100% emailed. Teaching-track (Professor of Teaching / Lecturer) are kept —
real faculty who mentor undergrads (mirrors the ncsu lecturer precedent).

The feed carries no per-person profile URL (the SPA builds it client-side from
``netId``), which ``json_dir`` can't template — so records fall back to each
department's human directory URL (an accepted engine pattern), and joint
appointments de-dupe on the always-present email.

Coverage: 40 departments across all six academic colleges (Bourns Engineering,
CNAS, CHASS, Business, Education, Public Policy) — ~1,150 ladder/teaching faculty.

Dropped / phase-2:
  * Materials Science & Engineering (D01342) and Neuroscience (D01250) — degree
    *programs*, not home departments: their faculty are joint-appointed and
    already covered under their home depts (ChemEnvEng/ME/Physics/Chem/Psych/
    BiomedSci). MSE's own code lists only ~2 core; Neuroscience's lists 0.
  * Title-less profile records (non-ladder transient appointments, heavy in the
    ag departments) are dropped by the raw-title gate — a handful of genuine but
    blank-title senior professors ride in that pool and are the only recoverable
    slice, left for a phase-2 profile-enrich pass.
"""

from __future__ import annotations

from .. import faculty_graph

# The campus profile API. One flat JSON array per account-structure code; the
# same field names on every unit, so one shared mapping serves all departments.
_API = (
    "https://profiles.ucr.edu/api/profile?acctStruct={code}&researchArea="
    "&affiliationFilter=Faculty&excludeStudentEmployees=true"
    "&excludeSecondaryDepartmentEmployees=false&excludeAffiliates=false"
)

# Raw-title ladder gate (runs before the engine's blank-title→"Professor"
# default): keep professorial + lecturer/teaching ranks, drop the retired /
# courtesy tails. This is the whole quality story — see the module docstring.
_LADDER = [{
    "field": "title",
    "include": r"profess|lect",
    "exclude": r"emerit|adjunct|affiliate|visiting|retir",
}]

# Shared field mapping (name/title/email scalars; researchAreas is a clean
# controlled-vocab string array → keywords). No link field in the feed → each
# record falls back to its department directory_url.
_MAP = {
    "name_fields": ["name"],
    "title_field": "title",
    "email_field": "email",
    "research_field": "researchAreas[]",
    "field_filters": _LADDER,
}


def _dept(short: str, name: str, majors: list[str], directory: str, code: str) -> dict:
    """A UCR department fetched from the profiles.ucr.edu acctStruct JSON feed."""
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": directory,
        "json_dir": {"url": _API.format(code=code), **_MAP},
    }


SCHOOL: dict = {
    "school_slug": "ucr",
    "source": "ucr_faculty",
    "organization": "University of California, Riverside",
    "location": "Riverside, CA",
    "id_prefix": "ucr",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of California, Riverside) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Marlan and Rosemary Bourns College of Engineering ------------
        _dept("CS", "Department of Computer Science & Engineering",
              ["Computer Science", "Computer Engineering", "Data Science",
               "Computer Science with Business Applications"],
              "https://www1.cs.ucr.edu/people/faculty", "D01003"),
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              "https://ece.ucr.edu/Tenure-Track-Faculty", "D01004"),
        _dept("CEE", "Department of Chemical and Environmental Engineering",
              ["Chemical Engineering", "Environmental Engineering"],
              "https://cee.ucr.edu", "D01005"),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              "https://me.ucr.edu/about/faculty", "D01006"),
        _dept("BME", "Department of Bioengineering",
              ["Bioengineering", "Biomedical Engineering"],
              "https://bioeng.ucr.edu/about/faculty", "D01285"),
        # ---- College of Natural and Agricultural Sciences -----------------
        _dept("Physics", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"],
              "https://www.physics.ucr.edu/people/faculty", "D01057"),
        _dept("Chemistry", "Department of Chemistry", ["Chemistry"],
              "https://chem.ucr.edu/people/faculty", "D01054"),
        _dept("Math", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"],
              "https://mathdept.ucr.edu/people", "D01056"),
        _dept("Statistics", "Department of Statistics", ["Statistics"],
              "https://statistics.ucr.edu/people/faculty", "D01058"),
        _dept("Biochem", "Department of Biochemistry", ["Biochemistry"],
              "https://biochemistry.ucr.edu", "D01045"),
        _dept("EEOB", "Department of Evolution, Ecology and Organismal Biology",
              ["Biology"],
              "https://eeob.ucr.edu", "D01046"),
        _dept("BPSC", "Department of Botany and Plant Sciences",
              ["Plant Biology"],
              "https://plantbiology.ucr.edu", "D01047"),
        _dept("MCSB", "Department of Molecular, Cell and Systems Biology",
              ["Cell, Molecular, and Developmental Biology", "Biology"],
              "https://mcsb.ucr.edu", "D01051"),
        _dept("MPP", "Department of Microbiology and Plant Pathology",
              ["Microbiology"],
              "https://microbiology.ucr.edu", "D01052"),
        _dept("Entomology", "Department of Entomology", ["Entomology"],
              "https://entomology.ucr.edu", "D01048"),
        _dept("Nematology", "Department of Nematology", ["Biology"],
              "https://nematology.ucr.edu", "D01050"),
        _dept("EnvSci", "Department of Environmental Sciences",
              ["Environmental Sciences", "Sustainability Studies"],
              "https://envisci.ucr.edu", "D01053"),
        _dept("EPS", "Department of Earth and Planetary Sciences",
              ["Earth Sciences", "Geology", "Geophysics"],
              "https://epsci.ucr.edu", "D01055"),
        _dept("BMSC", "Division of Biomedical Sciences",
              ["Biomedical Sciences", "Neuroscience"],
              "https://biomed.ucr.edu", "D01059"),
        # ---- College of Humanities, Arts, and Social Sciences -------------
        _dept("English", "Department of English", ["English"],
              "https://english.ucr.edu/people", "D01018"),
        _dept("History", "Department of History", ["History"],
              "https://history.ucr.edu/people", "D01019"),
        _dept("CompLit", "Department of Comparative Literature and Languages",
              ["Comparative Literature", "Linguistics"],
              "https://complitlang.ucr.edu", "D01020"),
        _dept("Philosophy", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.ucr.edu", "D01021"),
        _dept("Religion", "Department of Religious Studies",
              ["Religious Studies"],
              "https://religiousstudies.ucr.edu", "D01022"),
        _dept("Hispanic", "Department of Hispanic Studies", ["Spanish"],
              "https://hispanicstudies.ucr.edu", "D01023"),
        _dept("MCS", "Department of Media and Cultural Studies",
              ["Media and Cultural Studies"],
              "https://mcs.ucr.edu", "D01303"),
        _dept("Anthropology", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.ucr.edu", "D01025"),
        _dept("Economics", "Department of Economics",
              ["Economics", "Business Economics"],
              "https://economics.ucr.edu", "D01026"),
        _dept("Ethnic", "Department of Ethnic Studies",
              ["Ethnic Studies", "Asian American Studies", "Chicano Studies"],
              "https://ethnicstudies.ucr.edu", "D01027"),
        _dept("PoliSci", "Department of Political Science",
              ["Political Science"],
              "https://politicalscience.ucr.edu", "D01029"),
        _dept("Psychology", "Department of Psychology",
              ["Psychology", "Neuroscience"],
              "https://psychology.ucr.edu/people", "D01030"),
        _dept("Sociology", "Department of Sociology", ["Sociology"],
              "https://sociology.ucr.edu", "D01031"),
        _dept("GSST", "Department of Gender and Sexuality Studies",
              ["Gender and Sexuality Studies"],
              "https://gsst.ucr.edu", "D01032"),
        _dept("BlackStudy", "Department of Black Study", ["Ethnic Studies"],
              "https://blackstudy.ucr.edu", "D02094"),
        _dept("Art", "Department of Art", ["Art"],
              "https://art.ucr.edu", "D01033"),
        _dept("ArtHistory", "Department of the History of Art", ["Art History"],
              "https://arthistory.ucr.edu", "D01034"),
        _dept("CreativeWriting", "Department of Creative Writing",
              ["Creative Writing"],
              "https://creativewriting.ucr.edu", "D01035"),
        _dept("Dance", "Department of Dance", ["Dance"],
              "https://dance.ucr.edu", "D01036"),
        _dept("Music", "Department of Music", ["Music"],
              "https://music.ucr.edu", "D01037"),
        _dept("TFDP", "Department of Theatre, Film and Digital Production",
              ["Theatre, Film, and Digital Production"],
              "https://theatre.ucr.edu", "D01038"),
        _dept("LiberalStudies", "Liberal Studies and Interdisciplinary Programs",
              ["Liberal Studies", "Global Studies"],
              "https://liberalstudies.ucr.edu", "D01256"),
        # ---- School of Business (single academic unit) --------------------
        _dept("Business", "School of Business",
              ["Business Administration"],
              "https://business.ucr.edu", "ORG13"),
        # ---- School of Education (single academic unit) -------------------
        _dept("Education", "School of Education",
              ["Education, Society, and Human Development"],
              "https://education.ucr.edu/faculty", "ORG10"),
        # ---- School of Public Policy (single academic unit) ---------------
        _dept("PublicPolicy", "School of Public Policy", ["Public Policy"],
              "https://spp.ucr.edu/faculty", "ORG37"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
