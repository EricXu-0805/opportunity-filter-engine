"""University of Delaware campus opportunity-graph config.

Curated seed records of UD's undergraduate-research landscape, centered on the
Undergraduate Research Program office (urp.udel.edu) — its office hub, the
getting-started pathway, the Summer Programs index (named summer scholar / REU
placements), the University of Delaware Research Apprenticeship (UDRAW) for
first- and second-year students, and the Winter Fellows Award. URLs
curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → udel_research_programs (udel / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "udel",
    "organization": "University of Delaware",
    "location": "Newark, DE",
    "emit": {
        "campus": ("udel_research_programs", "udel", "campus"),
    },
    "sources": [
        {
            "source_name": "udel_urp_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.urp.udel.edu/",
                "https://www.urp.udel.edu/summer-programs/",
            ],
            "programs": [
                program(
                    "udel_undergraduate_research_program",
                    "Undergraduate Research Program (University of Delaware)",
                    "https://www.urp.udel.edu/",
                    "The University of Delaware's Undergraduate Research Program is "
                    "the campus hub for getting involved in research and creative "
                    "scholarship across every college and major. It connects "
                    "students with faculty mentors, funding awards, summer programs, "
                    "and the annual symposium, and guides them from first exploring "
                    "research to presenting their own work.",
                    lab_or_program="Undergraduate Research Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "udel_getting_started_research",
                    "Getting Started with Undergraduate Research (University of Delaware)",
                    "https://www.urp.udel.edu/getting-started/",
                    "UD's guide for undergraduates new to research: how to explore "
                    "your interests, identify and approach faculty mentors, and take "
                    "the first steps into a lab or creative project. It walks "
                    "students through finding on-campus opportunities and preparing "
                    "to contact potential research advisors.",
                    lab_or_program="Undergraduate Research Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
                program(
                    "udel_summer_programs",
                    "Summer Research Programs (University of Delaware)",
                    "https://www.urp.udel.edu/summer-programs/",
                    "UD's index of summer undergraduate research programs, including "
                    "Summer Scholars, National Science Foundation REU sites, and "
                    "discipline-specific summer research fellowships. Students can "
                    "browse funded, full-time summer placements that pair them with "
                    "a faculty mentor and a stipend across the sciences, engineering, "
                    "and beyond.",
                    lab_or_program="Undergraduate Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["Summer Scholars", "REU", "summer research",
                              "research stipend"],
                ),
                program(
                    "udel_udraw_apprenticeship",
                    "UD Research Apprenticeship (UDRAW)",
                    "https://www.urp.udel.edu/udraw/",
                    "The University of Delaware Research Apprenticeship (UDRAW) pairs "
                    "first- and second-year students with an experienced student "
                    "researcher and faculty mentor to learn the fundamentals of "
                    "research early in their undergraduate career. It is designed as "
                    "an on-ramp for newcomers to get hands-on lab experience before "
                    "leading their own project.",
                    lab_or_program="UDRAW",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["research apprenticeship", "first-year research",
                              "peer mentoring", "getting started"],
                ),
                program(
                    "udel_winter_fellows_award",
                    "Winter Fellows Award (University of Delaware)",
                    "https://www.urp.udel.edu/winter-fellows-award/",
                    "The Winter Fellows Award funds University of Delaware "
                    "undergraduates to conduct full-time research or creative work "
                    "with a faculty mentor over Winter Session. It provides a "
                    "stipend for a concentrated, multi-week research experience "
                    "between fall and spring terms.",
                    lab_or_program="Undergraduate Research Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["winter session research", "research fellowship",
                              "research stipend", "faculty mentorship"],
                ),
            ],
        },
    ],
}
