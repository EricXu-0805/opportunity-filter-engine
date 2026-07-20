"""Tufts University campus opportunity-graph config.

Curated seed records of Tufts' undergraduate-research landscape, centered on
the AS&E Scholarship & Research hub (Summer Scholars, the VERSE early-research
immersion, and the Undergraduate Research Fund) plus the university-wide
Laidlaw Scholars leadership-research program, the Beckman Scholars biochemistry
fellowship, the Dewald chemistry summer scholarship, and the Tisch College
Summer Fellows civic program. URLs curl-verified live (HTTP 200) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → tufts_research_programs (tufts / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "tufts",
    "organization": "Tufts University",
    "location": "Medford, MA",
    "emit": {
        "campus": ("tufts_research_programs", "tufts", "campus"),
    },
    "sources": [
        {
            "source_name": "tufts_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://students.tufts.edu/academic-advising-and-undergraduate-studies/scholarship-and-research/internal-research-opportunities",
                "https://provost.tufts.edu/laidlaw-scholars-program/",
            ],
            "programs": [
                program(
                    "tufts_internal_research_hub",
                    "Internal Research Opportunities and Funding (Tufts AS&E)",
                    "https://students.tufts.edu/academic-advising-and-undergraduate-studies/scholarship-and-research/internal-research-opportunities",
                    "The AS&E Scholarship & Research office's hub of internal "
                    "undergraduate research opportunities and funding — Summer "
                    "Scholars, the VERSE early-research program, the "
                    "Undergraduate Research Fund, the Beckman and Laidlaw "
                    "scholarships, and discipline-specific summer awards across "
                    "Arts, Sciences, and Engineering.",
                    lab_or_program="Scholarship & Research (AS&E)",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research funding",
                              "fellowships", "faculty mentorship"],
                ),
                program(
                    "tufts_summer_scholars",
                    "Tufts Summer Scholars Program",
                    "https://students.tufts.edu/academic-advising-and-undergraduate-studies/scholarship-and-research/summer-scholars-program",
                    "A ten-week summer program in which undergraduates work "
                    "closely with faculty from any of the Tufts campuses on an "
                    "independent research project of their own design, "
                    "supported by a summer stipend. Open to all disciplines; "
                    "scholars present their work at a fall research symposium.",
                    lab_or_program="Summer Scholars",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "independent project",
                              "faculty mentor", "stipend"],
                ),
                program(
                    "tufts_verse",
                    "VERSE — Visiting and Early Research Scholars' Experiences (Tufts)",
                    "https://students.tufts.edu/academic-advising-and-undergraduate-studies/scholarship-and-research/verse-program",
                    "A ten-week summer research immersion for undergraduates "
                    "who have not yet had a research opportunity, providing a "
                    "summer stipend, meal plan, and on-campus summer housing "
                    "while students join a Tufts faculty lab.",
                    lab_or_program="VERSE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["early research", "summer immersion",
                              "stipend", "housing"],
                ),
                program(
                    "tufts_undergrad_research_fund",
                    "Tufts Undergraduate Research Fund",
                    "https://students.tufts.edu/academic-advising-and-undergraduate-studies/scholarship-and-research/undergraduate-research-fund",
                    "Provides funding for senior theses and other proposals "
                    "emphasizing original research, and supports travel to a "
                    "conference for students presenting their research. Open to "
                    "undergraduates across Arts, Sciences, and Engineering.",
                    lab_or_program="Undergraduate Research Fund",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    keywords=["senior thesis", "research funding",
                              "conference travel", "original research"],
                ),
                program(
                    "tufts_laidlaw",
                    "Tufts Laidlaw Scholars Program",
                    "https://provost.tufts.edu/laidlaw-scholars-program/",
                    "An 18-month leadership-and-research program selecting "
                    "student-faculty pairs for two consecutive six-week summer "
                    "research projects (in any discipline) alongside a "
                    "leadership-development curriculum and membership in the "
                    "global Laidlaw scholars network.",
                    lab_or_program="Laidlaw Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore"],
                    international_friendly="yes",
                    keywords=["leadership", "summer research", "any discipline",
                              "faculty mentor"],
                ),
                program(
                    "tufts_beckman_scholars",
                    "Tufts Beckman Scholars Program",
                    "https://sites.tufts.edu/beckmanscholars/",
                    "A prestigious in-depth research experience funding two "
                    "summers of full-time and one academic year of part-time "
                    "mentored research in chemistry and biochemistry, with "
                    "research supplies and travel support; scholars pursue "
                    "independent projects culminating in first-author work.",
                    lab_or_program="Beckman Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["biochemistry", "chemistry", "mentored research",
                              "stipend"],
                ),
                program(
                    "tufts_dewald_chem",
                    "Robert R. Dewald Undergraduate Summer Scholarship (Tufts Chemistry)",
                    "https://chem.tufts.edu/research/robert-r-dewald-summer-scholarship-award",
                    "Supports Chemistry and Biochemistry majors in a summer "
                    "research project in a laboratory setting with a Tufts "
                    "Chemistry faculty member.",
                    lab_or_program="Department of Chemistry",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["chemistry", "biochemistry", "summer research",
                              "laboratory"],
                ),
                program(
                    "tufts_tisch_summer_fellows",
                    "Tisch Summer Fellows (Tufts Tisch College of Civic Life)",
                    "https://tischcollege.tufts.edu/programs-major/programs-undergraduates/tisch-summer-fellows",
                    "A summer program placing undergraduates with community-"
                    "based advocacy organizations, national non-profits, "
                    "government agencies, and elected officials for "
                    "professional and career development in democracy-building "
                    "and civic work.",
                    lab_or_program="Tisch College of Civic Life",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["civic engagement", "public service",
                              "advocacy", "career development"],
                ),
            ],
        },
    ],
}
