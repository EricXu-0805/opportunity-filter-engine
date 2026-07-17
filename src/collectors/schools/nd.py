"""University of Notre Dame campus opportunity-graph config.

Curated seed records of Notre Dame's undergraduate-research landscape,
centered on CUSE (the Flatley Center for Undergraduate Scholarly Engagement,
the central UR office in the Provost's Office) and its FUSE cohort, plus the
Kellogg Institute's two undergraduate research tracks, the Glynn Family
Honors Program, ND Energy's Slatt fellowships, and the Physics REU. URLs
verified live (HTTP 200) on 2026-07-17. Note CUSE has suspended its own
internal funding program — its funding page now guides students to other
campus sources, which is what the funding record describes.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → nd_research_programs (nd / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "nd",
    "organization": "University of Notre Dame",
    "location": "Notre Dame, IN",
    "emit": {
        "campus": ("nd_research_programs", "nd", "campus"),
    },
    "sources": [
        {
            "source_name": "nd_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://cuse.nd.edu/",
                "https://kellogg.nd.edu/opportunities/undergraduate-students/",
                "https://energy.nd.edu/opportunities/student-research-fellowships/",
            ],
            "programs": [
                program(
                    "cuse_hub",
                    "CUSE — Flatley Center for Undergraduate Scholarly Engagement (Notre Dame)",
                    "https://cuse.nd.edu/",
                    "CUSE is Notre Dame's central undergraduate research office, "
                    "housed in the Office of the Provost. It supports research, "
                    "scholarship, and creative endeavors across all colleges, "
                    "runs a searchable faculty-research-interest tool, and "
                    "advises students one-on-one on finding mentors and funding. "
                    "It also coordinates national fellowship advising and "
                    "maintains a campus-wide map of scholars, honors, and "
                    "fellows programs.",
                    lab_or_program="CUSE",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "advising", "fellowships"],
                ),
                program(
                    "fuse_program",
                    "FUSE Program — Fellows for Undergraduate Scholarly Engagement (Notre Dame)",
                    "https://cuse.nd.edu/fuse-program/",
                    "FUSE, formerly the Sorin Scholars program, admits 10-12 "
                    "high-potential first-year students from all colleges "
                    "through a competitive spring application. Fellows are "
                    "selected for scholarly engagement such as research, "
                    "creative endeavors, and leadership, and receive "
                    "specialized advising, unique programming, and priority "
                    "funding consideration from CUSE.",
                    lab_or_program="FUSE",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["cohort program", "research fellows",
                              "priority funding", "interdisciplinary"],
                ),
                program(
                    "cuse_funding",
                    "CUSE Undergraduate Research Funding Guidance (Notre Dame)",
                    "https://cuse.nd.edu/undergraduate-research/funding-research/",
                    "CUSE helps undergraduates fund research projects and "
                    "conference presentations: searching for funding sources "
                    "across campus, writing grant applications, and navigating "
                    "IRB approval. CUSE has suspended its own internal funding "
                    "program but actively assists students in finding other "
                    "funding across campus.",
                    lab_or_program="CUSE",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research grants", "travel funding", "IRB",
                              "grant writing"],
                ),
                program(
                    "physics_reu",
                    "Notre Dame Physics & Astronomy REU Program",
                    "https://physics.nd.edu/research/reu-program/",
                    "Notre Dame's Research Experiences for Undergraduates "
                    "program in physics has run for over 35 years and gives "
                    "undergraduate physics majors hands-on summer research with "
                    "faculty and graduate students across many areas of "
                    "physics. Enrichment includes weekly seminars, a "
                    "programming course, GRE prep, ethics workshops, a "
                    "grad-school application workshop, field trips to nearby "
                    "national laboratories, and a closing REU Symposium.",
                    lab_or_program="Physics REU",
                    department="Department of Physics and Astronomy",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Physics", "Astronomy"],
                    preferred_year=["sophomore", "junior"],
                    keywords=["REU", "summer research", "physics", "astronomy", "NSF"],
                ),
                program(
                    "glynn_honors",
                    "Glynn Family Honors Program (Notre Dame)",
                    "https://glynnhonors.nd.edu/",
                    "The Glynn Family Honors Program is Notre Dame's liberal "
                    "arts and sciences honors community built around small "
                    "seminars and faculty-guided inquiry, open to Arts & "
                    "Letters and Science students and culminating in a senior "
                    "thesis. It provides research funding for members — the "
                    "program spotlights students such as a history major who "
                    "traveled to Boston archives to research her senior thesis.",
                    lab_or_program="Glynn Family Honors Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors program", "senior thesis",
                              "research funding", "liberal arts", "science"],
                ),
                program(
                    "kellogg_international_scholars",
                    "Kellogg International Scholars Program (Notre Dame)",
                    "https://kellogg.nd.edu/opportunities/undergraduate-students/research-programs/kellogg-international-scholars-program",
                    "The Kellogg Institute's International Scholars Program "
                    "pairs selected students one-on-one with a Kellogg faculty "
                    "fellow as a research assistant starting after their first "
                    "year, building toward their own senior-year research "
                    "project. Scholars can apply for summer grants and "
                    "fellowships of up to $6,000, including Experiencing the "
                    "World Fellowships for sophomores and Kellogg/Kroc "
                    "Undergraduate Research grants for juniors, and write a "
                    "senior thesis.",
                    lab_or_program="Kellogg International Scholars Program",
                    opportunity_type="research",
                    compensation="Summer grants and fellowships up to $6,000",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["international studies", "research assistant",
                              "faculty mentorship", "summer grants",
                              "global democracy"],
                ),
                program(
                    "kellogg_developing_researchers",
                    "Kellogg Developing Researchers Program (Notre Dame)",
                    "https://kellogg.nd.edu/opportunities/undergraduate-students/kellogg-developing-researchers",
                    "The Kellogg Developing Researchers Program trains "
                    "undergraduates through research-skills workshops (minimum "
                    "3 per semester) and places them in a paid "
                    "research-assistant pool matched with Kellogg Faculty "
                    "Fellows for short-term projects. Eligibility spans "
                    "second-semester first-years through seniors.",
                    lab_or_program="Kellogg Developing Researchers Program",
                    opportunity_type="research",
                    paid="yes",
                    deadline_note=("Fall application due September 10, 2026; "
                                   "spring deadline December 7, open to first-years."),
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["paid research assistant", "skills workshops",
                              "social science", "international studies"],
                ),
                program(
                    "energy_slatt_fellowship",
                    "ND Energy Student Research Fellowships — Vincent P. Slatt Fellowship (Notre Dame)",
                    "https://energy.nd.edu/opportunities/student-research-fellowships/",
                    "ND Energy provides paid research fellowships for students "
                    "to conduct energy-related research with faculty "
                    "affiliates, including the Vincent P. Slatt Fellowship for "
                    "Undergraduate Research in Energy Systems and Processes. "
                    "Fellows gain new skills and join a community of energy "
                    "researchers, with a Summer Undergraduate Research "
                    "Symposium held on campus.",
                    lab_or_program="ND Energy",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["energy research", "paid fellowship",
                              "sustainability", "engineering"],
                ),
            ],
        },
    ],
}
