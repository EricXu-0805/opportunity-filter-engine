"""University of Pittsburgh campus opportunity-graph config.

Curated seed records of Pitt's undergraduate-research landscape: the
university-wide Office of Undergraduate Research, Scholarship & Creative Activity
(OUR) opportunities hub, the Dietrich School's OUR programs (SURA, First
Experiences in Research, Curiosity Grants), the Frederick Honors College research
& creative fellowships (Brackenridge, CURF, RCF), and the School of Medicine's
Summer Undergraduate Research Program (SURP). URLs curl-verified live (HTTP 200)
on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → pitt_research_programs (pitt / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "pitt",
    "organization": "University of Pittsburgh",
    "location": "Pittsburgh, PA",
    "emit": {
        "campus": ("pitt_research_programs", "pitt", "campus"),
    },
    "sources": [
        {
            "source_name": "pitt_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.undergradstudies.pitt.edu/undergrad-research-opportunities",
                "https://www.asundergrad.pitt.edu/research/our-opportunities",
                "https://www.frederickhonors.pitt.edu/research/research-creative-fellowships",
                "https://somgrad.pitt.edu/prospective-students/summer-undergraduate-research-program-surp",
            ],
            "programs": [
                program(
                    "pitt_our_research_opportunities",
                    "Undergraduate Research Opportunities (University of Pittsburgh)",
                    "https://www.undergradstudies.pitt.edu/undergrad-research-opportunities",
                    "The University of Pittsburgh's central hub for getting "
                    "involved in undergraduate research, scholarship, and creative "
                    "activity. It points students toward finding a faculty mentor, "
                    "funding and fellowship options, and ways to present and "
                    "publish their work across every school on campus.",
                    lab_or_program="Office of Undergraduate Research, Scholarship & Creative Activity",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentor",
                              "research funding", "creative activity"],
                ),
                program(
                    "pitt_dietrich_our_opportunities",
                    "OUR Research Opportunities — Dietrich School (University of Pittsburgh)",
                    "https://www.asundergrad.pitt.edu/research/our-opportunities",
                    "The Kenneth P. Dietrich School of Arts and Sciences Office of "
                    "Undergraduate Research runs structured pathways into research, "
                    "including the Summer Undergraduate Research Award (SURA), the "
                    "First Experiences in Research program for students new to "
                    "research, and Curiosity Grants that fund student-driven "
                    "projects.",
                    lab_or_program="Dietrich School Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research award", "first experiences in research",
                              "curiosity grants", "arts and sciences"],
                ),
                program(
                    "pitt_honors_research_fellowships",
                    "Research & Creative Fellowships — Frederick Honors College (University of Pittsburgh)",
                    "https://www.frederickhonors.pitt.edu/research/research-creative-fellowships",
                    "The David C. Frederick Honors College awards research and "
                    "creative fellowships open to Pitt undergraduates, including "
                    "the Brackenridge Fellowship for full-time summer research, the "
                    "Chancellor's Undergraduate Research Fellowship (CURF), and the "
                    "Research & Creative Fellowship (RCF) supporting mentored "
                    "scholarly and creative projects.",
                    lab_or_program="David C. Frederick Honors College",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["Brackenridge fellowship", "undergraduate research fellowship",
                              "creative fellowship", "mentored research"],
                ),
                program(
                    "pitt_som_surp",
                    "Summer Undergraduate Research Program (SURP) — School of Medicine (University of Pittsburgh)",
                    "https://somgrad.pitt.edu/prospective-students/summer-undergraduate-research-program-surp",
                    "The University of Pittsburgh School of Medicine's Summer "
                    "Undergraduate Research Program is a mentored full-time summer "
                    "research experience in the biomedical sciences, pairing "
                    "undergraduates with faculty labs and providing professional "
                    "development for students considering research and graduate "
                    "training.",
                    lab_or_program="School of Medicine Graduate Studies",
                    opportunity_type="summer_program",
                    preferred_year=["sophomore", "junior"],
                    keywords=["summer research", "biomedical sciences",
                              "mentored research", "graduate preparation"],
                ),
            ],
        },
    ],
}
