"""Haverford College faculty config (via the faculty_graph engine).

Haverford is a top liberal-arts college (~1,400 undergraduates, no graduate
school) and a member of the Tri-College Consortium with Bryn Mawr and
Swarthmore. Its entire public site is a single Drupal build behind a
Cloudflare **managed challenge** (``cf-mitigated: challenge``) — plain curl
gets a "Just a moment..." interstitial (HTTP 403) on every page — but a
headless Chromium render clears the challenge in one settle and returns the
real page, so every department scrape runs with ``render: True``. No stealth
or evasion is used; the challenge is an ordinary interactive one that a normal
browser render passes.

Live-verified 2026-07-23 (headless render): every academic department
publishes a "Faculty & Staff" page on ONE shared college-wide component at
``haverford.edu/<dept>/faculty-staff``, so a single selector family covers the
whole college — no per-department bespoke markup.

Markup family (``haverford_dir``): each person is a ``.faculty-staff-row``
card; the name + profile link is ``.profile_link-full-name a`` (a
``/users/<slug>`` profile page), and the rank is the first ``div.italic`` block
("Associate Professor of Biology", "Assistant Professor of Chemistry", named
chairs like "The John and Barbara Bush Professorship … Professor and Chair of
Chemistry", plus staff/visiting/emeriti titles that share the card). Emails are
NOT exposed on either the listing or the ``/users/<slug>`` profile pages, so no
email is captured — records carry the profile URL as the contact path (topics
come from OpenAlex). Verified live: Biology 27 rows, Chemistry 30 rows, sharing
the identical component.

Because these are "Faculty & Staff" pages, each list mixes teaching faculty
with lab instructors, coordinators, technicians and department staff (whose
titles carry no "professor"/"lecturer"), plus emeriti and visiting
appointments. The ``ladder_filter`` keeps professorial + lecturer + instructor
ranks and drops emeriti/visiting/adjunct as well as the non-teaching staff.

Tri-College note: Haverford runs several programs jointly with Bryn Mawr
(Bi-Co) and Swarthmore (Tri-Co). This config captures Haverford-home
departments; the engine's per-school url/name dedup collapses the handful of
faculty cross-listed onto more than one Haverford department page. The
Bi-Co/Tri-Co programs administered from Bryn Mawr (East Asian Languages,
German, Comparative Literature, Education, Neuroscience, Health Studies,
Environmental Studies, Gender & Sexuality Studies, Chinese/Japanese language,
Asian American Studies, Visual Studies) list cross-appointed faculty whose home
campus is elsewhere and are covered on the campus/program side, not as faculty
departments here.

Single source ("haverford_faculty"); department rides each record, ids
namespaced by department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# Person card on the shared Haverford Drupal "Faculty & Staff" component.
_SELECTORS = {
    "card": ".faculty-staff-row",
    "name": ".profile_link-full-name a",
    "link": ".profile_link-full-name a",
    "title": "div.italic",
}

# Keep professorial + lecturer + instructor ranks; drop emeriti, visiting and
# adjunct appointments plus the non-teaching staff (lab instructor / coordinator
# / technician / manager) whose titles carry neither "professor" nor "lecturer".
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
    "drop": r"emerit|\bvisiting\b|\badjunct\b",
}


def _dept(short: str, name: str, majors: list[str], slug: str,
          path: str = "faculty-staff") -> dict:
    """A Haverford department on the shared faculty-staff render template."""
    url = f"https://www.haverford.edu/{slug}/{path}"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "render": True,
            "render_settle": 5000,
            "selectors": _SELECTORS,
            "ladder_filter": _LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "haverford",
    "source": "haverford_faculty",
    "organization": "Haverford College",
    "location": "Haverford, PA",
    "id_prefix": "haverford",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Haverford College) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    # 19 departments live-verified 2026-07-23 (per-dept ladder counts in the
    # comment); all share the same faculty-staff render template. Nine further
    # units 404 at ``/<slug>/faculty-staff`` and are DEFERRED: Political Science
    # and French & Francophone Studies (dept exists but its people page lives at
    # a non-standard path — revisit), plus the interdisciplinary /
    # Bi-Co-hosted programs Biochemistry & Biophysics, Scientific Computing,
    # Mathematical Economics, African & Africana Studies, Latin American Iberian
    # & Latinx Studies, Middle East & Islamic Studies, and the Writing Program
    # (these cross-list faculty whose home department is already captured
    # below, and are covered on the campus/program side).
    "departments": [
        # ---- Natural Sciences & Mathematics (KINSC) ----------------------
        _dept("BIOL", "Department of Biology", ["Biology"], "biology"),  # 14
        _dept("CHEM", "Department of Chemistry", ["Chemistry"], "chemistry"),  # 18
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"], "physics-and-astronomy"),  # 9
        _dept("MATH", "Department of Mathematics and Statistics",
              ["Mathematics", "Statistics"], "mathematics-and-statistics"),  # 11
        _dept("CMSC", "Department of Computer Science", ["Computer Science"],
              "computer-science"),  # 9
        _dept("PSYC", "Department of Psychology", ["Psychology"], "psychology"),  # 9
        # ---- Social Sciences ---------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "anthropology"),  # 7
        _dept("ECON", "Department of Economics", ["Economics"], "economics"),  # 12
        _dept("SOCI", "Department of Sociology", ["Sociology"], "sociology"),  # 3
        _dept("PJHR", "Peace, Justice, and Human Rights Program",
              ["Peace, Justice, and Human Rights"],
              "peace-justice-and-human-rights"),  # 3
        # ---- Humanities --------------------------------------------------
        _dept("ENGL", "Department of English", ["English", "Creative Writing"],
              "english"),  # 6
        _dept("HIST", "Department of History", ["History"], "history"),  # 9
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], "philosophy"),  # 4
        _dept("RELG", "Department of Religion", ["Religion"], "religion"),  # 8
        _dept("CLAS", "Department of Classics", ["Classics"], "classics"),  # 3
        _dept("SPAN", "Department of Spanish", ["Spanish"], "spanish"),  # 6
        _dept("LING", "Linguistics Program", ["Linguistics"], "linguistics"),  # 6
        # ---- Arts --------------------------------------------------------
        _dept("ARTS", "Department of Fine Arts", ["Fine Arts"], "fine-arts"),  # 4
        _dept("MUSI", "Department of Music", ["Music"], "music"),  # 6
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
