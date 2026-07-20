"""Worcester Polytechnic Institute campus opportunity-graph config.

Curated seed records of WPI's distinctive project-based-learning landscape,
centered on the Project-Based Learning hub and the three flagship undergraduate
project experiences every WPI student completes: the Major Qualifying Project
(MQP, the major-field research/design capstone), the Interactive Qualifying
Project (IQP, the interdisciplinary science-technology-society project), and the
Global Projects Program (the network of 50+ project centers where students carry
out those projects worldwide). Every URL was curl-verified live (HTTP 200)
through the proxy on 2026-07-20 — WPI's edge returns 403 for bad slugs, so a 200
confirms a real page.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> wpi_research_programs (wpi / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "wpi",
    "organization": "Worcester Polytechnic Institute",
    "location": "Worcester, MA",
    "emit": {
        "campus": ("wpi_research_programs", "wpi", "campus"),
    },
    "sources": [
        {
            "source_name": "wpi_project_based_learning_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.wpi.edu/project-based-learning",
            ],
            "programs": [
                program(
                    "wpi_project_based_learning",
                    "Project-Based Learning (Worcester Polytechnic Institute)",
                    "https://www.wpi.edu/project-based-learning",
                    "WPI's signature undergraduate model puts students on "
                    "team-driven, open-ended projects that tackle real-world "
                    "challenges, working alongside faculty mentors from their "
                    "first year through a professional-level capstone. It is the "
                    "campus hub for how WPI students get into hands-on research "
                    "and project work across every major.",
                    lab_or_program="Project-Based Learning",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["project-based learning", "faculty mentorship",
                              "hands-on research", "any major"],
                ),
                program(
                    "wpi_major_qualifying_project",
                    "Major Qualifying Project (MQP) — Worcester Polytechnic Institute",
                    "https://www.wpi.edu/academics/undergraduate/major-qualifying-project",
                    "The Major Qualifying Project (MQP) is WPI's senior-year "
                    "research and design capstone: a professional-level project "
                    "in the student's major field, carried out in a faculty "
                    "member's lab or research group over roughly a year. It is "
                    "the core undergraduate-research experience at WPI, where "
                    "students produce original work under direct faculty "
                    "mentorship.",
                    lab_or_program="Major Qualifying Project",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    keywords=["MQP", "capstone research", "faculty-mentored research",
                              "major field project"],
                ),
                program(
                    "wpi_interactive_qualifying_project",
                    "Interactive Qualifying Project (IQP) — Worcester Polytechnic Institute",
                    "https://www.wpi.edu/academics/undergraduate/interactive-qualifying-project",
                    "The Interactive Qualifying Project (IQP) is WPI's "
                    "interdisciplinary junior-year project addressing how science "
                    "and technology intersect with societal needs. Students work "
                    "in teams with faculty advisors — often at a global project "
                    "center — to research and deliver solutions for a real "
                    "community or organization, gaining research and fieldwork "
                    "experience across disciplines.",
                    lab_or_program="Interactive Qualifying Project",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["IQP", "interdisciplinary project",
                              "science technology society", "community research"],
                ),
                program(
                    "wpi_global_projects_program",
                    "Global Projects Program (Worcester Polytechnic Institute)",
                    "https://www.wpi.edu/project-based-learning/project-based-education/global-project-program",
                    "WPI's Global Projects Program sends student teams to a "
                    "network of 50+ project centers on six continents to complete "
                    "their IQP or MQP research in a local community. Science, "
                    "engineering, and business undergraduates apply to spend a "
                    "term doing mentored, hands-on project work that makes a "
                    "tangible impact, either internationally or at a domestic "
                    "center.",
                    lab_or_program="Global Projects Program",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["global projects", "project centers",
                              "off-campus research", "faculty-mentored project"],
                ),
            ],
        },
    ],
}
