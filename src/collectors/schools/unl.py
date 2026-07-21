"""University of Nebraska-Lincoln campus opportunity-graph config.

Curated seed records of UNL's undergraduate-research landscape, centered on the
Office of Undergraduate Research & Fellowships (URAF, uraf.unl.edu) and its
flagship UCARE program, plus the First Year Research Experience (FYRE), the
Nebraska Summer Research Program (the NSF-funded REU umbrella,
summerprogram.unl.edu), and URAF's Research Fellowships advising track. Every URL
was curl-verified live (HTTP 200) on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → unl_research_programs (unl / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "unl",
    "organization": "University of Nebraska-Lincoln",
    "location": "Lincoln, NE",
    "emit": {
        "campus": ("unl_research_programs", "unl", "campus"),
    },
    "sources": [
        {
            "source_name": "unl_uraf_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://uraf.unl.edu/",
                "https://uraf.unl.edu/undergraduate-research/",
            ],
            "programs": [
                program(
                    "unl_office_undergraduate_research_fellowships",
                    "Office of Undergraduate Research & Fellowships (University of Nebraska-Lincoln)",
                    "https://uraf.unl.edu/",
                    "The Office of Undergraduate Research & Fellowships (URAF) is "
                    "Nebraska's campus hub for getting undergraduates of every "
                    "major involved in research and creative activity. It connects "
                    "students with faculty mentors, funding, and structured "
                    "programs, and advises them on nationally competitive "
                    "fellowships — the starting point for finding an opportunity, "
                    "learning how to begin, and applying for research support.",
                    lab_or_program="Office of Undergraduate Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "unl_ucare",
                    "UCARE: Undergraduate Creative Activities & Research Experience (University of Nebraska-Lincoln)",
                    "https://uraf.unl.edu/undergraduate-research/ucare-undergraduate-research/",
                    "UCARE (Undergraduate Creative Activities and Research "
                    "Experience) is UNL's flagship program pairing undergraduates "
                    "with faculty mentors on research or creative projects, with a "
                    "stipend across the academic year and summer. Open to students "
                    "in every college, it funds a first independent project and a "
                    "deeper second-year research experience under faculty guidance.",
                    lab_or_program="UCARE",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["UCARE", "faculty-mentored research",
                              "research stipend", "creative activity"],
                ),
                program(
                    "unl_fyre",
                    "First Year Research Experience (FYRE) (University of Nebraska-Lincoln)",
                    "https://uraf.unl.edu/undergraduate-research/first-year-research-experience/",
                    "The First Year Research Experience (FYRE) introduces "
                    "first-year Huskers to research early, placing them with a "
                    "faculty mentor and a research project in their first year at "
                    "Nebraska. Designed for students new to research, it is a "
                    "structured on-ramp to a lab or scholarly project and a first "
                    "step toward UCARE and independent undergraduate research.",
                    lab_or_program="First Year Research Experience",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["first-year research", "first research experience",
                              "faculty mentorship", "getting started"],
                ),
                program(
                    "unl_summer_research_program",
                    "Nebraska Summer Research Program (University of Nebraska-Lincoln)",
                    "https://summerprogram.unl.edu/",
                    "The Nebraska Summer Research Program (SRP) offers "
                    "undergraduates a full-time, ten-week paid summer research "
                    "experience in nationally funded research groups across many "
                    "disciplines. This NSF-supported REU umbrella provides a "
                    "stipend, housing, and travel, and is open to students from "
                    "UNL and other institutions, including those from groups "
                    "underrepresented in research.",
                    lab_or_program="Nebraska Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "REU", "research stipend",
                              "faculty-mentored research"],
                ),
                program(
                    "unl_research_fellowships",
                    "Research Fellowships Advising (URAF, University of Nebraska-Lincoln)",
                    "https://uraf.unl.edu/fellowships/research-fellowships/",
                    "URAF's Research Fellowships track advises Nebraska "
                    "undergraduates and recent graduates pursuing nationally "
                    "competitive research fellowships — Goldwater, NSF GRFP, "
                    "Fulbright research grants, and similar awards. It offers "
                    "one-on-one advising, application support, and campus "
                    "endorsement for students building toward research careers and "
                    "graduate study.",
                    lab_or_program="Research Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    keywords=["research fellowships", "Goldwater", "NSF GRFP",
                              "nationally competitive awards"],
                ),
            ],
        },
    ],
}
