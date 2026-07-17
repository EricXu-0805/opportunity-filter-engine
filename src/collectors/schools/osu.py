"""Ohio State University campus opportunity-graph config.

Curated seed records of OSU's undergraduate-research landscape, centered on
the Office of Undergraduate Research & Creative Inquiry (UR&CI) and its
funding/presentation programs (URAP, funding list, Denman Forum, Spring
Research Festival, structured-programs list), plus STEP second-year
fellowships and the Honors & Scholars center. URLs verified live (HTTP 200)
on 2026-07-17.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → osu_research_programs (osu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "osu",
    "organization": "Ohio State University",
    "location": "Columbus, OH",
    "emit": {
        "campus": ("osu_research_programs", "osu", "campus"),
    },
    "sources": [
        {
            "source_name": "osu_ugresearch_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ugresearch.osu.edu/",
                "https://step.osu.edu/",
                "https://honors-scholars.osu.edu/",
            ],
            "programs": [
                program(
                    "ugresearch_office",
                    "Office of Undergraduate Research & Creative Inquiry (Ohio State)",
                    "https://ugresearch.osu.edu/",
                    "OSU's central undergraduate research office. It helps "
                    "undergraduates find research opportunities and faculty "
                    "mentors, offers presentation and publishing venues and "
                    "funding guidance, and runs events including the Denman "
                    "Forum and the Spring Undergraduate Research Festival. The "
                    "office maintains lists of faculty-led projects and open "
                    "research positions.",
                    lab_or_program="UR&CI",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "mentorship",
                              "research positions", "creative inquiry"],
                ),
                program(
                    "urap",
                    "Undergraduate Research Apprenticeship Program — URAP (Ohio State)",
                    "https://ugresearch.osu.edu/get-involved/undergraduate-research-apprenticeship-program-urap",
                    "Competitive funding and professional development program "
                    "through UR&CI that supports about 70 undergraduates per "
                    "year across two terms (Summer May-August and Fall/Spring "
                    "September-April). Open to Ohio State undergraduates "
                    "eligible for student employment, in any major; students "
                    "must secure a faculty mentor and develop their own "
                    "research proposal (URAP does not match students). "
                    "Fall/Spring prioritizes majors with fewer summer research "
                    "options.",
                    lab_or_program="URAP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["paid research", "apprenticeship", "faculty mentor",
                              "proposal", "stipend"],
                ),
                program(
                    "ug_research_funding",
                    "Undergraduate Research Funding Opportunities (Ohio State)",
                    "https://ugresearch.osu.edu/current-researchers/funding-opportunities",
                    "Curated list of research funding awards for OSU "
                    "undergraduates from various areas of the university, each "
                    "with its own requirements and deadlines requiring "
                    "application well in advance. UR&CI notes it does not "
                    "currently fund conference travel and recommends asking "
                    "mentors or departments for discretionary travel funds.",
                    lab_or_program="UR&CI Funding",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research funding", "awards", "grants"],
                ),
                program(
                    "denman_forum",
                    "Denman Undergraduate Research Forum (Ohio State)",
                    "https://ugresearch.osu.edu/present-publish/denman-undergraduate-research-forum",
                    "The Richard J. and Martha D. Denman Undergraduate Research "
                    "Forum is OSU's annual competitive poster forum, supported "
                    "by the Denman family since 1995. Graduating student "
                    "researchers present posters to the university community "
                    "and are judged by faculty, staff, and Denman alumni "
                    "reviewers, with winners recognized in each category based "
                    "on written poster content and oral presentation.",
                    lab_or_program="Denman Forum",
                    opportunity_type="research",
                    preferred_year=["senior"],
                    keywords=["poster", "research forum", "competition", "presentation"],
                ),
                program(
                    "spring_research_festival",
                    "Spring Undergraduate Research Festival (Ohio State)",
                    "https://ugresearch.osu.edu/present-publish/spring-undergraduate-research-festival",
                    "Annual spring poster forum open to all students engaged in "
                    "mentored undergraduate research, not restricted to any "
                    "discipline or graduation year. Students present during "
                    "60-minute poster sessions to the broader academic "
                    "community; unlike the Denman it is non-competitive and "
                    "application-based.",
                    lab_or_program="Spring Undergraduate Research Festival",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["poster", "research festival", "presentation"],
                ),
                program(
                    "structured_research_programs",
                    "Structured Research Programs list (Ohio State)",
                    "https://ugresearch.osu.edu/new-researchers/research-programs",
                    "UR&CI's list of structured research programs that do not "
                    "require students to already have a project or advisor — "
                    "students are matched with or choose a project and research "
                    "advisor. Many are summer programs ideal for short-term "
                    "research experience, and the majority offer funding or a "
                    "stipend; includes programs like the Center for Cognitive "
                    "and Brain Sciences.",
                    lab_or_program="Structured Research Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["summer research", "matched placement", "stipend",
                              "structured program"],
                ),
                program(
                    "step",
                    "Second-year Transformational Experience Program — STEP (Ohio State)",
                    "https://step.osu.edu/",
                    "OSU program for second-year students combining a "
                    "faculty-mentored cohort with professional development "
                    "co-curriculars. Participants can submit a proposal for a "
                    "fellowship of up to $2,000 toward a STEP Signature Project "
                    "(categories include undergraduate research), and present "
                    "outcomes at the STEP Expo.",
                    lab_or_program="STEP",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Fellowship of up to $2,000 toward a Signature Project",
                    preferred_year=["sophomore"],
                    keywords=["fellowship", "signature project", "faculty mentor",
                              "second year"],
                ),
                program(
                    "honors_scholars",
                    "Honors & Scholars Programs (Ohio State)",
                    "https://honors-scholars.osu.edu/",
                    "OSU's Honors and Scholars center runs the Honors Program "
                    "(enriched academic curriculum), themed Scholars "
                    "living-learning communities, the Stamps Eminence "
                    "Scholarship Program for exceptionally ambitious students, "
                    "and the President's Ohio Scholarship for Ohio first-years "
                    "with perfect ACT/SAT scores.",
                    lab_or_program="Honors & Scholars",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors", "scholars", "eminence", "scholarship",
                              "learning community"],
                ),
            ],
        },
    ],
}
