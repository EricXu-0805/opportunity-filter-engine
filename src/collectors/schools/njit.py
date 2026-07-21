"""New Jersey Institute of Technology campus opportunity-graph config.

Curated seed records of NJIT's undergraduate-research landscape, centered on the
Office of Undergraduate Research and Innovation (URI, research.njit.edu/uri) —
its office hub and Programs overview — plus the two flagship URI-administered
funding programs: the Provost URI Summer Fellowship and the URI Student Seed
Grants. Every URL was curl-verified live (HTTP 200) on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → njit_research_programs (njit / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "njit",
    "organization": "New Jersey Institute of Technology",
    "location": "Newark, NJ",
    "emit": {
        "campus": ("njit_research_programs", "njit", "campus"),
    },
    "sources": [
        {
            "source_name": "njit_uri_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://research.njit.edu/uri/",
                "https://research.njit.edu/uri/programs",
            ],
            "programs": [
                program(
                    "njit_uri_office",
                    "Undergraduate Research and Innovation (New Jersey Institute of Technology)",
                    "https://research.njit.edu/uri/",
                    "NJIT's Undergraduate Research and Innovation (URI) program is the "
                    "campus hub connecting undergraduates of every major with "
                    "faculty-mentored research and innovation experiences. It "
                    "administers the university's undergraduate research funding, "
                    "summer fellowships, and seed grants, and helps students find a "
                    "mentor and get started on a research or entrepreneurial project.",
                    lab_or_program="Undergraduate Research and Innovation",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "innovation", "any major"],
                ),
                program(
                    "njit_uri_programs",
                    "URI Programs Overview (NJIT Undergraduate Research and Innovation)",
                    "https://research.njit.edu/uri/programs",
                    "An overview of NJIT's Undergraduate Research and Innovation (URI) "
                    "programs, which are offered annually to promote undergraduate "
                    "research and innovation across all disciplines. The page "
                    "describes the Student Seed Programs, the Summer Research "
                    "Programs, and the Dr. James F. Stevenson Innovation Awards, and "
                    "how undergraduates apply to each.",
                    lab_or_program="Undergraduate Research and Innovation",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research programs", "innovation",
                              "getting started", "any major"],
                ),
                program(
                    "njit_provost_uri_summer_fellowship",
                    "Provost URI Summer Fellowship (New Jersey Institute of Technology)",
                    "https://research.njit.edu/uri/summer-research-programs",
                    "The NJIT Provost Undergraduate Research and Innovation (URI) "
                    "Summer Fellowship is a 10-week program that provides summer "
                    "stipend support (about $5,000 per awardee) to undergraduates "
                    "from all disciplines to pursue full-time research under the "
                    "guidance of a faculty mentor, culminating in a presentation at "
                    "the URI Summer Research Symposium. Applications are accepted "
                    "from students in any major.",
                    lab_or_program="Provost URI Summer Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend, approximately $5,000",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "research stipend",
                              "faculty-mentored research", "any major"],
                ),
                program(
                    "njit_uri_student_seed_grants",
                    "URI Student Seed Grants (New Jersey Institute of Technology)",
                    "https://research.njit.edu/uri/student-seed-programs",
                    "The NJIT Undergraduate Research and Innovation (URI) Student "
                    "Seed Grant program provides small awards (Phase-1 grants of "
                    "about $500 per project) to undergraduates to pursue preliminary "
                    "research or demonstrate an initial proof-of-concept or "
                    "prototype during the academic year. It is a first step toward "
                    "larger funded projects and the summer fellowship, open to "
                    "students across disciplines.",
                    lab_or_program="URI Student Seed Grants",
                    opportunity_type="research",
                    paid="yes",
                    compensation="Phase-1 seed grant, approximately $500 per project",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["seed grant", "research funding",
                              "proof of concept", "any major"],
                ),
            ],
        },
    ],
}
