"""Cornell University campus opportunity-graph config.

Curated seed records of Cornell's undergraduate-research landscape: the
Cornell Undergraduate Research Board (CURB) hub, the College of Arts &
Sciences undergraduate-research portal (Nexus Scholars), the university's
Research & Innovation office, and Engineering Learning Initiatives (ELI).
URLs verified live (HTTP 200) on 2026-07-12.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → cornell_research_programs (cornell / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "cornell",
    "organization": "Cornell University",
    "location": "Ithaca, NY",
    "emit": {
        "campus": ("cornell_research_programs", "cornell", "campus"),
    },
    "sources": [
        {
            "source_name": "cornell_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://curb.cornell.edu/",
                "https://as.cornell.edu/undergraduate-research",
                "https://research-and-innovation.cornell.edu/",
                "https://www.engineering.cornell.edu/students/eli",
            ],
            "programs": [
                program(
                    "curb",
                    "Cornell Undergraduate Research Board (CURB)",
                    "https://curb.cornell.edu/",
                    "CURB is Cornell's student-run hub for undergraduate research: it "
                    "connects students across every college to faculty labs, runs the "
                    "annual Spring Research Forum and Fall Research Night, maintains a "
                    "searchable list of research opportunities and summer programs, and "
                    "administers Research Grants that fund undergraduate projects. Start "
                    "here to find a lab or a funding source in any field.",
                    lab_or_program="Cornell Undergraduate Research Board",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship", "research funding"],
                ),
                program(
                    "nexus_scholars",
                    "Nexus Scholars Program — Summer Research (Arts & Sciences, Cornell)",
                    "https://as.cornell.edu/undergraduate-research",
                    "The College of Arts & Sciences Nexus Scholars Program places "
                    "undergraduates in an 8-week paid summer research project working "
                    "directly with an A&S faculty member across the humanities, social "
                    "sciences, and natural sciences. The A&S undergraduate-research "
                    "portal also lists course-credit research, honors theses, and "
                    "department research funds.",
                    lab_or_program="Nexus Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "arts and sciences"],
                ),
                program(
                    "research_innovation",
                    "Cornell Research & Innovation — University Research Office",
                    "https://research-and-innovation.cornell.edu/",
                    "The office of Cornell's Vice President for Research & Innovation is "
                    "the front door to the university's research centers, institutes, "
                    "and core facilities. Browse centers and facilities by theme to find "
                    "a research group whose work matches your interests, then reach out "
                    "about undergraduate involvement.",
                    lab_or_program="Cornell Research & Innovation",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research centers", "institutes"],
                ),
                program(
                    "engineering_eli",
                    "Engineering Learning Initiatives (ELI) — Undergraduate Research (Cornell)",
                    "https://www.engineering.cornell.edu/students/eli",
                    "Engineering Learning Initiatives funds and supports undergraduate "
                    "research in the College of Engineering: semester and summer research "
                    "grants, the Engineering Undergraduate Research Programs, research "
                    "travel funding, and Maximizing Access to Research Careers. Open to "
                    "Cornell Engineering undergraduates working with a faculty mentor.",
                    lab_or_program="Engineering Learning Initiatives",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["engineering research", "research grant"],
                ),
            ],
        },
    ],
}
