"""University of Chicago campus opportunity-graph config (US-News Top-50 rollout).

Curated, offline-safe seed records of UChicago's undergraduate-research
landscape on the generic ``campus_graph`` engine: the College Center for
Research and Fellowships (CCRF) hub + its Quad grant/scholars programs and the
College Summer Institute, the Jeff Metcalf internship program and UChicago
Handshake (career), BFI and BSCD department research pathways, and the James
Franck Institute as a lab cold-email target.

Three programs are deliberately in the OPEN bucket rather than campus-only:
the DSI Summer Lab (its FAQ admits undergraduates from any institution), the
UChicago MRSEC REU (national pool, US citizen/PR required), and Chicago Booth/
BFI's Expanding Discovery in Economics+ (early undergrads nationwide). Everything
else is UChicago-enrollment-gated.

URLs verified Jul 2026 (curl with browser headers, cross-checked via a fetch
service). ccrf.uchicago.edu is bot-walled — 403 to every scraper UA while live
in a browser — so the deep crawl degrades to the seed for CCRF pages, exactly
like Michigan's lsa/careercenter pages. Deliberately NOT seeded: the Dean's
Fund for Undergraduate Research (no longer listed on CCRF's live grants hub —
apparently renamed to Quad Undergraduate Research Conference Grants; page
unverifiable through the bot wall), the Physics REU (its page states the
program will not operate in Summer 2026), Leadership Alliance SR-EIP (UChicago
absent from the Alliance's 2026 member/host list), EPIC fellowships (predoc/
grad-only), and PME's visiting-student research (pay-to-participate).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> uchicago_research_programs (uchicago / campus)
    open   -> uchicago_external_research (national / open)
    lab    -> uchicago_labs              (uchicago / unknown)
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
    "school_slug": "uchicago",
    "organization": "University of Chicago",
    "location": "Chicago, IL",
    "emit": {
        "campus": ("uchicago_research_programs", "uchicago", "campus"),
        "open": ("uchicago_external_research", None, "open"),
        "lab": ("uchicago_labs", "uchicago", "unknown"),
    },
    "sources": [
        {
            "source_name": "uchicago_announcement",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://ccrf.uchicago.edu/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "ccrf_hub",
                    "College Center for Research and Fellowships (CCRF)",
                    "https://ccrf.uchicago.edu/",
                    "The CCRF is the College's hub for undergraduate research and nationally competitive fellowships: it runs the Quad research-grant and scholars programs, maintains searchable research-opportunity and fellowship-opportunity databases, advises on national awards (Rhodes, Marshall, Fulbright, Goldwater, Schwarzman), and hosts the annual campus-wide UChicago Undergraduate Research Symposium each May.",
                    organization="The College, University of Chicago",
                    lab_or_program="College Center for Research and Fellowships",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "fellowships", "research office", "research symposium", "advising"],
                ),
            ],
        },
        {
            "source_name": "uchicago_program",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://ccrf.uchicago.edu/office-undergraduate-research/college-summer-institute-csi",
                "https://ccrf.uchicago.edu/office-undergraduate-research/quad-summer-undergraduate-research-scholars",
                "https://ccrf.uchicago.edu/office-undergraduate-research/quad-undergraduate-research-scholars-program",
                "https://ccrf.uchicago.edu/undergraduate-research/college-research-fellows-program",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "college_summer_institute",
                    "College Summer Institute in Humanistic Research (CSI)",
                    "https://ccrf.uchicago.edu/office-undergraduate-research/college-summer-institute-csi",
                    "A selective nine-week, full-time summer research program (2026: June 15-August 13) for up to 25 UChicago undergraduates in the arts, humanities, and humanistic social sciences. Scholars work as research associates on faculty-led projects with partners such as the Franke Institute, ISAC, and Special Collections, receive training in archival research, textual analysis, and digital humanities, and present at a closing symposium. In-residence required; no concurrent internships.",
                    organization="UChicago College Center for Research and Fellowships",
                    lab_or_program="College Summer Institute in Humanistic Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,500 stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Annual cycle; the 2026 application has closed.",
                    keywords=["humanities", "archival research", "digital humanities", "faculty-led projects", "summer research"],
                ),
                program(
                    "quad_summer_scholars",
                    "Quad Summer Undergraduate Research Scholars",
                    "https://ccrf.uchicago.edu/office-undergraduate-research/quad-summer-undergraduate-research-scholars",
                    "Competitive $5,500 grants supporting College students who dedicate their summer to a faculty mentor's research or creative inquiry in any discipline, at UChicago or another US research institution. Scholars join CCRF cohort programming and present at the annual Undergraduate Research Symposium. The student's role must be intellectual rather than administrative, and the award cannot be combined with course credit or other pay for the same work.",
                    organization="UChicago College Center for Research and Fellowships",
                    lab_or_program="Quad Summer Undergraduate Research Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$5,500 stipend (to the student; not for supplies)",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Priority deadline Feb 16, 2026; rolling review through Mar 30, 2026.",
                    keywords=["faculty mentor", "summer research", "any discipline", "stipend", "research symposium"],
                ),
                program(
                    "quad_year_scholars",
                    "Quad Undergraduate Research Scholars (academic year)",
                    "https://ccrf.uchicago.edu/office-undergraduate-research/quad-undergraduate-research-scholars-program",
                    "Quarter-based grants for College undergraduates pursuing faculty-mentored research during the academic year at roughly 10-13 hours per week, with awardees presenting at the spring Undergraduate Research Symposium. Per university policy, funding may not be combined with course credit or other pay for the same research.",
                    organization="UChicago College Center for Research and Fellowships",
                    lab_or_program="Quad Undergraduate Research Scholars Program",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Quarterly research grant",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Autumn-quarter deadline Oct 6, 2025; Winter-quarter deadline Jan 8, 2026.",
                    keywords=["faculty mentor", "academic year research", "quarterly grant", "research symposium", "any discipline"],
                ),
                program(
                    "quad_faculty_research_grant",
                    "Quad Faculty Research Grant Program",
                    "https://ccrf.uchicago.edu/undergraduate-research/college-research-fellows-program",
                    "Faculty of any rank (and senior scholars at UChicago institutes) receive funding to hire an early-career College undergraduate with no prior paid research experience for academic-year research at a uniform hourly rate — a designed entry point into a first paid research position (formerly the College Research Fellows program). Students work 10-13 hours per week and are hired through participating faculty; federal work-study students are prioritized.",
                    organization="UChicago College Center for Research and Fellowships",
                    lab_or_program="Quad Faculty Research Grant Program",
                    opportunity_type="research",
                    paid="yes",
                    compensation="Hourly, up to $5,000 per academic year",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    deadline_note="Faculty application deadline Oct 13, 2025 (one cycle per year).",
                    keywords=["first research job", "paid research", "early-career", "faculty hiring", "work-study"],
                ),
            ],
        },
        {
            "source_name": "uchicago_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://datascience.uchicago.edu/education/summerlab/",
                "https://mrsec.uchicago.edu/educational-outreach/undergraduate-research-opportunities/",
                "https://www.chicagobooth.edu/expanding-discovery-in-economics",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "dsi_summer_lab",
                    "DSI Summer Lab (Data Science Institute)",
                    "https://datascience.uchicago.edu/education/summerlab/",
                    "An immersive eight-week paid summer research program (2026: June 15-August 7) pairing undergraduates from any institution — plus Chicago-area high school students — with data-science mentors across computer science, social science, climate and energy policy, materials science, and biomedical research. No prior research experience required; programming familiarity preferred. Free optional housing for college students; international students are eligible if US work-authorized.",
                    organization="UChicago Data Science Institute",
                    lab_or_program="DSI Summer Lab",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,600 stipend for 8 weeks (2026), plus free optional housing",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual cycle; the 2026 application has closed (typically opens in winter). Seniors graduating in the program year are ineligible.",
                    keywords=["data science", "mentored research", "machine learning", "open to all institutions", "summer research"],
                ),
                program(
                    "mrsec_reu",
                    "UChicago MRSEC Research Experiences for Undergraduates (REU)",
                    "https://mrsec.uchicago.edu/educational-outreach/undergraduate-research-opportunities/",
                    "A 9.5-week summer program (June 10-August 14) placing undergraduates in materials-science research groups at the NSF-funded UChicago Materials Research Science and Engineering Center. Open to US citizens or permanent residents enrolled in (not yet graduated from) an accredited undergraduate program in a materials-related field; admission is competitive, with under 10% of applicants accepted. Applications go by email to the MRSEC REU coordinator.",
                    organization="UChicago Materials Research Science and Engineering Center",
                    lab_or_program="UChicago MRSEC REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$7,000 stipend plus modest travel reimbursement",
                    eligibility_majors=["Materials Science", "Physics", "Chemistry", "Molecular Engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["REU", "materials science", "soft matter", "condensed matter", "summer research"],
                ),
                program(
                    "ede_plus",
                    "Expanding Discovery in Economics+ (EDE+)",
                    "https://www.chicagobooth.edu/expanding-discovery-in-economics",
                    "A nine-week summer program from Chicago Booth and the Becker Friedman Institute introducing early undergraduates from colleges across the country to economics research: a week-long virtual bootcamp, in-residence weeks in Washington, DC (at Brookings' Hutchins Center) and at UChicago, and a six-week synchronous evening online course. Travel, housing, and group activities are covered, with a stipend awarded on successful completion.",
                    organization="Chicago Booth / Becker Friedman Institute for Economics",
                    lab_or_program="Expanding Discovery in Economics+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend on completion; travel, housing, and group activities covered",
                    eligibility_majors=["Economics"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    deadline_note="2026 cohort application closed Feb 16, 2026 (annual cycle).",
                    keywords=["economics research", "early undergraduate", "research pipeline", "Brookings", "summer program"],
                ),
            ],
        },
        {
            "source_name": "uchicago_department",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://bfi.uchicago.edu/info-for/students/",
                "https://college.uchicago.edu/academics/biological-sciences-collegiate-division",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "bfi_student_opportunities",
                    "Becker Friedman Institute — Opportunities for Students",
                    "https://bfi.uchicago.edu/info-for/students/",
                    "The Becker Friedman Institute for Economics posts undergraduate research-assistant roles (academic-year and summer) on a rolling basis via UChicago Handshake, runs the Kapani and Brickell Metcalf internship tracks in economics and policy research, and offers dedicated funding for otherwise unpaid or underpaid public- and nonprofit-sector summer internships.",
                    organization="Becker Friedman Institute for Economics (UChicago)",
                    department="Becker Friedman Institute",
                    lab_or_program="BFI student opportunities",
                    opportunity_type="research",
                    paid="yes",
                    eligibility_majors=["Economics"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["economics", "research assistant", "policy research", "Handshake", "rolling"],
                ),
                program(
                    "bscd_research_pathways",
                    "Biological Sciences Collegiate Division — Research Pathways",
                    "https://college.uchicago.edu/academics/biological-sciences-collegiate-division",
                    "The BSCD builds hands-on research into the College's biology and neuroscience curriculum and routes students to on-campus lab positions, Metcalf internships, and Marine Biological Laboratory programs in Woods Hole — including the Jeff Metcalf Summer Undergraduate Research Fellows (SURF) fellowship and the spring Quarter in Biological Discovery.",
                    organization="UChicago Biological Sciences Collegiate Division",
                    department="Biological Sciences Collegiate Division",
                    lab_or_program="BSCD research pathways",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Biological Sciences", "Neuroscience"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["biology", "neuroscience", "lab positions", "Marine Biological Laboratory", "research curriculum"],
                ),
            ],
        },
        {
            "source_name": "uchicago_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://careeradvancement.uchicago.edu/student-opportunities/month-long-programs/jeff-metcalf-internship-program/",
                "https://careeradvancement.uchicago.edu/career-toolkit/find-opportunities/uchicago-handshake/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "metcalf_internships",
                    "Jeff Metcalf Internship Program",
                    "https://careeradvancement.uchicago.edu/student-opportunities/month-long-programs/jeff-metcalf-internship-program/",
                    "UChicago's flagship internship program offering paid, substantive internships exclusively to College students — more than 4,500 Metcalf internships across industries and locations in 2024-25 alone. Compensation is employer-paid, a $4,000 UChicago stipend for full-time experiences (8+ weeks or 320+ hours), or grants for student-secured internships; students apply through UChicago Handshake.",
                    organization="UChicago Career Advancement",
                    lab_or_program="Jeff Metcalf Internship Program",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Employer-paid or a $4,000 stipend for full-time (8+ weeks / 320+ hours) internships",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Rolling by posting via UChicago Handshake.",
                    keywords=["internship", "Metcalf", "paid internship", "Handshake", "career center"],
                ),
                program(
                    "uchicago_handshake",
                    "UChicago Handshake (Career Advancement)",
                    "https://careeradvancement.uchicago.edu/career-toolkit/find-opportunities/uchicago-handshake/",
                    "The central job and internship board for UChicago College students and alumni within five years of graduation, hosting external postings, campus recruiting, and all Metcalf internship listings. Requires a CNetID login, so postings are visible only to enrolled students.",
                    organization="UChicago Career Advancement",
                    lab_or_program="UChicago Handshake",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["job board", "Handshake", "internships", "campus recruiting", "career center"],
                ),
            ],
        },
        {
            "source_name": "uchicago_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://jfi.uchicago.edu/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "james_franck_institute",
                    "James Franck Institute — Research Labs",
                    "https://jfi.uchicago.edu/",
                    "The James Franck Institute is UChicago's interdisciplinary home for materials science, condensed-matter physics, and physical chemistry; its member labs (the Irvine, Gardel, Chin, Tian, and Park groups, among others) work on controlled turbulence, cell mechanosensation, moiré nanomaterials, and ultracold quantum simulation. The site lists job opportunities and lab pages, making it a cold-email target for joining a research group.",
                    organization="James Franck Institute (UChicago)",
                    lab_or_program="James Franck Institute",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Physics", "Chemistry", "Materials Science"],
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["condensed matter", "materials science", "physical chemistry", "research institute", "cold email"],
                ),
            ],
        },
    ],
}
