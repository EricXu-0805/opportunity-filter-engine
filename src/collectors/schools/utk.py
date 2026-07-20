"""University of Tennessee, Knoxville campus opportunity-graph config.

Curated seed records of UTK's undergraduate-research landscape, centered on the
Office of Undergraduate Research & Fellowships (URF, studentsuccess.utk.edu/urf)
— its office hub and its "how to get started in research" and "find
opportunities" guides — plus two flagship URF-administered programs: the
Exploration Grant (undergraduate research funding) and EURēCA, the university's
annual Exhibition of Undergraduate Research and Creative Achievement. Every URL
was curl-verified live (HTTP 200) on 2026-07-20; the EURēCA seed uses its current
canonical path (``/urf/eureca/`` 301-redirects to
``/urf/getting-started/share/eureca/``).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> utk_research_programs (utk / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "utk",
    "organization": "University of Tennessee, Knoxville",
    "location": "Knoxville, TN",
    "emit": {
        "campus": ("utk_research_programs", "utk", "campus"),
    },
    "sources": [
        {
            "source_name": "utk_urf_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://studentsuccess.utk.edu/urf/",
                "https://studentsuccess.utk.edu/urf/undergraduate-research/",
            ],
            "programs": [
                program(
                    "utk_office_of_undergraduate_research_fellowships",
                    "Office of Undergraduate Research & Fellowships (University of Tennessee, Knoxville)",
                    "https://studentsuccess.utk.edu/urf/",
                    "UTK's Office of Undergraduate Research & Fellowships (URF) helps "
                    "students of every major get involved in research, scholarship, "
                    "and creative activity, connecting them with faculty mentors, "
                    "funding, and nationally competitive fellowships. It is the "
                    "campus hub for finding opportunities, learning how to get "
                    "started, and applying for undergraduate research grants and "
                    "fellowships.",
                    lab_or_program="Office of Undergraduate Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "utk_getting_started_undergraduate_research",
                    "Getting Started in Undergraduate Research (UTK Office of Undergraduate Research & Fellowships)",
                    "https://studentsuccess.utk.edu/urf/undergraduate-research/",
                    "URF's guide to beginning undergraduate research at UTK: what "
                    "research is across the disciplines, how to identify faculty "
                    "mentors and labs, and the first steps to joining a research or "
                    "creative project. It walks students through reaching out to "
                    "professors and getting involved regardless of major or class "
                    "year.",
                    lab_or_program="Office of Undergraduate Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "first research experience"],
                ),
                program(
                    "utk_find_research_opportunities",
                    "Find Research Opportunities (UTK Office of Undergraduate Research & Fellowships)",
                    "https://studentsuccess.utk.edu/urf/getting-started/find-opportunities/",
                    "URF's guide to locating undergraduate research positions at "
                    "UTK: browsing posted openings, searching department and lab "
                    "listings, and connecting with faculty across the sciences, "
                    "engineering, humanities, and social sciences. It helps students "
                    "find and pursue open research and creative-scholarship "
                    "positions.",
                    lab_or_program="Office of Undergraduate Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["research positions", "finding opportunities",
                              "research listings", "faculty labs"],
                ),
                program(
                    "utk_exploration_grant",
                    "Exploration Grant Program (University of Tennessee, Knoxville)",
                    "https://studentsuccess.utk.edu/urf/exploration-grant/",
                    "The Exploration Grant provides funding to UTK undergraduates "
                    "beginning a mentored research, scholarship, or creative project. "
                    "Open to students in every major, it supports early-stage "
                    "student-driven projects carried out under faculty mentorship, "
                    "helping students launch their first independent research "
                    "experience.",
                    lab_or_program="Exploration Grant",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["research funding", "undergraduate grant",
                              "faculty-mentored research", "student-driven project"],
                ),
                program(
                    "utk_eureca",
                    "EURēCA: Exhibition of Undergraduate Research and Creative Achievement (University of Tennessee, Knoxville)",
                    "https://studentsuccess.utk.edu/urf/getting-started/share/eureca/",
                    "EURēCA is UTK's annual Exhibition of Undergraduate Research and "
                    "Creative Achievement, where undergraduates from every college "
                    "present their mentored research, scholarship, and creative work "
                    "to the university community. Students showcase projects, compete "
                    "for awards, and share results developed with faculty mentors "
                    "across disciplines.",
                    lab_or_program="EURēCA",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research exhibition", "presenting research",
                              "creative achievement", "faculty-mentored research"],
                ),
            ],
        },
    ],
}
