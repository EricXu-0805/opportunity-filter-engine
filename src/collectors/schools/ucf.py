"""University of Central Florida campus opportunity-graph config.

Curated seed records of UCF's undergraduate-research landscape, centered on the
Office of Undergraduate Research (OUR). The office's public site is served from
``academicsuccess.ucf.edu/our/`` (the ``www.our.ucf.edu`` vanity host mirrors
it); every URL below was curl-verified live (HTTP 200) on 2026-07-19.

Seeds: the OUR office hub + its Funding Opportunities / named-programs page.
Programs: the office hub, the Summer Undergraduate Research Fellowship (SURF),
the named scholar/mentoring programs (RAMP, L.E.A.R.N. first-year, McNair), the
OUR Research Grants, and the "looking for research opportunities" getting-started
pathway.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ucf_research_programs (ucf / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "ucf",
    "organization": "University of Central Florida",
    "location": "Orlando, FL",
    "emit": {
        "campus": ("ucf_research_programs", "ucf", "campus"),
    },
    "sources": [
        {
            "source_name": "ucf_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://academicsuccess.ucf.edu/our/",
                "https://academicsuccess.ucf.edu/our/current/programs/",
            ],
            "programs": [
                program(
                    "ucf_office_of_undergraduate_research",
                    "Office of Undergraduate Research (UCF)",
                    "https://academicsuccess.ucf.edu/our/",
                    "The University of Central Florida's Office of Undergraduate "
                    "Research (OUR) helps students of every major get involved in "
                    "research, connecting them with faculty mentors, funding, and "
                    "named scholar programs. It is the campus hub for discovering "
                    "opportunities, learning how to get started, and finding "
                    "support for undergraduate research and creative projects.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "ucf_surf",
                    "Summer Undergraduate Research Fellowship — SURF (UCF)",
                    "https://academicsuccess.ucf.edu/our/summer-undergraduate-research-fellowship/",
                    "SURF is UCF's Summer Undergraduate Research Fellowship: a "
                    "competitive award that funds students to work full-time on a "
                    "faculty-mentored research or creative project over the summer, "
                    "with a stipend and structured cohort support. Open to "
                    "continuing UCF undergraduates across disciplines who have "
                    "identified a faculty mentor.",
                    lab_or_program="Summer Undergraduate Research Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["summer research", "research fellowship",
                              "stipend", "faculty-mentored"],
                ),
                program(
                    "ucf_ramp_scholar_programs",
                    "RAMP, L.E.A.R.N. & McNair Scholar Programs (UCF)",
                    "https://academicsuccess.ucf.edu/our/current/programs/",
                    "UCF's structured undergraduate-research scholar programs, "
                    "including the Research and Mentoring Program (RAMP) and the "
                    "L.E.A.R.N. first-year program for students new to research, "
                    "and the McNair Scholars Program preparing underrepresented "
                    "and first-generation students for doctoral study. These "
                    "cohort programs pair students with faculty mentors and provide "
                    "training, community, and funding toward graduate school.",
                    lab_or_program="Research and Mentoring Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["RAMP", "McNair Scholars", "first-year research",
                              "mentoring program"],
                ),
                program(
                    "ucf_our_research_grants",
                    "OUR Research & Presentation Grants (UCF)",
                    "https://academicsuccess.ucf.edu/our/research-grants/",
                    "The Office of Undergraduate Research awards competitive "
                    "Research Grants that fund undergraduate research project "
                    "expenses (supplies, materials, and related costs) and "
                    "Presentation Travel Awards that help students present their "
                    "work at conferences. Applications are accepted on a rolling "
                    "basis for UCF undergraduates working with a faculty mentor.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research grants", "presentation travel award",
                              "project funding", "conference travel"],
                ),
                program(
                    "ucf_looking_for_research",
                    "Looking for Research Opportunities (UCF)",
                    "https://academicsuccess.ucf.edu/our/looking-for-research-opportunities/",
                    "UCF's guide for undergraduates new to research: how to explore "
                    "interests, identify and contact faculty mentors, and take the "
                    "first steps into a lab or creative project. It walks students "
                    "through finding on-campus opportunities and preparing to reach "
                    "out to potential research advisors across every college.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
            ],
        },
    ],
}
