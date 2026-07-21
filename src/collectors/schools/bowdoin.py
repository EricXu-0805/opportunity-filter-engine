"""Bowdoin College campus opportunity-graph config.

Curated seed records of Bowdoin's undergraduate-research landscape, centered on
the Office of Student Fellowships and Research (which awards ~70 summer research
fellowships a year), the college's named academic-year and summer research
grants, and its two flagship field-science stations — the Schiller Coastal
Studies Center and the Bowdoin Scientific Station on Kent Island. Bowdoin is a
liberal arts college: research is undergraduate-only and faculty-mentored, so
these programs are the funded routes into a professor's lab. URLs verified live
(HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → bowdoin_research_programs (bowdoin / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_YEARS = ["freshman", "sophomore", "junior", "senior"]

SCHOOL: dict = {
    "school_slug": "bowdoin",
    "organization": "Bowdoin College",
    "location": "Brunswick, ME",
    "emit": {
        "campus": ("bowdoin_research_programs", "bowdoin", "campus"),
    },
    "sources": [
        {
            "source_name": "bowdoin_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.bowdoin.edu/student-fellowships/",
                "https://www.bowdoin.edu/coastal-studies-center/",
                "https://www.bowdoin.edu/kent-island/",
            ],
            "programs": [
                program(
                    "student_fellowships_hub",
                    "Bowdoin Office of Student Fellowships and Research",
                    "https://www.bowdoin.edu/student-fellowships/",
                    "The central hub for undergraduate research at Bowdoin. Each "
                    "spring the office awards research fellowships to around 70 "
                    "current students, enabling them to engage in independent, "
                    "faculty-mentored research across the sciences, social "
                    "sciences, and humanities, and advises students on finding a "
                    "mentor, writing proposals, and the funded programs below.",
                    lab_or_program="Student Fellowships and Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["undergraduate research", "faculty-mentored research",
                              "research fellowships"],
                ),
                program(
                    "summer_research_fellowships",
                    "Bowdoin Summer Research Fellowships",
                    "https://www.bowdoin.edu/student-fellowships/summer-opportunities/"
                    "research-fellowships/index.html",
                    "Funded full-time summer research fellowships that place "
                    "Bowdoin undergraduates in a faculty member's lab or research "
                    "project for eight to ten weeks. Students receive a stipend "
                    "and, where relevant, campus housing to pursue independent, "
                    "mentored research over the summer.",
                    lab_or_program="Summer Research Fellowships",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["summer research", "faculty-mentored research",
                              "research stipend"],
                ),
                program(
                    "fall_research_award",
                    "Bowdoin Fall Research Award",
                    "https://www.bowdoin.edu/student-fellowships/"
                    "academic-year-research-project/fall-research-award/index.html",
                    "An academic-year grant that funds a student's independent, "
                    "faculty-mentored research project during the fall semester — "
                    "the term-time counterpart to the summer fellowships, "
                    "supporting continued work on a research question with a "
                    "Bowdoin professor.",
                    lab_or_program="Fall Research Award",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["academic-year research", "faculty-mentored research",
                              "research grant"],
                ),
                program(
                    "mini_grants_research",
                    "Bowdoin Monthly Mini-Grants for Research",
                    "https://www.bowdoin.edu/student-fellowships/"
                    "academic-year-research-project/mini-grants-summer-no-app/index.html",
                    "Small rolling research grants that cover the costs of an "
                    "ongoing independent or faculty-mentored research project "
                    "during the academic year — materials, travel to archives or "
                    "field sites, and conference expenses for undergraduate "
                    "researchers.",
                    lab_or_program="Monthly Mini-Grants for Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["research grant", "conference travel",
                              "undergraduate research"],
                ),
                program(
                    "faculty_scholars",
                    "Bowdoin Faculty Scholars",
                    "https://www.bowdoin.edu/student-fellowships/faculty-scholars/"
                    "index.html",
                    "A merit award for incoming students that grants $3,000 to be "
                    "used at any time during their Bowdoin career for non-credit "
                    "enrichment — including independent study and faculty-mentored "
                    "research, career-related internships, and other scholarly "
                    "projects developed with a faculty mentor.",
                    lab_or_program="Faculty Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["merit fellowship", "independent study",
                              "enrichment award"],
                ),
                program(
                    "schiller_coastal_studies",
                    "Schiller Coastal Studies Center — Marine & Coastal Research",
                    "https://www.bowdoin.edu/coastal-studies-center/",
                    "Bowdoin's marine field station on Orr's Island: 118 acres "
                    "with 2.5 miles of rocky Gulf of Maine shoreline, a marine "
                    "lab, running-seawater facilities, and research vessels. It "
                    "hosts funded summer fellowships and term-time projects in "
                    "marine biology, ecology, oceanography, and coastal "
                    "environmental science with Bowdoin faculty.",
                    lab_or_program="Schiller Coastal Studies Center",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Biology", "Earth and Oceanographic Science",
                                        "Environmental Studies"],
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["marine biology", "coastal studies", "field research"],
                ),
                program(
                    "kent_island_station",
                    "Bowdoin Scientific Station on Kent Island",
                    "https://www.bowdoin.edu/kent-island/",
                    "A remote field research station on an island in the Bay of "
                    "Fundy, New Brunswick. Each summer students are awarded "
                    "fellowships to conduct scientific field research — seabird "
                    "ecology, ornithology, plant and climate science — living and "
                    "working at the station, with a parallel artist-in-residence "
                    "track for creative field work.",
                    lab_or_program="Bowdoin Scientific Station (Kent Island)",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Biology", "Environmental Studies",
                                        "Earth and Oceanographic Science"],
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["field research", "ecology", "ornithology"],
                ),
                program(
                    "mellon_mays",
                    "Mellon Mays Undergraduate Fellowship (MMUF)",
                    "https://www.bowdoin.edu/mellon-mays/index.html",
                    "A multi-year research fellowship that prepares students from "
                    "backgrounds underrepresented in the academy for PhD study in "
                    "the humanities and humanistic social sciences. Fellows work "
                    "closely with faculty mentors on a sustained research agenda, "
                    "with summer research funding and cohort programming.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["humanities research", "PhD preparation",
                              "mentored research"],
                ),
                program(
                    "national_fellowships",
                    "Bowdoin National Fellowships Advising",
                    "https://www.bowdoin.edu/student-fellowships/national-fellowships/"
                    "index.html",
                    "Advising and campus endorsement for nationally competitive "
                    "research and study fellowships (Fulbright, Goldwater, "
                    "Watson, and similar), guiding Bowdoin students through "
                    "proposal writing and applications for external research and "
                    "graduate-study funding.",
                    lab_or_program="National Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["national fellowships", "research funding",
                              "graduate study"],
                ),
                program(
                    "academic_year_research",
                    "Bowdoin Academic-Year Research Projects",
                    "https://www.bowdoin.edu/student-fellowships/"
                    "academic-year-research-project/index.html",
                    "The umbrella for term-time independent research at Bowdoin: "
                    "funding and support for students carrying out faculty-mentored "
                    "research projects during the academic year, whether continuing "
                    "summer work or launching a new question toward an honors "
                    "thesis.",
                    lab_or_program="Academic-Year Research",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["academic-year research", "honors thesis",
                              "faculty-mentored research"],
                ),
            ],
        },
    ],
}
