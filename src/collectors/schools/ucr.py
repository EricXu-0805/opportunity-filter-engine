"""UC Riverside campus opportunity-graph config.

Curated seed records of UC Riverside's undergraduate-research landscape: the
central undergraduate-research office (uResearch) and the Center for
Undergraduate Research and Engaged Learning (CUREL), the two flagship summer
research programs (RISE and MSRIP), University Honors' faculty-mentored research
track, and the CNAS student research & internship hub. URLs curl-verified live
(HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ucr_research_programs (ucr / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "ucr",
    "organization": "University of California, Riverside",
    "location": "Riverside, CA",
    "emit": {
        "campus": ("ucr_research_programs", "ucr", "campus"),
    },
    "sources": [
        {
            "source_name": "ucr_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.ucr.edu/research/undergrad-research",
                "https://engage.ucr.edu/",
                "https://rise.ucr.edu/",
                "https://apro.ucr.edu/undergrad/msrip",
                "https://honors.ucr.edu/",
                "https://cnas.ucr.edu/student-research-and-internship-opportunities",
            ],
            "programs": [
                program(
                    "ucr_uresearch",
                    "UCR uResearch — Undergraduate Research (University of California, Riverside)",
                    "https://www.ucr.edu/research/undergrad-research",
                    "UC Riverside's central undergraduate-research gateway, "
                    "connecting students across every college to faculty-mentored "
                    "research, funding, and the campus's research programs. It is "
                    "the starting point for finding a lab, learning how to get "
                    "involved in research, and navigating undergraduate research "
                    "opportunities at UCR.",
                    lab_or_program="Undergraduate Research (uResearch)",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "getting started"],
                ),
                program(
                    "ucr_curel",
                    "Center for Undergraduate Research and Engaged Learning (CUREL, UC Riverside)",
                    "https://engage.ucr.edu/",
                    "CUREL supports UC Riverside undergraduates in pursuing "
                    "research, creative activity, and engaged learning. It helps "
                    "students connect with mentors, access research resources and "
                    "funding, and present their work, and serves as a campus hub "
                    "for high-impact experiential learning across disciplines.",
                    lab_or_program="Center for Undergraduate Research and Engaged Learning",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["engaged learning", "research mentorship",
                              "experiential learning", "creative activity"],
                ),
                program(
                    "ucr_rise",
                    "RISE — Research in Science & Engineering (UC Riverside)",
                    "https://rise.ucr.edu/",
                    "A 10-week summer research program at UC Riverside that "
                    "immerses undergraduates in hands-on, faculty-mentored "
                    "research in science and engineering. Participants work in a "
                    "lab full-time over the summer, build research skills, and "
                    "present their results, with professional-development and "
                    "graduate-school preparation woven throughout.",
                    lab_or_program="Research in Science & Engineering (RISE)",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "science and engineering",
                              "faculty mentor", "graduate school preparation"],
                ),
                program(
                    "ucr_msrip",
                    "MSRIP — Mentoring Summer Research Internship Program (UC Riverside)",
                    "https://apro.ucr.edu/undergrad/msrip",
                    "An 8-week summer research internship run by UC Riverside's "
                    "Academic Programs (Graduate Division) that pairs "
                    "undergraduates with faculty mentors for an intensive research "
                    "experience. MSRIP supports students in preparing for graduate "
                    "study through mentored research, workshops, and a "
                    "culminating research symposium.",
                    lab_or_program="Mentoring Summer Research Internship Program",
                    opportunity_type="summer_program",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["summer internship", "mentored research",
                              "graduate school preparation", "research symposium"],
                ),
                program(
                    "ucr_university_honors",
                    "University Honors (UC Riverside)",
                    "https://honors.ucr.edu/",
                    "UC Riverside's University Honors program challenges "
                    "high-achieving undergraduates across all majors with an "
                    "enriched curriculum that culminates in faculty-mentored "
                    "research and a Capstone project. Honors students build a "
                    "close relationship with a faculty mentor while completing an "
                    "original scholarly or creative thesis.",
                    lab_or_program="University Honors",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["honors", "capstone research", "faculty mentor",
                              "thesis"],
                ),
                program(
                    "ucr_cnas_student_research",
                    "CNAS Student Research & Internship Opportunities (UC Riverside)",
                    "https://cnas.ucr.edu/student-research-and-internship-opportunities",
                    "The College of Natural and Agricultural Sciences' hub for "
                    "undergraduate research and internships, listing pathways such "
                    "as the Chancellor's Research Fellowship, UC LEADS, and the "
                    "Summer Bridge to Research program. It points CNAS students "
                    "toward funded, mentored research experiences in the natural "
                    "and agricultural sciences.",
                    lab_or_program="College of Natural and Agricultural Sciences",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research fellowship", "UC LEADS",
                              "summer bridge to research", "natural sciences"],
                ),
            ],
        },
    ],
}
