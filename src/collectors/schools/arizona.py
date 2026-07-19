"""University of Arizona campus opportunity-graph config.

Curated seed records of the University of Arizona's undergraduate-research
landscape, centered on the Office of Undergraduate Research (ur.arizona.edu)
and its program catalog for UA students, plus the campus-wide Undergraduate
Research Opportunities Consortium (UROC), the UA/NASA Space Grant
undergraduate internship, and the Undergraduate Biology Research Program
(UBRP). URLs curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → arizona_research_programs (arizona / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "arizona",
    "organization": "University of Arizona",
    "location": "Tucson, AZ",
    "emit": {
        "campus": ("arizona_research_programs", "arizona", "campus"),
    },
    "sources": [
        {
            "source_name": "arizona_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ur.arizona.edu/",
                "https://research.arizona.edu/undergraduate-research-opportunities-consortium-uroc",
                "https://spacegrant.arizona.edu/students/u-internships",
                "https://ubrp.arizona.edu/",
            ],
            "programs": [
                program(
                    "arizona_office_undergraduate_research",
                    "Office of Undergraduate Research (University of Arizona)",
                    "https://ur.arizona.edu/",
                    "The University of Arizona's Office of Undergraduate "
                    "Research is the central hub for getting involved in "
                    "research as an undergraduate. It helps students find "
                    "research across every college, connect with faculty "
                    "mentors and labs, and access campus research programs, "
                    "funding, and events — from first steps through presenting "
                    "and publishing work.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research opportunities",
                              "faculty mentorship", "getting started"],
                ),
                program(
                    "arizona_ur_programs_for_students",
                    "Undergraduate Research Programs for UA Students (University of Arizona)",
                    "https://ur.arizona.edu/find-research/programs-ua-students",
                    "A catalog of structured undergraduate-research programs "
                    "open to University of Arizona students, spanning "
                    "summer research institutes, the Undergraduate Biology "
                    "Research Program, Vertically Integrated Projects, SURE and "
                    "REU-style experiences, and the McNair Scholars program. "
                    "Each program pairs students with faculty-mentored research "
                    "and, in many cases, funding or a stipend.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research programs", "summer research",
                              "REU", "McNair Scholars"],
                ),
                program(
                    "arizona_uroc",
                    "Undergraduate Research Opportunities Consortium (UROC, University of Arizona)",
                    "https://research.arizona.edu/undergraduate-research-opportunities-consortium-uroc",
                    "UROC is the University of Arizona's consortium of summer "
                    "undergraduate research programs designed to prepare "
                    "students for graduate school. Participants carry out "
                    "faculty-mentored research projects and take part in "
                    "professional-development and graduate-school-readiness "
                    "programming, with many tracks offering a stipend.",
                    lab_or_program="Undergraduate Research Opportunities Consortium",
                    opportunity_type="summer_program",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["summer research", "graduate school preparation",
                              "faculty-mentored research", "stipend"],
                ),
                program(
                    "arizona_nasa_space_grant",
                    "UA/NASA Space Grant Undergraduate Internship Program (University of Arizona)",
                    "https://spacegrant.arizona.edu/students/u-internships",
                    "The Arizona/NASA Space Grant program funds paid "
                    "academic-year research internships for University of "
                    "Arizona undergraduates. Interns work one-on-one with a "
                    "faculty mentor on a research or public-outreach project in "
                    "a science, engineering, or space-related field, and "
                    "present their work at the statewide Space Grant Symposium.",
                    lab_or_program="Arizona/NASA Space Grant",
                    opportunity_type="internship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["paid internship", "NASA", "space grant",
                              "faculty mentor"],
                ),
                program(
                    "arizona_ubrp",
                    "Undergraduate Biology Research Program (UBRP, University of Arizona)",
                    "https://ubrp.arizona.edu/",
                    "UBRP is a long-running University of Arizona program that "
                    "places undergraduates in biology-related research labs to "
                    "work alongside faculty and graduate mentors, with a paid "
                    "research experience and a supportive research community. "
                    "It anchors a family of affiliated programs (including "
                    "Beckman, BRAVO, and PHIRE) for students across the life "
                    "and biomedical sciences.",
                    lab_or_program="Undergraduate Biology Research Program",
                    opportunity_type="summer_program",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["biology research", "paid research",
                              "life sciences", "research community"],
                ),
            ],
        },
    ],
}
