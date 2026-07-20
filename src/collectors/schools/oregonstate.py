"""Oregon State University campus opportunity-graph config.

Curated seed records of Oregon State's undergraduate-research landscape, centered
on Undergraduate Research, Scholarship, and the Arts (URSA,
undergradresearch.oregonstate.edu) — the campus hub — plus its Summer Research
Opportunities guide, its Student Resources getting-started guide, and the College
of Science Research and Innovation Seed (SciRIS) program. Every URL was
curl-verified live (HTTP 200) on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → oregonstate_research_programs (oregonstate / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "oregonstate",
    "organization": "Oregon State University",
    "location": "Corvallis, OR",
    "emit": {
        "campus": ("oregonstate_research_programs", "oregonstate", "campus"),
    },
    "sources": [
        {
            "source_name": "oregonstate_ursa_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergradresearch.oregonstate.edu/",
                "https://undergradresearch.oregonstate.edu/summer-research-opportunities",
                "https://undergradresearch.oregonstate.edu/resources-students",
            ],
            "programs": [
                program(
                    "oregonstate_ursa",
                    "URSA: Undergraduate Research, Scholarship, and the Arts (Oregon State University)",
                    "https://undergradresearch.oregonstate.edu/",
                    "Undergraduate Research, Scholarship, and the Arts (URSA) is "
                    "Oregon State's campus hub for undergraduate research and "
                    "creative work. It helps students of every major and year get "
                    "started in research, find and connect with faculty mentors, "
                    "fund their projects, and present their work — the front door "
                    "to inquiry across the sciences, engineering, humanities, and "
                    "the arts at OSU.",
                    lab_or_program="Undergraduate Research, Scholarship, and the Arts",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "any major", "getting started"],
                ),
                program(
                    "oregonstate_summer_research",
                    "Summer Research Opportunities (Oregon State University URSA)",
                    "https://undergradresearch.oregonstate.edu/summer-research-opportunities",
                    "URSA's guide to summer research opportunities at Oregon "
                    "State: a curated list of full-time summer research programs, "
                    "REUs, and faculty-mentored projects open to OSU "
                    "undergraduates across disciplines. It points students to "
                    "paid summer research experiences on campus and beyond and "
                    "explains how to apply.",
                    lab_or_program="URSA Summer Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "REU", "faculty-mentored research",
                              "research stipend"],
                ),
                program(
                    "oregonstate_ursa_get_started",
                    "Getting Started in Research — Student Resources (Oregon State University URSA)",
                    "https://undergradresearch.oregonstate.edu/resources-students",
                    "URSA's student resources for getting started in research at "
                    "Oregon State: how to find a research area and a faculty "
                    "mentor, reach out to professors, join a lab, and navigate "
                    "first steps as a new undergraduate researcher. Designed for "
                    "students new to research who want a concrete path into a "
                    "project.",
                    lab_or_program="Undergraduate Research, Scholarship, and the Arts",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "contacting faculty",
                              "joining a lab", "first research experience"],
                ),
                program(
                    "oregonstate_sciris",
                    "SciRIS: Research and Innovation Seed Program (Oregon State University College of Science)",
                    "https://science.oregonstate.edu/research/research-and-innovation-seed-program",
                    "The College of Science Research and Innovation Seed (SciRIS) "
                    "Program funds collaborative research projects at Oregon "
                    "State, including a track that supports undergraduate "
                    "researchers working alongside faculty on high-impact "
                    "proposals. It provides seed funding and mentorship for "
                    "students pursuing research in the sciences.",
                    organization="Oregon State University College of Science",
                    lab_or_program="Research and Innovation Seed Program",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["seed funding", "collaborative research",
                              "College of Science", "faculty-mentored research"],
                ),
            ],
        },
    ],
}
