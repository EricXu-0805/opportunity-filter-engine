"""Vassar College campus opportunity-graph config.

Curated seed records of Vassar's undergraduate-research and fellowship
landscape, centered on the college's flagship summer science-research program
(the Undergraduate Research Summer Institute, URSI), its Ford Scholars program
for mentored humanities and social-science research, and the Beckman Scholars
Program in the life sciences, plus the college's ecological field-research
Preserve, the Mellon-funded Creative Arts Across Disciplines initiative, the
nationally competitive Fellowships Office, and the Grants in Action research
hub. Every URL was curl-verified live (HTTP 200) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → vassar_research_programs (vassar / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "vassar",
    "organization": "Vassar College",
    "location": "Poughkeepsie, NY",
    "emit": {
        "campus": ("vassar_research_programs", "vassar", "campus"),
    },
    "sources": [
        {
            "source_name": "vassar_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.vassar.edu/ursi",
                "https://offices.vassar.edu/grants/",
                "https://offices.vassar.edu/fellowships/",
            ],
            "programs": [
                program(
                    "vassar_ursi",
                    "Undergraduate Research Summer Institute (URSI)",
                    "https://www.vassar.edu/ursi",
                    "Vassar's flagship summer science-research program: roughly "
                    "80 students team up with about 30 faculty for an immersive "
                    "summer of full-time, faculty-mentored research across the "
                    "natural sciences, with a stipend, scientific workshops, and "
                    "a fall symposium; students frequently present at regional "
                    "and national meetings and publish their work.",
                    lab_or_program="Undergraduate Research Summer Institute",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "sciences", "faculty mentor",
                              "stipend"],
                ),
                program(
                    "vassar_ursi_application",
                    "URSI Summer Research — Student Application",
                    "https://offices.vassar.edu/ursi/2026-student-application/",
                    "The student application portal for URSI summer research "
                    "positions: continuing Vassar students apply to join a "
                    "faculty member's summer research project in the sciences, "
                    "receiving a stipend and campus housing for the full-time "
                    "research term.",
                    lab_or_program="Undergraduate Research Summer Institute",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "application", "sciences",
                              "stipend"],
                ),
                program(
                    "vassar_ford_scholars",
                    "Ford Scholars Program (Vassar)",
                    "https://www.vassar.edu/ford-scholars",
                    "The Ford Scholars program pairs students with faculty "
                    "mentors for collaborative summer research in the "
                    "humanities and social sciences, funding a stipended "
                    "research term that culminates in a fall symposium "
                    "presentation of the scholar's project.",
                    lab_or_program="Ford Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer research", "humanities",
                              "social sciences", "faculty mentor"],
                ),
                program(
                    "vassar_beckman_scholars",
                    "Beckman Scholars Program (Vassar)",
                    "https://offices.vassar.edu/grants/beckman-scholars/",
                    "First-year and sophomore students planning studies in "
                    "biology, chemistry, biochemistry, or neuroscience & "
                    "behavior may apply for a generous 15-month stipend to "
                    "pursue independent, faculty-mentored research through the "
                    "Arnold and Mabel Beckman Foundation's Beckman Scholars "
                    "Program.",
                    lab_or_program="Beckman Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    eligibility_majors=["Biology", "Chemistry", "Biochemistry",
                                        "Neuroscience and Behavior"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["independent research", "life sciences",
                              "faculty mentor", "stipend"],
                ),
                program(
                    "vassar_preserve",
                    "Research at The Preserve at Vassar",
                    "https://www.vassar.edu/preserve",
                    "Vassar's 500+ acre ecological Preserve supports student and "
                    "faculty field research, teaching, and land stewardship — "
                    "an outdoor laboratory for ecology, environmental science, "
                    "earth science, and biology projects that deepen "
                    "understanding of the natural world.",
                    lab_or_program="The Preserve at Vassar",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Environmental Studies", "Biology",
                                        "Earth Science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["field research", "ecology",
                              "environmental science", "biology"],
                ),
                program(
                    "vassar_caad",
                    "Creative Arts Across Disciplines (CAAD)",
                    "https://www.vassar.edu/creativearts",
                    "A Mellon Foundation-funded initiative that serves as an "
                    "experimental laboratory for cross-disciplinary creative "
                    "and arts-integrated projects, partnering with departments, "
                    "programs, and student projects to support collaborative "
                    "creative research across the arts and humanities.",
                    lab_or_program="Creative Arts Across Disciplines",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Art", "Drama", "Film", "Dance",
                                        "Media Studies"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["creative research", "arts", "interdisciplinary",
                              "humanities"],
                ),
                program(
                    "vassar_fellowships",
                    "Nationally Competitive Fellowships (Vassar)",
                    "https://offices.vassar.edu/fellowships/",
                    "The Center for Career Education and the faculty Committee "
                    "on Fellowships coordinate applications for nationally "
                    "competitive fellowships requiring institutional "
                    "endorsement (Fulbright, Goldwater, and similar research "
                    "and graduate-study awards) and advise students on funding "
                    "for research during and after Vassar.",
                    lab_or_program="Fellowships Office",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["fellowship", "nationally competitive",
                              "graduate study", "research funding"],
                ),
                program(
                    "vassar_grants_in_action",
                    "Grants in Action — Funded Faculty Research (Vassar)",
                    "https://www.vassar.edu/grants-in-action",
                    "A hub celebrating Vassar's externally funded research "
                    "projects and the principal investigators who lead them; a "
                    "starting point for students seeking to join grant-funded "
                    "faculty research across the sciences, social sciences, and "
                    "humanities.",
                    lab_or_program="Grants in Action",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["funded research", "faculty research",
                              "principal investigator", "grants"],
                ),
            ],
        },
    ],
}
