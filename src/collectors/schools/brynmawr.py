"""Bryn Mawr College campus opportunity-graph config.

Curated seed records of Bryn Mawr's undergraduate-research and funded
experiential-learning landscape, centered on the college's two flagship summer
research programs — Summer Science Research (SSR, STEM) and the Humanities and
Social Science Summer Research program — together with the Mellon Mays
Undergraduate Fellowship (a founding-member program at Bryn Mawr), the STEM
Liberal Arts (STEMLA) Fellows program, the Praxis community-engaged learning
program, the Career & Civic Engagement Center summer funding awards, the
Sponsored Research Office, and Global Engagement fellowships advising. URLs
curl-verified live (HTTP 200) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → brynmawr_research_programs (brynmawr / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_RES = "https://www.brynmawr.edu/inside/academic-information/research"
_CCEC = "https://www.brynmawr.edu/inside/offices-services/career-civic-engagement-center"

SCHOOL: dict = {
    "school_slug": "brynmawr",
    "organization": "Bryn Mawr College",
    "location": "Bryn Mawr, PA",
    "emit": {
        "campus": ("brynmawr_research_programs", "brynmawr", "campus"),
    },
    "sources": [
        {
            "source_name": "brynmawr_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _RES,
                "https://www.brynmawr.edu/academics/student-research",
            ],
            "programs": [
                program(
                    "brynmawr_ssr",
                    "Summer Science Research (SSR) (Bryn Mawr)",
                    f"{_RES}/summer-science-research",
                    "Bryn Mawr's flagship STEM summer program: students receive "
                    "a $5,000 stipend to conduct ten weeks of independent "
                    "research under the mentorship of science and mathematics "
                    "faculty, enriched by professional-development workshops, a "
                    "speaker series, and a culminating poster session.",
                    lab_or_program="Summer Science Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,000 stipend for 10 weeks",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "STEM", "faculty mentor",
                              "stipend"],
                ),
                program(
                    "brynmawr_hssr",
                    "Humanities and Social Science Summer Research (Bryn Mawr)",
                    f"{_RES}/humanitiessocial-science-summer-program",
                    "A funded summer research program supporting student "
                    "research and project opportunities in humanities and "
                    "social-science fields, pairing students with faculty "
                    "mentors who supervise the work over the summer.",
                    lab_or_program="Humanities and Social Science Summer Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "humanities", "social science",
                              "faculty mentor"],
                ),
                program(
                    "brynmawr_mmuf",
                    "Mellon Mays Undergraduate Fellowship (MMUF) (Bryn Mawr)",
                    f"{_RES}/mellon-mays-undergraduate-fellowship",
                    "A founding-member Mellon Foundation fellowship at Bryn Mawr "
                    "(five juniors and five seniors each year) that provides "
                    "mentorship, research support, and a scholarly community for "
                    "students in the humanities and humanistic social sciences "
                    "who are preparing for PhD study and careers in the academy.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["Mellon Mays", "humanities", "PhD pathway",
                              "research mentorship"],
                ),
                program(
                    "brynmawr_stemla",
                    "STEM Liberal Arts (STEMLA) Fellows Program (Bryn Mawr)",
                    "https://www.brynmawr.edu/inside/academic-information/"
                    "special-academic-programs/stem-liberal-arts-fellows-program",
                    "A cohort program supporting first-generation and "
                    "limited-income Bryn Mawr students in STEM through "
                    "mentorship, community, research exploration, and "
                    "comprehensive academic support along the path to STEM "
                    "careers and graduate study.",
                    lab_or_program="STEM Liberal Arts Fellows",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["STEM", "first-generation", "mentorship",
                              "research pathway"],
                ),
                program(
                    "brynmawr_praxis",
                    "Praxis Community-Engaged Learning (Bryn Mawr)",
                    f"{_CCEC}/experiential-learning/academic-connections-praxis",
                    "Praxis is Bryn Mawr's curricular, experiential, and "
                    "community-engaged learning program, integrating academic "
                    "theory with hands-on practice through fieldwork placements "
                    "and collaboration with community partners as part of "
                    "credit-bearing courses.",
                    lab_or_program="Praxis Program",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["experiential learning", "community-engaged",
                              "fieldwork", "praxis"],
                ),
                program(
                    "brynmawr_ccec_funding",
                    "Career & Civic Engagement Summer Funding (Bryn Mawr)",
                    f"{_CCEC}/funding-opportunities",
                    "Need-based funding awarded by the Career & Civic Engagement "
                    "Center to eligible students to support an otherwise unpaid "
                    "summer internship or research project, making experiential "
                    "opportunities financially accessible.",
                    lab_or_program="CCEC Summer Funding",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer funding", "internship", "research",
                              "stipend"],
                ),
                program(
                    "brynmawr_sro",
                    "Sponsored Research Office (Bryn Mawr)",
                    f"{_RES}/sponsored-research-office",
                    "The Sponsored Research Office helps Bryn Mawr students and "
                    "faculty find and manage external funding for research and "
                    "scholarly projects, providing grant-search support and "
                    "administration for funded research across disciplines.",
                    lab_or_program="Sponsored Research Office",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research funding", "grants", "sponsored research",
                              "faculty mentor"],
                ),
                program(
                    "brynmawr_global_fellowships",
                    "Global Engagement Fellowships (Bryn Mawr)",
                    "https://www.brynmawr.edu/inside/offices-services/"
                    "global-engagement/fellowships",
                    "Advising and support for nationally competitive "
                    "fellowships and scholarships (Fulbright, Watson, and "
                    "others) through Bryn Mawr's Global Engagement office, "
                    "guiding students toward funded research, study, and "
                    "project awards abroad and in the US.",
                    lab_or_program="Global Engagement Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["national fellowships", "Fulbright", "Watson",
                              "funded research"],
                ),
            ],
        },
    ],
}
