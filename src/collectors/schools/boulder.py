"""University of Colorado Boulder campus opportunity-graph config (#13 on the
campus_graph engine).

Curated seed records of CU Boulder's undergraduate-research landscape: the
Undergraduate Research Opportunities Program (UROP — the campus-wide grant +
assistantship funder), the Research & Innovation Office hub, the Office of
Scholarship Services, Career Services, a department research entry point
(MCDB), and the flagship research institutes that hire undergraduates (LASP,
JILA, CIRES, BioFrontiers). URLs verified live = 200 (Jul 2026).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → boulder_research_programs (boulder / campus)
    open   → boulder_external_research (national / open)
    lab    → boulder_labs              (boulder / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    DEPARTMENT,
    LAB,
    PROGRAM,
    RECURSIVE,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "boulder",
    "organization": "University of Colorado Boulder",
    "location": "Boulder, CO",
    "emit": {
        "campus": ("boulder_research_programs", "boulder", "campus"),
        "open": ("boulder_external_research", None, "open"),
        "lab": ("boulder_labs", "boulder", "unknown"),
    },
    "sources": [
        # ---- Research office / UROP hub ------------------------------------
        {
            "source_name": "boulder_research_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://www.colorado.edu/urop/",
                "https://www.colorado.edu/researchinnovation/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "urop_hub",
                    "Undergraduate Research Opportunities Program (UROP) — CU Boulder",
                    "https://www.colorado.edu/urop/",
                    "UROP is CU Boulder's campus-wide funder of student-faculty "
                    "research partnerships: individual grants and paid "
                    "assistantships support undergraduates in any major doing "
                    "research, scholarship, or creative work with a faculty "
                    "mentor. The site walks you from exploring topics to "
                    "finding a mentor to applying for funding.",
                    lab_or_program="Undergraduate Research Opportunities Program",
                    paid="stipend",
                    compensation="UROP grant or paid research assistantship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research funding", "faculty mentor"],
                ),
                program(
                    "rio_hub",
                    "Research & Innovation Office — CU Boulder Research Hub",
                    "https://www.colorado.edu/researchinnovation/",
                    "The Research & Innovation Office is the front door to CU "
                    "Boulder's research enterprise: campus institutes and "
                    "centers, research news, and funding programs. A starting "
                    "point for mapping which labs and institutes work in your "
                    "field before reaching out to faculty.",
                    organization="Research & Innovation Office, CU Boulder",
                    lab_or_program="Research & Innovation Office",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research institutes", "undergraduate research"],
                ),
            ],
        },
        # ---- Scholarships ----------------------------------------------------
        {
            "source_name": "boulder_scholarships",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://www.colorado.edu/scholarships/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "scholarship_services",
                    "Office of Scholarship Services — CU Boulder Scholarships",
                    "https://www.colorado.edu/scholarships/",
                    "CU Boulder's Office of Scholarship Services runs the "
                    "campus scholarship application and points students to "
                    "college, departmental, and donor scholarships — including "
                    "awards that support research and academic-year study.",
                    organization="Office of Scholarship Services, CU Boulder",
                    lab_or_program="Scholarship Services",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Scholarship awards (varies by program)",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["scholarship", "funding"],
                ),
            ],
        },
        # ---- Department research entry points --------------------------------
        {
            "source_name": "boulder_department_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://www.colorado.edu/mcdb/undergraduate-program/undergraduate-research",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "mcdb_undergrad_research",
                    "MCDB Undergraduate Research — CU Boulder",
                    "https://www.colorado.edu/mcdb/undergraduate-program/undergraduate-research",
                    "The Molecular, Cellular & Developmental Biology "
                    "department's guide to joining a research lab: finding a "
                    "faculty sponsor, research for course credit, and honors "
                    "thesis work — the department-level entry point to bench "
                    "research at CU Boulder.",
                    organization="Department of MCDB, CU Boulder",
                    department="Molecular, Cellular & Developmental Biology",
                    eligibility_majors=["Molecular, Cellular and Developmental Biology",
                                        "Biochemistry", "Neuroscience"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["biology", "lab research", "course credit"],
                ),
            ],
        },
        # ---- Career / internship hub ------------------------------------------
        {
            "source_name": "boulder_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://www.colorado.edu/career/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_services",
                    "Career Services — Internships & Jobs (CU Boulder)",
                    "https://www.colorado.edu/career/",
                    "CU Boulder Career Services connects undergraduates to "
                    "internships, research experiences, and jobs through "
                    "Handshake, advising appointments, and career fairs. Open "
                    "to all class years and majors.",
                    organization="Career Services, CU Boulder",
                    lab_or_program="Career Services",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "handshake"],
                ),
            ],
        },
        # ---- Research institutes (cold-email / student-job targets) ------------
        {
            "source_name": "boulder_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://lasp.colorado.edu/careers/",
                "https://jila.colorado.edu/",
                "https://cires.colorado.edu/",
                "https://www.colorado.edu/biofrontiers/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "lasp_student_jobs",
                    "LASP — Student Positions in Space Missions (CU Boulder)",
                    "https://lasp.colorado.edu/careers/",
                    "The Laboratory for Atmospheric and Space Physics builds "
                    "and operates spacecraft instruments and famously staffs "
                    "real mission work with undergraduates — paid student "
                    "positions span instrument engineering, mission "
                    "operations, software, and data analysis.",
                    department="Laboratory for Atmospheric and Space Physics",
                    lab_or_program="LASP",
                    opportunity_type="research",
                    paid="paid",
                    compensation="Paid student research/engineering positions",
                    eligibility_majors=["Aerospace Engineering", "Physics",
                                        "Astronomy", "Computer Science",
                                        "Electrical Engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["space", "spacecraft", "mission operations", "student jobs"],
                ),
                program(
                    "jila",
                    "JILA — AMO Physics & Quantum Research Institute (CU Boulder/NIST)",
                    "https://jila.colorado.edu/",
                    "JILA, a joint institute of CU Boulder and NIST, hosts "
                    "research groups in atomic/molecular/optical physics, "
                    "precision measurement, quantum information, biophysics, "
                    "and astrophysics — a dense target list for students "
                    "seeking physics research groups to join.",
                    department="JILA",
                    lab_or_program="JILA",
                    eligibility_majors=["Physics", "Engineering Physics",
                                        "Astronomy", "Chemistry"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["quantum", "AMO physics", "precision measurement"],
                ),
                program(
                    "cires",
                    "CIRES — Environmental Sciences Research Institute (CU Boulder/NOAA)",
                    "https://cires.colorado.edu/",
                    "The Cooperative Institute for Research in Environmental "
                    "Sciences — a CU Boulder/NOAA partnership — spans "
                    "atmospheric science, cryosphere, geology, and "
                    "environmental data science, with hundreds of scientists "
                    "whose groups take on student researchers.",
                    department="CIRES",
                    lab_or_program="CIRES",
                    eligibility_majors=["Atmospheric and Oceanic Sciences", "Geology",
                                        "Environmental Studies", "Geography"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["climate", "environmental science", "atmospheric science"],
                ),
                program(
                    "biofrontiers",
                    "BioFrontiers Institute — Interdisciplinary Biosciences (CU Boulder)",
                    "https://www.colorado.edu/biofrontiers/",
                    "The BioFrontiers Institute brings engineering, computer "
                    "science, and biology labs under one roof for "
                    "interdisciplinary bioscience — undergraduates join labs "
                    "working on genomics, imaging, biomaterials, and "
                    "computational biology.",
                    department="BioFrontiers Institute",
                    lab_or_program="BioFrontiers",
                    eligibility_majors=["Biochemistry", "Molecular, Cellular and Developmental Biology",
                                        "Chemical Engineering", "Computer Science",
                                        "Integrative Physiology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["genomics", "computational biology", "bioengineering"],
                ),
            ],
        },
    ],
}
