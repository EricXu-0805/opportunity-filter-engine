"""Rensselaer Polytechnic Institute campus opportunity-graph config.

Curated seed records of RPI's undergraduate-research landscape, centered on the
Office of Undergraduate Education's Undergraduate Research hub
(undergrad.rpi.edu/undergraduate-research) — the office itself, its flagship
Summer Undergraduate Research Award, the faculty-research-advisor pathway, and
the campus fellowships & scholarships office. URLs curl-verified live (HTTP 200)
on 2026-07-19; the older info.rpi.edu/undergraduate-research hub now
301-redirects to the undergrad.rpi.edu path, which these seeds use directly.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → rpi_research_programs (rpi / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "rpi",
    "organization": "Rensselaer Polytechnic Institute",
    "location": "Troy, NY",
    "emit": {
        "campus": ("rpi_research_programs", "rpi", "campus"),
    },
    "sources": [
        {
            "source_name": "rpi_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergrad.rpi.edu/undergraduate-research",
                "https://research.rpi.edu/",
            ],
            "programs": [
                program(
                    "rpi_undergraduate_research_office",
                    "Undergraduate Research (Rensselaer Polytechnic Institute)",
                    "https://undergrad.rpi.edu/undergraduate-research",
                    "Rensselaer's Office of Undergraduate Education hub for "
                    "undergraduate research: it helps students of every major get "
                    "involved in faculty-mentored research, learn how to identify "
                    "and approach a research advisor, and find funding and academic "
                    "credit for their projects. The central starting point for "
                    "discovering research opportunities across RPI's schools of "
                    "Engineering, Science, Architecture, Humanities/Arts/Social "
                    "Sciences, and the Lally School of Management.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research credit", "any major"],
                ),
                program(
                    "rpi_summer_undergraduate_research_award",
                    "Summer Undergraduate Research Award (Rensselaer)",
                    "https://undergrad.rpi.edu/undergraduate-research/summer-undergraduate-research-award",
                    "The Summer Undergraduate Research Award (SURA) funds RPI "
                    "undergraduates to work full-time on a faculty-mentored "
                    "research project over the summer, providing a stipend so "
                    "students can pursue hands-on research in science, "
                    "engineering, architecture, management, or the humanities. "
                    "Students apply with a faculty mentor and a research proposal "
                    "for a structured summer research experience on campus.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "research stipend",
                              "faculty-mentored", "SURA"],
                ),
                program(
                    "rpi_faculty_research_advisors",
                    "Finding a Faculty Research Advisor (Rensselaer)",
                    "https://undergrad.rpi.edu/undergraduate-research/faculty-research-advisors",
                    "RPI's guide for undergraduates on identifying and connecting "
                    "with a faculty research advisor: how to explore faculty "
                    "research areas, reach out to professors whose work matches "
                    "their interests, and arrange to join a lab or research group. "
                    "The practical first step for a student who wants to start "
                    "research but needs to find and contact a mentor.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["finding a mentor", "contacting faculty",
                              "research advisor", "getting started"],
                ),
                program(
                    "rpi_fellowships_and_scholarships",
                    "Fellowships and Scholarships (Rensselaer Undergraduate Education)",
                    "https://undergrad.rpi.edu/fellowships-and-scholarships",
                    "Rensselaer's Office of Undergraduate Education fellowships and "
                    "scholarships hub points students to nationally competitive "
                    "awards and research fellowships (Goldwater, Fulbright, NSF and "
                    "similar) and helps them prepare applications. It supports "
                    "undergraduates seeking funding for research, graduate study, "
                    "and scholarly projects across disciplines.",
                    lab_or_program="Undergraduate Education",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["fellowships", "scholarships",
                              "Goldwater", "research funding"],
                ),
            ],
        },
    ],
}
