"""Dartmouth College campus opportunity-graph config.

Curated seed records of Dartmouth's undergraduate-research landscape, centered
on SURF-D (Scholars Programs, Undergraduate Research, and Fellowships at
Dartmouth — the renamed UGAR office; the old /ugar/ path 301s to /surfd/) and
its funding programs, plus the E.E. Just STEM pipeline and Thayer's
undergraduate research routes. URLs verified live (HTTP 200) on 2026-07-12.
The standalone WISP site is dead (redirects to the homepage) — its first-year
research-internship role now lives in Dartmouth ERAS, so WISP is not wired.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → dartmouth_research_programs (dartmouth / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "dartmouth",
    "organization": "Dartmouth College",
    "location": "Hanover, NH",
    "emit": {
        "campus": ("dartmouth_research_programs", "dartmouth", "campus"),
    },
    "sources": [
        {
            "source_name": "dartmouth_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://students.dartmouth.edu/surfd/",
                "https://students.dartmouth.edu/eejust/",
                "https://engineering.dartmouth.edu/undergraduate/opportunities",
            ],
            "programs": [
                program(
                    "surfd_hub",
                    "SURF-D — Scholars Programs, Undergraduate Research, and Fellowships at Dartmouth",
                    "https://students.dartmouth.edu/surfd/",
                    "SURF-D (formerly UGAR) is Dartmouth's central office for "
                    "undergraduate research funding, scholars programs, and "
                    "competitive fellowships. It walks students through getting "
                    "started in research, finding a faculty mentor, funding "
                    "deadlines, and the application system, and administers the "
                    "research assistantship and grant programs below.",
                    lab_or_program="SURF-D",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research funding", "fellowships"],
                ),
                program(
                    "presidential_scholars",
                    "James O. Freedman Presidential Scholars Program (Dartmouth)",
                    "https://students.dartmouth.edu/surfd/undergraduate-research/presidential-scholars",
                    "The Presidential Scholars program gives Dartmouth juniors "
                    "first-hand research experience as part-time research "
                    "assistants to faculty. Scholars earn a $1,700 fellowship "
                    "stipend for each completed term of research and often "
                    "continue into honors thesis work with their mentor.",
                    lab_or_program="Presidential Scholars",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$1,700 per completed research term",
                    preferred_year=["junior"],
                    international_friendly="yes",
                    keywords=["research assistantship", "faculty mentorship"],
                ),
                program(
                    "urad",
                    "Undergraduate Research Assistantships at Dartmouth (URAD)",
                    "https://students.dartmouth.edu/surfd/undergraduate-research/undergraduate-research-assistantships-dartmouth-urad",
                    "URAD places undergraduates in part-time research "
                    "assistantships with Dartmouth faculty across all divisions, "
                    "with a $1,700 stipend at the end of the completed research "
                    "term. The open-application counterpart to Presidential "
                    "Scholars — any student can apply with a sponsoring faculty "
                    "member.",
                    lab_or_program="URAD",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$1,700 per completed research term",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research assistantship", "stipend"],
                ),
                program(
                    "eras",
                    "Dartmouth ERAS — Early Research Access in the Sciences",
                    "https://students.dartmouth.edu/surfd/undergraduate-research/dartmouth-early-research-access-sciences",
                    "Dartmouth ERAS matches first-year students to faculty "
                    "mentors for part-time paid research experiences in the "
                    "sciences, with a faculty project database and structured "
                    "mentor onboarding. The successor to WISP's first-year "
                    "research internships — the entry point into STEM labs at "
                    "Dartmouth.",
                    lab_or_program="Dartmouth ERAS",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    keywords=["first-year research", "STEM", "faculty mentorship"],
                ),
                program(
                    "leave_term_grants",
                    "SURF-D Leave Term Grants (Dartmouth)",
                    "https://students.dartmouth.edu/surfd/undergraduate-research/leave-term-grants",
                    "Leave Term Grants fund full-time research during a "
                    "Dartmouth leave term, letting students devote an entire "
                    "off-term to a faculty-mentored project; recipients submit a "
                    "final report at term end.",
                    lab_or_program="Leave Term Grants",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "leave term"],
                ),
                program(
                    "senior_fellowships",
                    "Senior Fellowships (Dartmouth)",
                    "https://students.dartmouth.edu/surfd/undergraduate-research/senior-fellowships",
                    "Senior Fellowships support year-long senior projects whose "
                    "intellectual scope goes beyond the existing curriculum — a "
                    "self-designed capstone pursued with faculty mentorship in "
                    "place of some or all regular coursework.",
                    lab_or_program="Senior Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["senior"],
                    international_friendly="yes",
                    keywords=["senior project", "capstone", "fellowship"],
                ),
                program(
                    "ee_just",
                    "E.E. Just Program — STEM Scholars (Dartmouth)",
                    "https://students.dartmouth.edu/eejust/",
                    "The E.E. Just Program broadens participation in STEM at "
                    "Dartmouth with undergraduate fellowships, summer research "
                    "internships (including a Marine Biological Laboratory "
                    "placement and the DALI Lab internship), mentoring, and the "
                    "Just Science forum. Named for pioneering Black biologist "
                    "Ernest Everett Just, Dartmouth class of 1907.",
                    lab_or_program="E.E. Just Program",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["STEM", "diversity in science", "summer research"],
                ),
                program(
                    "thayer_ugr",
                    "Thayer Research & Entrepreneurship Opportunities (Dartmouth Engineering)",
                    "https://engineering.dartmouth.edu/undergraduate/opportunities",
                    "Thayer School routes undergraduates into engineering labs "
                    "via FYREE (First-Year Research in Engineering Experience) "
                    "for first-years and prospective majors, Dartmouth ERAS "
                    "placements, and direct lab positions with Thayer faculty, "
                    "alongside entrepreneurship programming.",
                    lab_or_program="Thayer Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Engineering Sciences"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["engineering research", "FYREE"],
                ),
            ],
        },
    ],
}
