"""University of Houston campus opportunity-graph config.

Curated seed records of UH's undergraduate-research landscape, centered on the
Office of Undergraduate Research and Major Awards (OURMA) —
uh.edu/honors/undergraduate-research — its office hub, the "getting started"
pathway, and the named OURMA programs: the Houston Early Research Experience
(HERE), the Summer Undergraduate Research Fellowship (SURF), the Provost's
Undergraduate Research Scholarship (PURS), and the Houston Scholars program.
Every URL curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → houston_research_programs (houston / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "houston",
    "organization": "University of Houston",
    "location": "Houston, TX",
    "emit": {
        "campus": ("houston_research_programs", "houston", "campus"),
    },
    "sources": [
        {
            "source_name": "houston_ourma_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.uh.edu/honors/undergraduate-research/",
                "https://www.uh.edu/honors/undergraduate-research/our-programs/",
            ],
            "programs": [
                program(
                    "houston_ourma_office",
                    "Office of Undergraduate Research and Major Awards (University of Houston)",
                    "https://www.uh.edu/honors/undergraduate-research/",
                    "The University of Houston's Office of Undergraduate Research "
                    "and Major Awards (OURMA) is the campus hub for getting "
                    "undergraduates of every major involved in research. It "
                    "connects students with faculty mentors, funds mentored "
                    "research through named fellowship and scholarship programs, "
                    "and supports students applying for prestigious national "
                    "awards.",
                    lab_or_program="Office of Undergraduate Research and Major Awards",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "houston_getting_started_research",
                    "Getting Started in Research (University of Houston)",
                    "https://www.uh.edu/honors/undergraduate-research/about/getting-started/",
                    "UH's guide for undergraduates new to research: how to explore "
                    "your interests, find and contact a faculty mentor, and take "
                    "the first steps into a lab or scholarly project. It walks "
                    "students through identifying opportunities across campus and "
                    "preparing to reach out to potential research advisors.",
                    lab_or_program="Office of Undergraduate Research and Major Awards",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
                program(
                    "houston_here",
                    "Houston Early Research Experience (HERE)",
                    "https://www.uh.edu/honors/undergraduate-research/our-programs/here/",
                    "The Houston Early Research Experience (HERE) introduces "
                    "first- and second-year UH students to hands-on research early "
                    "in their college careers, pairing them with faculty mentors "
                    "and a supportive cohort. It is designed to help students who "
                    "are new to research explore a discipline and build the skills "
                    "to continue in a lab.",
                    lab_or_program="Houston Early Research Experience",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["early research experience", "first-year research",
                              "faculty mentorship", "research cohort"],
                ),
                program(
                    "houston_surf",
                    "Summer Undergraduate Research Fellowship (SURF)",
                    "https://www.uh.edu/honors/undergraduate-research/our-programs/surf/",
                    "The Summer Undergraduate Research Fellowship (SURF) funds UH "
                    "undergraduates to work full-time on a mentored research "
                    "project over roughly ten weeks in the summer, culminating in "
                    "a research showcase. Fellows receive a stipend and work "
                    "closely with a faculty mentor across the sciences, "
                    "engineering, humanities, and other disciplines.",
                    lab_or_program="Summer Undergraduate Research Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "research fellowship",
                              "stipend", "full-time research"],
                ),
                program(
                    "houston_purs",
                    "Provost's Undergraduate Research Scholarship (PURS)",
                    "https://www.uh.edu/honors/undergraduate-research/our-programs/purs/",
                    "The Provost's Undergraduate Research Scholarship (PURS) funds "
                    "UH undergraduates to carry out a part-time, mentored research "
                    "project during the fall or spring semester. Students design a "
                    "project with a faculty mentor and receive a scholarship to "
                    "support their independent research during the academic year.",
                    lab_or_program="Provost's Undergraduate Research Scholarship",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["semester research", "research scholarship",
                              "mentored research", "independent study"],
                ),
                program(
                    "houston_scholars",
                    "Houston Scholars (University of Houston)",
                    "https://www.uh.edu/honors/undergraduate-research/our-programs/houston-scholars/",
                    "The Houston Scholars program supports UH undergraduates in "
                    "early academic development and mentored research, helping "
                    "students build a scholarly identity and pathway toward "
                    "advanced research and major national awards. Scholars receive "
                    "mentorship, community, and guidance as they grow into "
                    "independent researchers.",
                    lab_or_program="Houston Scholars",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["scholars program", "academic development",
                              "faculty mentorship", "undergraduate research"],
                ),
            ],
        },
    ],
}
