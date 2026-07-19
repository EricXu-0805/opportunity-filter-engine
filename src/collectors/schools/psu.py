"""Penn State University Park campus opportunity-graph config.

Curated seed records of Penn State's undergraduate-research landscape,
centered on URFM (Undergraduate Research and Fellowships Mentoring — the
central undergraduate research office) and its funding/presentation programs,
plus the college-level research gateways (Eberly Science, Ag Sciences,
Engineering), the MRSEC center, Millennium Scholars, Schreyer honors thesis,
and the Multi-Campus REU. URLs verified live (HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → psu_research_programs (psu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "psu",
    "organization": "Penn State University Park",
    "location": "University Park, PA",
    "emit": {
        "campus": ("psu_research_programs", "psu", "campus"),
    },
    "sources": [
        {
            "source_name": "psu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://urfm.psu.edu/research-home",
                "https://science.psu.edu/science-engagement/undergraduate-research",
                "https://www.engr.psu.edu/research/undergrad-opportunities.aspx",
            ],
            "programs": [
                program(
                    "urfm_office",
                    "Undergraduate Research and Fellowships Mentoring (URFM) — Penn State",
                    "https://urfm.psu.edu/research-home",
                    "URFM is Penn State's central undergraduate research office. "
                    "Its site walks students through understanding research (what "
                    "it is, its benefits, when to get involved), finding an "
                    "opportunity and a mentor — including the Undergraduate "
                    "Research Opportunities Database — funding an experience, and "
                    "communicating findings. It also runs the Undergraduate "
                    "Research Ambassadors and Research Readiness programs.",
                    lab_or_program="URFM",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["undergraduate research", "mentoring",
                              "research opportunities database", "fellowships"],
                ),
                program(
                    "erickson_discovery_grant",
                    "Rodney A. Erickson Discovery Grant (Penn State)",
                    "https://urfm.psu.edu/programs/erickson-discovery-grant",
                    "Named for Penn State's seventeenth president, the Erickson "
                    "Discovery Grant funds undergraduate engagement in original "
                    "research, scholarship, and creative work under the direct "
                    "supervision of a research mentor; forty-three grants were "
                    "awarded for summer 2024. Grants support student-initiated "
                    "projects across the arts, engineering, humanities, sciences, "
                    "and social sciences, covering the full arc from proposal "
                    "writing to communicating results.",
                    lab_or_program="Erickson Discovery Grant",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research funding", "student-initiated project",
                              "research grant", "creative work"],
                ),
                program(
                    "undergraduate_exhibition",
                    "Penn State Undergraduate Exhibition",
                    "https://urfm.psu.edu/programs/undergraduate-exhibition",
                    "Held annually each spring, the Undergraduate Exhibition "
                    "offers virtual and in-person opportunities to present "
                    "research through a poster, an oral presentation, or a "
                    "performance. Posters are the most popular format, while oral "
                    "presentations and performances serve disciplines like the "
                    "visual and performing arts; awards and judging are part of "
                    "the event.",
                    lab_or_program="Undergraduate Exhibition",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research presentation", "poster session",
                              "exhibition", "awards"],
                ),
                program(
                    "eberly_undergrad_research",
                    "Eberly College of Science Undergraduate Research (Penn State)",
                    "https://science.psu.edu/science-engagement/undergraduate-research",
                    "The Eberly College of Science promotes hands-on lab research "
                    "with its faculty: 'a fantastic opportunity exists to work "
                    "directly in a laboratory, learning from some of the most "
                    "innovative minds in science.' The page describes multiple "
                    "pathways, from formalized programs with certificates to "
                    "practical hands-on lab activities.",
                    lab_or_program="Eberly Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["laboratory research", "science",
                              "research certificate", "faculty mentorship"],
                ),
                program(
                    "agsci_student_research",
                    "College of Agricultural Sciences Student Research Opportunities (Penn State)",
                    "https://agsci.psu.edu/students/research",
                    "The College of Agricultural Sciences invites students to "
                    "work side by side with faculty, graduate students, and other "
                    "undergraduates in lab or field experiences. Options include "
                    "joining cutting-edge research through a part-time wage "
                    "position or serving as a research assistant on a "
                    "faculty-led research project.",
                    lab_or_program="Ag Sciences Student Research",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["agriculture", "field research", "paid research",
                              "research assistant"],
                ),
                program(
                    "engineering_undergrad_research",
                    "College of Engineering Undergraduate Research Opportunities (Penn State)",
                    "https://www.engr.psu.edu/research/undergrad-opportunities.aspx",
                    "Penn State Engineering points undergraduates to research "
                    "experiences including projects in engineering at Penn State, "
                    "projects at other universities, and research internships at "
                    "Penn State's Applied Research Lab, in industry, or with "
                    "national laboratories. It notes that Schreyer Honors "
                    "College, Millennium Scholars, and Engineering Science "
                    "students conduct research as part of their degree paths.",
                    lab_or_program="Engineering Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Computer Science", "Electrical Engineering",
                                        "Mechanical Engineering", "Aerospace Engineering",
                                        "Biomedical Engineering", "Chemical Engineering",
                                        "Industrial Engineering"],
                    preferred_year=["sophomore", "junior"],
                    keywords=["engineering research", "applied research lab",
                              "research internship", "national laboratories"],
                ),
                program(
                    "mrsec_undergrad_research",
                    "Penn State MRSEC Research Opportunities for Undergrads",
                    "https://www.mrsec.psu.edu/education-outreach/research-opportunities-undergrads",
                    "The Penn State MRSEC (Center for Nanoscale Science) offers "
                    "research opportunities for undergraduates within its "
                    "interdisciplinary research groups on 2D polar metals and "
                    "heterostructures and crystalline oxides with high entropy. "
                    "Its education-outreach arm also runs the PREM partnership "
                    "with NCCU and publishes undergraduate research highlights.",
                    lab_or_program="Penn State MRSEC",
                    opportunity_type="research",
                    eligibility_majors=["Materials Science and Engineering",
                                        "Physics", "Chemistry"],
                    preferred_year=["sophomore", "junior"],
                    keywords=["materials science", "nanoscale", "REU", "MRSEC"],
                ),
                program(
                    "millennium_scholars",
                    "Millennium Scholars Program (Penn State)",
                    "https://www.millennium.psu.edu/",
                    "The Millennium Scholars Program cultivates 'a community of "
                    "STEM scholars who will produce sustainable solutions to "
                    "global challenges and actively engage as innovative leaders "
                    "in society.' The cohort-based program includes a Summer "
                    "Bridge Program before freshman year and spans the "
                    "participating STEM colleges, with research engagement "
                    "expected of scholars.",
                    lab_or_program="Millennium Scholars",
                    opportunity_type="fellowship",
                    preferred_year=["freshman"],
                    keywords=["STEM scholars", "summer bridge", "cohort program",
                              "research pipeline"],
                ),
                program(
                    "schreyer_thesis",
                    "Schreyer Honors College Thesis Research (Penn State)",
                    "https://www.shc.psu.edu/academics/thesis/",
                    "Every Schreyer Scholar completes an honors thesis as the "
                    "culmination of the honors experience, demonstrating command "
                    "of the relevant scholarly work and making a personal "
                    "contribution to that scholarship. Projects range from "
                    "laboratory experiments to artistic creations, with the "
                    "document capturing background, methods, and results.",
                    lab_or_program="Schreyer Honors College",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    keywords=["honors thesis", "independent research",
                              "honors college", "faculty mentorship"],
                ),
                program(
                    "mc_reu",
                    "Multi-Campus Research Experience for Undergraduates (Penn State MC REU)",
                    "https://sites.psu.edu/mcreu/",
                    "The Multi-Campus REU pairs Penn State undergraduate and "
                    "faculty teams across campuses for a summer research program "
                    "capped by a research exhibition. The 2026 exhibition site "
                    "showcases projects browsable by major and by campus, "
                    "celebrating student-faculty research teams from the summer "
                    "program, with annual editions back to 2020.",
                    lab_or_program="MC REU",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["summer REU", "multi-campus", "engineering research",
                              "research exhibition"],
                ),
            ],
        },
    ],
}
