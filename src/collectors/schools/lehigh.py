"""Lehigh University campus opportunity-graph config.

Curated seed records of Lehigh's undergraduate-research landscape: the P.C.
Rossin College of Engineering undergraduate-research hub plus Lehigh's
campus-wide Creative Inquiry / Mountaintop Initiative — its office hub, the
flagship Mountaintop Summer Experience impact fellowship, and the Inquiry to
Impact project-initiation grants. Every URL was curl-verified live (HTTP 200,
redirects already resolved to their canonical 200 target) on 2026-07-20:
``/undergraduate-research`` 301-redirects to the engineering experiential-learning
path, and the Mountaintop Summer Experience canonical path is
``/impactfellowships/mountaintop-summer-experience``.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> lehigh_research_programs (lehigh / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "lehigh",
    "organization": "Lehigh University",
    "location": "Bethlehem, PA",
    "emit": {
        "campus": ("lehigh_research_programs", "lehigh", "campus"),
    },
    "sources": [
        {
            "source_name": "lehigh_undergraduate_research_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://engineering.lehigh.edu/academics/undergraduate/experiential-learning/lehigh-engineering-undergraduate-student-research",
                "https://creativeinquiry.lehigh.edu/",
            ],
            "programs": [
                program(
                    "lehigh_engineering_undergraduate_research",
                    "Undergraduate Student Research (P.C. Rossin College of Engineering, Lehigh University)",
                    "https://engineering.lehigh.edu/academics/undergraduate/experiential-learning/lehigh-engineering-undergraduate-student-research",
                    "The P.C. Rossin College of Engineering's undergraduate "
                    "research hub connects Lehigh engineering and applied-science "
                    "students with faculty-mentored research across every "
                    "department. It explains how to find a lab, earn research "
                    "credit or pay, and pursue summer and academic-year projects "
                    "in computing, electrical, mechanical, bio, chemical, civil, "
                    "materials, and industrial/systems engineering.",
                    lab_or_program="Rossin College Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "engineering research",
                              "faculty mentorship", "research for credit"],
                ),
                program(
                    "lehigh_creative_inquiry",
                    "Creative Inquiry + Mountaintop Initiative (Lehigh University)",
                    "https://creativeinquiry.lehigh.edu/",
                    "Creative Inquiry is Lehigh's campus-wide home for "
                    "student-driven, interdisciplinary research and creative "
                    "work. Anchored by the Mountaintop Initiative, it helps "
                    "undergraduates in any major design and lead impact-focused "
                    "projects with faculty mentors and external partners, and "
                    "points them to fellowships, grants, and summer research "
                    "experiences.",
                    lab_or_program="Creative Inquiry / Mountaintop Initiative",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["interdisciplinary research", "creative inquiry",
                              "any major", "student-driven projects"],
                ),
                program(
                    "lehigh_mountaintop_summer_experience",
                    "Mountaintop Summer Experience (Lehigh University)",
                    "https://creativeinquiry.lehigh.edu/impactfellowships/mountaintop-summer-experience",
                    "The Mountaintop Summer Experience is a 10-week summer "
                    "program where Lehigh students take a deep dive into an "
                    "interdisciplinary, impact-focused project in small teams "
                    "with faculty mentors and external partners. Accepted "
                    "students receive a Mountaintop Fellowship stipend and "
                    "project budget, and take radical ownership of open-ended "
                    "research and creative work.",
                    lab_or_program="Mountaintop Summer Experience",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Mountaintop Fellowship stipend (~$5,000 for undergraduates) plus project budget",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "Mountaintop fellowship",
                              "interdisciplinary project", "research stipend"],
                ),
                program(
                    "lehigh_inquiry_to_impact_grants",
                    "Inquiry to Impact Project Initiation Grants (Lehigh University)",
                    "https://creativeinquiry.lehigh.edu/mountaintop-programs/inquiry-impact-project-initiation-grants",
                    "Inquiry to Impact Project Initiation Grants award seed "
                    "funding to Lehigh students and faculty to launch new "
                    "interdisciplinary, impact-driven research and creative "
                    "projects through the Mountaintop Initiative. The grants help "
                    "undergraduates get a student-designed project off the ground "
                    "with mentorship and resources before scaling it into a "
                    "larger research effort.",
                    lab_or_program="Inquiry to Impact Grants",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["seed grant", "project funding",
                              "student-designed project", "research funding"],
                ),
            ],
        },
    ],
}
