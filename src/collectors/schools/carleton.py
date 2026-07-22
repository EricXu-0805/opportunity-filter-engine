"""Carleton College campus opportunity-graph config.

Curated seed records of Carleton's undergraduate-research landscape. Carleton
is a top-10 liberal arts college with an unusually strong science-research
culture: research is undergraduate-only and faculty-mentored, so these programs
are the funded routes into a professor's lab or scholarly project. The picture
centers on Carleton Integrated Math & Science (CISMI) — which fielded ~100
faculty-mentored summer science researchers in 2025 — the paid Student Research
Partner (SRP) appointments, the Summer Science Fellowship, and the Office of
Student Fellowships' portfolio of named Carleton-funded research fellowships.
All URLs verified live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → carleton_research_programs (carleton / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_YEARS = ["freshman", "sophomore", "junior", "senior"]

SCHOOL: dict = {
    "school_slug": "carleton",
    "organization": "Carleton College",
    "location": "Northfield, MN",
    "emit": {
        "campus": ("carleton_research_programs", "carleton", "campus"),
    },
    "sources": [
        {
            "source_name": "carleton_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.carleton.edu/fellowships/",
                "https://www.carleton.edu/math-science/for-students/"
                "undergraduate-research-in-stem/",
                "https://www.carleton.edu/research/for-students/"
                "faculty-directed-research/",
            ],
            "programs": [
                program(
                    "fellowships_hub",
                    "Carleton Office of Student Fellowships",
                    "https://www.carleton.edu/fellowships/",
                    "The central hub for Carleton's funded fellowships and "
                    "research awards. The office advises students on finding a "
                    "faculty mentor, developing a research or creative project, "
                    "and applying for both Carleton-funded and nationally "
                    "competitive fellowships across the sciences, social "
                    "sciences, humanities, and arts.",
                    lab_or_program="Office of Student Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["undergraduate research", "fellowships",
                              "faculty-mentored research"],
                ),
                program(
                    "stem_undergraduate_research",
                    "Undergraduate Research in STEM (Carleton Integrated Math & Science)",
                    "https://www.carleton.edu/math-science/for-students/"
                    "undergraduate-research-in-stem/",
                    "Carleton Integrated Math & Science (CISMI) coordinates "
                    "faculty-mentored research across every science and math "
                    "department — biology, chemistry, physics and astronomy, "
                    "geology, mathematics and statistics, computer science, "
                    "psychology, neuroscience, biochemistry, and environmental "
                    "science. Around 100 students do full-time faculty-mentored "
                    "science research each summer and hundreds more during the "
                    "academic year.",
                    lab_or_program="Carleton Integrated Math & Science (CISMI)",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Biology", "Chemistry", "Physics",
                                        "Geology", "Mathematics", "Computer Science",
                                        "Psychology", "Neuroscience", "Biochemistry",
                                        "Environmental Studies"],
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["STEM research", "summer research",
                              "faculty-mentored research"],
                ),
                program(
                    "student_research_partners",
                    "Faculty-Directed Research — Student Research Partners (SRP)",
                    "https://www.carleton.edu/research/for-students/"
                    "faculty-directed-research/",
                    "Student Research Partner (SRP) appointments place students "
                    "in a faculty member's research under direct supervision, "
                    "full-time over summer or winter break (three to ten weeks) "
                    "and part-time during the term. SRP positions are paid at a "
                    "standard hourly rate and are the primary paid route into "
                    "faculty research at Carleton.",
                    lab_or_program="Student Research Partners",
                    opportunity_type="research",
                    paid="yes",
                    compensation="Paid hourly (standard College research rate)",
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["paid research", "faculty-directed research",
                              "research assistantship"],
                ),
                program(
                    "summer_science_fellowship",
                    "Carleton Summer Science Fellowship",
                    "https://www.carleton.edu/math-science/for-students/summer-fellows/",
                    "A two-summer research-support fellowship aimed at broadening "
                    "participation in the sciences and math among students from "
                    "backgrounds historically underrepresented in STEM. Fellows "
                    "receive weekly funding for up to ten weeks of full-time "
                    "summer research, working with a Carleton faculty mentor or "
                    "with scientific investigators elsewhere.",
                    lab_or_program="Summer Science Fellowship",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Biology", "Chemistry", "Physics",
                                        "Geology", "Mathematics", "Computer Science",
                                        "Neuroscience"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "STEM research",
                              "broadening participation"],
                ),
                program(
                    "physics_summer_research",
                    "Summer Research in Physics and Astronomy",
                    "https://www.carleton.edu/physics-astronomy/opportunities/"
                    "research/summer-research/",
                    "Funded full-time summer research positions in the Department "
                    "of Physics and Astronomy, in which students join a faculty "
                    "member's lab or observational program — gravitational-wave "
                    "and astrophysics, optics, condensed matter, and more — for "
                    "an intensive summer of mentored research.",
                    lab_or_program="Physics and Astronomy Summer Research",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Physics", "Astronomy"],
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["physics research", "astronomy", "summer research"],
                ),
                program(
                    "research_creative_fellowships",
                    "Carleton Fellowships for Research and Creative/Artistic Projects",
                    "https://www.carleton.edu/fellowships/carleton-fellowships/research/",
                    "The umbrella for Carleton-funded fellowships that support an "
                    "independent, faculty-mentored research project or a creative/"
                    "artistic project — funding students to pursue their own "
                    "scholarly or artistic work over the summer or during the "
                    "academic year through a family of named endowed fellowships.",
                    lab_or_program="Fellowships for Research and Creative Projects",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["independent research", "creative projects",
                              "research fellowship"],
                ),
                program(
                    "class_1963_fellowship",
                    "Class of 1963 Fellowship",
                    "https://www.carleton.edu/fellowships/carleton-fellowships/"
                    "research/1963-2/",
                    "A Carleton-funded fellowship supporting a student's "
                    "self-designed research or independent project, giving "
                    "undergraduates the resources to carry out sustained "
                    "faculty-mentored scholarly work of their own design.",
                    lab_or_program="Class of 1963 Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="unknown",
                    keywords=["independent research", "research fellowship",
                              "mentored research"],
                ),
                program(
                    "kelley_international_fellowship",
                    "Paul and Lynn Kelley International Fellowship",
                    "https://www.carleton.edu/fellowships/carleton-fellowships/"
                    "research/paul-and-lynn-kelley/",
                    "A Carleton-funded fellowship supporting a student's "
                    "international research or project abroad — funding "
                    "field-based, archival, or comparative research outside the "
                    "United States under faculty guidance.",
                    lab_or_program="Kelley International Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["international research", "research abroad",
                              "field research"],
                ),
                program(
                    "wilkie_archaeology_fellowship",
                    "Nancy Wilkie Fellowship for Archaeological Field Experience",
                    "https://www.carleton.edu/fellowships/carleton-fellowships/"
                    "experiential/wilkie/",
                    "A Carleton-funded fellowship that funds a student's "
                    "participation in an archaeological field school or excavation "
                    "— hands-on field research in archaeology, classics, or "
                    "anthropology at a dig site under professional supervision.",
                    lab_or_program="Nancy Wilkie Fellowship",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Archaeology", "Classics", "Anthropology"],
                    preferred_year=_YEARS,
                    international_friendly="yes",
                    keywords=["archaeology", "field research", "excavation"],
                ),
                program(
                    "national_fellowships",
                    "Carleton National and International Fellowships Advising",
                    "https://www.carleton.edu/fellowships/national/",
                    "Advising and campus endorsement for nationally competitive "
                    "research and scholarship fellowships (Goldwater, Fulbright, "
                    "Watson, and similar), guiding Carleton students through "
                    "proposal writing and the application process for external "
                    "research and graduate-study funding.",
                    lab_or_program="National Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["national fellowships", "research funding",
                              "graduate study"],
                ),
            ],
        },
    ],
}
