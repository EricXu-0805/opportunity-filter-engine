"""Williams College campus opportunity-graph config.

Curated seed records of Williams' undergraduate summer-research and fellowship
landscape. Williams runs one of the largest liberal-arts summer research
programs in the country (~200 students on campus each summer), split across the
Science Center (Summer Science Research), the Mathematics department's flagship
SMALL REU, the Class of 1957 program for the humanities & social sciences, and
the Pathways / Fellowships offices. URLs are the canonical program pages
surfaced in the public Williams web index (the whole williams.edu site sits
behind Cloudflare, so program metadata is curated rather than crawled).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> williams_research_programs (williams / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "williams",
    "organization": "Williams College",
    "location": "Williamstown, MA",
    "emit": {
        "campus": ("williams_research_programs", "williams", "campus"),
    },
    "sources": [
        {
            "source_name": "williams_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.williams.edu/summer-opportunities/",
                "https://science.williams.edu/summer-programs/",
                "https://www.williams.edu/academics/undergraduate-study/undergraduate-research/",
            ],
            "programs": [
                program(
                    "ssr",
                    "Williams Summer Science Research (SSR)",
                    "https://science.williams.edu/summer-programs/",
                    "The Science Center's Summer Science Research program places "
                    "roughly 200 undergraduates on campus each summer to work "
                    "intensively, full-time, on faculty-directed research projects "
                    "across biology, chemistry, physics, astronomy, geosciences, "
                    "computer science, math, psychology and neuroscience. Students "
                    "live on campus, receive a stipend and housing, and present "
                    "their work at a summer poster session.",
                    lab_or_program="Summer Science Research",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=[
                        "Biology", "Chemistry", "Physics", "Astronomy", "Geosciences",
                        "Computer Science", "Mathematics", "Psychology", "Neuroscience",
                    ],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer research", "STEM", "faculty-mentored research"],
                ),
                program(
                    "small_reu",
                    "SMALL Undergraduate Research Project (NSF REU in Mathematics)",
                    "https://math.williams.edu/small/",
                    "SMALL is a nine-week residential summer REU in which "
                    "undergraduates from Williams and other institutions "
                    "investigate open problems in mathematics and statistics in "
                    "small faculty-led groups. One of the largest programs of its "
                    "kind in the U.S. (NSF-funded since 1988), it carries a stipend "
                    "of about $4,000 plus housing; many groups publish and present "
                    "at national conferences.",
                    lab_or_program="SMALL REU",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="~$4,000 stipend plus housing (9 weeks)",
                    eligibility_majors=["Mathematics", "Statistics"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["mathematics", "REU", "summer research"],
                ),
                program(
                    "class_of_1957",
                    "Class of 1957 Summer Research Program (Humanities & Social Sciences)",
                    "https://www.williams.edu/summer-opportunities/category/fellowships/",
                    "The Class of 1957 Summer Research Program funds Division I & II "
                    "faculty to hire eligible students as full-time, on-campus "
                    "research assistants for up to ten weeks, building the "
                    "humanities and social-science counterpart to the Science "
                    "Center's summer program. Students collaborate directly on a "
                    "professor's scholarly project and receive a summer stipend.",
                    lab_or_program="Class of 1957 Summer Research",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=[
                        "History", "Economics", "Political Science", "English",
                        "Philosophy", "Art History", "Anthropology", "Sociology",
                    ],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["humanities research", "social science research",
                              "research assistantship"],
                ),
                program(
                    "shss",
                    "Summer Humanities and Social Sciences Program (SHSS)",
                    "https://diversity.williams.edu/pathways/shss/",
                    "SHSS is a five-week residential program for incoming first-year "
                    "students with a passion for the humanities or social sciences "
                    "(first-generation students especially encouraged). Students "
                    "take classes with Williams professors, are matched with faculty "
                    "advisors, and are introduced to research and writing "
                    "opportunities; the College covers room, board, and travel and "
                    "provides a stipend.",
                    lab_or_program="SHSS",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Room, board, travel, and a $300 stipend (5 weeks)",
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    keywords=["humanities", "social sciences", "first-year program"],
                ),
                program(
                    "adrf",
                    "Allison Davis Research Fellowship (ADRF)",
                    "https://diversity.williams.edu/pathways/fellowships/",
                    "Administered by the Pathways for Inclusive Excellence office, "
                    "the Allison Davis Research Fellowship supports students of "
                    "color, first-generation students, and eligible international "
                    "students in carrying out ten-week independent, "
                    "faculty-mentored research projects after their sophomore and "
                    "junior years, with training in advanced research methods, "
                    "graduate-school preparation, and financial support.",
                    lab_or_program="Allison Davis Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["independent research", "faculty mentorship",
                              "diversity in academia"],
                ),
                program(
                    "mmuf",
                    "Mellon Mays Undergraduate Fellowship (MMUF) at Williams",
                    "https://diversity.williams.edu/pathways/fellowships/",
                    "The Mellon Mays Undergraduate Fellowship prepares students from "
                    "underrepresented groups for PhD study and academic careers "
                    "through multi-year mentored research, a summer research "
                    "colloquium, conference travel, and stipend support, launching "
                    "from the same summer research colloquium as ADRF.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["PhD pipeline", "mentored research", "fellowship"],
                ),
                program(
                    "sentinels_policy",
                    "Sentinels Public Policy Research Fellowship (Williams)",
                    "https://fellowships.williams.edu/summer-travel-fellowships/",
                    "The Sentinels Public Policy Research Fellowship funds student "
                    "research projects on contemporary issues in U.S. economic, "
                    "social, and environmental policy, providing stipends for four "
                    "to ten weeks of summer research. Open to rising sophomores, "
                    "juniors, and seniors.",
                    lab_or_program="Sentinels Public Policy Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    eligibility_majors=["Political Science", "Economics",
                                        "Environmental Studies", "Public Health"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["public policy", "policy research", "summer fellowship"],
                ),
                program(
                    "summer_travel_fellowships",
                    "Williams Summer & Travel Research Fellowships",
                    "https://fellowships.williams.edu/summer-travel-fellowships/",
                    "The Fellowships Office administers a portfolio of competitive "
                    "summer research and travel fellowships — including the Russell "
                    "Bostert Memorial Fellowship (Division II / history / "
                    "international relations) and the Barbara Solow Research "
                    "Fellowship (economic and business history) — that fund "
                    "independent student research projects lasting six weeks or "
                    "more, on or off campus. Sophomores and juniors are eligible.",
                    lab_or_program="Summer & Travel Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["research fellowship", "travel fellowship",
                              "independent research"],
                ),
                program(
                    "ugr_hub",
                    "Williams Undergraduate Research (central hub)",
                    "https://www.williams.edu/academics/undergraduate-study/undergraduate-research/",
                    "The College's central undergraduate-research portal explains "
                    "how Williams students get into faculty labs and scholarly "
                    "projects — during the term, over the summer, and through the "
                    "senior thesis — and links the funding programs, the Science "
                    "Center, and the Fellowships office that support them.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "faculty mentorship",
                              "senior thesis"],
                ),
                program(
                    "summer_opportunity_funding",
                    "Williams Summer Opportunity Funding",
                    "https://www.williams.edu/summer-opportunities/",
                    "The Summer Opportunity Funding hub aggregates the College's "
                    "funded summer options — on-campus research assistantships, "
                    "fellowships, and internship funding — into one searchable "
                    "portal with a single application cycle, letting students find "
                    "and apply to faculty-mentored research and other paid summer "
                    "experiences.",
                    lab_or_program="Summer Opportunity Funding",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer funding", "research assistantship",
                              "internship funding"],
                ),
            ],
        },
    ],
}
