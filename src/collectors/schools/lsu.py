"""Louisiana State University campus opportunity-graph config.

Curated seed records of LSU's undergraduate-research landscape, centered on the
Office of Undergraduate Research (OUR, www.lsu.edu/our) — its office hub and
"How to Get Involved" guide — plus four flagship OUR-administered programs: the
Distinguished Undergraduate Research Program, the President's Future Leaders in
Research early-research program, the Summer Programs & REUs directory, and the
NSF Gulf Scholars Program. Every URL was curl-verified live (HTTP 200) on
2026-07-20.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> lsu_research_programs (lsu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "lsu",
    "organization": "Louisiana State University",
    "location": "Baton Rouge, LA",
    "emit": {
        "campus": ("lsu_research_programs", "lsu", "campus"),
    },
    "sources": [
        {
            "source_name": "lsu_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.lsu.edu/our/",
                "https://www.lsu.edu/our/students/index.php",
            ],
            "programs": [
                program(
                    "lsu_office_of_undergraduate_research",
                    "Office of Undergraduate Research (Louisiana State University)",
                    "https://www.lsu.edu/our/",
                    "LSU's Office of Undergraduate Research (OUR) helps students of "
                    "every major get involved in research and creative scholarship, "
                    "connecting them with faculty mentors, funding, and structured "
                    "programs. It is the campus hub for finding a mentor, learning "
                    "how to get started, and applying for research funding and "
                    "summer opportunities across every college.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "lsu_get_involved_in_research",
                    "How to Get Involved in Undergraduate Research (LSU Office of Undergraduate Research)",
                    "https://www.lsu.edu/our/students/index.php",
                    "OUR's step-by-step guide for LSU undergraduates on getting "
                    "started in research: how to identify faculty mentors and labs, "
                    "search the campus Mentor Database, reach out to professors, and "
                    "join a research project or creative endeavor. It walks students "
                    "through the first steps of finding and contacting a mentor "
                    "across the sciences, engineering, humanities, and the arts.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "mentor database",
                              "contacting faculty", "getting started"],
                ),
                program(
                    "lsu_distinguished_undergraduate_research_program",
                    "Distinguished Undergraduate Research Program (Louisiana State University)",
                    "https://www.lsu.edu/our/students/distinguished-undergraduate-research-program.php",
                    "The Distinguished Undergraduate Research Program recognizes LSU "
                    "students who complete substantial, sustained mentored research "
                    "or creative work with a faculty mentor. Students pursue an "
                    "in-depth project over multiple semesters and earn a formal "
                    "distinction, deepening their research experience and preparing "
                    "for graduate study or research careers.",
                    lab_or_program="Distinguished Undergraduate Research Program",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["mentored research", "research distinction",
                              "independent project", "faculty mentorship"],
                ),
                program(
                    "lsu_presidents_future_leaders_in_research",
                    "President's Future Leaders in Research (Louisiana State University)",
                    "https://www.lsu.edu/our/funding/presidents_future_leaders_in_research.php",
                    "The President's Future Leaders in Research (PFLR) program gives "
                    "first- and second-year LSU students an early start in research "
                    "by pairing them with a faculty mentor and providing an award to "
                    "support a mentored research or creative project. It is designed "
                    "to bring new students into a lab early and build a foundation "
                    "for continued undergraduate research.",
                    lab_or_program="President's Future Leaders in Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["early research", "first-year research",
                              "research award", "faculty-mentored research"],
                ),
                program(
                    "lsu_summer_programs_and_reus",
                    "Summer Programs & REUs at LSU (Office of Undergraduate Research)",
                    "https://www.lsu.edu/our/students/summer-programs-and-reu-s.php",
                    "OUR's directory of summer research programs and NSF Research "
                    "Experiences for Undergraduates (REU) sites hosted at LSU. These "
                    "full-time summer programs place undergraduates — LSU students "
                    "and visiting students alike — in faculty labs across the "
                    "sciences and engineering, typically with a stipend, housing, "
                    "and a structured cohort experience.",
                    lab_or_program="Summer Programs & REUs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "REU", "research stipend",
                              "faculty-mentored research"],
                ),
                program(
                    "lsu_gulf_scholars_program",
                    "Gulf Scholars Program (Louisiana State University)",
                    "https://www.lsu.edu/our/funding/gulf_scholars_program.php",
                    "The NSF-supported Gulf Scholars Program engages LSU "
                    "undergraduates in interdisciplinary research and projects "
                    "addressing the environmental, economic, and health challenges "
                    "facing the Gulf of Mexico region. Scholars work with faculty "
                    "mentors and receive funding to pursue applied, "
                    "community-connected research across disciplines.",
                    lab_or_program="Gulf Scholars Program",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["Gulf of Mexico", "interdisciplinary research",
                              "applied research", "research funding"],
                ),
            ],
        },
    ],
}
