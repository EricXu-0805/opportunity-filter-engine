"""Stevens Institute of Technology campus opportunity-graph config.

Curated seed records of Stevens' undergraduate-research landscape, centered on the
Undergraduate Research hub (stevens.edu/undergraduate-research) — its office page
and the Portal for Undergraduate Research and Fellowships (PURF) — plus the
Summer Research Programs listing and the two flagship funded scholars programs
(the Lawrence T. Babbio '66 Pinnacle Scholars Program and the A. James Clark
Scholars Program). Every URL was curl-verified live (HTTP 200) on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → stevens_research_programs (stevens / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "stevens",
    "organization": "Stevens Institute of Technology",
    "location": "Hoboken, NJ",
    "emit": {
        "campus": ("stevens_research_programs", "stevens", "campus"),
    },
    "sources": [
        {
            "source_name": "stevens_undergraduate_research_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.stevens.edu/undergraduate-research",
                "https://www.stevens.edu/undergraduate-research/summer-research-programs",
            ],
            "programs": [
                program(
                    "stevens_undergraduate_research",
                    "Undergraduate Research (Stevens Institute of Technology)",
                    "https://www.stevens.edu/undergraduate-research",
                    "Stevens' Undergraduate Research hub is the campus starting point "
                    "for getting involved in faculty-mentored research across "
                    "engineering, the sciences, systems, business, and the arts. It "
                    "connects students with research advising, funding and "
                    "fellowship opportunities, and the annual Stevens Symposium for "
                    "Undergraduate Research, and explains how to find a faculty "
                    "mentor and join a lab.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research advising", "any major"],
                ),
                program(
                    "stevens_purf",
                    "Portal for Undergraduate Research and Fellowships (Stevens)",
                    "https://www.stevens.edu/undergraduate-research/portal-for-undergraduate-research-and-fellowship",
                    "The Portal for Undergraduate Research and Fellowships (PURF) is "
                    "Stevens' clearinghouse for finding and applying to research "
                    "positions, competitive fellowships, and scholarship "
                    "opportunities. It helps undergraduates identify faculty-led "
                    "projects, prepare applications for nationally competitive "
                    "awards, and navigate the steps to start doing research.",
                    lab_or_program="Portal for Undergraduate Research and Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["finding a mentor", "research positions",
                              "fellowships", "getting started"],
                ),
                program(
                    "stevens_summer_research_programs",
                    "Summer Research Programs (Stevens Institute of Technology)",
                    "https://www.stevens.edu/undergraduate-research/summer-research-programs",
                    "Stevens' Summer Research Programs place undergraduates in "
                    "full-time, faculty-mentored research over the summer, including "
                    "NSF Research Experiences for Undergraduates (REU) sites and "
                    "Stevens-run summer scholars projects across engineering and the "
                    "sciences. Students work on an independent research problem in a "
                    "faculty member's lab, typically with a stipend.",
                    lab_or_program="Summer Research Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "REU", "faculty-mentored research",
                              "research stipend"],
                ),
                program(
                    "stevens_pinnacle_scholars",
                    "Lawrence T. Babbio '66 Pinnacle Scholars Program (Stevens)",
                    "https://www.stevens.edu/pinnacle-scholars",
                    "The Lawrence T. Babbio '66 Pinnacle Scholars Program is a "
                    "merit-based honors program that funds a summer of experiential "
                    "learning — undergraduate research, entrepreneurship, or global "
                    "study — for selected Stevens undergraduates. Pinnacle Scholars "
                    "receive funding and mentorship to pursue a faculty-guided "
                    "research or innovation project early in their studies.",
                    lab_or_program="Pinnacle Scholars Program",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["Pinnacle Scholars", "funded summer research",
                              "honors program", "faculty mentorship"],
                ),
                program(
                    "stevens_clark_scholars",
                    "A. James Clark Scholars Program (Stevens Institute of Technology)",
                    "https://www.stevens.edu/a-james-clark-scholars-program",
                    "The A. James Clark Scholars Program is a selective scholarship "
                    "program for engineering undergraduates that combines financial "
                    "support with hands-on research, business and leadership "
                    "training, community service, and close faculty mentorship. "
                    "Clark Scholars engage in a structured cohort experience and "
                    "faculty-mentored engineering projects throughout their time at "
                    "Stevens.",
                    lab_or_program="A. James Clark Scholars Program",
                    opportunity_type="fellowship",
                    paid="yes",
                    eligibility_majors=["Engineering"],
                    preferred_year=["freshman", "sophomore"],
                    keywords=["Clark Scholars", "engineering scholarship",
                              "leadership", "faculty mentorship"],
                ),
            ],
        },
    ],
}
