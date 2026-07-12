"""Brown University campus opportunity-graph config.

Curated seed records of Brown's undergraduate-research landscape: the UTRA
(Undergraduate Teaching and Research Awards) program, the BrownConnect+ hub
that matches students to research and funded experiences, the College's
national & international fellowships office, and the Division of Research.
URLs verified live (HTTP 200) on 2026-07-12.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → brown_research_programs (brown / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "brown",
    "organization": "Brown University",
    "location": "Providence, RI",
    "emit": {
        "campus": ("brown_research_programs", "brown", "campus"),
    },
    "sources": [
        {
            "source_name": "brown_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://college.brown.edu/",
                "https://brownconnect.brown.edu/",
                "https://www.brown.edu/academics/college/fellowships/",
                "https://www.brown.edu/research/",
            ],
            "programs": [
                program(
                    "utra",
                    "UTRA — Undergraduate Teaching & Research Awards (Brown)",
                    "https://college.brown.edu/",
                    "Brown's flagship undergraduate-research funding: the Karen T. Romer "
                    "Undergraduate Teaching and Research Awards (UTRAs) fund students to "
                    "collaborate with a faculty mentor on research or course development "
                    "over the summer or academic year, with a stipend. Open to Brown "
                    "undergraduates in every concentration; applications run through the "
                    "College with a faculty sponsor.",
                    lab_or_program="Undergraduate Teaching & Research Awards (UTRA)",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "faculty mentorship"],
                ),
                program(
                    "brownconnect",
                    "BrownConnect+ — Research & Experience Hub (Brown)",
                    "https://brownconnect.brown.edu/",
                    "BrownConnect+ is Brown's central platform matching undergraduates to "
                    "research assistantships, funded summer experiences (LINK Awards), "
                    "internships, and alumni mentors. Search opportunities by field and "
                    "class year, and apply for I-Prov and LINK funding to support unpaid "
                    "research or internship placements.",
                    lab_or_program="BrownConnect+",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research assistantship", "summer funding", "mentorship"],
                ),
                program(
                    "college_fellowships",
                    "National & International Fellowships — The College (Brown)",
                    "https://www.brown.edu/academics/college/fellowships/",
                    "The College's fellowships office advises Brown undergraduates on "
                    "research and scholarship fellowships — including the Royce Fellowship "
                    "for independent research projects — and national awards (Goldwater, "
                    "Fulbright, and more). Start here to fund an independent research "
                    "project or a research-based fellowship.",
                    lab_or_program="Brown Fellowships Office",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research fellowship", "Royce Fellowship"],
                ),
                program(
                    "division_of_research",
                    "Division of Research (OVPR) — Centers & Institutes (Brown)",
                    "https://www.brown.edu/research/",
                    "Brown's Division of Research (Office of the Vice President for "
                    "Research) is the gateway to the university's research centers and "
                    "institutes. Browse centers by theme to find a research group whose "
                    "work matches your interests, then contact the group about "
                    "undergraduate research openings.",
                    lab_or_program="Division of Research",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research centers", "institutes"],
                ),
            ],
        },
    ],
}
