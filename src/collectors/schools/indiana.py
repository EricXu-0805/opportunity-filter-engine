"""Indiana University Bloomington campus opportunity-graph config.

Curated seed records of IU Bloomington's undergraduate-research landscape,
centered on the IU Undergraduate Research office (undergradresearch.indiana.edu)
— its office hub, the getting-started pathway, the residential Summer Research
Program, and the Advanced Summer Research Scholarships funding track. Every URL
curl-verified live (HTTP 200) through a proxy on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → indiana_research_programs (indiana / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "indiana",
    "organization": "Indiana University Bloomington",
    "location": "Bloomington, IN",
    "emit": {
        "campus": ("indiana_research_programs", "indiana", "campus"),
    },
    "sources": [
        {
            "source_name": "indiana_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergradresearch.indiana.edu/index.html",
                "https://undergradresearch.indiana.edu/programs/index.html",
            ],
            "programs": [
                program(
                    "indiana_undergraduate_research_office",
                    "IU Undergraduate Research (Indiana University Bloomington)",
                    "https://undergradresearch.indiana.edu/index.html",
                    "Indiana University Bloomington's central Undergraduate "
                    "Research office helps students of every major and every "
                    "stage get involved in research, connecting them with faculty "
                    "mentors, funding, summer programs, and ways to share their "
                    "work. It is the campus hub for discovering opportunities, "
                    "learning how to get started, and finding support for "
                    "undergraduate research and creative activity.",
                    lab_or_program="IU Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "indiana_summer_research_program",
                    "IUUR Summer Research Program (Indiana University Bloomington)",
                    "https://undergradresearch.indiana.edu/programs/summer-research.html",
                    "The IU Undergraduate Research Summer Research Program provides "
                    "undergraduates with an on-campus, residential research "
                    "experience over the summer, pairing students with faculty "
                    "mentors on original projects. The program spans STEM and, in "
                    "its expanded form, disciplines beyond STEM, giving students a "
                    "full-time immersive introduction to scholarly research.",
                    lab_or_program="IU Undergraduate Research",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "residential program",
                              "faculty mentorship", "STEM research"],
                ),
                program(
                    "indiana_advanced_summer_research_scholarships",
                    "Advanced Summer Research Scholarships (Indiana University Bloomington)",
                    "https://undergradresearch.indiana.edu/funding/asrs.html",
                    "IU Undergraduate Research's Advanced Summer Research "
                    "Scholarships help undergraduate researchers spend their "
                    "summers undertaking original research or creative projects "
                    "with a faculty mentor. The scholarships fund students who "
                    "have already begun research and are ready to pursue a more "
                    "advanced, independent summer project.",
                    lab_or_program="IU Undergraduate Research",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["summer scholarship", "research funding",
                              "independent research", "creative projects"],
                ),
                program(
                    "indiana_getting_started_research",
                    "Getting Started with Undergraduate Research (Indiana University Bloomington)",
                    "https://undergradresearch.indiana.edu/getting-started/index.html",
                    "IU Bloomington's guide for undergraduates new to research: "
                    "how to explore interests, build skills, identify and contact "
                    "faculty mentors, and take the first steps into a lab or "
                    "creative project. It is designed for students at every stage, "
                    "whether exploring interests or preparing for graduate school "
                    "or a career.",
                    lab_or_program="IU Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
            ],
        },
    ],
}
