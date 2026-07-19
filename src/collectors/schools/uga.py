"""University of Georgia campus opportunity-graph config.

Curated seed records of UGA's undergraduate-research landscape, centered on
the Center for Undergraduate Research Opportunities (CURO) — UGA's flagship
office that facilitates faculty-mentored research in any discipline from the
first semester on — plus its Summer Research Fellowship, the CURO Research
Award, the CURO Honors Scholarship (offered with the Morehead Honors College),
the Conference Participation Grant, and the annual CURO Symposium, together
with the Morehead Honors College Foundation Fellowship and the Office of
Research hub. URLs curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uga_research_programs (uga / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "uga",
    "organization": "University of Georgia",
    "location": "Athens, GA",
    "emit": {
        "campus": ("uga_research_programs", "uga", "campus"),
    },
    "sources": [
        {
            "source_name": "uga_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://curo.uga.edu/",
                "https://research.uga.edu/",
                "https://honors.uga.edu/foundation-fellowship/",
            ],
            "programs": [
                program(
                    "uga_curo",
                    "Center for Undergraduate Research Opportunities (CURO)",
                    "https://curo.uga.edu/about/about-undergraduate-research-at-uga/",
                    "CURO facilitates sustained, progressive, faculty-mentored "
                    "undergraduate research during any of a student's "
                    "undergraduate years at the University of Georgia — "
                    "including the first semester — across every discipline. "
                    "It is the central hub connecting students with research "
                    "mentors, funding, and a for-credit research course "
                    "sequence.",
                    lab_or_program="Center for Undergraduate Research Opportunities",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty-mentored",
                              "any discipline", "research mentorship"],
                ),
                program(
                    "uga_curo_current_opportunities",
                    "CURO Current Research Opportunities",
                    "https://curo.uga.edu/research-opportunities/current-opportunities/",
                    "A regularly updated listing of specific faculty-mentored "
                    "research opportunities currently open to UGA "
                    "undergraduates, with project descriptions and mentor "
                    "contacts so students can reach out directly to labs whose "
                    "work interests them.",
                    lab_or_program="Center for Undergraduate Research Opportunities",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["open positions", "research mentors",
                              "project listings", "cold email"],
                ),
                program(
                    "uga_curo_summer_research_fellowship",
                    "CURO Summer Research Fellowship (University of Georgia)",
                    "https://curo.uga.edu/research-opportunities/summer-research-fellowship/",
                    "CURO awards Summer Research Fellowships supporting UGA "
                    "undergraduates to pursue intensive, immersive, "
                    "faculty-mentored research during the summer, with a "
                    "stipend that lets students focus full-time on a project "
                    "and present at the CURO Summer Final Forum.",
                    lab_or_program="Center for Undergraduate Research Opportunities",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "full-time", "stipend",
                              "faculty-mentored"],
                ),
                program(
                    "uga_curo_research_award",
                    "CURO Research Award (University of Georgia)",
                    "https://curo.uga.edu/students/curo-research-award/",
                    "Each year the CURO Research Award provides 500 "
                    "scholarships of $1,000 each to outstanding UGA "
                    "undergraduates across campus to actively participate in "
                    "faculty-mentored research in any discipline.",
                    lab_or_program="Center for Undergraduate Research Opportunities",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$1,000 scholarship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research scholarship", "faculty-mentored",
                              "any discipline"],
                ),
                program(
                    "uga_curo_honors_scholarship",
                    "CURO Honors Scholarship (University of Georgia)",
                    "https://curo.uga.edu/students/curo-honors-scholarship/",
                    "UGA's top undergraduate research scholarship, offered "
                    "jointly through the Morehead Honors College and CURO, "
                    "providing sustained financial support for high-achieving "
                    "students engaged in faculty-mentored research.",
                    lab_or_program="Morehead Honors College / CURO",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["honors", "research scholarship",
                              "faculty-mentored", "merit"],
                ),
                program(
                    "uga_curo_conference_grant",
                    "CURO Conference Participation Grant (University of Georgia)",
                    "https://curo.uga.edu/students/conference-participation-grant/",
                    "The CURO Conference Participation Grant provides support "
                    "for UGA undergraduates to travel to and present their "
                    "research at conferences throughout the United States.",
                    lab_or_program="Center for Undergraduate Research Opportunities",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "travel grant"],
                ),
                program(
                    "uga_curo_symposium",
                    "CURO Symposium (University of Georgia)",
                    "https://curo.uga.edu/symposium/",
                    "The annual CURO Symposium showcases excellence in "
                    "undergraduate research at UGA, giving students from every "
                    "discipline a venue to present their faculty-mentored "
                    "research through oral and poster sessions to the campus "
                    "and wider community.",
                    lab_or_program="Center for Undergraduate Research Opportunities",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research symposium", "poster session",
                              "oral presentation", "showcase"],
                ),
                program(
                    "uga_foundation_fellowship",
                    "Morehead Honors College Foundation Fellowship (University of Georgia)",
                    "https://honors.uga.edu/foundation-fellowship/",
                    "The Foundation Fellowship is UGA's premier undergraduate "
                    "scholarship, administered by the Morehead Honors College. "
                    "It combines a substantial stipend with dedicated travel "
                    "and research funding, faculty mentorship, and enrichment "
                    "programming for exceptional incoming students.",
                    lab_or_program="Morehead Honors College",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["Foundation Fellowship", "honors", "research funding",
                              "merit scholarship"],
                ),
                program(
                    "uga_office_of_research",
                    "UGA Office of Research",
                    "https://research.uga.edu/",
                    "The Office of Research facilitates instruction, scholarly "
                    "and creative activity, and cross-disciplinary research "
                    "collaborations across the University of Georgia, "
                    "administering research units, centers, and institutes "
                    "that host undergraduate researchers.",
                    lab_or_program="Office of Research",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    keywords=["research office", "centers and institutes",
                              "interdisciplinary research"],
                ),
            ],
        },
    ],
}
