"""Iowa State University campus opportunity-graph config.

Curated seed records of Iowa State's undergraduate-research landscape, centered
on EUReCA — Exploring Undergraduate Research and Creative Activity, the campus
office at undergradresearch.iastate.edu. Seeds the office hub, its Iowa State
Opportunities database, the Summer Research Experiences for Undergraduates (REU)
listing, and the getting-started pathway. Every URL curl-verified live (HTTP 200)
on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → iastate_research_programs (iastate / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "iastate",
    "organization": "Iowa State University",
    "location": "Ames, IA",
    "emit": {
        "campus": ("iastate_research_programs", "iastate", "campus"),
    },
    "sources": [
        {
            "source_name": "iastate_eureca_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.undergradresearch.iastate.edu/",
                "https://www.undergradresearch.iastate.edu/iowa-state-opportunities",
            ],
            "programs": [
                program(
                    "iastate_eureca_office",
                    "Undergraduate Research at Iowa State (EUReCA)",
                    "https://www.undergradresearch.iastate.edu/",
                    "EUReCA — Exploring Undergraduate Research and Creative "
                    "Activity — is Iowa State University's central office for "
                    "undergraduate research. It helps students of every major get "
                    "started in research, connect with faculty mentors, find "
                    "funding, present their work, and discover named scholar and "
                    "summer research programs across campus.",
                    lab_or_program="EUReCA (Undergraduate Research)",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "any major", "creative activity"],
                ),
                program(
                    "iastate_iowa_state_opportunities",
                    "Iowa State Research Opportunities database (EUReCA)",
                    "https://www.undergradresearch.iastate.edu/iowa-state-opportunities",
                    "A curated listing of on-campus undergraduate research "
                    "opportunities at Iowa State University, spanning departments "
                    "and colleges. Students can browse posted research positions, "
                    "programs, and mentored projects to find a lab or faculty "
                    "mentor that matches their interests.",
                    lab_or_program="EUReCA (Undergraduate Research)",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research opportunities", "on-campus research",
                              "finding a lab", "faculty mentor"],
                ),
                program(
                    "iastate_summer_reu",
                    "Summer Research Experiences for Undergraduates (Iowa State)",
                    "https://www.undergradresearch.iastate.edu/summer-research-experiences-undergraduates",
                    "Iowa State's guide to Summer Research Experiences for "
                    "Undergraduates (REU), including NSF-funded REU sites and "
                    "structured summer research programs open to ISU and visiting "
                    "students. These paid, full-time summer placements pair "
                    "undergraduates with faculty mentors on focused research "
                    "projects across STEM and other fields.",
                    lab_or_program="EUReCA (Undergraduate Research)",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "paid research",
                              "NSF-funded"],
                ),
                program(
                    "iastate_getting_started_research",
                    "Getting Started with Undergraduate Research (Iowa State EUReCA)",
                    "https://www.undergradresearch.iastate.edu/how-get-started",
                    "Iowa State's step-by-step guide for undergraduates new to "
                    "research: how to explore interests, identify and contact "
                    "faculty mentors, and take the first steps into a lab or "
                    "creative project. It walks students through finding "
                    "opportunities on campus and preparing to reach out to "
                    "potential research advisors.",
                    lab_or_program="EUReCA (Undergraduate Research)",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
            ],
        },
    ],
}
