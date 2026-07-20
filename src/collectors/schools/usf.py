"""University of South Florida campus opportunity-graph config.

Curated seed records of USF's undergraduate-research landscape, centered on the
Office of Undergraduate Research / Student Engagement for Research & Innovation
(SERI, usf.edu/research-innovation/undergraduate-research) — its office hub — plus
the flagship SERI-administered pathways: the SERI office itself, the Research
Experiences for Undergraduates (REU) pathway, the per-college research-opportunity
guide, and the One USF Summer Undergraduate Research Symposium. Every URL was
curl-verified live (HTTP 200) on 2026-07-20.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → usf_research_programs (usf / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_UR = "https://www.usf.edu/research-innovation/undergraduate-research"

SCHOOL: dict = {
    "school_slug": "usf",
    "organization": "University of South Florida",
    "location": "Tampa, FL",
    "emit": {
        "campus": ("usf_research_programs", "usf", "campus"),
    },
    "sources": [
        {
            "source_name": "usf_undergraduate_research_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_UR}/index.aspx",
                f"{_UR}/seri.aspx",
            ],
            "programs": [
                program(
                    "usf_undergraduate_research_office",
                    "Undergraduate Research at USF (Student Engagement for Research & Innovation)",
                    f"{_UR}/index.aspx",
                    "USF's Office of Undergraduate Research, run by Student "
                    "Engagement for Research & Innovation (SERI), is the campus hub "
                    "for getting involved in research and creative scholarship. It "
                    "helps students of every major find faculty mentors, join labs, "
                    "earn research credit, and access funding, symposia, and "
                    "conferences across USF's Tampa, St. Petersburg, and "
                    "Sarasota-Manatee campuses.",
                    lab_or_program="Student Engagement for Research & Innovation",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "any major", "getting started"],
                ),
                program(
                    "usf_seri_office",
                    "Student Engagement for Research & Innovation (SERI) — University of South Florida",
                    f"{_UR}/seri.aspx",
                    "The SERI office supports high-impact learning opportunities — "
                    "particularly undergraduate research — across all USF campuses. "
                    "SERI connects students with mentors and research experiences, "
                    "helps them present and publish their work, and supports faculty "
                    "in mentoring undergraduate researchers. It is the front door "
                    "for students looking to start doing research at USF.",
                    lab_or_program="Student Engagement for Research & Innovation",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["research mentorship", "high-impact learning",
                              "finding a mentor", "getting started"],
                ),
                program(
                    "usf_reu",
                    "Research Experiences for Undergraduates (REU) at USF",
                    f"{_UR}/research-experiences-for-undergraduates.aspx",
                    "USF's Research Experiences for Undergraduates (REU) pathway "
                    "points students to NSF-funded and USF-hosted summer REU "
                    "programs, where undergraduates join a faculty-led research "
                    "project full time over the summer, typically with a stipend. "
                    "REU sites span the sciences and engineering and are open to "
                    "students from USF and other institutions.",
                    lab_or_program="Research Experiences for Undergraduates",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "research stipend",
                              "faculty-mentored research"],
                ),
                program(
                    "usf_college_research_opportunities",
                    "Research Opportunities with USF Colleges",
                    f"{_UR}/student-research-expriences-with-usf-colleges.aspx",
                    "A guide to undergraduate research opportunities offered within "
                    "USF's individual colleges — from Arts & Sciences and "
                    "Engineering to Public Health and Business. Part of USF's "
                    "experiential-learning plan (ExCEL), it helps students find "
                    "college-specific research programs, courses, and faculty "
                    "mentors in their own field of study.",
                    lab_or_program="USF Colleges Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["college research", "research courses",
                              "faculty mentorship", "experiential learning"],
                ),
                program(
                    "usf_summer_research_symposium",
                    "One USF Summer Undergraduate Research Symposium",
                    f"{_UR}/one-usf-summer-undergraduate-research-symposium-2026.aspx",
                    "The One USF Summer Undergraduate Research Symposium is an "
                    "annual event where undergraduates from across USF's campuses "
                    "present the research and creative projects they carried out "
                    "over the summer. It is a venue to share results, get feedback, "
                    "and connect with faculty mentors and fellow student "
                    "researchers.",
                    lab_or_program="One USF Summer Undergraduate Research Symposium",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research symposium", "summer research",
                              "presenting research", "undergraduate research"],
                ),
            ],
        },
    ],
}
