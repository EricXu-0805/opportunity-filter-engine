"""Clemson University campus opportunity-graph config.

Curated seed records of Clemson's undergraduate-research landscape, centered on
Creative Inquiry + Undergraduate Research (CI+UR, the Watt Family Innovation
Center program that is Clemson's flagship undergraduate-research vehicle) plus
its Summer CI+UR immersion award, the university's Student Research hub, and the
Scholar Programs office. Every URL was curl-verified live (final HTTP 200,
redirects followed) on 2026-07-20; the campus hub's legacy
``/academics/programs/creative-inquiry/`` path 301-redirects to the canonical
``/centers-institutes/watt/creative-inquiry/`` used here.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → clemson_research_programs (clemson / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "clemson",
    "organization": "Clemson University",
    "location": "Clemson, SC",
    "emit": {
        "campus": ("clemson_research_programs", "clemson", "campus"),
    },
    "sources": [
        {
            "source_name": "clemson_ciur_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.clemson.edu/centers-institutes/watt/creative-inquiry/",
                "https://www.clemson.edu/research/student-research.html",
            ],
            "programs": [
                program(
                    "clemson_creative_inquiry",
                    "Creative Inquiry + Undergraduate Research (Clemson University)",
                    "https://www.clemson.edu/centers-institutes/watt/creative-inquiry/",
                    "Creative Inquiry (CI) is Clemson's signature combination of "
                    "undergraduate research, experiential learning, and "
                    "cross-disciplinary teamwork. Each year roughly 4,500 "
                    "undergraduates across every discipline join about 400 "
                    "team-based, multi-semester research projects mentored by "
                    "faculty. Students propose questions, design investigations, "
                    "and present their findings — the central way to get involved "
                    "in research at Clemson.",
                    lab_or_program="Creative Inquiry + Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["creative inquiry", "undergraduate research",
                              "team-based research", "faculty mentorship",
                              "any major"],
                ),
                program(
                    "clemson_summer_ci_ur",
                    "Summer CI + UR: Summer Undergraduate Research Award (Clemson University)",
                    "https://www.clemson.edu/centers-institutes/watt/creative-inquiry/apply-to-ci/summer-ci-ur/",
                    "Summer CI + UR lets Creative Inquiry students immerse "
                    "full-time in research for 10 weeks over the summer under a "
                    "faculty mentor. Students are nominated by a CI mentor and "
                    "then apply; recipients receive a summer research award to "
                    "support the work. It is Clemson's flagship summer "
                    "undergraduate-research funding opportunity.",
                    lab_or_program="Summer CI + UR",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["summer research", "10-week program",
                              "faculty-mentored research", "research award"],
                ),
                program(
                    "clemson_student_research",
                    "Student Research at Clemson (Clemson University Division of Research)",
                    "https://www.clemson.edu/research/student-research.html",
                    "Clemson's Student Research hub showcases how undergraduates "
                    "get into research — often as early as their first year — "
                    "working alongside faculty and industry partners in labs, "
                    "fields, and hospitals across South Carolina. It is the "
                    "Division of Research's starting point for finding research "
                    "experiences, mentors, and hands-on projects with real-world "
                    "impact.",
                    lab_or_program="Division of Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["student research", "getting started",
                              "industry partners", "faculty mentorship"],
                ),
                program(
                    "clemson_scholar_programs",
                    "Scholar Programs (Clemson University)",
                    "https://www.clemson.edu/academics/student-academic-opportunities/scholar-programs.html",
                    "Clemson's Scholar Programs support high-achieving "
                    "undergraduates pursuing research, creative work, and "
                    "national fellowships through mentored, purpose-driven "
                    "academic opportunities. The office connects scholars with "
                    "faculty mentors and enrichment programs that deepen "
                    "independent inquiry beyond the classroom.",
                    lab_or_program="Scholar Programs",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["scholar programs", "national fellowships",
                              "mentored research", "academic enrichment"],
                ),
            ],
        },
    ],
}
