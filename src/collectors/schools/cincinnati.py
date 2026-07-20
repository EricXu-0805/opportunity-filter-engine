"""University of Cincinnati campus opportunity-graph config.

Curated seed records of UC's undergraduate-research landscape, centered on the
Office of Research (research.uc.edu) and Campus Life's university-wide student-
research guide, plus two flagship faculty-mentored summer programs: the CEAS
UPRISE summer research fellowship and the College of Medicine Summer
Undergraduate Research Fellowships (SURF). Every URL was curl-verified live
(HTTP 200 through the proxy) on 2026-07-20; the WISE/UPRISE program URL resolves
to its current canonical CEAS path (www.wise.uc.edu now 301-redirects to
``www.ceas.uc.edu/research/undergraduate/uprise.html``).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> cincinnati_research_programs (cincinnati / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "cincinnati",
    "organization": "University of Cincinnati",
    "location": "Cincinnati, OH",
    "emit": {
        "campus": ("cincinnati_research_programs", "cincinnati", "campus"),
    },
    "sources": [
        {
            "source_name": "cincinnati_research_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://research.uc.edu/",
                "https://www.uc.edu/campus-life/career-co-op-support/gain-experience/student-research.html",
            ],
            "programs": [
                program(
                    "cincinnati_office_of_research",
                    "Office of Research (University of Cincinnati)",
                    "https://research.uc.edu/",
                    "The University of Cincinnati Office of Research is the "
                    "campus hub for research across every college, connecting "
                    "students and faculty with funding, core facilities, and "
                    "research programs. For undergraduates it is the starting "
                    "point for finding faculty mentors and research "
                    "opportunities university-wide, from the sciences and "
                    "engineering to medicine and the humanities.",
                    lab_or_program="Office of Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "research funding", "any major"],
                ),
                program(
                    "cincinnati_undergraduate_research_guide",
                    "Undergraduate Research: Getting Started (University of Cincinnati)",
                    "https://www.uc.edu/campus-life/career-co-op-support/gain-experience/student-research/getting-started.html",
                    "Campus Life's university-wide guide to getting started in "
                    "undergraduate research at UC: how to identify your "
                    "interests, find a faculty mentor through the UC Research "
                    "Directory, reach out professionally, and explore "
                    "college-specific research centers and funding. It stresses "
                    "that research requires no prior experience — just curiosity "
                    "— and points students toward mentored projects across every "
                    "discipline.",
                    lab_or_program="Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "research directory",
                              "contacting faculty", "getting started"],
                ),
                program(
                    "cincinnati_uprise",
                    "UPRISE Summer Research Program (University of Cincinnati)",
                    "https://www.ceas.uc.edu/research/undergraduate/uprise.html",
                    "UPRISE is a 12-week immersive summer research program for UC "
                    "undergraduates passionate about STEMM fields. Students work "
                    "on cutting-edge research projects under a faculty mentor, "
                    "attend weekly professional-development workshops, and present "
                    "their findings to the university community. Participants "
                    "receive a $6,000 stipend distributed over six biweekly "
                    "payments during the program.",
                    lab_or_program="UPRISE Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 summer stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "STEMM research",
                              "faculty-mentored research", "research stipend"],
                ),
                program(
                    "cincinnati_surf",
                    "Summer Undergraduate Research Fellowships (UC College of Medicine)",
                    "https://med.uc.edu/education/graduate-education/summer-undergraduate-research-fellowships",
                    "The College of Medicine's Summer Undergraduate Research "
                    "Fellowships (SURF) place undergraduates in a 10-week, "
                    "full-time mentored research project in a faculty member's "
                    "laboratory, spanning clinical, translational, and basic "
                    "biomedical research. Designed for sophomore- and "
                    "junior-level students, the program awards fellowships each "
                    "summer with a stipend and structured career-development "
                    "programming.",
                    lab_or_program="Summer Undergraduate Research Fellowships",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["biomedical research", "summer research",
                              "faculty-mentored research", "research stipend"],
                ),
            ],
        },
    ],
}
