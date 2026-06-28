"""Georgia Institute of Technology (Atlanta) campus opportunity-graph config (US-News Top-50 rollout).

Curated, offline-safe seed records of Georgia Tech's undergraduate-research landscape on
the generic ``campus_graph`` engine: the central undergraduate-research office +
its signature scholarships/fellowships/summer programs, a department research
program, the career center, and research-institute cold-email targets.

The OPEN-bucket program(s) — SURE — Summer Undergraduate Research in Engineering; College of Sciences REU Programs — explicitly recruit students from other institutions, so they are national/open rather than campus-gated. Everything else is Georgia Tech-enrollment-gated.

URLs verified HTTP-200 against the official .edu domains (Jun 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> gatech_research_programs (gatech / campus)
    open   -> gatech_external_research (national / open)
    lab    -> gatech_labs              (gatech / unknown)
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
    "school_slug": "gatech",
    "organization": "Georgia Institute of Technology",
    "location": "Atlanta, GA",
    "emit": {
        "campus": ("gatech_research_programs", "gatech", "campus"),
        "open": ("gatech_external_research", None, "open"),
        "lab": ("gatech_labs", "gatech", "unknown"),
    },
    "sources": [
        {
            "source_name": "gatech_announcement",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://experiential.learning.gatech.edu/urop/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "urop_hub",
                    "Undergraduate Research Opportunities Program (UROP)",
                    "https://experiential.learning.gatech.edu/urop/",
                    "UROP is Georgia Tech's central campus office coordinating undergraduate research. It promotes research opportunities across campus, helps students find positions, supports faculty mentors, and runs the annual Undergraduate Research Spring Symposium. Students can pursue research for academic credit, pay, or on a volunteer basis.",
                    organization="Georgia Institute of Technology",
                    department="Office of Undergraduate Education & Student Success",
                    lab_or_program="UROP",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research office", "find a position", "mentorship", "research symposium"],
                ),
            ],
        },
        {
            "source_name": "gatech_program",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://experiential.learning.gatech.edu/urop/funding/",
                "https://bioresearch.gatech.edu/education-and-outreach/petit-scholars",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "pura_awards",
                    "President's Undergraduate Research Awards (PURA Salary & Travel)",
                    "https://experiential.learning.gatech.edu/urop/funding/",
                    "PURA funds Georgia Tech undergraduates conducting faculty-mentored research. PURA Salary Awards provide $2,000 for research under a Georgia Tech or GTRI faculty mentor; PURA Travel Awards provide up to $1,000 to present research at conferences. 200–300 competitive salary awards are offered each year.",
                    organization="Georgia Institute of Technology",
                    department="Undergraduate Research Opportunities Program",
                    lab_or_program="PURA",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="PURA Salary $2,000; PURA Travel up to $1,000",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Travel awards accepted on a rolling basis year-round; salary awards have fixed per-semester deadlines",
                    keywords=["PURA", "research salary award", "travel award", "faculty-mentored research", "research funding"],
                ),
                program(
                    "petit_scholars",
                    "Petit Undergraduate Research Scholars Program (IBB)",
                    "https://bioresearch.gatech.edu/education-and-outreach/petit-scholars",
                    "The Petit Scholars program provides year-long, faculty-and-graduate-mentored research opportunities in IBB labs across fields including biomaterials, cancer biology, and regenerative medicine. It is open to top undergraduates from Georgia Tech and Atlanta-area partner institutions.",
                    organization="Georgia Institute of Technology",
                    department="Parker H. Petit Institute for Bioengineering and Bioscience (IBB)",
                    lab_or_program="Petit Undergraduate Research Scholars",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="2027 cohort applications open with a September 15, 2026 deadline",
                    keywords=["bioengineering", "bioscience", "biomaterials", "cancer biology", "regenerative medicine"],
                ),
            ],
        },
        {
            "source_name": "gatech_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://sure.gatech.edu",
                "https://sciences.gatech.edu/gtcosreuprograms",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "sure_reu",
                    "SURE — Summer Undergraduate Research in Engineering",
                    "https://sure.gatech.edu",
                    "SURE is a 10-week summer research program (founded 1992) designed to attract rising juniors and seniors interested in graduate school in engineering and science. It explicitly welcomes students from all institutions, not just Georgia Tech, making it an REU-style national program.",
                    organization="Georgia Institute of Technology",
                    department="College of Engineering",
                    lab_or_program="SURE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$11,500 cost-per-student support listed; program dates May 17–July 24, 2026",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Applications open Oct 15, 2025; deadline Feb 15, 2026; decisions by April 1, 2026",
                    keywords=["REU", "summer research", "engineering", "graduate school prep", "rising juniors seniors"],
                ),
                program(
                    "cos_reu",
                    "College of Sciences REU Programs",
                    "https://sciences.gatech.edu/gtcosreuprograms",
                    "A listing of NSF-funded Research Experiences for Undergraduates hosted by Georgia Tech's College of Sciences, spanning Physics, Mathematics, Earth & Atmospheric Sciences, Chemistry, and Psychology/Neuroscience. The page explicitly encourages non-Georgia Tech undergraduates to apply for full-time summer research.",
                    organization="Georgia Institute of Technology",
                    department="College of Sciences",
                    lab_or_program="College of Sciences REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Application deadlines typically fall mid-February annually",
                    keywords=["REU", "physics", "mathematics", "chemistry", "neuroscience", "earth atmospheric sciences"],
                ),
            ],
        },
        {
            "source_name": "gatech_department",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://math.gatech.edu/undergraduate/undergraduate-summer-research-program",
                "https://www.cc.gatech.edu/undergraduate-research-opportunities-computing-uroc",
                "https://coe.gatech.edu/research/undergraduate-student-research",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "math_summer_research",
                    "School of Mathematics Undergraduate Summer Research Program",
                    "https://math.gatech.edu/undergraduate/undergraduate-summer-research-program",
                    "An eight-week summer program in which undergraduates conduct mathematical research under faculty supervision during the summer session. Participants receive a stipend and sometimes co-author peer-reviewed publications.",
                    organization="Georgia Institute of Technology",
                    department="School of Mathematics",
                    lab_or_program="School of Mathematics Undergraduate Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,400 stipend for the eight-week period",
                    eligibility_majors=["Mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["mathematics", "summer research", "stipend", "publications", "faculty-mentored"],
                ),
                program(
                    "uroc_computing",
                    "Undergraduate Research Opportunities in Computing (UROC)",
                    "https://www.cc.gatech.edu/undergraduate-research-opportunities-computing-uroc",
                    "UROC helps College of Computing undergraduates get involved in research to strengthen graduate-school and industry prospects. The page guides students on identifying faculty, reading their work, and cold-emailing a professor with a resume, and points to a research-opportunities database for paid and credit-based positions.",
                    organization="Georgia Institute of Technology",
                    department="College of Computing",
                    lab_or_program="UROC",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Computer Science", "Computational Media"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["computing research", "computer science", "join a lab", "cold email faculty", "research database"],
                ),
                program(
                    "coe_undergrad_research",
                    "College of Engineering — Undergraduate Student Research",
                    "https://coe.gatech.edu/research/undergraduate-student-research",
                    "An overview of research pathways for Georgia Tech engineering undergraduates across the college's eight schools, including the Research Option (transcript-designated, publication-oriented), PURA salary/travel awards, and Vertically Integrated Projects (VIP) team-based research for credit. Students can work in labs for course credit or pay.",
                    organization="Georgia Institute of Technology",
                    department="College of Engineering",
                    lab_or_program="College of Engineering Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["engineering research", "Research Option", "Vertically Integrated Projects", "VIP", "research labs"],
                ),
            ],
        },
        {
            "source_name": "gatech_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://career.gatech.edu",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center",
                    "Georgia Tech Career Center (CareerBuzz)",
                    "https://career.gatech.edu",
                    "Georgia Tech's central career services office, housed in the Bill Moore Student Success Center, supporting undergraduates with co-op/internship programs, job-search resources, and employer connections. It hosts and maintains the CareerBuzz job board for jobs, internships, and on-campus recruiting, plus dedicated CPT/OPT support for international students.",
                    organization="Georgia Institute of Technology",
                    department="Career Center",
                    lab_or_program="Career Center / CareerBuzz",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["career center", "CareerBuzz", "internships", "co-op", "job board"],
                ),
            ],
        },
        {
            "source_name": "gatech_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://bioresearch.gatech.edu",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "ibb_institute",
                    "Parker H. Petit Institute for Bioengineering and Bioscience (IBB)",
                    "https://bioresearch.gatech.edu",
                    "IBB is one of Georgia Tech's Interdisciplinary Research Institutes, bringing together engineers, scientists, and clinicians to tackle complex bioengineering and bioscience problems. It houses many faculty labs and education/outreach programs (e.g., Project ENGAGES, Petit Scholars) — a strong cold-email target for undergraduates seeking lab placements.",
                    organization="Georgia Institute of Technology",
                    department="Parker H. Petit Institute for Bioengineering and Bioscience (IBB)",
                    lab_or_program="Parker H. Petit Institute for Bioengineering and Bioscience",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["bioengineering", "bioscience", "research institute", "interdisciplinary", "faculty labs"],
                ),
            ],
        },
    ],
}
