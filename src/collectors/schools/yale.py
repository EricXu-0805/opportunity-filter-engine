"""Yale University campus opportunity-graph config.

Curated seed records of Yale's undergraduate-research landscape, centered on
Yale College's Science & Quantitative Reasoning office (the STEM fellowships
hub at science.yalecollege.yale.edu), its flagship funded programs (First-Year
Summer Research Fellowship, STARS), the university-wide funding portal
(funding.yale.edu), and SEAS undergraduate research. URLs verified live
(HTTP 200) on 2026-07-17.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → yale_research_programs (yale / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "yale",
    "organization": "Yale University",
    "location": "New Haven, CT",
    "emit": {
        "campus": ("yale_research_programs", "yale", "campus"),
    },
    "sources": [
        {
            "source_name": "yale_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://science.yalecollege.yale.edu/",
                "https://funding.yale.edu/",
                "https://seas.yale.edu/undergraduate-study/undergraduate-research",
            ],
            "programs": [
                program(
                    "science_qr_hub",
                    "Yale College Science & Quantitative Reasoning — STEM Fellowships Hub",
                    "https://science.yalecollege.yale.edu/",
                    "Yale College's Science & Quantitative Reasoning office is the "
                    "central hub for undergraduate STEM research: it walks students "
                    "through getting started in a lab, choosing a faculty mentor, "
                    "writing funding proposals, and the fellowship programs below, "
                    "and runs advising for research across the sciences and "
                    "engineering.",
                    lab_or_program="Science & Quantitative Reasoning",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "STEM fellowships",
                              "research funding"],
                ),
                program(
                    "first_year_summer_research",
                    "Yale College First-Year Summer Research Fellowship in the "
                    "Sciences & Engineering",
                    "https://science.yalecollege.yale.edu/stem-fellowships/"
                    "funding-stem-opportunities-yale/"
                    "yale-college-first-year-summer-research-fellowship",
                    "A funded summer research fellowship that places Yale "
                    "first-years in Yale science and engineering labs for their "
                    "first summer. Fellows work full-time with a faculty mentor "
                    "on campus and receive a summer stipend — one of the earliest "
                    "structured routes into research at Yale.",
                    lab_or_program="First-Year Summer Research Fellowship",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    keywords=["summer research", "first-year", "STEM"],
                ),
                program(
                    "stars",
                    "Yale STARS — Science, Technology and Research Scholars",
                    "https://science.yalecollege.yale.edu/stem-fellowships/"
                    "funding-stem-opportunities-yale/stars",
                    "STARS supports Yale undergraduates from backgrounds "
                    "historically underrepresented in the sciences with mentored "
                    "research placements, academic-year programming, and a funded "
                    "summer research track (STARS Summer Research Program), "
                    "building a cohort from the first year through the senior "
                    "thesis.",
                    lab_or_program="STARS",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["STARS", "mentored research", "diversity in STEM"],
                ),
                program(
                    "yale_funding_portal",
                    "Yale Student Grants & Fellowships (funding.yale.edu)",
                    "https://funding.yale.edu/",
                    "Yale's university-wide funding database for student grants "
                    "and fellowships — searchable listings of summer research "
                    "funding, international experience awards, and academic-year "
                    "fellowships administered across Yale College and the "
                    "graduate schools, with deadlines and application routes in "
                    "one portal.",
                    lab_or_program="Student Grants & Fellowships",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["fellowships", "research funding", "grants"],
                ),
                program(
                    "seas_undergrad_research",
                    "Yale SEAS Undergraduate Research",
                    "https://seas.yale.edu/undergraduate-study/undergraduate-research",
                    "Yale Engineering & Applied Science's route into faculty labs "
                    "for undergraduates: term-time independent research for "
                    "credit and funded summer research placements across the SEAS "
                    "departments, with guidance on approaching faculty and "
                    "matching to a lab.",
                    department="School of Engineering & Applied Science",
                    lab_or_program="SEAS Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Computer Science", "Electrical Engineering",
                                        "Mechanical Engineering", "Biomedical Engineering",
                                        "Chemical Engineering", "Applied Physics"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["engineering research", "summer research", "lab placement"],
                ),
            ],
        },
    ],
}
