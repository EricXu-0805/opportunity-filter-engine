"""Emory University campus opportunity-graph config.

Curated seed records of Emory's undergraduate-research landscape, centered on
the Emory College Undergraduate Research Programs (URP) office — now housed in
the Pathways Center — plus its flagship SURE summer fellowship, the SIRE
fall/spring first-time-researcher program, independent research and conference
grants, the ForagerOne faculty-matching platform, the Summer Research
Affiliates program, and the National Scholarships & Fellowships office. All
URLs fetched live (HTTP 200) on 2026-07-19.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> emory_research_programs (emory / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "emory",
    "organization": "Emory University",
    "location": "Atlanta, GA",
    "emit": {
        "campus": ("emory_research_programs", "emory", "campus"),
    },
    "sources": [
        {
            "source_name": "emory_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://college.emory.edu/undergraduate-research/",
                "https://pathways.emory.edu/",
                "https://college.emory.edu/national-awards/",
            ],
            "programs": [
                program(
                    "emory_undergraduate_research_programs",
                    "Emory College Undergraduate Research Programs (URP)",
                    "https://college.emory.edu/undergraduate-research/index.html",
                    "Undergraduate Research Programs (URP) supports students in "
                    "Emory College of Arts and Sciences as they pursue research "
                    "and creative scholarship in STEM, the humanities, social "
                    "sciences, and the arts. Housed in the Pathways Center, URP "
                    "runs the SURE summer fellowship and the SIRE program, "
                    "administers independent research and conference-presentation "
                    "grants, and connects students with faculty mentors.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentor",
                              "creative scholarship", "STEM and humanities"],
                ),
                program(
                    "emory_sure",
                    "Summer Undergraduate Research Experience (SURE, Emory)",
                    "https://college.emory.edu/undergraduate-research/summer-programs/sure.html",
                    "SURE is a ten-week summer program during which Emory College "
                    "of Arts and Sciences undergraduate research fellows conduct "
                    "full-time independent research under the direction of a "
                    "faculty mentor, spanning the arts, humanities, social "
                    "sciences, and STEM. Fellows receive a stipend, and SURE "
                    "participation fulfills the Experience and Application (XA) "
                    "General Education Requirement.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically due late winter/early spring (annual).",
                    keywords=["summer research", "full-time research", "stipend",
                              "faculty mentor"],
                ),
                program(
                    "emory_sire",
                    "Scholarly Inquiry and Research Experience (SIRE, Emory)",
                    "https://college.emory.edu/undergraduate-research/fall-and-spring-programs/sire.html",
                    "The Scholarly Inquiry and Research Experience (SIRE) Program "
                    "is a hands-on research opportunity for first-time "
                    "undergraduate researchers in Emory College of Arts and "
                    "Sciences. Intended for students with little to no research "
                    "experience, SIRE helps them gain skills, connect with "
                    "faculty mentors across the arts, humanities, social "
                    "sciences, and sciences, and begin their research journey "
                    "during the fall and spring semesters.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["first-time researchers", "mentored research",
                              "research skills", "academic year"],
                ),
                program(
                    "emory_independent_research_grants",
                    "Emory Undergraduate Independent Research Grants",
                    "https://college.emory.edu/undergraduate-research/fall-and-spring-programs/research-grants.html",
                    "Undergraduate Research Programs provides funding for "
                    "approved research projects led by Emory College of Arts and "
                    "Sciences undergraduates who have the endorsement of an Emory "
                    "faculty mentor. Eligible students may apply for up to $1,000 "
                    "to conduct a research project in the United States, or up to "
                    "$2,500 for an international project.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research grant", "project funding",
                              "faculty mentor", "independent research"],
                ),
                program(
                    "emory_conference_grants",
                    "Emory Undergraduate Conference Presentation Grants",
                    "https://college.emory.edu/undergraduate-research/fall-and-spring-programs/conference-grants.html",
                    "Each year the Undergraduate Research Programs office provides "
                    "funding for Emory College of Arts and Sciences undergraduates "
                    "to present their research at professional conferences. Grant "
                    "funding, up to $750, may be used to defray travel and other "
                    "expenses associated with presenting at a conference.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    keywords=["conference travel", "presentation grant",
                              "research dissemination"],
                ),
                program(
                    "emory_foragerone",
                    "ForagerOne Research Matching (Emory)",
                    "https://college.emory.edu/undergraduate-research/research-support/foragerone.html",
                    "ForagerOne simplifies making connections and sharing "
                    "research opportunities between faculty and undergraduate "
                    "students at Emory. Faculty claim auto-created profiles and "
                    "toggle an 'Accepting Students' switch, while students browse "
                    "and connect with mentors whose projects match their "
                    "interests across all disciplines.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research matching", "faculty connections",
                              "find a mentor", "research platform"],
                ),
                program(
                    "emory_summer_research_affiliates",
                    "Emory Summer Research Affiliates",
                    "https://college.emory.edu/undergraduate-research/summer-programs/summer-research-affiliates.html",
                    "Summer Research Affiliates collaborate with Emory's Office "
                    "of Undergraduate Research Programs to offer mentorship and "
                    "hands-on learning for undergraduate researchers who are not "
                    "currently enrolled at Emory. Participants engage in research "
                    "across diverse disciplines, including the natural sciences, "
                    "social sciences, humanities, and the arts.",
                    lab_or_program="Undergraduate Research Programs",
                    opportunity_type="summer_program",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["visiting researchers", "summer research",
                              "cross-institution", "mentorship"],
                ),
                program(
                    "emory_national_awards",
                    "Emory National Scholarships and Fellowships",
                    "https://college.emory.edu/national-awards/index.html",
                    "The National Scholarships & Fellowships Program Office "
                    "provides information and support for current Emory students "
                    "and recent alumni pursuing competitive merit awards. Each "
                    "year high-achieving Emory students win prestigious "
                    "fellowships (such as Fulbright, Goldwater, and Truman) that "
                    "enable them to study, research, and work around the world.",
                    lab_or_program="National Scholarships & Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    keywords=["Fulbright", "Goldwater", "national fellowships",
                              "merit awards"],
                ),
            ],
        },
    ],
}
