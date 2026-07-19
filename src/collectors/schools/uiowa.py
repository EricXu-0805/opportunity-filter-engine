"""University of Iowa campus opportunity-graph config.

Curated seed records of Iowa's undergraduate-research landscape, centered on the
Office of Undergraduate Research (our.research.uiowa.edu) — formerly the Iowa
Center for Research by Undergraduates (ICRU); the ``icru.research.uiowa.edu``
host now 301-redirects here. Seeds cover the office hub, its ICRU Fellowships
(stipended, any-discipline mentored research), the campus-wide Summer Research
Programs index (SROP, Microbiology REU, Computing for Health & Well-Being REU,
CROI, Edge of Space, …), and the Office of the Vice President for Research's
undergraduate-research page. URLs curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uiowa_research_programs (uiowa / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "uiowa",
    "organization": "University of Iowa",
    "location": "Iowa City, IA",
    "emit": {
        "campus": ("uiowa_research_programs", "uiowa", "campus"),
    },
    "sources": [
        {
            "source_name": "uiowa_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://our.research.uiowa.edu/",
                "https://research.uiowa.edu/undergraduate-research",
            ],
            "programs": [
                program(
                    "uiowa_office_of_undergraduate_research",
                    "Office of Undergraduate Research (University of Iowa)",
                    "https://our.research.uiowa.edu/",
                    "The University of Iowa's Office of Undergraduate Research "
                    "(formerly the Iowa Center for Research by Undergraduates, "
                    "ICRU) is the campus hub connecting undergraduates of every "
                    "major with faculty and staff research mentors, fellowships, "
                    "and summer programs. It helps students find opportunities, "
                    "learn how to get started in a lab or creative project, and "
                    "apply for funding to support mentored research.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "any major", "getting started"],
                ),
                program(
                    "uiowa_icru_fellowships",
                    "ICRU Fellowships (University of Iowa)",
                    "https://our.research.uiowa.edu/our-fellowships/icru-fellowships",
                    "ICRU Fellowships fund current University of Iowa "
                    "undergraduates in any discipline to work with a faculty or "
                    "professional-and-scientific staff mentor on a specific "
                    "research or creative project. The academic-year fellowship "
                    "pays a stipend for 8-10 hours per week; the summer fellowship "
                    "pays a stipend for 18-20 hours per week over ten weeks. The "
                    "program has awarded over $5.8 million directly to students "
                    "since 2010.",
                    lab_or_program="ICRU Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$2,500 academic-year / $3,000 summer stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research fellowship", "stipend",
                              "mentored research", "any discipline"],
                ),
                program(
                    "uiowa_summer_research_programs",
                    "Summer Research Programs at Iowa (University of Iowa)",
                    "https://our.research.uiowa.edu/summer-research-programs-iowa",
                    "The University of Iowa's index of summer undergraduate "
                    "research programs, including the Summer Research Opportunities "
                    "Program (SROP) for underrepresented students, NSF-funded REU "
                    "sites (Microbiology; Computing for Health and Well-Being), "
                    "Cancer Research Opportunities at Iowa (CROI), the Iowa Summer "
                    "Institute in Biostatistics (ISIB), and the Edge of Space "
                    "space-instrumentation program. Most are paid, full-time, "
                    "8-10 week placements open to students nationwide.",
                    lab_or_program="Summer Research Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["SROP", "REU", "summer research",
                              "cancer research", "biostatistics"],
                ),
                program(
                    "uiowa_undergraduate_research_ovpr",
                    "Undergraduate Research (UI Office of the Vice President for Research)",
                    "https://research.uiowa.edu/undergraduate-research",
                    "The Office of the Vice President for Research's undergraduate "
                    "research page points University of Iowa students to ways of "
                    "getting involved in mentored research across the sciences, "
                    "humanities, arts, and professional programs — connecting them "
                    "to the Office of Undergraduate Research, funding, and faculty "
                    "mentors, and describing how undergraduate research fits into "
                    "the university's broader research enterprise.",
                    lab_or_program="Office of the Vice President for Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research mentors",
                              "get involved", "any major"],
                ),
            ],
        },
    ],
}
