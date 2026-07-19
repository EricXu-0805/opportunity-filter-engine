"""UC Santa Cruz campus opportunity-graph config.

Curated seed records of UCSC's undergraduate-research landscape, centered on the
Undergraduate Research office (undergradresearch.ucsc.edu) — its office hub, the
getting-started pathway, and the Undergraduate Research Programs database that
indexes named programs (Amgen Scholars, Koret Scholars, Porter Fellowships, and
STEM summer programs) — plus the Office of Research's student funding /
fellowship opportunities. URLs curl-verified live (HTTP 200) on 2026-07-19; the
Office of Research seed uses its current canonical path (the older
/for-students/opportunities.html now 301-redirects to it).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ucsc_research_programs (ucsc / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "ucsc",
    "organization": "University of California, Santa Cruz",
    "location": "Santa Cruz, CA",
    "emit": {
        "campus": ("ucsc_research_programs", "ucsc", "campus"),
    },
    "sources": [
        {
            "source_name": "ucsc_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergradresearch.ucsc.edu/",
                "https://officeofresearch.ucsc.edu/ord/student-funding-opportunities/",
            ],
            "programs": [
                program(
                    "ucsc_undergraduate_research_office",
                    "Undergraduate Research (UC Santa Cruz)",
                    "https://undergradresearch.ucsc.edu/",
                    "UC Santa Cruz's central Undergraduate Research office helps "
                    "students of every major get involved in research, connecting "
                    "them with faculty mentors, funding, and named scholar and "
                    "fellowship programs. It is the campus hub for discovering "
                    "opportunities, learning how to get started, and finding "
                    "support for undergraduate research and creative projects.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "ucsc_undergraduate_research_programs",
                    "Undergraduate Research Programs database (UC Santa Cruz)",
                    "https://undergradresearch.ucsc.edu/discover-opportunities/undergraduate-research-programs/",
                    "A searchable database of UC Santa Cruz undergraduate research "
                    "programs, including named scholar programs and STEM summer "
                    "research experiences such as Amgen Scholars, Koret Scholars, "
                    "and the Porter Fellowships. Students can browse programs by "
                    "eligibility, discipline, and term to find structured research "
                    "opportunities and summer placements.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["Amgen Scholars", "Koret Scholars",
                              "Porter Fellowships", "summer research"],
                ),
                program(
                    "ucsc_getting_started_research",
                    "Getting Started with Undergraduate Research (UC Santa Cruz)",
                    "https://undergradresearch.ucsc.edu/getting-started/",
                    "UC Santa Cruz's guide for undergraduates new to research: how "
                    "to explore interests, identify and contact faculty mentors, "
                    "and take the first steps into a lab or creative project. It "
                    "walks students through finding opportunities on campus and "
                    "preparing to reach out to potential research advisors.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
                program(
                    "ucsc_office_of_research_student_funding",
                    "Student Funding & Fellowship Opportunities (UC Santa Cruz Office of Research)",
                    "https://officeofresearch.ucsc.edu/ord/student-funding-opportunities/",
                    "The UC Santa Cruz Office of Research's student funding hub "
                    "lists fellowships, grants, and scholarship opportunities "
                    "supporting undergraduate and graduate research. It points "
                    "students to internal and external funding for research "
                    "projects, conference travel, and fellowship applications "
                    "across disciplines.",
                    lab_or_program="Office of Research",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["fellowships", "research grants",
                              "student funding", "scholarships"],
                ),
            ],
        },
    ],
}
