"""University of Utah campus opportunity-graph config.

Curated seed records of Utah's undergraduate-research landscape, centered on the
Office of Undergraduate Research (our.utah.edu) — its office hub, the two flagship
named programs (UROP academic-year mentored research + SPUR summer research), the
OUR Research Opportunity Database for finding a project/mentor, and the Travel &
Small Grants fund. URLs curl-verified live (HTTP 200, direct — the short
/urop/ and /spur/ aliases 301-redirect into these canonical
/research-scholarship-opportunities/ paths) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → utah_research_programs (utah / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "utah",
    "organization": "University of Utah",
    "location": "Salt Lake City, UT",
    "emit": {
        "campus": ("utah_research_programs", "utah", "campus"),
    },
    "sources": [
        {
            "source_name": "utah_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://our.utah.edu/",
                "https://our.utah.edu/find-a-research-opportunity/",
            ],
            "programs": [
                program(
                    "utah_office_undergraduate_research",
                    "Office of Undergraduate Research (University of Utah)",
                    "https://our.utah.edu/",
                    "The University of Utah's Office of Undergraduate Research "
                    "(OUR) helps students of every major get involved in research "
                    "and creative projects, connecting them with faculty mentors, "
                    "funding, and structured scholar programs. It is the campus hub "
                    "for discovering opportunities, learning how to find a mentor, "
                    "and getting started in undergraduate research.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "utah_urop",
                    "Undergraduate Research Opportunities Program (UROP) — University of Utah",
                    "https://our.utah.edu/research-scholarship-opportunities/urop/",
                    "UROP is the University of Utah's flagship mentored-research "
                    "program: it pays undergraduates an hourly wage to work on a "
                    "research or creative project with a faculty mentor during the "
                    "academic year. Open to students across all disciplines, UROP "
                    "supports assistantships that pair students one-on-one with "
                    "professors on active scholarly work.",
                    lab_or_program="UROP",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["UROP", "mentored research", "research assistantship",
                              "paid research"],
                ),
                program(
                    "utah_spur",
                    "Summer Program for Undergraduate Research (SPUR) — University of Utah",
                    "https://our.utah.edu/research-scholarship-opportunities/spur/",
                    "SPUR is the University of Utah's ten-week summer research "
                    "program: undergraduates work full-time on an independent "
                    "research project under a faculty mentor and receive a stipend, "
                    "plus professional-development and cohort activities. It is "
                    "designed for students preparing for graduate school or "
                    "research-intensive careers across STEM and other fields.",
                    lab_or_program="SPUR",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["SPUR", "summer research", "research stipend",
                              "faculty mentor"],
                ),
                program(
                    "utah_our_research_opportunity_database",
                    "OUR Research Opportunity Database (University of Utah)",
                    "https://our.utah.edu/find-a-research-opportunity/",
                    "A searchable database of open research positions posted by "
                    "University of Utah faculty who are looking for undergraduate "
                    "research assistants. Students can browse projects by "
                    "department and topic to find a lab to join and a mentor to "
                    "contact, making it the starting point for finding a research "
                    "opportunity on campus.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["find a mentor", "research positions",
                              "lab openings", "any major"],
                ),
                program(
                    "utah_travel_small_grants",
                    "Undergraduate Research Travel & Small Grants (University of Utah)",
                    "https://our.utah.edu/research-scholarship-opportunities/travel-small-grants/",
                    "The Office of Undergraduate Research awards Travel and Small "
                    "Grants that help University of Utah undergraduates present "
                    "their research at conferences and cover project-related "
                    "expenses such as materials and supplies. The funds support "
                    "students who are already engaged in mentored research and "
                    "need financial help to advance or share their work.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["travel grant", "conference funding",
                              "research supplies", "student funding"],
                ),
            ],
        },
    ],
}
