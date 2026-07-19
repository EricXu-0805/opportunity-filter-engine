"""University of Connecticut campus opportunity-graph config.

Curated seed records of UConn's undergraduate-research landscape, centered on the
Office of Undergraduate Research (OUR, ugradresearch.uconn.edu) — its office hub
and Explore-Opportunities database — plus the four flagship OUR-administered
programs: the SURF summer research fund, the UConn IDEA Grant, the Barbara C.
Setlow Health Research Program, and the Research Apprenticeship Program. Every
URL was curl-verified live (HTTP 200) on 2026-07-19; the IDEA seed uses its
current canonical path (``/idea-2/`` 302-redirects to
``/idea-2/idea-program-information/``).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uconn_research_programs (uconn / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "uconn",
    "organization": "University of Connecticut",
    "location": "Storrs, CT",
    "emit": {
        "campus": ("uconn_research_programs", "uconn", "campus"),
    },
    "sources": [
        {
            "source_name": "uconn_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ugradresearch.uconn.edu/",
                "https://ugradresearch.uconn.edu/explore-opportunities/",
            ],
            "programs": [
                program(
                    "uconn_office_of_undergraduate_research",
                    "Office of Undergraduate Research (University of Connecticut)",
                    "https://ugradresearch.uconn.edu/",
                    "UConn's Office of Undergraduate Research (OUR) helps students "
                    "of every major get involved in research and creative activity, "
                    "connecting them with faculty mentors, funding, and structured "
                    "programs. It is the campus hub for finding opportunities, "
                    "learning how to get started, and applying for research funding "
                    "and summer fellowships.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "uconn_explore_opportunities",
                    "Explore Research Opportunities (UConn Office of Undergraduate Research)",
                    "https://ugradresearch.uconn.edu/explore-opportunities/",
                    "OUR's guide to finding undergraduate research opportunities at "
                    "UConn: how to identify labs and faculty mentors, browse posted "
                    "research positions, and connect with departments across the "
                    "sciences, engineering, humanities, and social sciences. It "
                    "walks students through the first steps of joining a research "
                    "project or creative endeavor.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "research positions",
                              "contacting faculty", "getting started"],
                ),
                program(
                    "uconn_surf",
                    "SURF: Summer Undergraduate Research Fund (University of Connecticut)",
                    "https://ugradresearch.uconn.edu/surf/",
                    "The Summer Undergraduate Research Fund (SURF) provides "
                    "competitive awards supporting UConn undergraduates conducting "
                    "full-time research or creative projects over the summer under "
                    "faculty mentorship. Open to students in all schools and "
                    "colleges, SURF funds independent, student-designed projects "
                    "across disciplines.",
                    lab_or_program="Summer Undergraduate Research Fund",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "SURF award",
                              "faculty-mentored research", "research stipend"],
                ),
                program(
                    "uconn_idea_grant",
                    "UConn IDEA Grant Program (University of Connecticut)",
                    "https://ugradresearch.uconn.edu/idea-2/idea-program-information/",
                    "The UConn IDEA Grant awards funding to support "
                    "student-designed projects, including research, creative work, "
                    "community engagement, and entrepreneurial ventures. Open to "
                    "undergraduates in every major, IDEA Grants fund individual or "
                    "small-group projects proposed and led by the students "
                    "themselves, with faculty or staff mentorship.",
                    lab_or_program="UConn IDEA Grant",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["IDEA Grant", "student-designed project",
                              "research funding", "creative projects"],
                ),
                program(
                    "uconn_health_research_program",
                    "Barbara C. Setlow Health Research Program (University of Connecticut)",
                    "https://ugradresearch.uconn.edu/hrp/",
                    "The Barbara C. Setlow Health Research Program supports UConn "
                    "undergraduates pursuing mentored research in the health and "
                    "life sciences, pairing students with faculty on projects "
                    "spanning biomedical, clinical, and public-health topics. It "
                    "provides funding and structured support for students exploring "
                    "health-related research careers.",
                    lab_or_program="Health Research Program",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["health research", "biomedical research",
                              "life sciences", "faculty-mentored research"],
                ),
                program(
                    "uconn_research_apprenticeship_program",
                    "Research Apprenticeship Program (UConn Office of Undergraduate Research)",
                    "https://ugradresearch.uconn.edu/research-apprenticeship-program/",
                    "The Research Apprenticeship Program introduces UConn "
                    "undergraduates to research by placing them as apprentices "
                    "alongside faculty and graduate-student mentors. Designed for "
                    "students new to research, it offers hands-on entry into a lab "
                    "or scholarly project and a first step toward independent "
                    "undergraduate research.",
                    lab_or_program="Research Apprenticeship Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["research apprenticeship", "first research experience",
                              "faculty mentorship", "getting started"],
                ),
            ],
        },
    ],
}
