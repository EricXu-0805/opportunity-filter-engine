"""Rice University campus opportunity-graph config.

Curated seed records of Rice's undergraduate-research landscape, centered on the
Office of Undergraduate Research & Inquiry (OURI): the OURI hub, the Rice
Undergraduate Scholars Program (RUSP), the Summer Undergraduate Research
Fellowship (SURF), Century Scholars, and the Rice Emerging Scholars Program.
URLs verified live (HTTP 200) on 2026-07-13.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → rice_research_programs (rice / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "rice",
    "organization": "Rice University",
    "location": "Houston, TX",
    "emit": {
        "campus": ("rice_research_programs", "rice", "campus"),
    },
    "sources": [
        {
            "source_name": "rice_ouri_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ouri.rice.edu/",
                "https://ouri.rice.edu/research-programs/rusp",
                "https://ouri.rice.edu/research-programs/surf",
                "https://ouri.rice.edu/research-programs/century-scholars",
                "https://success.rice.edu/rice-emerging-scholars-program",
            ],
            "programs": [
                program(
                    "ouri_hub",
                    "Office of Undergraduate Research & Inquiry (OURI) — Hub (Rice)",
                    "https://ouri.rice.edu/",
                    "OURI is Rice's front door to undergraduate research: it runs the "
                    "Rice Undergraduate Scholars Program (RUSP), Summer Undergraduate "
                    "Research Fellowships (SURF), Century Scholars, and the Inquiry "
                    "Weeks research symposium, and helps students of any major find a "
                    "faculty mentor and funding. Start here to get matched to a lab.",
                    lab_or_program="Office of Undergraduate Research & Inquiry",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
                program(
                    "rusp",
                    "Rice Undergraduate Scholars Program (RUSP)",
                    "https://ouri.rice.edu/research-programs/rusp",
                    "RUSP is a year-long, faculty-mentored independent-research program "
                    "culminating in a thesis and the Rice Undergraduate Research "
                    "Symposium. Open across disciplines; students propose a project with "
                    "a Rice faculty mentor.",
                    lab_or_program="Rice Undergraduate Scholars Program",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    keywords=["independent research", "thesis"],
                ),
                program(
                    "surf",
                    "Summer Undergraduate Research Fellowship (SURF) — Rice",
                    "https://ouri.rice.edu/research-programs/surf",
                    "SURF funds a full-time 10-week summer research project with a Rice "
                    "faculty mentor across the sciences, engineering, social sciences, "
                    "and humanities, with a stipend. Culminates in the summer research "
                    "colloquium.",
                    lab_or_program="Summer Undergraduate Research Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "stipend"],
                ),
                program(
                    "century_scholars",
                    "Century Scholars — Early Undergraduate Research (Rice)",
                    "https://ouri.rice.edu/research-programs/century-scholars",
                    "Century Scholars pairs first- and second-year students with a "
                    "faculty mentor for a two-year research relationship plus a research "
                    "stipend — an early on-ramp into a Rice lab.",
                    lab_or_program="Century Scholars",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["early research", "mentorship"],
                ),
                program(
                    "resp",
                    "Rice Emerging Scholars Program (RESP)",
                    "https://success.rice.edu/rice-emerging-scholars-program",
                    "RESP is an intensive summer-bridge + academic-year program for "
                    "students entering the sciences and engineering, including a paid "
                    "summer research/coursework component that builds a path into "
                    "faculty research.",
                    lab_or_program="Rice Emerging Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Natural Sciences", "Engineering"],
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    keywords=["summer bridge", "STEM research"],
                ),
            ],
        },
    ],
}
