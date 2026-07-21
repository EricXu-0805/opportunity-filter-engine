"""Syracuse University campus opportunity-graph config.

Curated seed records of Syracuse's undergraduate-research landscape, centered on
The SOURCE — the Syracuse Office of Undergraduate Research and Creative
Engagement (undergraduateresearch.syracuse.edu), the campus-wide hub that funds
and supports faculty-guided undergraduate research and creative inquiry across
every school and college — plus the College of Arts & Sciences undergraduate-
research hub. The five curated programs are The SOURCE office itself, its
getting-started guide for students, its grants-and-fellowships portfolio (the
SOURCE Bridge Award, the SOURCE Fellowship, and the CFSA–SOURCE Emerging Research
Fellows Program), its research-opportunities database, and its research symposia
(Fall Expo / Spring Showcase / Summer Symposium). Every URL was curl-verified
live (HTTP 200) on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → syracuse_research_programs (syracuse / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "syracuse",
    "organization": "Syracuse University",
    "location": "Syracuse, NY",
    "emit": {
        "campus": ("syracuse_research_programs", "syracuse", "campus"),
    },
    "sources": [
        {
            "source_name": "syracuse_source_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergraduateresearch.syracuse.edu/",
                "https://artsandsciences.syracuse.edu/research/undergraduate-research/",
            ],
            "programs": [
                program(
                    "syracuse_source_office",
                    "The SOURCE: Syracuse Office of Undergraduate Research and Creative Engagement",
                    "https://undergraduateresearch.syracuse.edu/",
                    "The SOURCE (Syracuse Office of Undergraduate Research and "
                    "Creative Engagement) fosters and supports diverse "
                    "undergraduate participation in faculty-guided scholarly "
                    "research and creative inquiry across every school and college "
                    "at Syracuse University. Based in Bird Library, it is the "
                    "campus hub for finding a faculty mentor, applying for research "
                    "funding, and getting started in research or creative work in "
                    "any discipline.",
                    lab_or_program="The SOURCE",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "creative inquiry", "any major"],
                ),
                program(
                    "syracuse_source_get_started",
                    "Getting Started in Research (The SOURCE, Syracuse University)",
                    "https://undergraduateresearch.syracuse.edu/for-students/",
                    "The SOURCE's guide for Syracuse students on how to begin "
                    "undergraduate research: identifying research interests, "
                    "finding and contacting faculty mentors, joining a lab or "
                    "creative project, and taking the first steps toward funded, "
                    "independent scholarly work. Aimed at students new to research "
                    "in any school or college.",
                    lab_or_program="The SOURCE",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "getting started",
                              "contacting faculty", "first research experience"],
                ),
                program(
                    "syracuse_source_grants_fellowships",
                    "SOURCE Grants and Fellowships (Syracuse University)",
                    "https://undergraduateresearch.syracuse.edu/for-faculty/source-awards/",
                    "The SOURCE's portfolio of undergraduate research funding: the "
                    "SOURCE Bridge Award (short-term, renewable support up to "
                    "$2,000 for mentored research, offered for fall, spring, and "
                    "summer), the SOURCE Fellowship (a larger competitive award for "
                    "advanced student-led or student-designed original research and "
                    "creative work over the summer and/or academic year), and the "
                    "CFSA–SOURCE Emerging Research Fellows Program for first-year "
                    "students. Funds faculty-mentored research and creative projects "
                    "across all disciplines.",
                    lab_or_program="The SOURCE",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research funding", "SOURCE Bridge Award",
                              "SOURCE Fellowship", "summer research"],
                ),
                program(
                    "syracuse_source_opportunities",
                    "SOURCE Research Opportunities Database (Syracuse University)",
                    "https://undergraduateresearch.syracuse.edu/source-opportunites/",
                    "The SOURCE's listing of current undergraduate research and "
                    "creative-engagement opportunities at Syracuse University — "
                    "open faculty projects, lab positions, and program openings "
                    "students can browse and apply to across the sciences, "
                    "engineering, humanities, social sciences, and the arts.",
                    lab_or_program="The SOURCE",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research positions", "open opportunities",
                              "faculty projects", "research listings"],
                ),
                program(
                    "syracuse_source_symposia",
                    "SOURCE Research Symposia: Fall Expo & Spring Showcase (Syracuse University)",
                    "https://undergraduateresearch.syracuse.edu/for-students/research-symposium/",
                    "The SOURCE's undergraduate research symposia — the Fall "
                    "Research Expo, the Spring Research Showcase, and the Summer "
                    "Symposium — where Syracuse undergraduates present posters and "
                    "talks on their faculty-mentored research and creative work. A "
                    "venue for students to share results, get feedback, and connect "
                    "with mentors and peers across disciplines.",
                    lab_or_program="The SOURCE",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research symposium", "poster presentation",
                              "research showcase", "presenting research"],
                ),
            ],
        },
    ],
}
