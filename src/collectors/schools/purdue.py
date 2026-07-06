"""Purdue University campus opportunity-graph config (US-News rollout).

Curated seed of Purdue's undergraduate-research landscape: the Office of
Undergraduate Research (OUR) hub, the College of Engineering SURF program, the
Center for Career Success, and Discovery Park research institutes. URLs verified
against purdue.edu (Jul 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> purdue_research_programs (purdue / campus)
    open   -> purdue_external_research (national / open)
    lab    -> purdue_labs              (purdue / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    DEPARTMENT,
    LAB,
    RECURSIVE,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "purdue",
    "organization": "Purdue University",
    "location": "West Lafayette, IN",
    "emit": {
        "campus": ("purdue_research_programs", "purdue", "campus"),
        "open": ("purdue_external_research", None, "open"),
        "lab": ("purdue_labs", "purdue", "unknown"),
    },
    "sources": [
        {
            "source_name": "purdue_our_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": ["https://www.purdue.edu/undergrad-research/"],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "our_hub",
                    "Office of Undergraduate Research (OUR) — Hub (Purdue)",
                    "https://www.purdue.edu/undergrad-research/",
                    "Purdue's central hub for undergraduate research: the fall/spring "
                    "Undergraduate Research Expo, research assistantships, scholarships, "
                    "and faculty-mentor matching across all colleges. Start here to find "
                    "a program by class year and field.",
                    lab_or_program="Office of Undergraduate Research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
            ],
        },
        {
            "source_name": "purdue_engineering_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": ["https://engineering.purdue.edu/Engr/Academics/Undergraduate/SURF"],
            "crawl": STATIC,
            "programs": [
                program(
                    "surf",
                    "Summer Undergraduate Research Fellowship (SURF) — Engineering (Purdue)",
                    "https://engineering.purdue.edu/Engr/Academics/Undergraduate/SURF",
                    "An 11-week full-time summer research program placing undergraduates "
                    "in College of Engineering labs alongside graduate-student mentors. "
                    "Pays a stipend (~$4,500) plus housing support; open to students from "
                    "Purdue and other institutions considering graduate study.",
                    organization="College of Engineering, Purdue University",
                    department="Engineering",
                    lab_or_program="SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="~$4,500 summer stipend + housing",
                    eligibility_majors=["Engineering", "Computer Science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Annual summer cycle; applications typically due late winter.",
                    keywords=["summer research", "engineering", "stipend"],
                ),
            ],
        },
        {
            "source_name": "purdue_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://www.cco.purdue.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_success",
                    "Center for Career Success — Internships (Purdue)",
                    "https://www.cco.purdue.edu/",
                    "Purdue's Center for Career Success supports undergraduates with "
                    "internship and job search, career fairs, and the campus job board. "
                    "Open to all class years and majors.",
                    organization="Center for Career Success, Purdue University",
                    lab_or_program="Center for Career Success",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career"],
                ),
            ],
        },
        {
            "source_name": "purdue_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": ["https://www.purdue.edu/discoverypark/"],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "discovery_park",
                    "Discovery Park District Institutes — Undergraduate Research (Purdue)",
                    "https://www.purdue.edu/discoverypark/",
                    "Purdue's interdisciplinary research institutes (Birck Nanotechnology "
                    "Center, Bindley Bioscience Center, and others) host undergraduate "
                    "researchers across nanotechnology, life sciences, and data science — "
                    "good cold-email targets for lab placements.",
                    department="Discovery Park",
                    lab_or_program="Discovery Park Institutes",
                    eligibility_majors=["Engineering", "Biology", "Data Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["nanotechnology", "bioscience", "join our lab"],
                ),
            ],
        },
    ],
}
