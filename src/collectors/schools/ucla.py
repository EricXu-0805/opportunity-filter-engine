"""University of California, Los Angeles (Los Angeles) campus opportunity-graph config (US-News Top-50 rollout).

Curated, offline-safe seed records of UCLA's undergraduate-research landscape on
the generic ``campus_graph`` engine: the central undergraduate-research office +
its signature scholarships/fellowships/summer programs, a department research
program, the career center, and research-institute cold-email targets.

The OPEN-bucket program(s) — Amgen Scholars Program at UCLA — explicitly recruit students from other institutions, so they are national/open rather than campus-gated. Everything else is UCLA-enrollment-gated.

URLs verified HTTP-200 against the official .edu domains (Jun 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> ucla_research_programs (ucla / campus)
    open   -> ucla_external_research (national / open)
    lab    -> ucla_labs              (ucla / unknown)
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
    "school_slug": "ucla",
    "organization": "University of California, Los Angeles",
    "location": "Los Angeles, CA",
    "emit": {
        "campus": ("ucla_research_programs", "ucla", "campus"),
        "open": ("ucla_external_research", None, "open"),
        "lab": ("ucla_labs", "ucla", "unknown"),
    },
    "sources": [
        {
            "source_name": "ucla_announcement",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://sciences.ugresearch.ucla.edu/get-started/",
                "https://hass.ugresearch.ucla.edu/scholarships/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "urc_sciences_get_started",
                    "UCLA Undergraduate Research Center—Sciences: Get Started",
                    "https://sciences.ugresearch.ucla.edu/get-started/",
                    "The central how-to-find-a-position hub from UCLA's Undergraduate Research Center—Sciences. It walks undergraduates through a four-step process to join a research lab: building a research network, compiling a faculty list, contacting faculty by email with a CV, and preparing for lab interviews.",
                    organization="UCLA Undergraduate Research Center—Sciences",
                    lab_or_program="Undergraduate Research Center—Sciences",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["sciences", "engineering", "lab placement", "faculty mentor", "STEM research"],
                ),
                program(
                    "urc_hass_scholarships",
                    "UCLA URC—Humanities, Arts & Social Sciences: Scholarships",
                    "https://hass.ugresearch.ucla.edu/scholarships/",
                    "The scholarships hub of UCLA's Undergraduate Research Center for the humanities, arts, and social sciences, listing the center's seven funding programs for undergraduate researchers. It serves as the central listing of HASS research awards and fellowships.",
                    organization="UCLA Undergraduate Research Center—Humanities, Arts, and Social Sciences",
                    lab_or_program="Undergraduate Research Center—Humanities, Arts, and Social Sciences",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["humanities", "arts", "social sciences", "scholarships", "fellowships"],
                ),
            ],
        },
        {
            "source_name": "ucla_program",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://sciences.ugresearch.ucla.edu/programs-and-scholarships/ursp/",
                "https://sciences.ugresearch.ucla.edu/programs-and-scholarships/urc-sciences-summer-program/",
                "https://hass.ugresearch.ucla.edu/scholarships/drf/",
                "https://hass.ugresearch.ucla.edu/scholarships/sri/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "ursp_sciences",
                    "Undergraduate Research Scholars Program (URSP) — Sciences",
                    "https://sciences.ugresearch.ucla.edu/programs-and-scholarships/ursp/",
                    "A three-quarter scholarship for UCLA juniors and seniors conducting life science, physical science, or engineering research with a UCLA faculty mentor. Juniors receive up to $4,500 and seniors up to $6,000, disbursed in three quarterly payments.",
                    organization="UCLA Undergraduate Research Center—Sciences",
                    lab_or_program="Undergraduate Research Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Juniors up to $4,500; seniors up to $6,000, disbursed in three equal quarterly payments",
                    eligibility_majors=["Life Sciences", "Physical Sciences", "Engineering", "Mathematics"],
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Application for 2026-2027 closes June 16, 2026 at 11:59 PM",
                    keywords=["scholarship", "life science", "physical science", "engineering", "thesis"],
                ),
                program(
                    "urc_sciences_summer",
                    "URC-Sciences Summer Program",
                    "https://sciences.ugresearch.ucla.edu/programs-and-scholarships/urc-sciences-summer-program/",
                    "A 10-week summer research program (June 22–August 28, 2026) for UCLA undergraduates working full-time or part-time in a faculty lab. Full-time participants receive up to $6,000 and part-time up to $2,000 in stipends.",
                    organization="UCLA Undergraduate Research Center—Sciences",
                    lab_or_program="URC-Sciences Summer Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Up to $6,000 (full-time) or up to $2,000 (part-time) stipend",
                    eligibility_majors=["Life Sciences", "Physical Sciences", "Engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Applications due 11:59 PM Monday, March 2, 2026",
                    keywords=["summer research", "STEM", "faculty mentor", "stipend", "10-week"],
                ),
                program(
                    "deans_research_fellowship",
                    "Dean's Research Fellowship (HASS)",
                    "https://hass.ugresearch.ucla.edu/scholarships/drf/",
                    "A $10,000 scholarship for UCLA juniors and seniors completing a comprehensive research project, capstone, or departmental honors thesis in the humanities or social sciences under a UCLA faculty mentor. Explicitly open to all degree-seeking UCLA students including international and undocumented students.",
                    organization="UCLA Undergraduate Research Center—Humanities, Arts, and Social Sciences",
                    lab_or_program="Dean's Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$10,000 scholarship spread evenly across fall, winter, and spring quarters",
                    eligibility_majors=["African American Studies", "Anthropology", "English", "History", "Philosophy", "Political Science", "Sociology"],
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="2026-2027 application opens May 15, 2026; deadline Tuesday, June 16, 2026 at 11:59 PM",
                    keywords=["humanities", "social sciences", "honors thesis", "scholarship", "research"],
                ),
                program(
                    "summer_research_incubator",
                    "Summer Research Incubator (HASS)",
                    "https://hass.ugresearch.ucla.edu/scholarships/sri/",
                    "A virtual, entry-level six-week summer program (Summer Session A, June 22–July 31, 2026) for UCLA students early in their research careers, focused on diversity or social justice topics in the humanities, arts, social sciences, or psychology. Participants receive a $3,000 scholarship; open to all UCLA degree-seeking students including international students.",
                    organization="UCLA Undergraduate Research Center—Humanities, Arts, and Social Sciences",
                    lab_or_program="Summer Research Incubator",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$3,000 scholarship",
                    eligibility_majors=["Humanities", "Arts", "Social Sciences", "Psychology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Application deadline for summer 2026: Sunday, March 1, 2026 at 11:59 PM",
                    keywords=["summer research", "diversity", "social justice", "humanities", "entry-level"],
                ),
            ],
        },
        {
            "source_name": "ucla_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://sciences.ugresearch.ucla.edu/programs-and-scholarships/amgen-scholars/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "amgen_scholars_ucla",
                    "Amgen Scholars Program at UCLA",
                    "https://sciences.ugresearch.ucla.edu/programs-and-scholarships/amgen-scholars/",
                    "A national 10-week summer research program (June 21–August 27, 2026) hosting 10 scholars in biomedical science, chemistry, bioengineering, or chemical engineering, of whom 8 come from other four-year colleges. Provides a $3,000 stipend plus on-campus housing and meals; limited to U.S. citizens or permanent residents.",
                    organization="UCLA Undergraduate Research Center—Sciences",
                    lab_or_program="Amgen Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$3,000 stipend for 10 weeks plus on-campus housing, meals, and travel allowance (up to $500 out-of-state, $250 CA)",
                    eligibility_majors=["Biomedical Science", "Chemistry", "Bioengineering", "Chemical Engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="All application materials must be received by February 1, 2026",
                    keywords=["biomedical", "chemistry", "bioengineering", "PhD pathway", "summer research"],
                ),
            ],
        },
        {
            "source_name": "ucla_department",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://sciences.ugresearch.ucla.edu/courses/srp/",
                "https://samueli.ucla.edu/undergraduate-research/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "srp_99",
                    "Student Research Program (SRP-99)",
                    "https://sciences.ugresearch.ucla.edu/courses/srp/",
                    "SRP-99 lets UCLA undergraduates earn university credit for faculty-supervised research, designed as an entry-level experience for lower-division and first-quarter transfer students. Credit (1–2 units per quarter, up to 10 cumulative) is awarded Pass/No Pass through the faculty member's department after the student secures a project with a UCLA faculty.",
                    organization="UCLA Undergraduate Research Center—Sciences",
                    lab_or_program="Student Research Program (SRP-99)",
                    opportunity_type="research",
                    paid="no",
                    eligibility_majors=["Life Sciences", "Physical Sciences", "Engineering"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["research for credit", "entry-level", "lower-division", "faculty mentor", "transfer students"],
                ),
                program(
                    "samueli_undergrad_research",
                    "Undergraduate Research — UCLA Samueli School of Engineering",
                    "https://samueli.ucla.edu/undergraduate-research/",
                    "The engineering school's undergraduate research hub, listing pathways for engineering students including the Student Research Program, research-for-credit, and summer programs (Amgen Scholars, SURP, SPUR, and the NSF NanoCER REU). Students conduct research under faculty at the leading edge of technological innovation.",
                    organization="UCLA Samueli School of Engineering",
                    lab_or_program="Samueli School of Engineering Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Engineering", "Computer Science", "Bioengineering", "Materials Science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["engineering", "research for credit", "summer research", "nanotechnology", "faculty"],
                ),
            ],
        },
        {
            "source_name": "ucla_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://career.ucla.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center",
                    "UCLA Career Center",
                    "https://career.ucla.edu/",
                    "UCLA's campus career services office for students, alumni, and postdocs, hosting the job and internship board (currently Handshake, transitioning to 12twenty by July 1, 2026). It offers counseling, workshops, and connections to employers hiring UCLA candidates.",
                    organization="UCLA Career Center",
                    lab_or_program="UCLA Career Center",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["internships", "jobs", "Handshake", "12twenty", "career services"],
                ),
            ],
        },
        {
            "source_name": "ucla_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://cnsi.ucla.edu/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "cnsi",
                    "California NanoSystems Institute (CNSI) at UCLA",
                    "https://cnsi.ucla.edu/",
                    "An interdisciplinary nanoscience research institute at UCLA spanning nanomedicine, sustainability, beyond-CMOS electronics, and microbiome research. It offers student pathways including the Magnify Internship Program, Summer Capstone Program, and technology training, and explicitly serves undergraduates, graduate students, and postdocs.",
                    organization="California NanoSystems Institute (CNSI), UCLA",
                    lab_or_program="California NanoSystems Institute (CNSI)",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Chemistry", "Engineering", "Bioengineering", "Materials Science", "Physics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["nanotechnology", "nanomedicine", "materials", "interdisciplinary", "institute"],
                ),
            ],
        },
    ],
}
