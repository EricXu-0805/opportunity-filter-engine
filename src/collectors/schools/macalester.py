"""Macalester College campus opportunity-graph config.

Curated seed records of Macalester's undergraduate-research and fellowship
landscape, centered on the college's Office of Student Research and Creativity
and the Jan Serie Center for Scholarship and Teaching. Covers the flagship
Collaborative Summer Research (CSR) program and its named summer-research and
fellowship tracks: the Young Researchers in STEM program, the Beckman Scholars
Program, the Serie Center student-faculty summer collaborations, the Mellon
Mays Undergraduate Fellowship, the national "Fellowships to Go Anywhere"
portal, the extended/longer-term research programs, and the on-campus/special
summer research opportunities hub. URLs curl-verified live (HTTP 200) on
2026-07-22.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → macalester_research_programs (macalester / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_OSR = "https://www.macalester.edu/student-research"
_SUMMER = f"{_OSR}/funded-summer-experiences-for-students"

SCHOOL: dict = {
    "school_slug": "macalester",
    "organization": "Macalester College",
    "location": "Saint Paul, MN",
    "emit": {
        "campus": ("macalester_research_programs", "macalester", "campus"),
    },
    "sources": [
        {
            "source_name": "macalester_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_OSR}/summer-research-opportunities/",
                f"{_OSR}/",
                "https://www.macalester.edu/serie-center/funding/studentresearch/",
            ],
            "programs": [
                program(
                    "macalester_csr",
                    "Collaborative Summer Research (CSR) Program (Macalester)",
                    f"{_OSR}/faculty-funding-to-hire-student-researchers/"
                    "collaborative-summer-research-csr-program/",
                    "Macalester's flagship summer research program: student "
                    "stipends plus support for project expenses and student "
                    "travel for up to ten weeks of collaborative scholarly work "
                    "in any discipline that intellectually engages a "
                    "student/faculty team, with free on-campus housing for "
                    "on-campus projects.",
                    lab_or_program="Collaborative Summer Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "any discipline"],
                ),
                program(
                    "macalester_young_researchers",
                    "Young Researchers in STEM (Macalester)",
                    f"{_SUMMER}/young-researchers-in-stem/",
                    "An early-research program giving Macalester students — "
                    "especially those from under-resourced and underrepresented "
                    "backgrounds — access to mentored STEM research "
                    "opportunities after their first or second year of college.",
                    lab_or_program="Young Researchers in STEM",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["early research", "STEM", "faculty mentor",
                              "diversity in research"],
                ),
                program(
                    "macalester_beckman",
                    "Beckman Scholars Program (Macalester)",
                    f"{_SUMMER}/extended-research-programs/beckman-scholars-program/",
                    "The Beckman Scholars Program supports a small cohort of "
                    "scholars in the chemical and biological sciences to conduct "
                    "research with a Macalester faculty member over a continuous "
                    "15-month period spanning two summers and one academic year, "
                    "with a generous research stipend and supply budget.",
                    lab_or_program="Beckman Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["chemistry", "biology", "mentored research",
                              "multi-year fellowship"],
                ),
                program(
                    "macalester_serie_collaboration",
                    "Student-Faculty Collaborations & Summer Research (Serie Center)",
                    "https://www.macalester.edu/serie-center/funding/studentresearch/",
                    "The Jan Serie Center for Scholarship and Teaching funds "
                    "teams of Macalester faculty and students to engage in "
                    "significant projects over a four- to ten-week period during "
                    "the summer, related to the faculty member's curricular, "
                    "pedagogical, scholarly, or creative interests.",
                    lab_or_program="Jan Serie Center",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["student-faculty collaboration", "summer research",
                              "any discipline", "faculty mentor"],
                ),
                program(
                    "macalester_mmuf",
                    "Mellon Mays Undergraduate Fellowship (Macalester)",
                    "https://www.macalester.edu/global-citizenship/"
                    "student-opportunities/mellon-mays/",
                    "The Mellon Mays Undergraduate Fellowship selects up to five "
                    "sophomores each year for a multi-year program in the "
                    "humanities and humanistic social sciences, providing summer "
                    "and semester stipends, research-expense and GRE-prep "
                    "support, and a faculty-mentored individual research project "
                    "during the junior and senior years.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["humanities", "faculty mentor", "graduate school",
                              "diversity in the academy"],
                ),
                program(
                    "macalester_fellowships_anywhere",
                    "Fellowships to Go Anywhere (Macalester)",
                    f"{_SUMMER}/fellowships-to-go-anywhere/",
                    "A curated portal of nationally competitive summer research "
                    "and study fellowships open to Macalester students — placing "
                    "students in funded research experiences at other "
                    "institutions and field sites across the country and abroad.",
                    lab_or_program="Office of Student Research and Creativity",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["national fellowship", "summer research",
                              "off-campus", "competitive"],
                ),
                program(
                    "macalester_extended_research",
                    "Extended / Longer-Term Research Programs (Macalester)",
                    f"{_SUMMER}/extended-research-programs/",
                    "Multi-summer and academic-year mentored research programs at "
                    "Macalester — including cohort scholar programs in the "
                    "sciences — that extend beyond a single summer, pairing "
                    "students with a faculty research mentor over a longer arc.",
                    lab_or_program="Office of Student Research and Creativity",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["multi-year research", "faculty mentor",
                              "cohort program", "sciences"],
                ),
                program(
                    "macalester_oncampus_research",
                    "On-Campus Summer Research Opportunities (Macalester)",
                    f"{_SUMMER}/on-campus-research-opportunities/",
                    "The Office of Student Research and Creativity's hub of "
                    "on-campus, faculty-mentored summer research positions across "
                    "departments, with a standard weekly stipend, benefits, and "
                    "free summer housing for the duration of the project.",
                    lab_or_program="Office of Student Research and Creativity",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["on-campus research", "summer stipend",
                              "faculty mentor", "housing"],
                ),
            ],
        },
    ],
}
