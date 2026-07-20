"""University at Buffalo (SUNY) campus opportunity-graph config.

Curated seed records of UB's undergraduate-research landscape, centered on the
Office for Undergraduate Research (OUR, www.buffalo.edu/undergrad-research) — the
campus hub — plus four named programs: the university-wide Research Experiences
for Undergraduates (REU) portal, the NSF REU listing run by the Office of
Fellowships and Scholarships, the Biological Sciences Summer REU, and OUR's
Undergraduate Research Project Funding award. Every URL was curl-verified live
(HTTP 200) on 2026-07-20.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> buffalo_research_programs (buffalo / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "buffalo",
    "organization": "University at Buffalo",
    "location": "Buffalo, NY",
    "emit": {
        "campus": ("buffalo_research_programs", "buffalo", "campus"),
    },
    "sources": [
        {
            "source_name": "buffalo_our_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.buffalo.edu/undergrad-research.html",
                "https://www.buffalo.edu/undergrad-research/opportunities.html",
            ],
            "programs": [
                program(
                    "buffalo_office_for_undergraduate_research",
                    "Office for Undergraduate Research (University at Buffalo)",
                    "https://www.buffalo.edu/undergrad-research.html",
                    "UB's Office for Undergraduate Research (OUR) is the campus hub "
                    "for getting involved in research and creative activity in any "
                    "major. It helps students find faculty mentors, get started in "
                    "a lab, secure funding, and share their work — pointing to "
                    "opportunities across engineering, the sciences, humanities, "
                    "and the social sciences.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "any major", "getting started"],
                ),
                program(
                    "buffalo_find_research_opportunities",
                    "Find Research Opportunities (UB Office for Undergraduate Research)",
                    "https://www.buffalo.edu/undergrad-research/opportunities.html",
                    "OUR's guide to finding undergraduate research at UB: how to "
                    "identify labs and faculty mentors, browse posted research "
                    "positions, and connect with departments across campus. It "
                    "walks students through the first steps of joining a research "
                    "project or creative endeavor.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "research positions",
                              "contacting faculty", "getting started"],
                ),
                program(
                    "buffalo_reu",
                    "Research Experiences for Undergraduates (University at Buffalo)",
                    "https://www.buffalo.edu/reu.html",
                    "UB's Research Experiences for Undergraduates (REU) portal "
                    "supports active research participation by undergraduates in "
                    "areas funded by the National Science Foundation, hosting "
                    "faculty-led summer REU sites across the School of Engineering "
                    "and Applied Sciences and the College of Arts and Sciences "
                    "(e.g. biometrics and authentication, environmental "
                    "engineering). REU sites are open to students from UB and other "
                    "institutions and typically carry a summer stipend.",
                    lab_or_program="Research Experiences for Undergraduates",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "NSF",
                              "faculty-mentored research"],
                ),
                program(
                    "buffalo_nsf_reu_fellowships",
                    "NSF Research Experiences for Undergraduates (UB Office of Fellowships and Scholarships)",
                    "https://www.buffalo.edu/fellowships/funding/nsf-reu.html",
                    "The Office of Fellowships and Scholarships' guide to NSF-funded "
                    "Research Experiences for Undergraduates: nationally competitive "
                    "summer research programs, hosted at UB and at universities "
                    "across the country, that place undergraduates in active labs "
                    "with a stipend and often housing and travel support.",
                    lab_or_program="Office of Fellowships and Scholarships",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["NSF REU", "summer research", "national program",
                              "research stipend"],
                ),
                program(
                    "buffalo_biology_summer_reu",
                    "Summer Research Experience for Undergraduates in Biological Sciences (University at Buffalo)",
                    "https://arts-sciences.buffalo.edu/biological-sciences/undergraduate/experiential-learning/summer-research.html",
                    "The Department of Biological Sciences' Summer Research "
                    "Experience for Undergraduates is an immersive, eight-week "
                    "program of hands-on, faculty-mentored research in the "
                    "life sciences, giving undergraduates full-time bench and field "
                    "research experience over the summer.",
                    lab_or_program="Department of Biological Sciences Summer REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "biology", "life sciences",
                              "eight-week program"],
                ),
                program(
                    "buffalo_undergraduate_research_project_funding",
                    "Undergraduate Research Project Funding (UB Office for Undergraduate Research)",
                    "https://www.buffalo.edu/undergrad-research/get-started/funding/project.html",
                    "OUR's Project Funding award supports faculty-mentored "
                    "undergraduate research with materials and supplies. It is open "
                    "to current UB undergraduates whose projects have not previously "
                    "received the award — individual students may receive up to $750 "
                    "and groups up to $1,000.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="yes",
                    compensation="Up to $750 per student / $1,000 per group for materials and supplies",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research funding", "project award",
                              "faculty-mentored research", "materials and supplies"],
                ),
            ],
        },
    ],
}
