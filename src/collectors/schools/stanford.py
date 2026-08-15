"""Stanford University (Stanford) campus opportunity-graph config (US-News Top-50 rollout).

Curated, offline-safe seed records of Stanford's undergraduate-research landscape on
the generic ``campus_graph`` engine: the central undergraduate-research office +
its signature scholarships/fellowships/summer programs, a department research
program, the career center, and research-institute cold-email targets.

The OPEN-bucket program(s) — Stanford Summer Research Program / Amgen Scholars (SSRP) — explicitly recruit students from other institutions, so they are national/open rather than campus-gated. Everything else is Stanford-enrollment-gated.

URLs verified HTTP-200 against the official .edu domains (Jun 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> stanford_research_programs (stanford / campus)
    open   -> stanford_external_research (national / open)
    lab    -> stanford_labs              (stanford / unknown)
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
    "school_slug": "stanford",
    "organization": "Stanford University",
    "location": "Stanford, CA",
    "emit": {
        "campus": ("stanford_research_programs", "stanford", "campus"),
        "open": ("stanford_external_research", None, "open"),
        "lab": ("stanford_labs", "stanford", "unknown"),
    },
    "sources": [
        {
            "source_name": "stanford_announcement",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://undergradresearch.stanford.edu/",
                "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "uar_vpue_hub",
                    "Undergraduate Research and Independent Projects (UAR/VPUE)",
                    "https://undergradresearch.stanford.edu/",
                    "Stanford's central undergraduate-research office hub. It organizes how students get started in research, find faculty mentors, and fund independent projects, and lists the university's student grants (Major Grant, Small Grant, Chappell Lougee, Conference Grant), departmental funding, and research-related national fellowships.",
                    organization="Stanford University",
                    department="Office of the Vice Provost for Undergraduate Education (VPUE) / Undergraduate Advising and Research",
                    lab_or_program="Undergraduate Research and Independent Projects (VPUE)",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "grants", "fellowships", "faculty mentor", "independent project"],
                ),
                program(
                    "uar_explore_grants",
                    "Explore Undergraduate Research Student Grants",
                    "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants",
                    "VPUE's listing of the undergraduate research student grants available to enrolled Stanford students, covering Major Grants (full-time summer projects), Small Grants (project expenses), the Chappell Lougee Scholarship (sophomore humanities/arts/qualitative social science summer projects), and Conference Grants, plus eligibility requirements and a 'which grant is best for you' guide.",
                    organization="Stanford University",
                    department="VPUE Undergraduate Research",
                    lab_or_program="VPUE Undergraduate Research Student Grants",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["student grants", "research funding", "stipend", "honors thesis", "independent project"],
                ),
            ],
        },
        {
            "source_name": "stanford_program",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/major",
                "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/small",
                "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/chappell-lougee",
                "https://undergradresearch.stanford.edu/fund-your-project/research-fellowships/vpue-stem-fellows-program",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "major_grant",
                    "VPUE Major Grant",
                    "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/major",
                    "Major Grants fund student-driven, full-time immersive summer projects supported by a faculty mentor, with priority given to juniors; most are awarded to students beginning an honors thesis, a senior project in the arts, or a senior synthesis project. The grant provides a 10-week summer stipend.",
                    organization="Stanford University",
                    department="VPUE Undergraduate Research",
                    lab_or_program="VPUE Major Grant",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$8,500 stipend (with a need-based supplement of $1,500 for eligible students)",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Application deadline Sunday, March 1, 2026, 11:59pm PST; faculty mentor letter due March 8, 2026; project execution Summer 2026.",
                    keywords=["summer research", "honors thesis", "faculty mentor", "stipend", "independent project"],
                ),
                program(
                    "small_grant",
                    "VPUE Small Grant",
                    "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/small",
                    "Small Grants support project expenses that enable independent, student-driven projects, prioritizing projects that demonstrate a high need for funding. Application deadlines are quarterly and students should apply at least one quarter before the project start date.",
                    organization="Stanford University",
                    department="VPUE Undergraduate Research",
                    lab_or_program="VPUE Small Grant",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Up to $1,500",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Quarterly deadlines; next deadline Friday, April 10, 2026 (Spring); faculty mentor letter due April 17, 2026. Projects not funded retroactively.",
                    keywords=["research funding", "project expenses", "independent project", "quarterly grant"],
                ),
                program(
                    "chappell_lougee",
                    "Chappell Lougee Scholarship",
                    "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/chappell-lougee",
                    "The Chappell Lougee Scholarship supports sophomores pursuing full-time immersive summer projects in the humanities, creative arts, and qualitative social sciences. Scholars receive a 10-week summer stipend and mentorship from current PhD students, preparing in spring and conducting the project the summer between sophomore and junior year.",
                    organization="Stanford University",
                    department="VPUE Undergraduate Research",
                    lab_or_program="Chappell Lougee Scholarship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$8,500 (with a need-based supplement of $1,500 for eligible students)",
                    eligibility_majors=["Humanities", "Creative Arts", "Qualitative Social Sciences"],
                    preferred_year=["sophomore"],
                    international_friendly="yes",
                    deadline_note="Application deadline Monday, December 1, 2025, 11:59pm PST; faculty mentor letter due December 8, 2025; project execution Summer 2026.",
                    keywords=["humanities", "creative arts", "social sciences", "summer research", "sophomore"],
                ),
                program(
                    "vpue_stem_fellows",
                    "VPUE STEM Fellows Program",
                    "https://undergradresearch.stanford.edu/fund-your-project/research-fellowships/vpue-stem-fellows-program",
                    "The Stanford Undergraduate STEM Fellows Program offers community, professional development workshops, mentorship from graduate students, and financial support (including a summer research stipend) to students passionate about scientific research, centering students who have not previously had abundant access to research experiences. Sophomores and first-year transfer students are nominated by Stanford staff and faculty.",
                    organization="Stanford University",
                    department="VPUE Undergraduate Research",
                    lab_or_program="VPUE STEM Fellows Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Stipend for summer research (sophomore year); up to $1,000 financial support for graduate school applications; conference presentation support",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    deadline_note="Nominations open early November; nomination deadline was Dec 1, 2025; student application deadline was Jan 26, 2026.",
                    keywords=["STEM", "scientific research", "graduate school", "mentorship", "summer stipend"],
                ),
            ],
        },
        {
            "source_name": "stanford_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://biosciences.stanford.edu/pathways/ssrp-amgen-scholars-program/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "ssrp_amgen_scholars",
                    "Stanford Summer Research Program / Amgen Scholars (SSRP)",
                    "https://biosciences.stanford.edu/pathways/ssrp-amgen-scholars-program/",
                    "The SSRP-Amgen Scholars Program is a fully-funded, residential 8-week summer research program that hosts visiting undergraduates from other institutions, matching each with a Stanford faculty member and a lab mentor. It targets students interested in pursuing a PhD in the biosciences and provides a stipend plus housing, meals, and travel.",
                    organization="Stanford University",
                    department="Stanford Biosciences / Office of Graduate Education",
                    lab_or_program="Stanford Summer Research Program (SSRP) / Amgen Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Fully funded: $4,800 stipend plus flex card, housing, meals, and travel",
                    eligibility_majors=["Biosciences", "Biology", "Chemistry", "Biomedical Sciences"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Application opened November 1, 2025; deadline February 1, 2026, 11:59pm PDT; notifications mid-March to April 11, 2026.",
                    keywords=["biosciences", "summer research", "Amgen Scholars", "PhD pathway", "visiting undergraduates"],
                ),
            ],
        },
        {
            "source_name": "stanford_department",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://www.cs.stanford.edu/bachelors/research-opportunities",
                "https://symsys.stanford.edu/opportunities/research/summer-undergraduate-research-symbolic-systems",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "cs_research_curis",
                    "Stanford CS Undergraduate Research Opportunities (CURIS)",
                    "https://www.cs.stanford.edu/bachelors/research-opportunities",
                    "The Computer Science department's page describing how undergraduates get involved in research: through CURIS (the CS summer research program, a paid full-time internship), independent study for academic credit, or informal arrangements with professors. It points students to the undergraduate CS research website where faculty post lab project openings.",
                    organization="Stanford University",
                    department="Computer Science",
                    lab_or_program="CURIS / CS Independent Study",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Computer Science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["computer science", "CURIS", "independent study", "summer research", "lab projects"],
                ),
                program(
                    "symsys_summer_research",
                    "Summer Undergraduate Research in Symbolic Systems",
                    "https://symsys.stanford.edu/opportunities/research/summer-undergraduate-research-symbolic-systems",
                    "The Symbolic Systems Summer Internship Program lets continuing undergraduates work as research assistants on projects defined by Symbolic Systems faculty, funded through external research grants and a departmental VPUE grant. Internships are full-time (35+ hours/week), 10 weeks, summer only, and may be done for a stipend or for course credit.",
                    organization="Stanford University",
                    department="Symbolic Systems Program",
                    lab_or_program="Symbolic Systems Summer Internship Program",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Symbolic Systems", "Cognitive Science", "Computer Science", "Linguistics", "Philosophy", "Psychology"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["symbolic systems", "cognitive science", "AI", "research assistant", "summer internship"],
                ),
            ],
        },
        {
            "source_name": "stanford_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://careered.stanford.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_education_handshake",
                    "Stanford Career Education (Handshake)",
                    "https://careered.stanford.edu/",
                    "Stanford Career Education (CareerEd, formerly BEAM) is the university's central career and internship center, offering coaching, career fairs, and jobs/internship search resources. It hosts Handshake as the primary job and internship platform for Stanford students.",
                    organization="Stanford University",
                    department="Stanford Career Education (CareerEd)",
                    lab_or_program="Stanford Career Education / Handshake",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["career center", "Handshake", "internships", "jobs", "coaching"],
                ),
            ],
        },
        {
            "source_name": "stanford_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://biox.stanford.edu/research/undergraduate-research",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            # biox.stanford.edu returns cf-mitigated: challenge to a plain GET.
            # Headless clears it: measured 2026-08-15, returns "Undergraduate
            # Research | Welcome to Bio-X".
            "render": True,
            "programs": [
                program(
                    "biox_usrp",
                    "Stanford Bio-X Undergraduate Summer Research Program (USRP)",
                    "https://biox.stanford.edu/research/undergraduate-research",
                    "The Stanford Sapp Family CS Bio-X Undergraduate Summer Research Program (USRP) awards eligible Stanford undergraduates a summer stipend for 10 weeks of full-time interdisciplinary biosciences research with a Bio-X affiliated faculty member, plus faculty talks, workshops, journal clubs, and a poster session. Students may come from any department, and first-time researchers are encouraged.",
                    organization="Stanford University",
                    department="Stanford Bio-X",
                    lab_or_program="Stanford Bio-X USRP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend of $8,000 (with need-based supplement up to $1,500 for eligible students) for 10 weeks (per recent cycle)",
                    eligibility_majors=["Bioengineering", "Biology", "Computer Science", "Neuroscience", "Chemistry", "any department"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Faculty mentor must be Bio-X affiliated; recent application cycle closed January 21, 2026.",
                    keywords=["Bio-X", "interdisciplinary biosciences", "summer research", "faculty mentor", "stipend"],
                ),
            ],
        },
    ],
}
