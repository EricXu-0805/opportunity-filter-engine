"""Rutgers University-New Brunswick campus opportunity-graph config.

Curated seed records of the Rutgers-NB undergraduate-research landscape,
centered on the Aresty Research Center (the campus's central undergraduate
research office: Research Assistant Program, Summer Science, RISE) plus the
DIMACS REU, Douglass SUPER, WINLAB internships, Honors College research
support, and the SEBS G.H. Cook Scholars honors thesis. URLs verified live
(HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → rutgers_research_programs (rutgers / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "rutgers",
    "organization": "Rutgers University-New Brunswick",
    "location": "New Brunswick, NJ",
    "emit": {
        "campus": ("rutgers_research_programs", "rutgers", "campus"),
    },
    "sources": [
        {
            "source_name": "rutgers_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://aresty.rutgers.edu/programs-funding/research-assistant-program",
                "https://honorscollege.rutgers.edu/academics/research",
                "https://sebs.rutgers.edu/admissions/honors-opportunities",
            ],
            "programs": [
                program(
                    "aresty_research_assistant",
                    "Aresty Research Assistant Program (Rutgers)",
                    "https://aresty.rutgers.edu/programs-funding/research-assistant-program",
                    "The Aresty Research Center's flagship year-long program for "
                    "first-years, sophomores, and juniors who are new to research. "
                    "Students are paired with faculty mentors and work about five "
                    "hours per week on the professor's research project across the "
                    "academic year, with structured training in research skills "
                    "alongside peer cohort meetings. The program is explicitly "
                    "designed as faculty's pipeline for recruiting and training "
                    "new undergraduate researchers.",
                    lab_or_program="Aresty Research Center",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research assistant", "academic-year research"],
                ),
                program(
                    "aresty_summer_science",
                    "Aresty Summer Science Program (Rutgers)",
                    "https://aresty.rutgers.edu/programs-funding/summer-science-program",
                    "An intensive full-time summer research experience exclusively "
                    "for Rutgers-New Brunswick rising sophomores who are new to "
                    "research. Students are matched with faculty mentors across "
                    "scientific disciplines and learn the research process by "
                    "working in the lab and participating in cohort programming. "
                    "One of the few structured entry points aimed at students "
                    "right after their first year.",
                    lab_or_program="Aresty Research Center",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["summer research", "STEM", "laboratory",
                              "rising sophomore", "faculty mentor"],
                ),
                program(
                    "aresty_rise",
                    "RISE — Research Intensive Summer Experience (Rutgers)",
                    "https://aresty.rutgers.edu/programs-funding/the-research-intensive-summer-experience",
                    "A structured 10-week summer research program pairing students "
                    "with Rutgers faculty mentors, framed as a pathway to graduate "
                    "school. Open to sophomores, juniors, and non-graduating "
                    "seniors with a GPA of at least 3.0; participants receive "
                    "housing and travel support plus a stipend. Historically the "
                    "RiSE program also recruits students from other institutions "
                    "into Rutgers labs.",
                    lab_or_program="RISE at Rutgers",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Stipend plus housing and travel support",
                    preferred_year=["sophomore", "junior"],
                    keywords=["summer research", "10-week program",
                              "graduate school pathway", "stipend"],
                ),
                program(
                    "dimacs_reu",
                    "DIMACS REU — Algorithms from Foundations to Applications (Rutgers)",
                    "http://reu.dimacs.rutgers.edu/",
                    "Research Experiences for Undergraduates hosted by DIMACS, "
                    "Rutgers' center for discrete mathematics and theoretical "
                    "computer science. The program runs roughly late May through "
                    "late July with projects in computer science, mathematics, "
                    "bioinformatics, and the physical sciences, and includes a "
                    "partner DIMACS/Charles University track in Prague plus a "
                    "Rutgers Math REU stream. Applications run through a portal "
                    "that closes in winter.",
                    lab_or_program="DIMACS",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications close in winter for the summer cohort",
                    keywords=["REU", "algorithms", "discrete mathematics",
                              "theoretical computer science", "bioinformatics",
                              "summer research"],
                ),
                program(
                    "douglass_super",
                    "Douglass SUPER Research Experience (Rutgers)",
                    "https://douglass.rutgers.edu/wise/stem-research",
                    "SUPER (Science for Undergraduates — a Program for Excellence "
                    "in Research) is a non-residential summer research program for "
                    "Douglass Residential College STEM students. Participants "
                    "complete 10 weeks of research from late May through early "
                    "August with a Rutgers faculty mentor and receive a $3,000 "
                    "stipend; no course credit is attached. Designed to get "
                    "students into research early in their education.",
                    lab_or_program="Douglass Residential College",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$3,000 stipend for the 10-week summer",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["women in STEM", "summer research", "stipend",
                              "Douglass", "early research experience"],
                ),
                program(
                    "winlab_summer_internship",
                    "WINLAB Summer Internship Program (Rutgers)",
                    "https://www.winlab.rutgers.edu/prospective-students/summer-internship/",
                    "Full- and part-time summer internships at Rutgers' Wireless "
                    "Information Network Laboratory, offering undergraduates a "
                    "real-world, team-based research experience in wireless "
                    "networks and systems. Open to students currently enrolled "
                    "full-time in a college or university who are eligible to "
                    "work in the US, with an anticipated graduation of 2027 or "
                    "later; applying requires a transcript through a short "
                    "process handled by WINLAB directly.",
                    lab_or_program="WINLAB",
                    opportunity_type="research",
                    eligibility_majors=["Electrical and Computer Engineering",
                                        "Computer Science"],
                    preferred_year=["sophomore", "junior"],
                    keywords=["wireless networks", "internship",
                              "electrical engineering", "computer science",
                              "summer research", "team-based"],
                ),
                program(
                    "honors_college_research",
                    "Honors College Research & Artistry Support (Rutgers)",
                    "https://honorscollege.rutgers.edu/academics/research",
                    "The Honors College supports undergraduate research and "
                    "artistry across disciplines — from humanities archival "
                    "projects to field environmental science — and works closely "
                    "with the Aresty Research Center on structured faculty-student "
                    "collaboration with financial and academic-credit support. "
                    "Every fall the Honors College hosts an Internship & Research "
                    "Mixer connecting students to research opportunities across "
                    "the university.",
                    lab_or_program="Honors College",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors", "undergraduate research", "artistry",
                              "research mixer", "Aresty partnership"],
                ),
                program(
                    "gh_cook_scholars",
                    "George H. Cook Scholars Program (Rutgers SEBS honors thesis)",
                    "https://sebs.rutgers.edu/admissions/honors-opportunities",
                    "The senior honors thesis program of the School of "
                    "Environmental and Biological Sciences: students complete an "
                    "independent research project under the direction of a faculty "
                    "advisor and defend it as a G.H. Cook Scholars thesis. "
                    "Application happens in the second semester of junior year, "
                    "making sustained undergraduate research the core of the SEBS "
                    "honors designation.",
                    lab_or_program="G.H. Cook Scholars",
                    opportunity_type="research",
                    department="School of Environmental and Biological Sciences",
                    preferred_year=["junior", "senior"],
                    keywords=["honors thesis", "SEBS", "independent research",
                              "faculty advisor", "environmental science",
                              "biological sciences"],
                ),
            ],
        },
    ],
}
