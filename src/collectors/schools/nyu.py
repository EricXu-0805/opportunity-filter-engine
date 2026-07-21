"""New York University campus opportunity-graph config.

Curated seed records of NYU's undergraduate-research landscape, centered on
the university-wide Office of Undergraduate Research (run out of the
Provost's Office, which also administers the Undergraduate Research Assistant
program) plus the College of Arts & Science hubs — the Dean's Undergraduate
Research Fund (DURF), the Summer Undergraduate Research Incubator (SURI), the
Women in Science (WINS) scholars program, and the annual Undergraduate
Research Conference / Inquiry journal — the central Student Research & Funding
portal, and the NYU Tandon student-research programs (the 10-week
Undergraduate Summer Research Program). URLs curl-verified live (HTTP 200) on
2026-07-19.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> nyu_research_programs (nyu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "nyu",
    "organization": "New York University",
    "location": "New York, NY",
    "emit": {
        "campus": ("nyu_research_programs", "nyu", "campus"),
    },
    "sources": [
        {
            "source_name": "nyu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.nyu.edu/research/undergraduate-research.html",
                "https://cas.nyu.edu/undergraduate-research.html",
                "https://engineering.nyu.edu/research-innovation/student-research",
                "https://engineering.nyu.edu/research/vertically-integrated-projects",
                "https://engineering.nyu.edu/research/student-research/research-expo",
                "https://cas.nyu.edu/undergraduate-research/deans-undergraduate-research-fund/durf-reasearch-ambassador-program.html",
            ],
            "programs": [
                program(
                    "nyu_office_undergraduate_research",
                    "NYU Office of Undergraduate Research",
                    "https://www.nyu.edu/research/undergraduate-research.html",
                    "NYU's university-wide Office of Undergraduate Research "
                    "(Provost's Office) is the central hub for getting into "
                    "research across every school. It administers the "
                    "Undergraduate Research Assistant (URA) program — where "
                    "faculty request pre-screened undergraduate research "
                    "assistants — and points students to the research programs "
                    "and funding available in each of NYU's schools.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "research assistant",
                              "faculty mentorship", "getting started"],
                ),
                program(
                    "nyu_durf_research_grant",
                    "Dean's Undergraduate Research Fund (DURF, NYU College of Arts & Science)",
                    "https://cas.nyu.edu/undergraduate-research/deans-undergraduate-research-fund.html",
                    "Created in 1996, DURF funds College of Arts & Science "
                    "undergraduates to carry out their own research and "
                    "creative projects. It offers Research Grants (up to "
                    "$1,250, individual or team), a First- and Second-Year "
                    "Training (FAST) grant of up to $750 for pre-research "
                    "skills, and Conference Grants of up to $1,000 to present "
                    "work. Open to current first-years, sophomores, juniors, "
                    "and first-term seniors in CAS.",
                    lab_or_program="Dean's Undergraduate Research Fund",
                    opportunity_type="fellowship",
                    paid="yes",
                    compensation="Research grants up to $1,250; FAST up to $750; "
                                 "conference grants up to $1,000",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "project funding",
                              "conference travel", "arts and science"],
                ),
                program(
                    "nyu_suri",
                    "Summer Undergraduate Research Incubator (SURI, NYU)",
                    "https://cas.nyu.edu/undergraduate-research/summer-undergraduate-research-incubator.html",
                    "SURI is a paid 6-week summer program pairing NYU "
                    "undergraduates with NYU doctoral-student mentors to design "
                    "and complete an original research or creative project, "
                    "often on issues of diversity or social justice. Scholars "
                    "receive a stipend and attend workshops on research skills, "
                    "ethics, professionalism, and graduate school, then present "
                    "their work at the end of the summer.",
                    lab_or_program="Summer Undergraduate Research Incubator",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "graduate mentor",
                              "original research", "stipend"],
                ),
                program(
                    "nyu_wins",
                    "Women in Science (WINS, NYU College of Arts & Science)",
                    "https://cas.nyu.edu/wins.html",
                    "The WINS program engages students to build a globally "
                    "inclusive environment in STEM research and careers. A core "
                    "group of undergraduate WINS Scholars is selected each year "
                    "on academic achievement, demonstrated research interest, "
                    "and commitment to inclusive STEM; scholars meet regularly, "
                    "give peer support, and host events with eminent scientists.",
                    lab_or_program="Women in Science",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["women in STEM", "research scholars",
                              "mentorship", "inclusive science"],
                ),
                program(
                    "nyu_ugr_conference",
                    "NYU Undergraduate Research Conference & Inquiry Journal",
                    "https://www.nyu.edu/research/undergraduate-research/events.html",
                    "NYU's annual Undergraduate Research Conference is a "
                    "campus-wide venue for undergraduates to present their "
                    "research and creative work; selected abstracts are "
                    "published in Inquiry, the College of Arts & Science's "
                    "undergraduate research journal. A capstone for students "
                    "already engaged in mentored research.",
                    lab_or_program="Undergraduate Research Conference",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research conference", "presentation",
                              "undergraduate journal", "Inquiry"],
                ),
                program(
                    "nyu_student_research_funding_portal",
                    "NYU Student Research & Funding Portal",
                    "https://studentresearchandfunding.nyu.edu/",
                    "The central application portal for NYU's undergraduate "
                    "research grants and fellowships, including the DURF "
                    "research, FAST, and conference grants and the Women in "
                    "Science program. Students browse open programs, deadlines, "
                    "and eligibility and submit applications online.",
                    lab_or_program="Student Research & Funding",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research funding", "grants", "fellowships",
                              "applications"],
                ),
                program(
                    "nyu_tandon_summer_research",
                    "NYU Tandon Undergraduate Summer Research Program",
                    "https://engineering.nyu.edu/research/student-research/undergraduate-summer-research-program",
                    "A 10-week full-time summer program at the Tandon School "
                    "of Engineering where rising sophomores, juniors, and "
                    "seniors conduct hands-on research in faculty labs and "
                    "present at poster sessions. Open to NYU Tandon, NYU Abu "
                    "Dhabi and Shanghai, and dual-degree engineering students, "
                    "plus non-NYU U.S. citizens/permanent residents with a "
                    "minimum 3.0 GPA; participants receive a stipend.",
                    lab_or_program="Tandon Undergraduate Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications typically due in early spring for "
                                  "the summer cohort.",
                    keywords=["engineering research", "summer research",
                              "faculty labs", "stipend"],
                ),
                program(
                    "nyu_tandon_student_research",
                    "NYU Tandon Student Research",
                    "https://engineering.nyu.edu/research-innovation/student-research",
                    "The Tandon School of Engineering's student-research hub "
                    "connecting undergraduates to research across its "
                    "departments and centers, including the Vertically "
                    "Integrated Projects (VIP) teams, the summer research "
                    "program, and faculty labs in computing, robotics, "
                    "wireless, cybersecurity, and biomedical engineering.",
                    lab_or_program="Tandon Student Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["engineering research", "VIP teams",
                              "faculty labs", "project teams"],
                ),
                program(
                    "nyu_tandon_vip",
                    "NYU Tandon Vertically Integrated Projects (VIP)",
                    "https://engineering.nyu.edu/research/vertically-integrated-projects",
                    "Vertically Integrated Projects (VIP) embed undergraduates "
                    "in large, multidisciplinary research teams led by NYU "
                    "Tandon faculty, working on ambitious long-term projects "
                    "for academic credit across multiple semesters. Students "
                    "join at any level and stay with a team as it advances, "
                    "gaining sustained hands-on research experience alongside "
                    "graduate students and faculty mentors.",
                    lab_or_program="Vertically Integrated Projects",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["vertically integrated projects", "research teams",
                              "multidisciplinary", "academic credit"],
                ),
                program(
                    "nyu_tandon_research_expo",
                    "NYU Tandon Research Excellence Exhibit",
                    "https://engineering.nyu.edu/research/student-research/research-expo",
                    "The Research Excellence Exhibit (Research Expo) is NYU "
                    "Tandon's annual showcase where undergraduate and graduate "
                    "students present posters and demonstrations of their "
                    "faculty-mentored research to the school community and "
                    "industry judges. A capstone venue for students already "
                    "engaged in a Tandon research group to present their work.",
                    lab_or_program="Research Excellence Exhibit",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research showcase", "poster session",
                              "student research", "engineering"],
                ),
                program(
                    "nyu_durf_research_ambassador",
                    "DURF Research Ambassador Program (NYU College of Arts & Science)",
                    "https://cas.nyu.edu/undergraduate-research/deans-undergraduate-research-fund/durf-reasearch-ambassador-program.html",
                    "The DURF Research Ambassadors are College of Arts & "
                    "Science undergraduates, experienced in research, who help "
                    "their peers get started: they hold office hours, run "
                    "workshops, and advise students on finding faculty mentors "
                    "and applying for Dean's Undergraduate Research Fund grants. "
                    "A near-peer entry point into the CAS research community.",
                    lab_or_program="DURF Research Ambassadors",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["peer mentorship", "getting started",
                              "research advising", "arts and science"],
                ),
            ],
        },
    ],
}
