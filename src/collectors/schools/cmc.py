"""Claremont McKenna College campus opportunity-graph config.

Curated seed records of CMC's undergraduate research-and-funding landscape: the
Sponsored Internships & Experiences (SIE) program that funds student
internships, the Fellowships & National Awards office, and CMC's cluster of
faculty-directed research institutes that hire undergraduate research
assistants — the Lowe Institute of Political Economy, the Financial Economics
Institute, the Rose Institute of State and Local Government, the Berger
Institute for Individual and Social Development, the Salvatori Center, the
Kravis Leadership Institute, the Roberts Environmental Center, and the Randall
Lewis Center for Innovation and Entrepreneurship. URLs curl-verified live
(HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → cmc_research_programs (cmc / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "cmc",
    "organization": "Claremont McKenna College",
    "location": "Claremont, CA",
    "emit": {
        "campus": ("cmc_research_programs", "cmc", "campus"),
    },
    "sources": [
        {
            "source_name": "cmc_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.cmc.edu/soll-center/sie-program",
                "https://www.cmc.edu/fellowships",
            ],
            "programs": [
                program(
                    "cmc_sie",
                    "Sponsored Internships & Experiences (SIE) Program (CMC)",
                    "https://www.cmc.edu/soll-center/sie-program",
                    "The Soll Center for Student Opportunity's SIE program "
                    "provides CMC students with college funding to pursue "
                    "otherwise-unpaid internships and hands-on experiences — "
                    "including research placements — during the summer and "
                    "academic year, so students can take substantive positions "
                    "regardless of whether the host site pays.",
                    lab_or_program="Soll Center for Student Opportunity",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["funded internship", "summer experience",
                              "career development", "stipend"],
                ),
                program(
                    "cmc_fellowships",
                    "Fellowships and National Awards (CMC)",
                    "https://www.cmc.edu/fellowships",
                    "CMC's Fellowships office advises students and alumni "
                    "pursuing nationally competitive scholarships and research "
                    "fellowships (Fulbright, Goldwater, Watson, and similar), "
                    "many of which fund independent or faculty-mentored "
                    "research projects.",
                    lab_or_program="Fellowships & National Awards",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["national fellowships", "scholarships",
                              "research funding", "Fulbright"],
                ),
                program(
                    "cmc_lowe",
                    "Lowe Institute of Political Economy (CMC)",
                    "https://www.cmc.edu/lowe-institute",
                    "A non-partisan economics research institute at CMC that "
                    "employs undergraduate research assistants on applied "
                    "political-economy projects, regional economic forecasting, "
                    "and faculty-led studies.",
                    lab_or_program="Lowe Institute of Political Economy",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["economics", "political economy",
                              "economic forecasting", "research assistant"],
                ),
                program(
                    "cmc_fei",
                    "Financial Economics Institute (CMC)",
                    "https://www.cmc.edu/financial-economics-institute",
                    "Founded in 2004, the FEI provides opportunities for "
                    "students interested in finance and related areas to "
                    "develop research skills and engage with faculty on "
                    "financial-economics research, supported by student "
                    "research assistantships and data resources.",
                    lab_or_program="Financial Economics Institute",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["finance", "financial economics",
                              "quantitative research", "research assistant"],
                ),
                program(
                    "cmc_rose",
                    "Rose Institute of State and Local Government (CMC)",
                    "https://www.cmc.edu/rose-institute",
                    "A leader in non-partisan political and policy research in "
                    "California, the Rose Institute hires undergraduate student "
                    "researchers to work on survey research, redistricting and "
                    "demographic analysis, and state-and-local governance "
                    "studies alongside faculty.",
                    lab_or_program="Rose Institute of State and Local Government",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["policy research", "political science",
                              "survey research", "research assistant"],
                ),
                program(
                    "cmc_berger",
                    "Berger Institute for Individual and Social Development (CMC)",
                    "https://www.cmc.edu/berger-institute",
                    "An interdisciplinary center for research and co-curricular "
                    "programming on human development and well-being; the "
                    "Institute produces high-quality social-science research "
                    "and engages undergraduates as research assistants on "
                    "projects spanning psychology, work-family issues, and "
                    "social development.",
                    lab_or_program="Berger Institute",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["human development", "psychology",
                              "social science", "research assistant"],
                ),
                program(
                    "cmc_salvatori",
                    "Salvatori Center for the Study of Individual Freedom (CMC)",
                    "https://www.cmc.edu/salvatori-center",
                    "The oldest research institute at CMC, the Henry Salvatori "
                    "Center advances the study of freedom, democracy, and "
                    "American constitutionalism, supporting student research "
                    "assistants and research fellowships in political theory "
                    "and constitutional government.",
                    lab_or_program="Salvatori Center",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["political theory", "constitutionalism",
                              "democracy", "research fellowship"],
                ),
                program(
                    "cmc_kli",
                    "Kravis Leadership Institute (CMC)",
                    "https://www.cmc.edu/kli",
                    "The Kravis Leadership Institute conducts research on "
                    "leadership and social innovation and engages "
                    "undergraduates as student research assistants and fellows, "
                    "including work on its Leadership Studies scholarship.",
                    lab_or_program="Kravis Leadership Institute",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["leadership", "social innovation",
                              "leadership studies", "research assistant"],
                ),
                program(
                    "cmc_rec",
                    "Roberts Environmental Center (CMC)",
                    "https://www.cmc.edu/roberts-environmental-center",
                    "A student-driven environmental research center at CMC "
                    "where undergraduates conduct analysis of corporate and "
                    "institutional sustainability performance and produce "
                    "published environmental reports under faculty direction.",
                    lab_or_program="Roberts Environmental Center",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["environmental analysis", "sustainability",
                              "corporate reporting", "student research"],
                ),
                program(
                    "cmc_rlcie",
                    "Randall Lewis Center for Innovation and Entrepreneurship (CMC)",
                    "https://www.cmc.edu/rlcie",
                    "The Randall Lewis Center supports student innovation and "
                    "entrepreneurship through funded projects, venture "
                    "incubation, and experiential programs that pair students "
                    "with mentors on applied entrepreneurial work.",
                    lab_or_program="Randall Lewis Center for Innovation and Entrepreneurship",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["entrepreneurship", "innovation",
                              "startups", "experiential learning"],
                ),
            ],
        },
    ],
}
