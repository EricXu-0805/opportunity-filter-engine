"""Wesleyan University campus opportunity-graph config.

Curated seed records of Wesleyan's undergraduate-research landscape, centered
on the College of Integrative Sciences (CIS) Summer Research Program — the
university's flagship 10-week paid summer science-research fellowship — and its
companion structured-research tracks (named Research Fellows, cross-lab
Research Pods, the South Asia Research Opportunity, and course-based CUREs),
plus the Ronald E. McNair post-baccalaureate program, the university-wide
Wesleyan Summer Grants, the Quantitative Analysis Center summer apprenticeship
and fellowships, and the College of the Environment Think Tank student
fellowships. All URLs curl-verified live (HTTP 200) on 2026-07-22.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → wesleyan_research_programs (wesleyan / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_CIS = "https://www.wesleyan.edu/cis"

SCHOOL: dict = {
    "school_slug": "wesleyan",
    "organization": "Wesleyan University",
    "location": "Middletown, CT",
    "emit": {
        "campus": ("wesleyan_research_programs", "wesleyan", "campus"),
    },
    "sources": [
        {
            "source_name": "wesleyan_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_CIS}/summer-program/index.html",
                f"{_CIS}/research/index.html",
                "https://www.wesleyan.edu/mcnair/",
                "https://www.wesleyan.edu/qac/",
            ],
            "programs": [
                program(
                    "wesleyan_cis_summer",
                    "CIS Summer Research Program (Wesleyan)",
                    f"{_CIS}/summer-program/index.html",
                    "Wesleyan's flagship summer research program, run by the "
                    "College of Integrative Sciences: undergraduates spend about "
                    "ten weeks doing full-time, faculty-mentored laboratory and "
                    "field research in the natural sciences, mathematics, and "
                    "quantitative social sciences, with a stipend and summer "
                    "housing, culminating in the Summer Science Symposium.",
                    lab_or_program="College of Integrative Sciences",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Biology", "Chemistry", "Physics",
                                        "Astronomy", "Mathematics",
                                        "Molecular Biology and Biochemistry"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "laboratory",
                              "sciences", "stipend"],
                ),
                program(
                    "wesleyan_cis_fellows",
                    "CIS Research Fellows (Wesleyan)",
                    f"{_CIS}/summer-program/research-fellowships.html",
                    "Named summer research fellowships awarded through the "
                    "College of Integrative Sciences that fund individual "
                    "undergraduates to carry out mentored, independent research "
                    "projects with Wesleyan science faculty.",
                    lab_or_program="CIS Research Fellows",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research fellowship", "faculty mentor",
                              "independent research", "sciences"],
                ),
                program(
                    "wesleyan_cis_pods",
                    "CIS Research Pods (Wesleyan)",
                    f"{_CIS}/summer-program/pods.html",
                    "Collaborative summer 'research pods' that group several "
                    "undergraduates with faculty around a shared cross-"
                    "disciplinary research theme, giving students team-based "
                    "mentored research experience within the College of "
                    "Integrative Sciences.",
                    lab_or_program="CIS Research Pods",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["team research", "interdisciplinary",
                              "faculty mentor", "summer"],
                ),
                program(
                    "wesleyan_saro",
                    "South Asia Research Opportunity (Wesleyan)",
                    f"{_CIS}/summer-program/saro.html",
                    "A summer research opportunity pairing Wesleyan "
                    "undergraduates with faculty on projects connected to South "
                    "Asia, bridging the sciences and area studies within the "
                    "College of Integrative Sciences summer program.",
                    lab_or_program="South Asia Research Opportunity",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["South Asia", "summer research", "faculty mentor",
                              "area studies"],
                ),
                program(
                    "wesleyan_cures",
                    "Course-based Undergraduate Research Experiences (CUREs) (Wesleyan)",
                    f"{_CIS}/research/cures.html",
                    "Course-based Undergraduate Research Experiences embed "
                    "authentic, original research into regular Wesleyan science "
                    "courses, so that students contribute to faculty research "
                    "questions as part of their coursework rather than in a "
                    "separate lab placement.",
                    lab_or_program="CUREs",
                    opportunity_type="research",
                    paid="no",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["course-based research", "sciences",
                              "authentic research", "curriculum"],
                ),
                program(
                    "wesleyan_mcnair",
                    "Ronald E. McNair Program (Wesleyan)",
                    "https://www.wesleyan.edu/mcnair/",
                    "The federally funded Ronald E. McNair Post-Baccalaureate "
                    "Achievement Program prepares first-generation, "
                    "income-eligible, and underrepresented Wesleyan "
                    "undergraduates for doctoral study through paid mentored "
                    "summer research, graduate-school advising, and scholarly "
                    "training.",
                    lab_or_program="McNair Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    keywords=["McNair", "mentored research", "doctoral prep",
                              "first-generation"],
                ),
                program(
                    "wesleyan_summer_grants",
                    "Wesleyan Summer Grants",
                    "https://careercenter.wesleyan.edu/channels/"
                    "wesleyan-summer-grants/",
                    "University-wide summer grants administered through the "
                    "Gordon Career Center that fund Wesleyan students to pursue "
                    "unpaid or low-paid summer research, internships, and "
                    "project work — including faculty-mentored research — across "
                    "any field.",
                    lab_or_program="Wesleyan Summer Grants",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer grant", "funding", "research",
                              "any discipline"],
                ),
                program(
                    "wesleyan_qac_apprenticeship",
                    "QAC Summer Apprenticeship (Wesleyan)",
                    "https://www.wesleyan.edu/qac/summer.html",
                    "The Quantitative Analysis Center's summer apprenticeship "
                    "trains undergraduates in statistical computing and data "
                    "analysis and embeds them as paid research apprentices on "
                    "faculty data-intensive research projects across the "
                    "disciplines.",
                    lab_or_program="Quantitative Analysis Center",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Data Science", "Mathematics",
                                        "Computer Science"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["data analysis", "statistics", "research apprentice",
                              "quantitative methods"],
                ),
                program(
                    "wesleyan_qac_fellowships",
                    "QAC Fellowships (Wesleyan)",
                    "https://www.wesleyan.edu/qac/fellowships.html",
                    "Quantitative Analysis Center fellowships supporting "
                    "Wesleyan students who serve as data-analysis tutors and "
                    "collaborators on quantitative research, deepening their "
                    "methodological training while assisting faculty and peer "
                    "research.",
                    lab_or_program="Quantitative Analysis Center",
                    opportunity_type="fellowship",
                    paid="stipend",
                    eligibility_majors=["Data Science", "Mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["data analysis", "quantitative research",
                              "fellowship", "statistics"],
                ),
                program(
                    "wesleyan_coe_thinktank",
                    "College of the Environment Think Tank Student Fellowships (Wesleyan)",
                    "https://www.wesleyan.edu/coe/thinktank/index.html",
                    "The College of the Environment's Think Tank convenes an "
                    "annual interdisciplinary research cohort around an "
                    "environmental theme; student research fellows work "
                    "alongside faculty fellows on collaborative, theme-based "
                    "environmental research.",
                    lab_or_program="College of the Environment Think Tank",
                    opportunity_type="fellowship",
                    paid="stipend",
                    eligibility_majors=["Environmental Studies",
                                        "Earth and Environmental Sciences"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["environment", "interdisciplinary research",
                              "think tank", "faculty mentor"],
                ),
            ],
        },
    ],
}
