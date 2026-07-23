"""Smith College campus opportunity-graph config.

Curated seed records of Smith's undergraduate-research and funded-internship
landscape, centered on the Clark Science Center's Summer Research Fellowship
(SURF) — the college's flagship paid summer research program — together with
the college-wide STRIDE mentored-research program, the Kahn Liberal Arts
Institute research fellowships, the Lazarus Center Praxis internship-funding
guarantee, the AEMES program and its McKinley Honors Fellowships, and the
NIST-SURF federal-lab partnership. URLs curl-verified live (HTTP 200) on
2026-07-22.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → smith_research_programs (smith / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_UGR = "https://www.smith.edu/academics/integrative-learning/undergraduate-research"

SCHOOL: dict = {
    "school_slug": "smith",
    "organization": "Smith College",
    "location": "Northampton, MA",
    "emit": {
        "campus": ("smith_research_programs", "smith", "campus"),
    },
    "sources": [
        {
            "source_name": "smith_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _UGR,
                "https://www.science.smith.edu/student-opportunities/",
            ],
            "programs": [
                program(
                    "smith_surf",
                    "Summer Research Fellowship (SURF) — Clark Science Center",
                    "http://www.science.smith.edu/student-opportunities/surf/",
                    "Smith's flagship summer research program: roughly ten "
                    "weeks of full-time, paid, faculty-mentored research in the "
                    "sciences, mathematics, engineering and beyond through the "
                    "Clark Science Center, with a stipend, campus housing and a "
                    "culminating fall poster session.",
                    lab_or_program="Summer Research Fellowship (SURF)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "STEM"],
                ),
                program(
                    "smith_stride",
                    "STRIDE — Student Research in Departments (Smith)",
                    "https://www.smith.edu/academics/applied-learning-research/"
                    "stride-program",
                    "A two-year mentored-research scholarship pairing selected "
                    "entering students with a faculty member for paid research "
                    "collaboration during the first and second years, across all "
                    "disciplines, to build research skills early in the "
                    "undergraduate career.",
                    lab_or_program="STRIDE",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["mentored research", "faculty mentor",
                              "any discipline", "scholarship"],
                ),
                program(
                    "smith_kahn",
                    "Kahn Liberal Arts Institute — Research Fellowships (Smith)",
                    "https://www.smith.edu/academics/integrative-learning/"
                    "kahn-liberal-arts-institute",
                    "The Kahn Liberal Arts Institute runs year-long "
                    "interdisciplinary research projects in which student "
                    "fellows work alongside faculty fellows and visiting "
                    "scholars on a common theme, spanning the humanities, arts, "
                    "social sciences and sciences.",
                    lab_or_program="Kahn Liberal Arts Institute",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["interdisciplinary research", "faculty mentor",
                              "humanities", "fellowship"],
                ),
                program(
                    "smith_praxis",
                    "Praxis Internship Funding (Smith Lazarus Center)",
                    "https://www.smith.edu/your-campus/offices-services/"
                    "lazarus-center-career-development/internships/praxis-funding",
                    "Smith's Praxis program guarantees every undergraduate one "
                    "funding award for an otherwise-unpaid summer internship, "
                    "including research placements in labs, museums, nonprofits "
                    "and agencies, administered by the Lazarus Center for Career "
                    "Development.",
                    lab_or_program="Praxis",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer internship", "funding", "stipend",
                              "any discipline"],
                ),
                program(
                    "smith_aemes",
                    "AEMES Research Program (Smith)",
                    "https://www.smith.edu/academics/departments-programs-courses/"
                    "aemes",
                    "Achieving Excellence in Mathematics, Engineering and "
                    "Science (AEMES) supports students historically "
                    "underrepresented in STEM with early faculty-mentored "
                    "research placements, peer mentoring and academic-year "
                    "research opportunities in the sciences.",
                    lab_or_program="AEMES",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["STEM", "faculty mentor", "diversity in research",
                              "mentored research"],
                ),
                program(
                    "smith_mckinley",
                    "McKinley Honors Fellowship (AEMES, Smith)",
                    "https://www.smith.edu/academics/departments-programs-courses/"
                    "aemes",
                    "The McKinley Honors Fellowship provides a summer research "
                    "stipend and academic-year support for AEMES students "
                    "pursuing honors-level, faculty-mentored research in the "
                    "sciences and engineering.",
                    lab_or_program="McKinley Honors Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["honors research", "summer research",
                              "faculty mentor", "science"],
                ),
                program(
                    "smith_nist_surf",
                    "NIST-SURF Fellowship (Smith / NIST partnership)",
                    "https://www.science.smith.edu/student-opportunities/"
                    "nist-surf/",
                    "A federal partnership placing Smith science and "
                    "engineering students in paid summer research fellowships at "
                    "the National Institute of Standards and Technology (NIST) "
                    "laboratories in Gaithersburg, Maryland, with a stipend and "
                    "travel support.",
                    lab_or_program="NIST-SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["NIST", "summer research", "federal laboratory",
                              "STEM"],
                ),
            ],
        },
    ],
}
