"""Washington University in St. Louis campus opportunity-graph config.

Curated seed records of WashU's undergraduate-research landscape, centered on
the Office of Undergraduate Research (OUR, undergradresearch.washu.edu) and
its award programs (AYURA, SURGE, Conference Travel Award), the WRAP peer-
mentoring ambassadors, the Pulitzer Center reporting fellowship, the fall
research symposium, and DBBS's Amgen Scholars summer program on the medical
campus. URLs verified live (HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → washu_research_programs (washu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "washu",
    "organization": "Washington University in St. Louis",
    "location": "St. Louis, MO",
    "emit": {
        "campus": ("washu_research_programs", "washu", "campus"),
    },
    "sources": [
        {
            "source_name": "washu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergradresearch.washu.edu/",
                "https://dbbs.wustl.edu/admissions/summer-undergraduate-research-programs/",
            ],
            "programs": [
                program(
                    "our_hub",
                    "Office of Undergraduate Research (WashU)",
                    "https://undergradresearch.washu.edu/",
                    "WashU's central hub for undergraduate research across all "
                    "disciplines, coordinating funding, mentorship matching, "
                    "and dissemination. OUR runs the internal award programs "
                    "(AYURA, SURGE, Conference Travel Award), the WashU "
                    "Research Ambassador Program, and the undergraduate "
                    "research symposia. Contact: undergradresearch@wustl.edu.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "getting started in research"],
                ),
                program(
                    "ayura",
                    "Academic Year Undergraduate Research Award — AYURA (WashU)",
                    "https://undergradresearch.washu.edu/academic-year-undergraduate-research-award-ayura",
                    "A budget-based award of up to $2,500 supporting project "
                    "expenses for student-initiated, faculty-mentored "
                    "independent research or creative work in the Humanities, "
                    "Social Sciences, and Arts. Originally term-time only, "
                    "AYURA is now also available in summer to help rising "
                    "seniors launch thesis research. Requires a faculty mentor "
                    "and a project budget.",
                    lab_or_program="AYURA",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Up to $2,500 in project expenses",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["humanities", "social sciences", "arts",
                              "research award", "independent research", "thesis"],
                ),
                program(
                    "surge",
                    "SURGE — Summer Undergraduate Research Guided Experience (WashU)",
                    "https://undergradresearch.washu.edu/summer-undergraduate-research-guided-experience",
                    "A summer program providing stipends and flexible "
                    "programming for WashU undergraduates pursuing faculty-"
                    "mentored, project-based inquiry across all academic "
                    "disciplines. Strong candidates develop a research "
                    "proposal, secure a nomination from their faculty research "
                    "mentor, and immerse themselves in the WashU undergraduate "
                    "research community over the summer.",
                    lab_or_program="SURGE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "stipend", "faculty-mentored",
                              "all disciplines", "research proposal"],
                ),
                program(
                    "conference_travel_award",
                    "Conference Travel Award (WashU Office of Undergraduate Research)",
                    "https://undergradresearch.washu.edu/conference-travel-award",
                    "Financial support of up to $500 for WashU undergraduates "
                    "to present faculty-mentored research at professional "
                    "academic conferences. Students must be nominated by a "
                    "WashU faculty mentor; priority goes to students who have "
                    "not previously used the award.",
                    lab_or_program="Conference Travel Award",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Up to $500 in conference travel support",
                    preferred_year=["junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "faculty nomination", "academic conference"],
                ),
                program(
                    "wrap_research_ambassadors",
                    "WashU Research Ambassador Program (WRAP)",
                    "https://undergradresearch.washu.edu/research-ambassadors",
                    "A peer-mentoring program in which trained undergraduate "
                    "Research Ambassadors serve as the student face of the "
                    "Office of Undergraduate Research, increasing awareness of "
                    "and access to undergraduate research across disciplines. "
                    "Ambassadors help build pathways for all students to "
                    "engage in mentored research and staff peer-advising "
                    "sessions.",
                    lab_or_program="WRAP",
                    opportunity_type="internship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["peer mentoring", "research ambassador",
                              "student leadership", "research advising"],
                ),
                program(
                    "pulitzer_center_fellowship",
                    "Pulitzer Center Reporting Fellowship (WashU)",
                    "https://undergradresearch.washu.edu/pulitzer-center-reporting-fellowship",
                    "A competitive fellowship, administered through the Office "
                    "of Undergraduate Research, funding a WashU undergraduate "
                    "to pursue an underreported global issue as a reporting "
                    "project in partnership with the Pulitzer Center. Fellows "
                    "receive funding and mentorship to carry out field "
                    "reporting and share their work with a global audience.",
                    lab_or_program="Pulitzer Center Reporting Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["journalism", "global reporting", "field reporting",
                              "underreported issues", "Pulitzer Center"],
                ),
                program(
                    "fall_ur_symposium",
                    "Fall Undergraduate Research Symposium (WashU)",
                    "https://undergradresearch.washu.edu/fall-2026-undergraduate-research-symposium",
                    "A university-wide symposium (November 6, 2026) where "
                    "WashU undergraduates present posters and talks on "
                    "faculty-mentored research and creative projects to peers, "
                    "faculty, and the broader community. Paired with a spring "
                    "symposium, it is OUR's flagship venue for sharing "
                    "undergraduate scholarship.",
                    lab_or_program="Fall Undergraduate Research Symposium",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research symposium", "poster session",
                              "research presentation", "dissemination"],
                ),
                program(
                    "dbbs_amgen_scholars",
                    "DBBS Amgen Scholars Program — Summer Undergraduate Research (WashU)",
                    "https://dbbs.wustl.edu/admissions/summer-undergraduate-research-programs/",
                    "The Division of Biology & Biomedical Sciences hosts the "
                    "WashU Amgen Scholars Program, a fully funded summer "
                    "research experience in the biomedical and biological "
                    "sciences supported by the Amgen Foundation. Provides a "
                    "stipend, housing, and mentored lab research for "
                    "undergraduates nationwide; the 2026 cohort deadline was "
                    "February 2, 2026. Contact: "
                    "DBBS-SummerResearch@email.wustl.edu.",
                    lab_or_program="DBBS Amgen Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + housing (fully funded summer program)",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="2026 application deadline was February 2, 2026",
                    keywords=["biomedical research", "summer research",
                              "Amgen Scholars", "life sciences", "lab research"],
                ),
            ],
        },
    ],
}
