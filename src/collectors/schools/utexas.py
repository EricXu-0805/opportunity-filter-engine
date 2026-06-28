"""The University of Texas at Austin (Austin) campus opportunity-graph config (US-News Top-50 rollout).

Curated, offline-safe seed records of UT Austin's undergraduate-research landscape on
the generic ``campus_graph`` engine: the central undergraduate-research office +
its signature scholarships/fellowships/summer programs, a department research
program, the career center, and research-institute cold-email targets.

The OPEN-bucket program(s) — CDCM (MRSEC) Research Experience for Undergraduates — explicitly recruit students from other institutions, so they are national/open rather than campus-gated. Everything else is UT Austin-enrollment-gated.

URLs verified HTTP-200 against the official .edu domains (Jun 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> utexas_research_programs (utexas / campus)
    open   -> utexas_external_research (national / open)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    DEPARTMENT,
    PROGRAM,
    RECURSIVE,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "utexas",
    "organization": "The University of Texas at Austin",
    "location": "Austin, TX",
    "emit": {
        "campus": ("utexas_research_programs", "utexas", "campus"),
        "open": ("utexas_external_research", None, "open"),
    },
    "sources": [
        {
            "source_name": "utexas_announcement",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://undergraduates.utexas.edu/academics/undergraduate-research",
                "https://undergraduates.utexas.edu/academics/undergraduate-research/research-resources/students/ut-research-programs",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "our_hub",
                    "Office of Undergraduate Research — Main Hub",
                    "https://undergraduates.utexas.edu/academics/undergraduate-research",
                    "Central undergraduate-research hub run by UT Austin's Office of Undergraduate Research (OUR). It points students to the Eureka research-opportunities database, Summer Research Scholars programs, fellowships, advising, info sessions, and presentation events, and conducts faculty outreach on mentoring undergraduate researchers.",
                    organization="The University of Texas at Austin",
                    department="Office of Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "research office", "mentoring", "advising", "fellowships"],
                ),
                program(
                    "ut_research_programs",
                    "UT Research Programs — How to Find a Research Position",
                    "https://undergraduates.utexas.edu/academics/undergraduate-research/research-resources/students/ut-research-programs",
                    "A directory page that helps enrolled UT undergraduates find research positions across colleges, linking to discipline-specific opportunities in engineering, natural sciences, liberal arts, business, and geosciences. It highlights the Freshman Research Initiative, the Accelerated Research Initiative for current students, McNair Scholars, and Bridging Disciplines Programs.",
                    organization="The University of Texas at Austin",
                    department="Office of Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research positions", "find a lab", "FRI", "accelerated research initiative", "bridging disciplines"],
                ),
            ],
        },
        {
            "source_name": "utexas_program",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://undergraduates.utexas.edu/academics/undergraduate-research/scholarships-awards/undergraduate-research-fellowship",
                "https://undergraduates.utexas.edu/academics/undergraduate-research/conducting-research/summer-research-scholars-programs",
                "https://fri.cns.utexas.edu/",
                "https://exl.cns.utexas.edu/events/series/undergraduate-research-forum",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "undergrad_research_fellowship",
                    "Undergraduate Research Fellowship (URF)",
                    "https://undergraduates.utexas.edu/academics/undergraduate-research/scholarships-awards/undergraduate-research-fellowship",
                    "A competitive fellowship providing up to $1,000 to support specific scholarly research projects proposed by UT Austin undergraduates, undertaken under the supervision of a faculty member or full-time research staff. Open to full-time UT undergraduates in any department.",
                    organization="The University of Texas at Austin",
                    department="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="yes",
                    compensation="Up to $1,000 per fellowship",
                    eligibility_majors=["any"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="2025-2026 deadlines: Oct. 13 and Feb. 2",
                    keywords=["research fellowship", "research funding", "faculty supervision", "project grant"],
                ),
                program(
                    "summer_research_scholars",
                    "Summer Research Scholars Programs",
                    "https://undergraduates.utexas.edu/academics/undergraduate-research/conducting-research/summer-research-scholars-programs",
                    "A catalog of on-campus summer undergraduate research programs across disciplines (astronomy, chemistry, biomedical engineering, geosciences, environmental science, and more), including NSF REUs and McNair. Eligibility varies by program; some are UT-only and others admit non-UT students.",
                    organization="The University of Texas at Austin",
                    department="Office of Undergraduate Research",
                    opportunity_type="summer_program",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["summer research", "REU", "STEM research", "research scholars", "internship"],
                ),
                program(
                    "fri",
                    "Freshman Research Initiative (FRI)",
                    "https://fri.cns.utexas.edu/",
                    "The College of Natural Sciences' signature first-year research program, described as the nation's largest university undergraduate research program. More than 1,000 CNS undergraduates each year join faculty-led research 'streams' to investigate open questions in STEM fields for course credit.",
                    organization="The University of Texas at Austin",
                    department="College of Natural Sciences",
                    lab_or_program="Freshman Research Initiative",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman"],
                    international_friendly="unknown",
                    keywords=["freshman research", "research streams", "STEM", "natural sciences", "course credit"],
                ),
                program(
                    "ts_research_forum",
                    "Technology & Science Undergraduate Research Forum",
                    "https://exl.cns.utexas.edu/events/series/undergraduate-research-forum",
                    "An annual spring forum where hundreds of CNS undergraduates present research posters, drawn from programs including the Freshman Research Initiative, Hello Maker Studio, and Impact Lab. Faculty, industry partners, and alumni serve as judges, and over $12,000 in student awards is distributed.",
                    organization="The University of Texas at Austin",
                    department="College of Natural Sciences",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Next forum: April 16, 2027, Welch Hall Grand Concourse",
                    keywords=["research forum", "poster session", "undergraduate research", "STEM showcase", "awards"],
                ),
                program(
                    "mcnair_scholars",
                    "Ronald E. McNair Scholars Program",
                    "https://undergraduates.utexas.edu/academics/post-graduate-programs/mcnair-scholars",
                    "A federally funded TRIO program (active at UT since 2007) that prepares low-income and first-generation undergraduates for doctoral study. Scholars conduct an independent faculty-mentored research project and receive research stipends, no-cost GRE prep, travel awards, and scholarship aid.",
                    organization="The University of Texas at Austin",
                    department="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Research stipends, travel awards, and scholarship aid (federally funded TRIO program)",
                    preferred_year=["junior", "senior"],
                    international_friendly="no",
                    keywords=["McNair", "first-generation", "low-income", "doctoral preparation", "faculty mentor"],
                ),
            ],
        },
        {
            "source_name": "utexas_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://mrsec.utexas.edu/education-outreach/research-experience-undergraduates",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "cdcm_mrsec_reu",
                    "CDCM (MRSEC) Research Experience for Undergraduates",
                    "https://mrsec.utexas.edu/education-outreach/research-experience-undergraduates",
                    "An NSF-funded 9-week summer REU at UT Austin's Center for Dynamics and Control of Materials (an NSF MRSEC) for undergraduates from institutions other than UT Austin. Participants do interdisciplinary materials science, chemistry, physics, and engineering research, receiving a $6,000 stipend plus housing and travel allowance.",
                    organization="The University of Texas at Austin",
                    lab_or_program="Center for Dynamics and Control of Materials (CDCM, NSF MRSEC)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 stipend, plus dorm housing and travel allowance",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="no",
                    keywords=["REU", "materials science", "MRSEC", "summer research", "physics chemistry engineering"],
                ),
            ],
        },
        {
            "source_name": "utexas_department",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://fri.cns.utexas.edu/research-streams",
                "https://cockrell.utexas.edu/student-life/research-and-projects/undergraduate-research/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "fri_research_streams",
                    "FRI Research Streams Directory",
                    "https://fri.cns.utexas.edu/research-streams",
                    "Directory of the ~40 faculty-led FRI research streams across biology, chemistry, physics, computer science, and engineering that first-year (and some upper-level/transfer) students can join. Streams include topics like Quantum Computing, Autonomous Robots, Behavioral Neuroscience, and White Dwarf Stars.",
                    organization="The University of Texas at Austin",
                    department="College of Natural Sciences — Freshman Research Initiative",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["research streams", "quantum computing", "robotics", "neuroscience", "biology chemistry physics"],
                ),
                program(
                    "cockrell_undergrad_research",
                    "Cockrell School of Engineering — Undergraduate Research Opportunities",
                    "https://cockrell.utexas.edu/student-life/research-and-projects/undergraduate-research/",
                    "The Cockrell School of Engineering's hub for undergraduate research, pointing students to EUREKA, the Office of Undergraduate Research, Undergraduate Research Week, the Texas Research Experience (connecting upper-division engineering students with faculty), and NSF REUs.",
                    organization="The University of Texas at Austin",
                    department="Cockrell School of Engineering",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["engineering research", "EUREKA", "Texas Research Experience", "REU", "faculty research"],
                ),
            ],
        },
        {
            "source_name": "utexas_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://careersuccess.utexas.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_success",
                    "Texas Career Success (12twenty@Texas job board)",
                    "https://careersuccess.utexas.edu/",
                    "UT Austin's central career-services hub coordinating 16 college- and school-specific career offices. It hosts the 12twenty@Texas job board where students and alumni connect with employers for jobs and internships.",
                    organization="The University of Texas at Austin",
                    department="Texas Career Success",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["career services", "internships", "12twenty", "job board", "employer engagement"],
                ),
            ],
        },
    ],
}
