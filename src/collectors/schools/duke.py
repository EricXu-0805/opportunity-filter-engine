"""Duke University campus opportunity-graph config (US-News rollout).

Curated seed of Duke's undergraduate-research landscape: the Undergraduate
Research Support Office (URS) hub, the signature interdisciplinary programs
(Bass Connections, Data+), the Career Center, and a couple of research
institutes. URLs verified against duke.edu (Jul 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> duke_research_programs (duke / campus)
    open   -> duke_external_research (national / open)
    lab    -> duke_labs              (duke / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    LAB,
    PROGRAM,
    RECURSIVE,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "duke",
    "organization": "Duke University",
    "location": "Durham, NC",
    "emit": {
        "campus": ("duke_research_programs", "duke", "campus"),
        "open": ("duke_external_research", None, "open"),
        "lab": ("duke_labs", "duke", "unknown"),
    },
    "sources": [
        {
            "source_name": "duke_urs_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": ["https://undergraduateresearch.duke.edu/"],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "urs_hub",
                    "Undergraduate Research Support Office (URS) — Hub (Duke)",
                    "https://undergraduateresearch.duke.edu/",
                    "Duke's central office for undergraduate research: independent-study "
                    "grants, summer research fellowships, conference travel awards, and "
                    "faculty-mentor matching across all schools. Start here to find a "
                    "program by class year and field.",
                    lab_or_program="Undergraduate Research Support",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship", "research grant"],
                ),
            ],
        },
        {
            "source_name": "duke_signature_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://bassconnections.duke.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "bass_connections",
                    "Bass Connections — Interdisciplinary Research Teams (Duke)",
                    "https://bassconnections.duke.edu/",
                    "Year-long interdisciplinary research teams pairing undergraduates, "
                    "graduate students, and faculty on real-world problems across five "
                    "themes (Brain & Society, Energy, Global Health, Information & "
                    "Society, Race & Society). Paid summer extensions available.",
                    lab_or_program="Bass Connections",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["interdisciplinary research", "team science"],
                ),
                program(
                    "data_plus",
                    "Data+ — Summer Data Research (Duke)",
                    "https://bigdata.duke.edu/data-summer-program/",
                    "A 10-week summer program where undergraduates work in small teams on "
                    "data-driven research projects with faculty and graduate mentors. Pays "
                    "a stipend; open to Duke students from any major.",
                    lab_or_program="Data+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Data Science", "Statistics", "Computer Science"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["data science", "summer research", "stipend"],
                ),
            ],
        },
        {
            "source_name": "duke_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://careerhub.students.duke.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center",
                    "Duke Career Center — Internships & Research",
                    "https://careerhub.students.duke.edu/",
                    "Duke's Career Center connects undergraduates to internships, research "
                    "assistantships, and funded summer experiences, with advising and the "
                    "campus job board. Open to all class years and majors.",
                    organization="Duke Career Center",
                    lab_or_program="Career Center",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "research assistant"],
                ),
            ],
        },
        {
            "source_name": "duke_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": ["https://nicholas.duke.edu/"],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "nicholas_environment",
                    "Nicholas School of the Environment — Undergraduate Research (Duke)",
                    "https://nicholas.duke.edu/",
                    "The Nicholas School hosts undergraduate research in environmental "
                    "science, ecology, climate, and marine science (including the Duke "
                    "Marine Lab), a strong cold-email target for field and lab placements.",
                    department="Nicholas School of the Environment",
                    lab_or_program="Nicholas School",
                    eligibility_majors=["Environmental Science", "Ecology", "Marine Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["environment", "ecology", "climate", "marine science"],
                ),
            ],
        },
    ],
}
