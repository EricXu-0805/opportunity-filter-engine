"""University of Miami campus opportunity-graph config.

Curated seed records of the University of Miami's undergraduate-research
landscape, centered on the Office of Undergraduate Research (ugr.miami.edu) — its
office hub plus the named programs it runs: MUSE (Mentors for Undergraduate
Scholarship Enrichment), SPARK (Sylvester Program for Academic Research &
Knowledge), UConnect, and the Open Research Positions board. URLs curl-verified
live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → miami_research_programs (miami / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "miami",
    "organization": "University of Miami",
    "location": "Coral Gables, FL",
    "emit": {
        "campus": ("miami_research_programs", "miami", "campus"),
    },
    "sources": [
        {
            "source_name": "miami_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ugr.miami.edu/",
                "https://ugr.miami.edu/research/open-positions/index.html",
            ],
            "programs": [
                program(
                    "miami_office_of_undergraduate_research",
                    "Office of Undergraduate Research (University of Miami)",
                    "https://ugr.miami.edu/",
                    "The University of Miami's Office of Undergraduate Research "
                    "helps students of every major get started in research — "
                    "connecting them with faculty mentors, funded scholar "
                    "programs, and a board of open research positions. It is the "
                    "campus hub for discovering opportunities, learning how to "
                    "get involved, and finding support for undergraduate research "
                    "and creative scholarship.",
                    organization="University of Miami",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "any major", "getting started"],
                ),
                program(
                    "miami_muse_scholars",
                    "MUSE Scholars — Mentors for Undergraduate Scholarship Enrichment (University of Miami)",
                    "https://ugr.miami.edu/programs/muse-scholars/index.html",
                    "Mentors for Undergraduate Scholarship Enrichment (MUSE) pairs "
                    "University of Miami undergraduates with faculty and peer "
                    "mentors to launch and sustain a research project. The program "
                    "supports students — especially those newer to research — with "
                    "mentorship, community, and guidance as they design, conduct, "
                    "and present original scholarship across disciplines.",
                    organization="University of Miami",
                    lab_or_program="MUSE Scholars",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["mentored research", "scholars program",
                              "faculty mentorship", "undergraduate research"],
                ),
                program(
                    "miami_spark",
                    "SPARK — Sylvester Program for Academic Research & Knowledge (University of Miami)",
                    "https://ugr.miami.edu/programs/spark/index.html",
                    "The Sylvester Program for Academic Research & Knowledge "
                    "(SPARK) places University of Miami undergraduates in "
                    "faculty-mentored research, with an emphasis on biomedical, "
                    "health, and cancer-related science connected to the "
                    "university's Sylvester Comprehensive Cancer Center. Students "
                    "gain hands-on laboratory experience and mentorship while "
                    "contributing to active research projects.",
                    organization="University of Miami",
                    lab_or_program="SPARK",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["biomedical research", "cancer research",
                              "mentored research", "laboratory experience"],
                ),
                program(
                    "miami_uconnect",
                    "UConnect research matching (University of Miami)",
                    "https://ugr.miami.edu/programs/uconnect/index.html",
                    "UConnect is the University of Miami's program for connecting "
                    "undergraduates with research and experiential-learning "
                    "opportunities across campus. Students can explore faculty "
                    "projects and match with mentors whose work aligns with their "
                    "interests — a starting point for finding a lab or research "
                    "team to join.",
                    organization="University of Miami",
                    lab_or_program="UConnect",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research matching", "finding a mentor",
                              "faculty projects", "getting involved"],
                ),
                program(
                    "miami_open_research_positions",
                    "Open Research Positions board (University of Miami)",
                    "https://ugr.miami.edu/research/open-positions/index.html",
                    "A regularly updated listing of open undergraduate research "
                    "positions at the University of Miami, where faculty post "
                    "specific projects seeking student researchers. Students can "
                    "browse current openings by field and reach out to the posting "
                    "professor to apply for a spot in a lab or research group.",
                    organization="University of Miami",
                    lab_or_program="Open Research Positions",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["open positions", "research openings",
                              "apply to a lab", "faculty-posted projects"],
                ),
            ],
        },
    ],
}
