"""Vanderbilt University campus opportunity-graph config.

Curated seed records of Vanderbilt's undergraduate-research landscape: the
Office of Undergraduate Research (URO), the Vanderbilt Undergraduate Summer
Research Program (VUSRP), the URO summer-programs directory, Immersion
Vanderbilt, and the Chancellor's Scholars. URLs verified live (HTTP 200) on
2026-07-13.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → vanderbilt_research_programs (vanderbilt / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "vanderbilt",
    "organization": "Vanderbilt University",
    "location": "Nashville, TN",
    "emit": {
        "campus": ("vanderbilt_research_programs", "vanderbilt", "campus"),
    },
    "sources": [
        {
            "source_name": "vanderbilt_uro_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.vanderbilt.edu/undergraduate-research/",
                "https://www.vanderbilt.edu/immersion/vusrp/",
                "https://www.vanderbilt.edu/undergraduate-research/getting-started/summer-research-programs/",
                "https://www.vanderbilt.edu/immersion/",
                "https://www.vanderbilt.edu/scholarships/chancellor/",
            ],
            "programs": [
                program(
                    "uro_hub",
                    "Office of Undergraduate Research (URO) — Hub (Vanderbilt)",
                    "https://www.vanderbilt.edu/undergraduate-research/",
                    "Vanderbilt's Office of Undergraduate Research is the front door to "
                    "faculty-mentored research for every major: it runs the Vanderbilt "
                    "Undergraduate Summer Research Program (VUSRP), maintains a summer "
                    "research-program directory, and advises on finding a lab and "
                    "funding. Start here to get matched to a faculty mentor.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
                program(
                    "vusrp",
                    "Vanderbilt Undergraduate Summer Research Program (VUSRP)",
                    "https://www.vanderbilt.edu/immersion/vusrp/",
                    "VUSRP funds a full-time summer of faculty-mentored research with a "
                    "stipend, culminating in a summer research symposium. Open across "
                    "disciplines; students apply with a Vanderbilt faculty mentor and it "
                    "can anchor the Immersion Vanderbilt experience.",
                    lab_or_program="Vanderbilt Undergraduate Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "stipend"],
                ),
                program(
                    "uro_summer_directory",
                    "URO Summer Research Programs Directory (Vanderbilt)",
                    "https://www.vanderbilt.edu/undergraduate-research/getting-started/summer-research-programs/",
                    "A curated directory of summer research programs open to Vanderbilt "
                    "undergraduates — on-campus labs, VUSRP, and external REUs — with "
                    "guidance on eligibility and deadlines by field.",
                    lab_or_program="URO Summer Research Directory",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "REU"],
                ),
                program(
                    "immersion",
                    "Immersion Vanderbilt — Research Path",
                    "https://www.vanderbilt.edu/immersion/",
                    "Immersion Vanderbilt is the university's required experiential-"
                    "learning program; the research path pairs a student with a faculty "
                    "mentor for a sustained project and a culminating creative/research "
                    "product. A structured on-ramp into a Vanderbilt lab for any major.",
                    lab_or_program="Immersion Vanderbilt",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["experiential learning", "faculty mentorship"],
                ),
                program(
                    "chancellors_scholars",
                    "Chancellor's Scholars — Research Scholarship (Vanderbilt)",
                    "https://www.vanderbilt.edu/scholarships/chancellor/",
                    "A merit scholarship that includes dedicated undergraduate-research "
                    "funding and faculty mentorship, supporting scholars in pursuing "
                    "independent research across their time at Vanderbilt.",
                    lab_or_program="Chancellor's Scholars",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research scholarship", "mentorship"],
                ),
            ],
        },
    ],
}
