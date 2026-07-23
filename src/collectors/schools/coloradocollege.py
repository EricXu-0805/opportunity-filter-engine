"""Colorado College campus opportunity-graph config.

Curated seed records of Colorado College's undergraduate-research and
fellowship landscape, centered on the college's flagship Summer SCoRe
(Student Collaborative Research) program and its named grants and
fellowships: the Keller Family Venture Grants, the Office of Scholarships &
Grants nationally competitive fellowships hub, the Public Interest Fellowship
Program, the State of the Rockies Project (environmental student research),
and the Career Center's student-research hub. URLs curl-verified live
(HTTP 200) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → coloradocollege_research_programs (coloradocollege / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_BASE = "https://www.coloradocollege.edu"

SCHOOL: dict = {
    "school_slug": "coloradocollege",
    "organization": "Colorado College",
    "location": "Colorado Springs, CO",
    "emit": {
        "campus": ("coloradocollege_research_programs", "coloradocollege", "campus"),
    },
    "sources": [
        {
            "source_name": "coloradocollege_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_BASE}/other/research/index.html",
                f"{_BASE}/offices/careercenter/research-opportunities/",
            ],
            "programs": [
                program(
                    "coloradocollege_score",
                    "Summer SCoRe — Student Collaborative Research (Colorado College)",
                    f"{_BASE}/offices/careercenter/research-opportunities/"
                    "summer-research-programming/index.html",
                    "Colorado College's flagship summer research program: "
                    "students spend the summer on full-time, faculty-mentored "
                    "collaborative research across the sciences, social "
                    "sciences, humanities and arts, with a stipend, summer "
                    "housing, professional-development workshops, and a "
                    "concluding Summer Research Symposium.",
                    lab_or_program="Summer SCoRe",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "collaborative research"],
                ),
                program(
                    "coloradocollege_venture_grants",
                    "Keller Family Venture Grants (Colorado College)",
                    f"{_BASE}/other/venturegrants/",
                    "The Keller Family Venture Grant Fund supports "
                    "co-curricular, experiential research: students design and "
                    "carry out innovative independent projects of high merit — "
                    "fieldwork, creative work, or scholarly investigation — that "
                    "benefit both the applicant and the wider Colorado College "
                    "community.",
                    lab_or_program="Keller Family Venture Grants",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "independent research",
                              "experiential learning", "any discipline"],
                ),
                program(
                    "coloradocollege_public_interest",
                    "Public Interest Fellowship Program (Colorado College)",
                    f"{_BASE}/offices/publicinterest/index.html",
                    "The Public Interest Fellowship Program (PIFP) places "
                    "students in funded summer fellowships with nonprofit and "
                    "public-sector organizations working for change across "
                    "Colorado, pairing hands-on community work with research, "
                    "reflection, and professional mentorship.",
                    lab_or_program="Public Interest Fellowship Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["public interest", "summer fellowship",
                              "community engagement", "nonprofit"],
                ),
                program(
                    "coloradocollege_state_of_rockies",
                    "State of the Rockies Project (Colorado College)",
                    f"{_BASE}/other/stateoftherockies/",
                    "A signature interdisciplinary research project on the "
                    "Rocky Mountain West: student and faculty fellows conduct "
                    "field-based investigation and reporting on critical "
                    "environmental and socio-economic issues facing the region, "
                    "producing public-facing research on sustainability and "
                    "community change.",
                    lab_or_program="State of the Rockies Project",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["environmental research", "field research",
                              "sustainability", "Rocky Mountain West"],
                ),
                program(
                    "coloradocollege_fellowships",
                    "Nationally Competitive Fellowships (Colorado College)",
                    f"{_BASE}/offices/scholarships-and-grants/",
                    "The Office of Scholarships & Grants advises Colorado "
                    "College students on nationally competitive fellowships, "
                    "scholarships, and research awards (Fulbright, Goldwater, "
                    "NSF graduate research fellowships, and more), guiding "
                    "applicants through selection and the application process.",
                    lab_or_program="Nationally Competitive Fellowships",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["national fellowships", "scholarships",
                              "graduate research", "Fulbright"],
                ),
                program(
                    "coloradocollege_research_hub",
                    "Student Research Opportunities (Colorado College Career Center)",
                    f"{_BASE}/offices/careercenter/research-opportunities/",
                    "The Career Center's student-research hub connects Colorado "
                    "College undergraduates to research experiences throughout "
                    "the academic year and summer — long-term faculty-mentored "
                    "projects and short experiential engagements alike — across "
                    "every academic division.",
                    lab_or_program="Student Research Opportunities",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "faculty mentor",
                              "research placements", "any discipline"],
                ),
                program(
                    "coloradocollege_research_at_cc",
                    "Research at CC (Colorado College)",
                    f"{_BASE}/other/research/index.html",
                    "Colorado College's central research portal: an overview of "
                    "student-faculty collaborative research across disciplines, "
                    "linking to departmental research, grants, human-subjects "
                    "review, and the college's undergraduate-research programs.",
                    lab_or_program="Research at CC",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "student-faculty research",
                              "interdisciplinary", "any discipline"],
                ),
            ],
        },
    ],
}
