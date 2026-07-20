"""University of Kentucky campus opportunity-graph config.

Curated seed records of UK's undergraduate-research landscape, centered on the
Office of Undergraduate Research (OUR, our.uky.edu) — its office hub and
"Getting Started" guide — plus four flagship OUR-administered programs: the
Beckman Scholars Program, the CURE (Commonwealth Undergraduate Research
Experience) Fellowship, the Sustainability Research Fellowships, and the
Undergraduate Research Ambassadors peer program. Every URL was curl-verified
live (HTTP 200) on 2026-07-20 (``/students/get-started`` 301-redirects to its
canonical ``/getstarted``).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uky_research_programs (uky / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "uky",
    "organization": "University of Kentucky",
    "location": "Lexington, KY",
    "emit": {
        "campus": ("uky_research_programs", "uky", "campus"),
    },
    "sources": [
        {
            "source_name": "uky_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://our.uky.edu/",
                "https://our.uky.edu/getstarted",
            ],
            "programs": [
                program(
                    "uky_office_of_undergraduate_research",
                    "Office of Undergraduate Research (University of Kentucky)",
                    "https://our.uky.edu/",
                    "UK's Office of Undergraduate Research (OUR) helps students of "
                    "every major get involved in mentored research and creative "
                    "work, connecting them with faculty mentors, funding, and "
                    "structured programs. It is the campus hub for finding "
                    "opportunities, learning how to get started, and applying for "
                    "research funding, fellowships, and presentation support.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "uky_get_started",
                    "Getting Started in Undergraduate Research (UK Office of Undergraduate Research)",
                    "https://our.uky.edu/getstarted",
                    "OUR's step-by-step guide to beginning undergraduate research "
                    "at UK: how to identify research areas and faculty mentors, "
                    "reach out to professors, and join a lab or scholarly project. "
                    "It walks students new to research through the first steps of "
                    "finding and securing a mentored research position across the "
                    "sciences, engineering, humanities, and social sciences.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "getting started",
                              "contacting faculty", "first research experience"],
                ),
                program(
                    "uky_beckman_scholars",
                    "Beckman Scholars Program (University of Kentucky)",
                    "https://our.uky.edu/BeckmanScholars",
                    "The Beckman Scholars Program provides a prestigious, multi-year "
                    "mentored research experience with a generous stipend for "
                    "outstanding UK undergraduates in chemistry, biochemistry, and "
                    "the biological and medical sciences. Funded by the Arnold and "
                    "Mabel Beckman Foundation, scholars conduct in-depth research "
                    "under a faculty mentor across two summers and the intervening "
                    "academic year.",
                    lab_or_program="Beckman Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["Beckman Scholars", "chemistry", "biochemistry",
                              "mentored research", "research stipend"],
                ),
                program(
                    "uky_cure_fellowship",
                    "CURE Fellowship: Commonwealth Undergraduate Research Experience (University of Kentucky)",
                    "https://our.uky.edu/CURE-Fellowship",
                    "The Commonwealth Undergraduate Research Experience (CURE) "
                    "Fellowship supports UK undergraduates — especially first- and "
                    "second-year students — in beginning faculty-mentored research "
                    "with a stipend. Open to students across disciplines, CURE pairs "
                    "students with a faculty mentor for a semester of hands-on "
                    "research and is a structured entry point into UK's research "
                    "community.",
                    lab_or_program="CURE Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["CURE Fellowship", "first-year research",
                              "faculty-mentored research", "research stipend"],
                ),
                program(
                    "uky_sustainability_fellowship",
                    "Sustainability Research Fellowships (University of Kentucky)",
                    "https://our.uky.edu/sustainability-fellowship",
                    "The Sustainability Research Fellowships fund UK undergraduates "
                    "pursuing faculty-mentored research and creative projects on "
                    "sustainability — spanning environmental, energy, social, and "
                    "economic dimensions. Administered through the Office of "
                    "Undergraduate Research with UK's sustainability program, the "
                    "fellowships provide a stipend for student-designed projects "
                    "that advance a more sustainable Commonwealth.",
                    lab_or_program="Sustainability Research Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["sustainability research", "environmental research",
                              "energy", "student-designed project"],
                ),
                program(
                    "uky_research_ambassadors",
                    "Undergraduate Research Ambassadors (UK Office of Undergraduate Research)",
                    "https://our.uky.edu/ambassadors",
                    "The Undergraduate Research Ambassadors are a peer team of "
                    "experienced UK student researchers who help fellow "
                    "undergraduates get started in research — hosting workshops, "
                    "advising on finding mentors, and sharing their own paths into "
                    "the lab. Joining is a leadership and peer-mentorship "
                    "opportunity for students already engaged in undergraduate "
                    "research.",
                    lab_or_program="Undergraduate Research Ambassadors",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research ambassador", "peer mentorship",
                              "student leadership", "getting started"],
                ),
            ],
        },
    ],
}
