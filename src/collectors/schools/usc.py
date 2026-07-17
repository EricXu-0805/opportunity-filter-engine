"""University of Southern California campus opportunity-graph config.

Curated seed records of USC's undergraduate-research landscape: Dornsife's
Continuing Student Scholarships umbrella (SOAR + SURF academic-year and summer
research funding), Viterbi's undergraduate research hub and CURVE fellowship,
the Academic Honors and Fellowships office, WiSE, and the Bridge Institute's
convergent-bioscience training environment. URLs verified live (HTTP 200) on
2026-07-17. Viterbi's SURE summer program is NOT wired — paused for Summer
2026 per its official page.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → usc_research_programs (usc / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "usc",
    "organization": "University of Southern California",
    "location": "Los Angeles, CA",
    "emit": {
        "campus": ("usc_research_programs", "usc", "campus"),
    },
    "sources": [
        {
            "source_name": "usc_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://dornsife.usc.edu/css/",
                "https://viterbiundergrad.usc.edu/research/",
                "https://ahf.usc.edu/",
            ],
            "programs": [
                program(
                    "dornsife_soar",
                    "Student Opportunities for Academic Research (SOAR) — USC Dornsife",
                    "https://dornsife.usc.edu/soar/",
                    "SOAR is a USC Dornsife Continuing Student Scholarship "
                    "program that funds undergraduates to conduct "
                    "faculty-mentored academic research during the academic "
                    "year. Students work in faculty labs and field projects "
                    "across the college — from sociological fieldwork and "
                    "molecular biology research teams to physics labs and "
                    "psycholinguistics research groups. Administered under "
                    "Dornsife's Continuing Student Scholarships office.",
                    department="Dornsife College of Letters, Arts and Sciences",
                    lab_or_program="SOAR",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["undergraduate research", "research funding",
                              "faculty-mentored research", "dornsife"],
                ),
                program(
                    "dornsife_surf",
                    "Summer Undergraduate Research Fund (SURF) — USC Dornsife",
                    "https://dornsife.usc.edu/surf/",
                    "Dornsife's Summer Undergraduate Research Fund supports "
                    "undergraduates doing summer research, including "
                    "field-based Problems without Passports courses — past "
                    "projects range from underwater research in Palau and "
                    "anthropology coursework in Brazil to archaeological "
                    "research and cell-culture lab work. Funds are part of the "
                    "Continuing Student Scholarships program and may support "
                    "research and academic-related travel.",
                    department="Dornsife College of Letters, Arts and Sciences",
                    lab_or_program="SURF",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "research funding", "fieldwork",
                              "study abroad research"],
                ),
                program(
                    "viterbi_curve",
                    "CURVE Fellowship — Center for Undergraduate Research in Viterbi Engineering",
                    "https://viterbiundergrad.usc.edu/research/curve/",
                    "CURVE provides a centralized pathway for Viterbi "
                    "undergraduates to engage in faculty-mentored research "
                    "early in their academic careers, with tracks for "
                    "first-time and experienced researchers, posted research "
                    "positions, and lab information sessions. It also hosts "
                    "the Daben Weiqing Liu Research Fellowship and connects "
                    "students to research and mentoring communities.",
                    department="Viterbi School of Engineering",
                    lab_or_program="CURVE",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Computer Science", "Electrical and Computer Engineering",
                                        "Biomedical Engineering", "Mechanical Engineering",
                                        "Aerospace Engineering", "Chemical Engineering",
                                        "Civil Engineering", "Industrial and Systems Engineering"],
                    preferred_year=["freshman", "sophomore"],
                    keywords=["engineering research", "fellowship",
                              "faculty-mentored research", "viterbi"],
                ),
                program(
                    "viterbi_ugr_hub",
                    "Viterbi Undergraduate Research (hub)",
                    "https://viterbiundergrad.usc.edu/research/",
                    "The Viterbi school's central undergraduate research hub: "
                    "how to get started in a lab, Viterbi research programs "
                    "for Viterbi students and non-USC students, and funding "
                    "resources. The page notes USC ranks second in the nation "
                    "among all universities in federally funded research and "
                    "links out to program-specific opportunities.",
                    department="Viterbi School of Engineering",
                    lab_or_program="Viterbi Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Computer Science", "Electrical and Computer Engineering",
                                        "Biomedical Engineering", "Mechanical Engineering",
                                        "Aerospace Engineering", "Chemical Engineering",
                                        "Civil Engineering", "Industrial and Systems Engineering"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["undergraduate research", "engineering",
                              "funding resources", "getting started"],
                ),
                program(
                    "usc_ahf",
                    "Academic Honors and Fellowships (USC)",
                    "https://ahf.usc.edu/",
                    "USC's Academic Honors and Fellowships office supports new "
                    "and continuing students in pursuing university awards, "
                    "commencement honors, and nationally competitive "
                    "fellowships, mentoring applicants through the process. "
                    "USC was again named a top producer of U.S. Fulbright "
                    "Students, and AHF runs events plus a subscription group "
                    "on engageSC.",
                    lab_or_program="Academic Honors and Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["fellowships", "scholarships", "Fulbright",
                              "national awards", "mentoring"],
                ),
                program(
                    "usc_wise",
                    "Women in Science and Engineering (WiSE) — USC",
                    "https://wise.usc.edu/",
                    "USC WiSE is committed to equal opportunity in science and "
                    "engineering and to the success of scientists at USC "
                    "through creative programs that enable scientists to "
                    "thrive at every stage of their careers, including "
                    "undergraduate research support. The program is open to "
                    "all eligible individuals and focuses on building a "
                    "supportive environment for scientists.",
                    lab_or_program="WiSE",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["women in STEM", "research support", "science",
                              "engineering"],
                ),
                program(
                    "usc_bridge_institute",
                    "USC Bridge Institute — team-science undergraduate involvement",
                    "https://dornsife.usc.edu/bridge-at-usc/",
                    "The USC Bridge Institute explores the interplay of "
                    "molecules, cells and tissues through team-science and "
                    "art-science frameworks to create mechanistic insights "
                    "that impact biomedical research and support science "
                    "training. It serves as a launchpad for projects drawing "
                    "on disparate disciplines of science, engineering, "
                    "medicine and the arts, and offers convergent research "
                    "training environments.",
                    lab_or_program="Bridge Institute",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["interdisciplinary research", "biomedical",
                              "team science", "convergent bioscience"],
                ),
                program(
                    "dornsife_css",
                    "Dornsife Continuing Student Scholarships (CSS)",
                    "https://dornsife.usc.edu/css/",
                    "USC Dornsife offers a large number of scholarships each "
                    "year to support continuing and graduating Dornsife "
                    "undergraduates. Depending on the award, funds may be "
                    "used for tuition, research support, academic-related "
                    "travel, or graduate study. The CSS page is the umbrella "
                    "application portal for programs including SOAR and SURF.",
                    department="Dornsife College of Letters, Arts and Sciences",
                    lab_or_program="Continuing Student Scholarships",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["scholarships", "research funding",
                              "academic travel", "dornsife"],
                ),
            ],
        },
    ],
}
