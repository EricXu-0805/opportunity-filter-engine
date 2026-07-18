"""University of Maryland, College Park campus opportunity-graph config.

Curated seed records of UMD's undergraduate-research landscape, centered on
the Office of Undergraduate Research (OUR) and its programs (VIP, plus the
ForagerOne matching platform it runs), the FIRE first-year research streams,
the Gemstone four-year team-research honors program, the CS-run REU-CAAR
summer program, and the College Park Scholars / Honors College living-learning
entry points. URLs verified live (HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → umd_research_programs (umd / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "umd",
    "organization": "University of Maryland, College Park",
    "location": "College Park, MD",
    "emit": {
        "campus": ("umd_research_programs", "umd", "campus"),
    },
    "sources": [
        {
            "source_name": "umd_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://our.umd.edu/",
                "https://fire.umd.edu/",
                "https://gemstone.umd.edu/",
            ],
            "programs": [
                program(
                    "our_office",
                    "Office of Undergraduate Research (OUR) — University of Maryland",
                    "https://our.umd.edu/",
                    "The Office of Undergraduate Research empowers UMD "
                    "undergraduates of all experience levels to engage and "
                    "succeed in shared inquiry, creative activity, and "
                    "scholarship. It runs ForagerOne, a continually available "
                    "platform matching students to campus research "
                    "opportunities by shared interests, and maintains databases "
                    "of opportunities within the University System of Maryland, "
                    "across the US, and abroad. It also hosts Undergraduate "
                    "Research Day and an annual Summer Undergraduate Research "
                    "Conference, and publishes guidance on cold-emailing "
                    "faculty.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research matching",
                              "ForagerOne", "research conference"],
                ),
                program(
                    "vip_teams",
                    "Vertically Integrated Projects (VIP) — University of Maryland",
                    "https://our.umd.edu/vip",
                    "VIP gives UMD students of all backgrounds, disciplines, "
                    "and levels of experience the opportunity to engage in "
                    "scaffolded, multidisciplinary team-based research "
                    "projects. Teams accept applications on a semester cycle "
                    "(Fall/Spring). Run through the Office of Undergraduate "
                    "Research.",
                    lab_or_program="Vertically Integrated Projects",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["team research", "multidisciplinary",
                              "vertically integrated projects",
                              "credit-bearing research"],
                ),
                program(
                    "fire_streams",
                    "FIRE — First-Year Innovation & Research Experience (UMD)",
                    "https://fire.umd.edu/",
                    "FIRE provides first-year UMD students with a "
                    "faculty-mentored research experience that drives "
                    "accelerated career readiness and opportunity. Students "
                    "work with authentic tools of the trade in themed research "
                    "streams; entry is via invitation with an open application "
                    "path for non-invited and spring-admit students.",
                    lab_or_program="FIRE",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["first-year research", "faculty-mentored",
                              "research streams", "career readiness"],
                ),
                program(
                    "gemstone_honors",
                    "Gemstone Honors Program (UMD)",
                    "https://gemstone.umd.edu/",
                    "Gemstone is a multidisciplinary four-year team research "
                    "program for selected undergraduate honors students of all "
                    "majors, now in its fourth decade. Student teams pursue a "
                    "shared research question across their degree, culminating "
                    "in a team thesis.",
                    lab_or_program="Gemstone Honors Program",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["honors", "team research", "four-year thesis",
                              "multidisciplinary"],
                ),
                program(
                    "reu_caar",
                    "REU-CAAR: Combinatorics, Algorithms, and AI for Real Problems (UMD)",
                    "https://www.cs.umd.edu/projects/reucaar/",
                    "A summer Research Experience for Undergraduates run by UMD "
                    "Computer Science on combinatorics, algorithms, and AI "
                    "applied to real problems. The site lists project topics, "
                    "mentors, and prior cohorts with outcomes (papers, alumni "
                    "placements); it recruits nationally, so non-UMD students "
                    "can apply too. Admissions for the current cycle were "
                    "marked closed at time of check.",
                    lab_or_program="REU-CAAR",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["REU", "algorithms", "combinatorics",
                              "artificial intelligence", "summer research"],
                ),
                program(
                    "college_park_scholars",
                    "College Park Scholars (UMD)",
                    "https://scholars.umd.edu/",
                    "College Park Scholars is a nationally acclaimed two-year "
                    "living-learning program for incoming students, organized "
                    "into themed programs. It advertises the attention of a "
                    "small college combined with the opportunities of a "
                    "cutting-edge research university.",
                    lab_or_program="College Park Scholars",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["living-learning", "themed programs", "community"],
                ),
                program(
                    "honors_college",
                    "University of Maryland Honors College",
                    "https://honors.umd.edu/",
                    "The Honors College serves students with exceptional "
                    "academic talents in a close-knit community committed to a "
                    "broad and balanced education. It comprises multiple honors "
                    "living-learning programs, several of which are "
                    "research-focused.",
                    lab_or_program="Honors College",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["honors", "selective admission", "living-learning",
                              "research clusters"],
                ),
            ],
        },
    ],
}
