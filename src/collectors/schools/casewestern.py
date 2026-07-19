"""Case Western Reserve University campus opportunity-graph config.

Curated seed records of CWRU's undergraduate-research landscape, centered on the
Undergraduate Research Office (case.edu/studentlife/ugresearch) — its office hub,
the "Start Your Research" getting-started pathway, and the two summer research
program tracks it runs: the Sponsored Summer Research Programs (SSRP, the
competitive merit-based summer research funding, faculty-mentored) and the
Campus-Based Summer Programs listing (on-campus full-time summer research for
CWRU and visiting students). All URLs curl-verified live (HTTP 200) on
2026-07-19 through the proxy.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> casewestern_research_programs (casewestern / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "casewestern",
    "organization": "Case Western Reserve University",
    "location": "Cleveland, OH",
    "emit": {
        "campus": ("casewestern_research_programs", "casewestern", "campus"),
    },
    "sources": [
        {
            "source_name": "casewestern_ugresearch_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://case.edu/studentlife/ugresearch/",
                "https://case.edu/studentlife/ugresearch/programs-and-funding",
            ],
            "programs": [
                program(
                    "casewestern_undergraduate_research_office",
                    "Undergraduate Research Office (Case Western Reserve University)",
                    "https://case.edu/studentlife/ugresearch/",
                    "Case Western Reserve University's central Undergraduate "
                    "Research Office helps students of every major get involved in "
                    "faculty-mentored research and creative endeavors. It is the "
                    "campus hub for finding a research mentor, discovering funded "
                    "programs and summer opportunities, and learning how to get "
                    "started on a research or creative project.",
                    lab_or_program="Undergraduate Research Office",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "creative endeavors", "any major"],
                ),
                program(
                    "casewestern_ssrp",
                    "Sponsored Summer Research Programs (SSRP, Case Western Reserve University)",
                    "https://case.edu/studentlife/ugresearch/programs-and-funding/ssrp",
                    "The Undergraduate Research Office's Sponsored Summer Research "
                    "Programs (SSRP) offer competitive, merit-based funding to CWRU "
                    "undergraduates pursuing faculty-mentored research or creative "
                    "work over the summer. Applicants identify a faculty mentor and "
                    "project in advance; many students join faculty-led projects, "
                    "especially in STEM and the social sciences, and independent "
                    "projects are also supported.",
                    lab_or_program="Sponsored Summer Research Programs",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Summer SSRP application deadline is typically mid-February.",
                    keywords=["summer research", "research funding",
                              "faculty-mentored", "merit-based award"],
                ),
                program(
                    "casewestern_campus_based_summer",
                    "Campus-Based Summer Research Programs (Case Western Reserve University)",
                    "https://case.edu/studentlife/ugresearch/programs-and-funding/campus-based-summer-programs",
                    "A directory of on-campus summer research and creative-endeavor "
                    "programs at CWRU, open to both CWRU and visiting students. "
                    "Participants carry out full-time independent projects under a "
                    "faculty mentor over the summer; application deadlines cluster "
                    "early in the spring semester (mid-January to mid-March).",
                    lab_or_program="Undergraduate Research Office",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "on-campus research",
                              "faculty mentor", "full-time project"],
                ),
                program(
                    "casewestern_start_your_research",
                    "Start Your Research (Case Western Reserve University)",
                    "https://case.edu/studentlife/ugresearch/start-your-research",
                    "CWRU's guide for undergraduates beginning research on campus: "
                    "how to search for a research position, contact and connect "
                    "with faculty mentors, and attend educational seminars on "
                    "getting started. It walks students through the first steps of "
                    "securing a faculty-mentored research or creative-endeavor role.",
                    lab_or_program="Undergraduate Research Office",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["getting started", "finding a mentor",
                              "contacting faculty", "research basics"],
                ),
            ],
        },
    ],
}
