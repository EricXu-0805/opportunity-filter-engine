"""Washington and Lee University campus opportunity-graph config.

Curated seed records of W&L's undergraduate-research landscape, centered on the
Provost's Office funding programs (the Summer Research Scholars program and the
Lenfest summer grants that pair students with faculty mentors), the Student
Summer Independent Research grants, the Johnson Opportunity Grants for
independent projects worldwide, the DART rare-disease research internship
program, and W&L's student-research showcase portal, plus two research-active
academic centers (Mudd Center for Ethics, DeLaney Center). URLs curl-verified
live (HTTP 200) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → wlu_research_programs (wlu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_PROVOST = ("https://www.wlu.edu/provosts-office/faculty-resources/"
            "faculty-development-and-funding-opportunities")
_UGR = "https://www.wlu.edu/academics/student-opportunities/undergraduate-research"

SCHOOL: dict = {
    "school_slug": "wlu",
    "organization": "Washington and Lee University",
    "location": "Lexington, VA",
    "emit": {
        "campus": ("wlu_research_programs", "wlu", "campus"),
    },
    "sources": [
        {
            "source_name": "wlu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _UGR,
                "https://studentresearch.academic.wlu.edu/",
            ],
            "programs": [
                program(
                    "wlu_srs",
                    "Summer Research Scholars (SRS) — Washington and Lee",
                    f"{_PROVOST}/summer-research-scholars",
                    "W&L's flagship summer undergraduate-research program: "
                    "students in any discipline carry out six, eight, or ten "
                    "weeks of full-time collaborative research supervised by a "
                    "faculty mentor, on campus or remotely, and are paid a "
                    "weekly stipend, culminating in the fall student-research "
                    "showcase.",
                    lab_or_program="Summer Research Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$500 per week stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "any discipline"],
                ),
                program(
                    "wlu_lenfest",
                    "Lenfest Summer Research Grants (Washington and Lee)",
                    f"{_PROVOST}/lenfest-grants",
                    "Lenfest summer grants fund faculty-led scholarly and "
                    "creative projects that regularly engage students as "
                    "research collaborators over roughly eight summer weeks, "
                    "with support for project expenses — a primary route for "
                    "student summer research alongside a professor.",
                    lab_or_program="Lenfest Grants",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["summer research", "faculty collaboration",
                              "research grant", "scholarship"],
                ),
                program(
                    "wlu_ssir",
                    "Student Summer Independent Research (SSIR) (Washington and Lee)",
                    "https://www.wlu.edu/provosts-office/curricular-and-student-"
                    "resources/student-funding-and-summer-opportunities/"
                    "student-summer-opportunities/"
                    "student-summer-independent-research-(ssir)",
                    "Grants supporting W&L students who design and carry out "
                    "their own independent research or creative projects during "
                    "the summer, in any field, with a faculty sponsor.",
                    lab_or_program="Student Summer Independent Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["independent research", "summer", "faculty sponsor",
                              "any discipline"],
                ),
                program(
                    "wlu_johnson",
                    "Johnson Opportunity Grants (Washington and Lee)",
                    "https://columns.wlu.edu/opportunities/johnson-opportunity-grant/",
                    "Competitive grants supporting independent student projects "
                    "around the world — including research projects, "
                    "internships, conference travel, and service — open to any "
                    "rising junior or senior.",
                    lab_or_program="Johnson Opportunity Grant",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    keywords=["independent research", "grant", "internships",
                              "global"],
                ),
                program(
                    "wlu_dart",
                    "DART Research Fellowship — Summer 2026 (Washington and Lee)",
                    "https://mga1.wlu.edu/campusnotices/view/web.php?id=9865&view=web",
                    "Washington and Lee's Neuroscience Program recruited students for "
                    "summer research on Niemann-Pick disease type C, supported by Dana’s "
                    "Angels Research Trust. The 2026 host labs were at the University of "
                    "Illinois Chicago, the University of Florida and the University of Michigan.",
                    department="Neuroscience Program",
                    lab_or_program="DART Fellowship",
                    preferred_year=[],
                    off_campus_location="University of Illinois Chicago, University of Florida, or University of Michigan",
                    opportunity_type="internship",
                    paid="stipend",
                    compensation="$6,600 fellowship for up to 10 weeks (summer 2026).",
                    keywords=["neuroscience", "Niemann-Pick disease type C"],
                ),
                program(
                    "wlu_student_research_portal",
                    "W&L Student Research Showcase Portal",
                    "https://studentresearch.academic.wlu.edu/",
                    "Washington and Lee's student-research portal, showcasing "
                    "current Summer Research Scholars projects across every "
                    "department and serving as the central hub for W&L-funded "
                    "research opportunities and application information.",
                    lab_or_program="W&L Student Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["student research", "summer research", "showcase",
                              "faculty mentor"],
                ),
                program(
                    "wlu_mudd_center",
                    "Mudd Center for Ethics Research (Washington and Lee)",
                    "https://www.wlu.edu/mudd-center",
                    "The Roger Mudd Center for Ethics supports faculty and "
                    "student research and programming on applied ethics across "
                    "disciplines, offering students opportunities to engage in "
                    "mentored ethics-focused scholarship.",
                    lab_or_program="Mudd Center for Ethics",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["ethics", "interdisciplinary research",
                              "humanities", "faculty mentor"],
                ),
                program(
                    "wlu_delaney_center",
                    "DeLaney Center Student Research (Washington and Lee)",
                    "https://www.wlu.edu/delaney-center",
                    "The DeLaney Center supports interdisciplinary research on "
                    "Southern race, culture, and history, engaging students in "
                    "faculty-mentored archival, digital-humanities, and "
                    "community-based research projects.",
                    lab_or_program="DeLaney Center",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["Southern studies", "digital humanities",
                              "archival research", "interdisciplinary"],
                ),
            ],
        },
    ],
}
