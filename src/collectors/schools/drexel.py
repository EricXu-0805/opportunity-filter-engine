"""Drexel University campus opportunity-graph config.

Curated seed records of Drexel's undergraduate-research landscape, centered on
the Pennoni Honors College's Undergraduate Research & Enrichment Programs (UREP,
drexel.edu/pennoni/urep) — its office hub and "Finding Research" guide — plus the
three flagship UREP-administered programs: the STAR Scholars summer program for
first-year students, the SuperNova Undergraduate Research Fellows continuation
program, and the Undergraduate Research Funding (mini-grants + travel grants).
Every URL was curl-verified live (HTTP 200) on 2026-07-20.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> drexel_research_programs (drexel / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "drexel",
    "organization": "Drexel University",
    "location": "Philadelphia, PA",
    "emit": {
        "campus": ("drexel_research_programs", "drexel", "campus"),
    },
    "sources": [
        {
            "source_name": "drexel_urep_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://drexel.edu/pennoni/urep/undergraduate-research/",
                "https://drexel.edu/pennoni/urep/undergraduate-research/finding-research/",
            ],
            "programs": [
                program(
                    "drexel_urep_office",
                    "Undergraduate Research & Enrichment Programs (Drexel University)",
                    "https://drexel.edu/pennoni/urep/undergraduate-research/",
                    "Drexel's Undergraduate Research & Enrichment Programs (UREP), "
                    "housed in the Pennoni Honors College, is the campus hub for "
                    "getting involved in faculty-mentored research, scholarship, "
                    "and creative work. UREP helps students of every major find "
                    "research mentors, secure funding, and present their work, and "
                    "administers Drexel's signature undergraduate research programs.",
                    lab_or_program="Undergraduate Research & Enrichment Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "drexel_finding_research",
                    "Finding Research (Drexel Undergraduate Research & Enrichment Programs)",
                    "https://drexel.edu/pennoni/urep/undergraduate-research/finding-research/",
                    "UREP's guide to finding a first undergraduate research "
                    "experience at Drexel: how to identify faculty mentors and "
                    "labs, reach out to professors, and connect with departments "
                    "across the sciences, engineering, humanities, and social "
                    "sciences. It walks students through the first steps of joining "
                    "a research project.",
                    lab_or_program="Undergraduate Research & Enrichment Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "contacting faculty",
                              "getting started", "research positions"],
                ),
                program(
                    "drexel_star_scholars",
                    "STAR Scholars Program (Drexel University)",
                    "https://drexel.edu/pennoni/urep/undergraduate-research/star-scholars/",
                    "The STAR (Students Tackling Advanced Research) Scholars "
                    "Program gives highly motivated first-year students an early, "
                    "faculty-mentored research, scholarship, or creative experience "
                    "during the summer after their freshman year. Selected students "
                    "complete 350 hours of mentored full-time research and present "
                    "their results, a competitive first step into Drexel research.",
                    lab_or_program="STAR Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman"],
                    keywords=["summer research", "first-year research",
                              "faculty-mentored research", "STAR Scholars"],
                ),
                program(
                    "drexel_supernova_fellows",
                    "SuperNova Undergraduate Research Fellows (Drexel University)",
                    "https://drexel.edu/pennoni/urep/undergraduate-research/supernova-research-fellows/",
                    "The SuperNova Undergraduate Research Fellows Program challenges "
                    "sophomore-through-senior students to build on a STAR or prior "
                    "research experience with progressively more demanding research "
                    "projects, courses, and activities. Students document and "
                    "reflect on their research throughout their time at Drexel and "
                    "are recognized with digital badges for sustained research "
                    "involvement.",
                    lab_or_program="SuperNova Undergraduate Research Fellows",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research fellowship", "continuing research",
                              "faculty-mentored research", "SuperNova Fellows"],
                ),
                program(
                    "drexel_ur_funding",
                    "Undergraduate Research Mini-Grants & Travel Grants (Drexel University)",
                    "https://drexel.edu/pennoni/urep/undergraduate-research/funding-research/",
                    "UREP funds undergraduate research through internal "
                    "mini-grants and travel grants. Mini-grants support Drexel "
                    "faculty and their undergraduate collaborators working together "
                    "on research, scholarship, and creative projects; travel grants "
                    "help students present their work at conferences. Both lower the "
                    "cost barrier to starting and sharing undergraduate research.",
                    lab_or_program="Undergraduate Research Funding",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research mini-grant", "travel grant",
                              "research funding", "conference presentation"],
                ),
            ],
        },
    ],
}
