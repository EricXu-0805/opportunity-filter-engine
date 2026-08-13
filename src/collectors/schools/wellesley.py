"""Wellesley College campus opportunity-graph config.

Curated seed records of Wellesley's undergraduate-research landscape, centered
on the Academics → Student Research hub, which describes the college's named
mentored-research programs and fellowships. Wellesley advertises one of the
highest undergraduate research publication rates among liberal arts colleges;
the programs below span first-year apprenticeships through the flagship
Wellesley Summer Research Program and competitive national fellowships.
URLs curl-verified live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → wellesley_research_programs (wellesley / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_HUB = "https://www.wellesley.edu/academics/student-research"

SCHOOL: dict = {
    "school_slug": "wellesley",
    "organization": "Wellesley College",
    "location": "Wellesley, MA",
    "emit": {
        "campus": ("wellesley_research_programs", "wellesley", "campus"),
    },
    "sources": [
        {
            "source_name": "wellesley_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _HUB,
                "https://urop.mit.edu/deadlines/audience/wellesley-students/",
            ],
            "programs": [
                program(
                    "wellesley_summer_research",
                    "Wellesley Summer Research Program",
                    _HUB,
                    "Students work with faculty full-time for nine weeks over "
                    "the summer on research projects in the natural and social "
                    "sciences. Participants live on campus and receive a "
                    "stipend, and present a research poster at the end of the "
                    "program.",
                    lab_or_program="Wellesley Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["summer research", "faculty mentor",
                              "natural sciences", "social sciences", "stipend"],
                ),
                program(
                    "wellesley_science_center_summer",
                    "Science Center Summer Research Program (Wellesley)",
                    _HUB,
                    "The Wellesley Science Center summer program lets student "
                    "researchers work on projects alongside faculty in the "
                    "natural sciences, gaining hands-on laboratory and field "
                    "research experience over the summer.",
                    lab_or_program="Wellesley Science Center",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["science research", "laboratory", "summer",
                              "faculty mentor"],
                ),
                program(
                    "wellesley_first_year_apprentice",
                    "First-Year Student Research Apprentice Program (Wellesley)",
                    _HUB,
                    "A spring-semester program providing apprenticeships in "
                    "faculty labs so first-year students with little or no "
                    "research experience can build research skills and "
                    "confidence, with faculty support toward applying for the "
                    "Wellesley Summer Research Program.",
                    lab_or_program="Student Research (Wellesley)",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    keywords=["first-year", "research apprenticeship",
                              "faculty lab", "mentorship"],
                ),
                program(
                    "wellesley_sophomore_early_research",
                    "Sophomore Early Research Program (Wellesley)",
                    _HUB,
                    "Students with limited research experience in the natural "
                    "and social sciences undertake collaborative research "
                    "projects with faculty mentors during the academic year. "
                    "These are work-study positions open to students who are "
                    "first-generation or low income/high need.",
                    lab_or_program="Sophomore Early Research Program",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore"],
                    international_friendly="unknown",
                    keywords=["early research", "faculty mentor", "work-study",
                              "first-generation"],
                ),
                program(
                    "wellesley_wintersession_research",
                    "Wintersession Research Week (Wellesley)",
                    _HUB,
                    "During January's Wintersession, students immerse "
                    "themselves in on-campus science research mentored by "
                    "graduate students from local medical schools, conducting "
                    "hands-on experiments and building basic laboratory skills.",
                    lab_or_program="Wintersession Research Week",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["wintersession", "laboratory skills",
                              "science research", "mentorship"],
                ),
                program(
                    "wellesley_knapp_social_science",
                    "Knapp Fellows Program in the Social Sciences (Wellesley)",
                    _HUB,
                    "Knapp Fellows receive a stipend and are matched with a "
                    "faculty member for collaborative one-on-one research work "
                    "during the academic year, an introduction to the "
                    "challenges and excitements of scholarly life in the "
                    "social sciences.",
                    lab_or_program="Knapp Fellows Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["social sciences", "faculty mentor",
                              "fellowship", "stipend"],
                ),
                program(
                    "wellesley_beckman_scholars",
                    "Beckman Scholars Program (Wellesley)",
                    _HUB,
                    "Sophomores and juniors excelling in their science courses "
                    "and showing exceptional promise for independent research "
                    "receive stipends for two summers of the Wellesley Summer "
                    "Research Program plus academic-year research, supplies, "
                    "and conference travel, completing an honors thesis.",
                    lab_or_program="Beckman Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["chemistry", "biochemistry", "independent research",
                              "honors thesis", "stipend"],
                ),
                program(
                    "wellesley_mellon_mays",
                    "Mellon Mays Undergraduate Fellowship (Wellesley)",
                    _HUB,
                    "MMUF supports students from underrepresented groups "
                    "through mentorship, research funding in the humanities and "
                    "social sciences, conference travel, and professional "
                    "development, preparing fellows for doctoral training and "
                    "faculty careers in higher education.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["humanities", "social sciences", "research funding",
                              "doctoral preparation", "mentorship"],
                ),
                program(
                    "wellesley_mcnair",
                    "Ronald E. McNair Post-Baccalaureate Scholarship Program (Wellesley)",
                    _HUB,
                    "A federally funded program supporting low-income, "
                    "potential first-generation students from underrepresented "
                    "backgrounds through mentored research and scholarly "
                    "activities, sponsoring summer research and conference "
                    "travel as they prepare for doctoral study in STEM.",
                    lab_or_program="McNair Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    keywords=["STEM", "doctoral preparation", "summer research",
                              "first-generation", "mentorship"],
                ),
                program(
                    "wellesley_mit_urop",
                    "MIT UROP for Wellesley Students",
                    "https://urop.mit.edu/deadlines/audience/wellesley-students/",
                    "Wellesley students cross-registered at MIT can apply to "
                    "MIT's Undergraduate Research Opportunities Program to work "
                    "with MIT faculty and researchers on real-world research "
                    "projects across science and engineering.",
                    lab_or_program="MIT UROP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["MIT", "cross-registration", "engineering",
                              "faculty research"],
                ),
            ],
        },
    ],
}
