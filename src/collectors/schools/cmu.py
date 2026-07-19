"""Carnegie Mellon University campus opportunity-graph config.

Curated seed records of CMU's undergraduate-research landscape, centered on
the Undergraduate Research Office (URO) and its funding programs — SURG
(academic-year small grants), the Summer Undergraduate Research Fellowships,
HURAY (paid hourly research apprenticeships for first- and second-years),
and ISURG for international summer research. URLs verified live (HTTP 200)
on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → cmu_research_programs (cmu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "cmu",
    "organization": "Carnegie Mellon University",
    "location": "Pittsburgh, PA",
    "emit": {
        "campus": ("cmu_research_programs", "cmu", "campus"),
    },
    "sources": [
        {
            "source_name": "cmu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.cmu.edu/uro/",
            ],
            "programs": [
                program(
                    "uro_hub",
                    "CMU Undergraduate Research Office (URO)",
                    "https://www.cmu.edu/uro/",
                    "The Undergraduate Research Office is CMU's central hub for "
                    "getting into research: it advises students on finding a "
                    "faculty mentor, runs the getting-started workshops, and "
                    "administers the university's research grants and summer "
                    "fellowships below — open to undergraduates in every "
                    "college.",
                    lab_or_program="Undergraduate Research Office",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research funding",
                              "faculty mentorship"],
                ),
                program(
                    "surg",
                    "SURG — Small Undergraduate Research Grants (CMU)",
                    "https://www.cmu.edu/uro/academic-research/SURG/index.html",
                    "SURG funds student-designed research projects during the "
                    "academic year — up to $1,000 for materials and expenses "
                    "(more for group projects), with proposals reviewed each "
                    "semester. Any CMU undergraduate in any discipline can "
                    "apply with a faculty advisor.",
                    lab_or_program="SURG",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Up to $1,000 per project (more for groups)",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grants", "student-designed research"],
                ),
                program(
                    "surf",
                    "CMU Summer Undergraduate Research Fellowships",
                    "https://www.cmu.edu/uro/summer%20research%20fellowships/",
                    "URO's summer fellowships fund CMU undergraduates to spend "
                    "the summer on full-time research with a faculty mentor — "
                    "a stipend in place of a summer job so students can commit "
                    "to a research project in any field, from engineering to "
                    "the humanities.",
                    lab_or_program="Summer Undergraduate Research Fellowship",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "fellowship", "stipend"],
                ),
                program(
                    "huray",
                    "HURAY — Hourly Undergraduate Research Apprenticeships (CMU)",
                    "https://www.cmu.edu/uro/academic-research/huray/index.html",
                    "HURAY pays first- and second-year students an hourly wage "
                    "to apprentice in a faculty member's research group during "
                    "the academic year — an entry route into research designed "
                    "for students with no prior experience, matched through "
                    "participating faculty projects.",
                    lab_or_program="HURAY",
                    opportunity_type="research",
                    paid="yes",
                    compensation="Hourly research apprenticeship wage",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["research apprenticeship", "paid research",
                              "early research experience"],
                ),
                program(
                    "isurg",
                    "ISURG — International Small Undergraduate Research Grants (CMU)",
                    "https://www.cmu.edu/uro/academic-research/isurg/index.html",
                    "ISURG extends CMU's undergraduate research grants to "
                    "projects with an international dimension — funding travel "
                    "and expenses for student research conducted abroad or in "
                    "collaboration with international partners, with a faculty "
                    "advisor's sponsorship.",
                    lab_or_program="ISURG",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["international research", "research grants"],
                ),
                program(
                    "uro_getting_started",
                    "Getting Started in Research at CMU",
                    "https://www.cmu.edu/uro/getting-started-in-research/index.html",
                    "URO's structured on-ramp for students new to research: how "
                    "to identify faculty whose work matches your interests, "
                    "write the first outreach email, and choose between "
                    "for-credit, paid, and grant-funded research routes at CMU.",
                    lab_or_program="Undergraduate Research Office",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["getting started", "finding a mentor"],
                ),
            ],
        },
    ],
}
