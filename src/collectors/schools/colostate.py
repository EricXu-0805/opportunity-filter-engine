"""Colorado State University campus opportunity-graph config.

Curated seed records of CSU's undergraduate-research landscape, centered on the
Office for Undergraduate Research and Artistry (OURA, tilt.colostate.edu/oura)
— its office hub and Mentored Research & Artistry pathway — plus three flagship
NSF-funded summer Research Experiences for Undergraduates (REU): Biochemistry &
Molecular Biology, Chemistry, and Atmospheric Science. Every URL was curl-verified
live (HTTP 200) on 2026-07-20 (``curc.colostate.edu`` 301-redirects into the OURA
tree at ``/oura/current-students/showcase/curc/`` — not seeded here; the resolved
OURA paths are used directly).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → colostate_research_programs (colostate / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "colostate",
    "organization": "Colorado State University",
    "location": "Fort Collins, CO",
    "emit": {
        "campus": ("colostate_research_programs", "colostate", "campus"),
    },
    "sources": [
        {
            "source_name": "colostate_oura_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://tilt.colostate.edu/oura/",
                "https://tilt.colostate.edu/oura/mentored-research-and-artistry/",
            ],
            "programs": [
                program(
                    "colostate_office_undergraduate_research_artistry",
                    "Office for Undergraduate Research and Artistry (Colorado State University)",
                    "https://tilt.colostate.edu/oura/",
                    "The Office for Undergraduate Research and Artistry (OURA) is "
                    "CSU's campus hub connecting undergraduates of every major to "
                    "mentored research and creative-inquiry opportunities. It helps "
                    "students find faculty mentors, learn how to get started, and "
                    "access funding, showcases, and structured programs that make a "
                    "scholarly or artistic contribution to knowledge.",
                    lab_or_program="Office for Undergraduate Research and Artistry",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "creative artistry", "any major"],
                ),
                program(
                    "colostate_mentored_research_and_artistry",
                    "Mentored Research and Artistry (CSU Office for Undergraduate Research and Artistry)",
                    "https://tilt.colostate.edu/oura/mentored-research-and-artistry/",
                    "OURA's Mentored Research and Artistry pathway pairs CSU "
                    "undergraduates with faculty mentors on original research, "
                    "scholarship, and creative projects across every discipline. It "
                    "walks students through finding a mentor, joining a lab or "
                    "studio, and turning a mentored investigation into a scholarly "
                    "or artistic contribution.",
                    lab_or_program="Mentored Research and Artistry",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["finding a mentor", "mentored research",
                              "creative inquiry", "getting started"],
                ),
                program(
                    "colostate_bmb_reu",
                    "Biochemistry & Molecular Biology REU (Colorado State University)",
                    "https://www.bmb.colostate.edu/research-experience-for-undergraduates-reu/",
                    "The Department of Biochemistry and Molecular Biology runs an "
                    "NSF-funded Research Experience for Undergraduates: a ten-week "
                    "paid summer program in which students from across the country "
                    "conduct independent research projects in biochemistry and "
                    "molecular biology under faculty mentorship. It is oriented "
                    "toward students who have completed some college-level biology "
                    "and general chemistry.",
                    lab_or_program="Biochemistry & Molecular Biology REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "biochemistry",
                              "molecular biology"],
                ),
                program(
                    "colostate_chemistry_summer_reu",
                    "Chemistry Summer REU (Colorado State University)",
                    "https://www.chem.colostate.edu/summer-program/summer-programs/",
                    "The Department of Chemistry hosts an NSF-supported ten-week "
                    "summer Research Experience for Undergraduates: about ten "
                    "students from institutions outside CSU pursue independent "
                    "research projects in chemistry, materials science, and "
                    "nanotechnology alongside faculty mentors, from late May through "
                    "early August, with a stipend and housing support.",
                    lab_or_program="Chemistry Summer REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "chemistry",
                              "materials science"],
                ),
                program(
                    "colostate_atmospheric_science_reu",
                    "Atmospheric Science REU (Colorado State University)",
                    "https://www.atmos.colostate.edu/ATS_REU/",
                    "The Department of Atmospheric Science offers an NSF-supported "
                    "paid summer Research Experience for Undergraduates: a ten-week "
                    "internship from early June through early August in which "
                    "students work with faculty on atmospheric, climate, and weather "
                    "research projects. Open to undergraduates nationally, it "
                    "provides a stipend and mentored entry into atmospheric-science "
                    "research.",
                    lab_or_program="Atmospheric Science REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "atmospheric science",
                              "climate"],
                ),
            ],
        },
    ],
}
