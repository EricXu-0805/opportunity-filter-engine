"""Florida State University campus opportunity-graph config.

Curated seed records of FSU's undergraduate-research landscape, centered on the
Center for Undergraduate Research and Academic Engagement (CRE, cre.fsu.edu) —
its office hub — plus the flagship CRE-administered programs: the UROP
Undergraduate Research Opportunity Program, the IDEA Grants student-project
funding program, the CRE "Getting Started" mentor-finding guide, and the Tyler
Center for Global Studies Fellowship. Every URL was curl-verified live (HTTP 200)
on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → fsu_research_programs (fsu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "fsu",
    "organization": "Florida State University",
    "location": "Tallahassee, FL",
    "emit": {
        "campus": ("fsu_research_programs", "fsu", "campus"),
    },
    "sources": [
        {
            "source_name": "fsu_cre_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://cre.fsu.edu/",
                "https://cre.fsu.edu/undergradresearch",
            ],
            "programs": [
                program(
                    "fsu_center_undergraduate_research",
                    "Center for Undergraduate Research and Academic Engagement (Florida State University)",
                    "https://cre.fsu.edu/",
                    "FSU's Center for Undergraduate Research and Academic "
                    "Engagement (CRE) is the campus hub connecting undergraduates "
                    "of every major to research mentors, funding, and structured "
                    "programs. It houses the UROP research program, IDEA Grants "
                    "funding, the annual Undergraduate Research Symposium, and "
                    "guidance on how to find a faculty mentor and get started in "
                    "research and creative activity.",
                    lab_or_program="Center for Undergraduate Research and Academic Engagement",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "fsu_urop",
                    "UROP: Undergraduate Research Opportunity Program (Florida State University)",
                    "https://cre.fsu.edu/undergradresearch/urop",
                    "The Undergraduate Research Opportunity Program (UROP) pairs "
                    "first- and second-year FSU students with faculty and "
                    "graduate-student mentors on ongoing research and creative "
                    "projects across every discipline. Participants join a "
                    "year-long colloquium, work in a mentor's lab or project, and "
                    "present at the spring Undergraduate Research Symposium — a "
                    "structured entry point into research for students new to it.",
                    lab_or_program="Undergraduate Research Opportunity Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["UROP", "faculty-mentored research",
                              "first research experience", "any major"],
                ),
                program(
                    "fsu_idea_grants",
                    "IDEA Grants (FSU Center for Undergraduate Research and Academic Engagement)",
                    "https://cre.fsu.edu/undergradresearch/ideagrants",
                    "FSU IDEA Grants provide competitive funding to support "
                    "student-initiated research, creative, and entrepreneurial "
                    "projects. Open to undergraduates in every major, the grants "
                    "fund independent projects proposed and led by the students "
                    "themselves under faculty mentorship, covering project costs, "
                    "materials, travel, and related research expenses.",
                    lab_or_program="IDEA Grants",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["IDEA Grant", "student-initiated project",
                              "research funding", "creative projects"],
                ),
                program(
                    "fsu_getting_started_research",
                    "Getting Involved With Undergraduate Research (FSU CRE)",
                    "https://cre.fsu.edu/gettingstarted",
                    "CRE's guide to finding and joining undergraduate research at "
                    "FSU: how to identify labs and faculty mentors, reach out to "
                    "professors, explore posted research opportunities, and take "
                    "the first steps toward a mentored research or creative "
                    "project across the sciences, engineering, humanities, and "
                    "social sciences.",
                    lab_or_program="Center for Undergraduate Research and Academic Engagement",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "contacting faculty",
                              "getting started", "research opportunities"],
                ),
                program(
                    "fsu_tyler_global_studies_fellowship",
                    "Tyler Center for Global Studies Fellowship (Florida State University)",
                    "https://cre.fsu.edu/undergraduate-research/tyler-center-global-studies-fellowship",
                    "The Tyler Center for Global Studies Fellowship funds FSU "
                    "undergraduates pursuing internationally focused research and "
                    "global-studies projects, supporting mentored scholarly work "
                    "with a global or cross-cultural dimension. It provides funding "
                    "and structured support for students developing a research or "
                    "creative project connected to international engagement.",
                    lab_or_program="Tyler Center for Global Studies",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["global studies", "international research",
                              "fellowship", "faculty-mentored research"],
                ),
            ],
        },
    ],
}
