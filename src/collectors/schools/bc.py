"""Boston College campus opportunity-graph config.

Curated seed records of Boston College's undergraduate-research landscape,
centered on the university-wide Undergraduate Research Opportunities hub and
the Advanced Study Grants (ASG) family administered through the Office of the
Provost's University Fellowships Committee — BC's main mechanism for funding
student-designed summer research, arts, and language-acquisition projects —
plus Conference Travel Grants, the national/prestigious fellowships pipeline,
and the Schiller Institute for Integrated Science and Society (BC's
interdisciplinary STEM research hub, home to Human-Centered Engineering).
All URLs curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → bc_research_programs (bc / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_P = "https://www.bc.edu/content/bc-web"
_UFC = (_P + "/academics/sites/office-of-provost/about/provost-committees/"
        "university-fellowship-committee")

SCHOOL: dict = {
    "school_slug": "bc",
    "organization": "Boston College",
    "location": "Chestnut Hill, MA",
    "emit": {
        "campus": ("bc_research_programs", "bc", "campus"),
    },
    "sources": [
        {
            "source_name": "bc_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _P + "/research/undergrad-research-opps.html",
                _UFC + "/undergraduate-research-support.html",
                _P + "/centers/schiller-institute/research.html",
            ],
            "programs": [
                program(
                    "bc_undergrad_research_opportunities",
                    "Undergraduate Research Opportunities (Boston College)",
                    _P + "/research/undergrad-research-opps.html",
                    "Boston College's university-wide hub for undergraduate "
                    "research. Across the humanities, sciences, business, and "
                    "education, students gain exposure to new methods and lead "
                    "their own research projects, with funding pathways "
                    "including Advanced Study Grants, Summer Fellowships, "
                    "Conference Travel Grants, and Thesis Research Supplemental "
                    "Grants, plus links to prestigious national fellowships.",
                    lab_or_program="Undergraduate Research Opportunities",
                    opportunity_type="research",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research funding",
                              "any major", "mentored research"],
                ),
                program(
                    "bc_advanced_study_grants",
                    "Advanced Study Grants (Boston College)",
                    _UFC + "/undergraduate-research-support.html",
                    "Boston College Advanced Study Grants (ASGs) fund "
                    "student-designed summer skill-acquisition or research "
                    "projects that dramatically advance a student's progress "
                    "in their major, or provide research assistance for juniors "
                    "completing a thesis or Scholar of the College project. "
                    "Students are nominated by a faculty member at the start of "
                    "the spring semester; applications (a three-page proposal, "
                    "budget, transcript, and recommendation) are due in "
                    "mid-March.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Faculty nomination in early spring; "
                                  "applications due mid-March (early April for "
                                  "thesis applicants).",
                    keywords=["advanced study grants", "summer research",
                              "faculty nomination", "research funding"],
                ),
                program(
                    "bc_asg_summer_research",
                    "Advanced Study Grants for Summer Research (Boston College)",
                    _UFC + "/undergraduate-research-support.html",
                    "The summer-research track of BC's Advanced Study Grants, "
                    "awarded for student-designed summer research or skill "
                    "development projects. The program encourages "
                    "undergraduates to acquire skills that make more "
                    "sophisticated research possible in the junior and senior "
                    "years; preference is given to freshmen and sophomores, "
                    "though juniors may also apply.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="summer_program",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "skill development",
                              "student-designed project", "research grant"],
                ),
                program(
                    "bc_asg_arts",
                    "Advanced Study Grants in the Arts (Boston College)",
                    _UFC + "/undergraduate-research-support.html",
                    "A track of BC's Advanced Study Grants supporting freshmen, "
                    "sophomores, and juniors who show initiative and "
                    "imagination in the performing, literary, and visual arts. "
                    "These grants fund summer skill-acquisition projects that "
                    "significantly accelerate a student's progress in an "
                    "artistic field of study.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["arts", "creative practice", "summer project",
                              "performing and visual arts"],
                ),
                program(
                    "bc_asg_language",
                    "Advanced Study Grants for Language Acquisition (Boston College)",
                    _UFC + "/undergraduate-research-support.html",
                    "A track of BC's Advanced Study Grants offering support for "
                    "freshmen and sophomores who wish to acquire language "
                    "skills needed for advanced academic work that would not "
                    "otherwise be available through normal coursework. Students "
                    "have used these grants for intensive foreign-language "
                    "study, often abroad.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["language acquisition", "foreign language",
                              "study abroad", "summer program"],
                ),
                program(
                    "bc_asg_thesis_research",
                    "Advanced Study Grants for Thesis Research (Boston College)",
                    _UFC + "/undergraduate-research-support.html",
                    "The thesis-research track of BC's Advanced Study Grants "
                    "provides research assistance for juniors who will be "
                    "completing a senior thesis or a Scholar of the College "
                    "project the following year. The grant funds the summer "
                    "research — fieldwork, archival study, lab work, data "
                    "collection — that a student needs to launch an ambitious "
                    "independent thesis, working under a faculty thesis advisor.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["junior", "senior"],
                    deadline_note="Applications due mid-March (early April for "
                                  "thesis applicants).",
                    keywords=["senior thesis", "summer research",
                              "Scholar of the College", "faculty-mentored research"],
                ),
                program(
                    "bc_conference_travel_grants",
                    "Conference Travel Grants (Boston College)",
                    _P + "/research/undergrad-research-opps.html",
                    "Conference Travel Grants support Boston College "
                    "undergraduates presenting original research at academic or "
                    "professional conferences worldwide, covering travel and "
                    "related expenses so students can share their scholarship "
                    "with a broader research community.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "travel grant", "academic conference"],
                ),
                program(
                    "bc_university_fellowships",
                    "University Fellowships Committee — National Fellowships (Boston College)",
                    _UFC + ".html",
                    "The Office of the Provost's University Fellowships "
                    "Committee advises Boston College students applying for "
                    "prestigious national and international awards — including "
                    "the Fulbright U.S. Student Program, Rhodes and Marshall "
                    "scholarships, and the Boren and James Madison fellowships "
                    "— providing mentorship through the nomination and "
                    "application process.",
                    lab_or_program="University Fellowships Committee",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="unknown",
                    preferred_year=["junior", "senior"],
                    deadline_note="Deadlines vary by award; most national "
                                  "fellowships have fall campus deadlines.",
                    keywords=["Fulbright", "Rhodes", "Marshall",
                              "national fellowships"],
                ),
                program(
                    "bc_schiller_institute",
                    "Schiller Institute for Integrated Science and Society (Boston College)",
                    _P + "/centers/schiller-institute/research.html",
                    "The Schiller Institute supports BC faculty, students, and "
                    "staff conducting interdisciplinary research and "
                    "scholarship through seed-grant funding, training, and "
                    "events that connect people across disciplines, schools, "
                    "and methods. It is home to Human-Centered Engineering and "
                    "focuses on energy, health, and environment challenges — a "
                    "hub for students seeking cross-disciplinary STEM research.",
                    lab_or_program="Schiller Institute for Integrated Science and Society",
                    opportunity_type="research",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["interdisciplinary research", "energy",
                              "health", "environment"],
                ),
            ],
        },
    ],
}
