"""UC San Diego campus opportunity-graph config (first stop of the UC-system rollout).

Curated seed records of UCSD's undergraduate-research landscape: the
Undergraduate Research Hub (URH) + its named academic-year programs (TRELS,
Faculty Mentor Program, RSRI, STARTneuro) and the paid SRP summer umbrella
(UC Scholars, URS, McNair, CAMP, …), the school-run department research pages,
career services, and research institutes with undergraduate involvement. URLs
verified against ugresearch.ucsd.edu (Jul 2026); the Qualcomm Institute is left
out for now (its site 403s non-browser clients, unverifiable).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ucsd_research_programs (ucsd / campus)
    open   → ucsd_external_research (national / open)
    lab    → ucsd_labs              (ucsd / unknown)
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
    "school_slug": "ucsd",
    "organization": "University of California, San Diego",
    "location": "La Jolla, CA",
    "emit": {
        "campus": ("ucsd_research_programs", "ucsd", "campus"),
        "open": ("ucsd_external_research", None, "open"),
        "lab": ("ucsd_labs", "ucsd", "unknown"),
    },
    "sources": [
        # ---- Announcements / URH hub --------------------------------------
        {
            "source_name": "ucsd_urh_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://ugresearch.ucsd.edu/",
                "https://ugresearch.ucsd.edu/programs/index.html",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "urh_hub",
                    "Undergraduate Research Hub (URH) — UC San Diego",
                    "https://ugresearch.ucsd.edu/",
                    "UC San Diego's Undergraduate Research Hub is the front door to "
                    "research programs in every major: academic-year programs (TRELS, "
                    "the Faculty Mentor Program, RSRI, STARTneuro), the paid Summer "
                    "Research Program umbrella, research conferences (SRC, URC), and "
                    "conference travel funding. Start here to find a program by class "
                    "year and field.",
                    lab_or_program="Undergraduate Research Hub",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
                program(
                    "urh_research_directory",
                    "Undergraduate Research Directory (URH, UC San Diego)",
                    "https://ugresearch.ucsd.edu/students/research-directory.html",
                    "The URH's campus-wide directory of undergraduate research "
                    "opportunities across UC San Diego departments, institutes, and "
                    "labs — the starting point for finding term-time and summer "
                    "openings beyond the named URH programs.",
                    lab_or_program="Undergraduate Research Hub",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research directory"],
                ),
            ],
        },
        # ---- Signature programs -------------------------------------------
        {
            "source_name": "ucsd_urh_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://ugresearch.ucsd.edu/programs/urh-academic-year/index.html",
                "https://ugresearch.ucsd.edu/programs/urh-summer/index.html",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "trels",
                    "TRELS — Triton Research and Experiential Learning Scholars (UCSD)",
                    "https://ugresearch.ucsd.edu/programs/all-urh-programs/trels/index.html",
                    "TRELS awards $1,000 for a quarter-long (winter or spring) "
                    "faculty-mentored project — research, guided artistic or creative "
                    "work, or public service — open to UC San Diego undergraduates in "
                    "any major.",
                    lab_or_program="TRELS",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$1,000 quarterly award",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Awarded for the winter or spring quarter; apply the quarter before.",
                    keywords=["undergraduate research", "creative project", "funding"],
                ),
                program(
                    "fmp",
                    "Faculty Mentor Program (FMP) — Academic-Year Research (UCSD)",
                    "https://ugresearch.ucsd.edu/programs/all-urh-programs/fmp/index.html",
                    "The Faculty Mentor Program places students with at least "
                    "sophomore standing (45+ units) as research assistants to a UC San "
                    "Diego faculty member: 10+ hours/week during the academic year, 4 "
                    "units of independent-study credit per quarter, and a presentation "
                    "at the year-end Online Undergraduate Research Symposium.",
                    lab_or_program="Faculty Mentor Program",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Academic-year program; applications open in fall.",
                    keywords=["research assistant", "faculty mentor", "course credit"],
                ),
                program(
                    "srp_summer",
                    "Summer Research Program (SRP) — Paid Summer Cohorts (UCSD)",
                    "https://ugresearch.ucsd.edu/programs/urh-summer/index.html",
                    "URH's Summer Research Program umbrella: 8+ cohort programs of 8 "
                    "or 10 weeks (UC Scholars, URS, McNair, CAMP, EMPOWER, Hope SRP, "
                    "TUSRP, STARTastro, the Ahmadian fellowship, the Tyler Center "
                    "international fellowship). Every SRP student is paid a stipend "
                    "for 30+ hours/week of mentor-directed research, ending with the "
                    "Summer Research Conference.",
                    lab_or_program="Summer Research Program (SRP)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend (8–10 weeks, full-time)",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual summer cycle — applications typically due in winter/early spring.",
                    keywords=["summer research", "paid", "stipend", "cohort"],
                ),
                program(
                    "uc_scholars",
                    "UC Scholars Program — 8-Week Summer Research (UCSD)",
                    "https://ugresearch.ucsd.edu/programs/all-urh-programs/uc-scholars/index.html",
                    "An 8-week, full-time summer research experience supported by UC "
                    "San Diego's Office of Student Affairs and the URH — open to "
                    "students of any major, building research skills and graduate-"
                    "school readiness with learning and networking opportunities.",
                    lab_or_program="UC Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "any major", "graduate school prep"],
                ),
                program(
                    "urs",
                    "Undergraduate Research Scholarships (URS, UCSD)",
                    "https://ugresearch.ucsd.edu/programs/all-urh-programs/urs/index.html",
                    "Donor-funded scholarships across multiple research areas: "
                    "undergraduates use the funds for a summer research project "
                    "completed under the guidance of a UC San Diego faculty mentor.",
                    lab_or_program="Undergraduate Research Scholarships",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Donor-funded research scholarship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["scholarship", "summer research", "funding"],
                ),
                program(
                    "rsri",
                    "Regents Scholar Research Initiative (RSRI, UCSD)",
                    "https://ugresearch.ucsd.edu/programs/all-urh-programs/rsri/index.html",
                    "RSRI provides research experiences for incoming Regents Scholars "
                    "to jump-start their UC San Diego career, with flexible, "
                    "customizable faculty-lab mentorship.",
                    lab_or_program="Regents Scholar Research Initiative",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["regents scholars", "early research", "mentorship"],
                ),
                program(
                    "startneuro",
                    "STARTneuro — Transfer Students into Neuroscience Research (UCSD)",
                    "https://ugresearch.ucsd.edu/programs/all-urh-programs/start-neuro/index.html",
                    "STARTneuro trains, mentors, and funds incoming transfer students "
                    "entering neuroscience research: starting the summer before "
                    "matriculation and continuing for two years of academic-year and "
                    "summer research.",
                    lab_or_program="STARTneuro",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Funded research training",
                    eligibility_majors=["Neuroscience", "Neurobiology", "Cognitive Science"],
                    preferred_year=["junior"],
                    keywords=["neuroscience", "transfer students", "funded research"],
                ),
                program(
                    "mcnair",
                    "McNair Program — Doctoral-Prep Research (UCSD)",
                    "https://mcnair.ucsd.edu/",
                    "UC San Diego's McNair Program (federal TRIO) prepares "
                    "undergraduates for doctoral study through faculty-mentored "
                    "research running winter quarter through the summer, plus "
                    "graduate-school application support. Eligibility follows U.S. "
                    "Department of Education TRIO criteria.",
                    lab_or_program="McNair Program",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Research stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Annual cycle — research runs winter quarter through summer.",
                    keywords=["mcnair", "doctoral preparation", "TRIO", "mentored research"],
                ),
            ],
        },
        # ---- Department research programs ---------------------------------
        {
            "source_name": "ucsd_department_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://biology.ucsd.edu/education/undergrad/research/index.html",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "bio_undergrad_research",
                    "School of Biological Sciences — Undergraduate Research (UCSD)",
                    "https://biology.ucsd.edu/education/undergrad/research/index.html",
                    "The School of Biological Sciences' guide to getting started in "
                    "research: finding a faculty lab, research for course credit "
                    "(BISP 195/196/197/199), and presenting results — the school-level "
                    "entry point to bench research across UCSD biology labs.",
                    organization="School of Biological Sciences, UC San Diego",
                    department="Biological Sciences",
                    eligibility_majors=["Biology", "General Biology", "Molecular and Cell Biology",
                                        "Neurobiology", "Human Biology", "Microbiology"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["biology", "lab research", "course credit"],
                ),
            ],
        },
        # ---- Career / internship hub --------------------------------------
        {
            "source_name": "ucsd_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://career.ucsd.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center",
                    "UC San Diego Career Center — Internships & Research",
                    "https://career.ucsd.edu/",
                    "The UC San Diego Career Center connects undergraduates to "
                    "internships, research experiences, and jobs through Handshake, "
                    "advising, and employer events. Open to all class years and "
                    "majors.",
                    organization="UC San Diego Career Center",
                    lab_or_program="Career Center",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "handshake"],
                ),
            ],
        },
        # ---- Research institutes / labs (cold-email targets) --------------
        {
            "source_name": "ucsd_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.sdsc.edu/education_and_training/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "sdsc",
                    "San Diego Supercomputer Center — Education, Training & Internships",
                    "https://www.sdsc.edu/education_and_training/",
                    "SDSC offers hands-on training in computational thinking, "
                    "high-performance computing, and big-data exploration, plus "
                    "internship opportunities open to undergraduate (as well as "
                    "graduate and high-school) students working with SDSC experts.",
                    department="San Diego Supercomputer Center",
                    lab_or_program="SDSC",
                    eligibility_majors=["Computer Science", "Data Science", "Computer Engineering",
                                        "Mathematics", "Cognitive Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["supercomputing", "data science", "internship", "HPC"],
                ),
            ],
        },
    ],
}
