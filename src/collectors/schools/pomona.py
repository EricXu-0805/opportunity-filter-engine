"""Pomona College campus opportunity-graph config.

Curated seed records of Pomona College's undergraduate-research landscape,
centered on the Academic Dean's Office "Student Research Opportunities" hub
and its flagship Summer Undergraduate Research Program (SURP), plus the named
endowed summer-research and research-travel funds the Dean's Office and
programs administer, and the Oldenborg Center's funded summer language
opportunities. Pomona is undergraduate-only, so every program here is aimed
squarely at Pomona undergraduates working with a faculty mentor.

All URLs curl-verified live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → pomona_research_programs (pomona / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_SRO = ("https://www.pomona.edu/administration/academic-dean/funding/"
        "student-research-opportunities")

SCHOOL: dict = {
    "school_slug": "pomona",
    "organization": "Pomona College",
    "location": "Claremont, CA",
    "emit": {
        "campus": ("pomona_research_programs", "pomona", "campus"),
    },
    "sources": [
        {
            "source_name": "pomona_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _SRO,
                _SRO + "/surp",
                "https://www.pomona.edu/research",
            ],
            "programs": [
                program(
                    "pomona_surp",
                    "Summer Undergraduate Research Program (SURP) — Pomona College",
                    _SRO + "/surp",
                    "SURP is Pomona College's flagship summer research "
                    "fellowship: a multi-week program that either pairs "
                    "undergraduates with a faculty member's research program "
                    "as a research assistant or funds a student-driven project "
                    "designed with a faculty mentor. Projects run four to ten "
                    "weeks across the sciences, social sciences, humanities, "
                    "and arts, and carry a stipend plus on-campus housing "
                    "support. Faculty submit research-assistant applications; "
                    "students apply to join a project or propose their own.",
                    lab_or_program="Summer Undergraduate Research Program",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Spring application cycle for the following "
                                  "summer; faculty and student applications via "
                                  "the Academic Dean's Office (grants@pomona.edu).",
                    keywords=["summer research", "faculty-mentored research",
                              "research assistant", "any major"],
                ),
                program(
                    "pomona_student_research_opportunities",
                    "Student Research Opportunities (Pomona College)",
                    _SRO,
                    "The Academic Dean's Office hub for Pomona's competitive "
                    "summer research program, giving students and faculty the "
                    "chance to collaborate on scholarly work over four to ten "
                    "weeks. The hub links the college-wide SURP program to the "
                    "named endowed funds that support summer research, field "
                    "schools, and conference travel across every division.",
                    lab_or_program="Academic Dean's Office",
                    opportunity_type="research",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "summer research",
                              "faculty collaboration", "research funding"],
                ),
                program(
                    "pomona_craddock_mcvicar",
                    "Evelyn B. Craddock McVicar Summer Undergraduate Research Fund "
                    "(Pomona College)",
                    _SRO + "/craddock-mcvicar-summer-undergraduate-research-fund",
                    "The Evelyn B. Craddock McVicar Memorial Fund supports "
                    "summer research for one or two junior Pomona College "
                    "students each year. The funded research must be carried "
                    "out with a faculty mentor and completed on campus, "
                    "supporting an ambitious independent project in the "
                    "student's field.",
                    lab_or_program="Academic Dean's Office",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["junior"],
                    keywords=["summer research", "faculty mentor",
                              "endowed research fund", "junior research"],
                ),
                program(
                    "pomona_schulz_environmental",
                    "Schulz Summer Research Awards in Environmental Studies "
                    "(Pomona College)",
                    _SRO + "/schulz-fund-environmental-studies",
                    "Established through a gift from Jean Schulz, the Summer "
                    "Research Awards in Environmental Studies select Pomona "
                    "students in their junior year to work with a faculty "
                    "mentor on environmental research over the summer, "
                    "supporting fieldwork and independent study in "
                    "environmental analysis and the environmental sciences.",
                    lab_or_program="Environmental Analysis Program",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["junior"],
                    keywords=["environmental studies", "summer research",
                              "fieldwork", "faculty mentor"],
                ),
                program(
                    "pomona_stonehill_media",
                    "Stonehill Media Studies Research Grant (Pomona College)",
                    _SRO + "/stonehill-media-studies-research-grant",
                    "The Media Studies Program awards Stonehill research grants "
                    "to Pomona College students (except seniors) to cover the "
                    "direct costs — travel, living expenses, equipment rental — "
                    "of a media studies research or production project, "
                    "enabling hands-on independent work in the field.",
                    lab_or_program="Media Studies Program",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["media studies", "research grant",
                              "production project", "travel funding"],
                ),
                program(
                    "pomona_wade_anthropology_field_school",
                    "Wade Family Anthropology Field School Fund (Pomona College)",
                    _SRO + "/wade-family-anthropology-field-school-fund",
                    "Established in 2003 by the Wade family, this endowment "
                    "provides financial support for continuing Pomona students "
                    "who wish to pursue a summer field school program in "
                    "anthropology — hands-on archaeological or ethnographic "
                    "training in the field under professional supervision.",
                    lab_or_program="Department of Anthropology",
                    opportunity_type="summer_program",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["anthropology", "field school", "archaeology",
                              "summer program"],
                ),
                program(
                    "pomona_research_travel",
                    "Faculty-Sponsored Student Research Travel Fund "
                    "(Pomona College)",
                    _SRO + "/faculty-sponsored-student-research-travel",
                    "Administered by the Dean's Office and advised by the "
                    "Research Committee, this fund supports Pomona students "
                    "presenting their research at academic and professional "
                    "conferences, covering travel and related costs so students "
                    "can share original scholarship with a broader research "
                    "community.",
                    lab_or_program="Academic Dean's Office",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "travel grant", "faculty-sponsored"],
                ),
                program(
                    "pomona_oldenborg_funded_summer",
                    "Oldenborg Center Funded Summer Language Opportunities "
                    "(Pomona College)",
                    "https://www.pomona.edu/administration/oldenborg-center/"
                    "opportunities/funded-summer",
                    "The Oldenborg Center for Modern Languages and "
                    "International Relations offers funded summer opportunities "
                    "for Pomona students to advance their foreign-language "
                    "study and cross-cultural research, supporting intensive "
                    "language acquisition and internationally oriented projects "
                    "that complement undergraduate coursework.",
                    lab_or_program="Oldenborg Center for Modern Languages",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["foreign language", "language acquisition",
                              "international", "summer program"],
                ),
            ],
        },
    ],
}
