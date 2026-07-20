"""University of Texas at Dallas campus opportunity-graph config.

Curated seed records of UT Dallas's undergraduate-research landscape, centered on
the Office of Undergraduate Education (OUE) research unit
(``oue.utdallas.edu/research/``) — the campus hub — plus three OUE-administered
programs: the Undergraduate Research Scholar Awards (URSA), the Patti Henry Pinch
Scholarship for Undergraduate Research, and OUE's Prospective Undergraduate
Researchers getting-started guide. Every URL was curl-verified live (HTTP 200)
through the proxy on 2026-07-20.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> utdallas_research_programs (utdallas / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "utdallas",
    "organization": "The University of Texas at Dallas",
    "location": "Richardson, TX",
    "emit": {
        "campus": ("utdallas_research_programs", "utdallas", "campus"),
    },
    "sources": [
        {
            "source_name": "utdallas_oue_research_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://oue.utdallas.edu/research/",
                "https://oue.utdallas.edu/research/student-research-resources/",
            ],
            "programs": [
                program(
                    "utdallas_oue_undergraduate_research",
                    "Undergraduate Research (UT Dallas Office of Undergraduate Education)",
                    "https://oue.utdallas.edu/research/",
                    "The Office of Undergraduate Education's research unit is UT "
                    "Dallas's hub for undergraduate research, helping students of "
                    "every major find faculty mentors, join labs and scholarly "
                    "projects, secure research funding, and present their work. It "
                    "connects prospective researchers with opportunities across the "
                    "sciences, engineering, arts, and humanities and explains how "
                    "to get started.",
                    lab_or_program="Office of Undergraduate Education — Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "utdallas_ursa",
                    "Undergraduate Research Scholar Awards (UT Dallas)",
                    "https://oue.utdallas.edu/research/undergraduate-research-scholar-awards/",
                    "The Undergraduate Research Scholar Awards (URSA) are "
                    "competitive awards from the Office of Undergraduate Education "
                    "that recognize UT Dallas undergraduate researchers and support "
                    "their professional development. Recipients receive a monetary "
                    "award tied to participation in the URSA poster competition held "
                    "each spring, showcasing faculty-mentored research across "
                    "disciplines.",
                    lab_or_program="Undergraduate Research Scholar Awards",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research award", "poster competition",
                              "faculty-mentored research", "undergraduate research"],
                ),
                program(
                    "utdallas_patti_henry_pinch",
                    "Patti Henry Pinch Scholarship for Undergraduate Research (UT Dallas)",
                    "https://oue.utdallas.edu/research/patti-henry-pinch-scholarship-for-undergraduate-research/",
                    "The Patti Henry Pinch Scholarship helps UT Dallas "
                    "undergraduates cover research and travel expenses through "
                    "supplemental financial support, jointly funded by the "
                    "student's school and the Office of Undergraduate Education. It "
                    "is intended to fund research activities where other sources of "
                    "support are inadequate or unavailable, so students can pursue "
                    "and present mentored research.",
                    lab_or_program="Patti Henry Pinch Scholarship",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research scholarship", "travel funding",
                              "undergraduate research", "conference travel"],
                ),
                program(
                    "utdallas_prospective_researchers",
                    "Prospective Undergraduate Researchers (UT Dallas Office of Undergraduate Education)",
                    "https://oue.utdallas.edu/research/student-research-resources/prospective-undergraduate-researchers/",
                    "OUE's guide for UT Dallas students who want to start doing "
                    "research: how to identify faculty mentors and labs, approach "
                    "professors, find funded and for-credit research opportunities, "
                    "and take the first steps toward joining a research project. A "
                    "practical entry point for students new to undergraduate "
                    "research in any field.",
                    lab_or_program="Office of Undergraduate Education — Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "getting started",
                              "contacting faculty", "research positions"],
                ),
            ],
        },
    ],
}
