"""University of Washington (Seattle) campus opportunity-graph config (US-News).

Third school on the generic ``campus_graph`` engine (after Princeton and
Michigan), and the named first peer-school target in the Top-50 rollout. Curated
seed records of UW's undergraduate-research landscape: the Office of
Undergraduate Research (URP) hub + its research database, the signature
academic-year and summer programs (Mary Gates Research Scholarship, Levinson
Emerging Scholars, Washington Research Foundation Fellowship, the Summer
Institute in the Arts & Humanities, conference travel awards), a department
summer-research program (Chemistry), the career center, and the Institute for
Protein Design + Allen School as research-lab targets.

One program is deliberately in the OPEN bucket rather than campus-only: the
Institute for Protein Design undergraduate research program explicitly recruits
full-time undergraduates from *any* institution worldwide, so it's national/open.
Everything else is UW-enrollment-gated.

URLs verified 200 against washington.edu / ipd.uw.edu / cs.washington.edu (Jun
2026). The Mary Gates Endowment page (expd.washington.edu) serves an incomplete
TLS chain — it loads in a browser but fails strict scrapers — so the deep crawl
degrades to the seed for it, same as Michigan's Cloudflare-walled pages.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uw_research_programs (uw / campus)
    open   → uw_external_research (national / open)
    lab    → uw_labs              (uw / unknown)
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
    "school_slug": "uw",
    "organization": "University of Washington",
    "location": "Seattle, WA",
    "emit": {
        "campus": ("uw_research_programs", "uw", "campus"),
        "open": ("uw_external_research", None, "open"),
        "lab": ("uw_labs", "uw", "unknown"),
    },
    "sources": [
        # ---- Announcements / URP hub --------------------------------------
        {
            "source_name": "uw_our_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://www.washington.edu/undergradresearch/",
                "https://www.washington.edu/undergradresearch/find/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "our_hub",
                    "Office of Undergraduate Research (URP) — Hub (UW)",
                    "https://www.washington.edu/undergradresearch/",
                    "UW's Office of Undergraduate Research is the central front door to "
                    "research across every school and college: getting-started advising, "
                    "the searchable research-opportunities database, the Undergraduate "
                    "Research Symposium, and the academic-year and summer funding "
                    "programs (Mary Gates, Levinson, WRF Fellowship, SIAH). Start here "
                    "to find a program by class year and field.",
                    lab_or_program="Office of Undergraduate Research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
                program(
                    "research_database",
                    "Research Opportunities Database — Find a Research Position (UW)",
                    "https://www.washington.edu/undergradresearch/find/",
                    "A searchable database of current undergraduate research openings "
                    "posted by UW faculty and labs across disciplines, plus guidance on "
                    "identifying faculty and cold-emailing mentors. Open to all enrolled "
                    "UW undergraduates.",
                    lab_or_program="URP Research Database",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research positions"],
                ),
            ],
        },
        # ---- Signature campus programs ------------------------------------
        {
            "source_name": "uw_research_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://www.washington.edu/undergradresearch/academic-year-programs/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "mary_gates",
                    "Mary Gates Research Scholarship (UW)",
                    "https://expd.washington.edu/mge/apply/research/",
                    "A competitive $5,000 scholarship (paid as $2,500 across two "
                    "quarters) that supports UW undergraduates engaged in faculty-guided "
                    "research, letting them deepen a project with a reduced financial "
                    "burden. Open to UW undergraduates in any discipline; two application "
                    "cycles per year.",
                    lab_or_program="Mary Gates Endowment",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$5,000 ($2,500 x 2 quarters)",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Two cycles per year (autumn and spring application deadlines).",
                    keywords=["research scholarship", "funding", "faculty-mentored research"],
                ),
                program(
                    "levinson",
                    "Levinson Emerging Scholars Award (UW)",
                    "https://www.washington.edu/undergradresearch/academic-year-programs/levinson/",
                    "An academic-year award for UW undergraduates pursuing advanced, "
                    "independent research in the biological, physical, and health "
                    "sciences. Provides funding to support a faculty-mentored research "
                    "project; shares a single application with the WRF Fellowship.",
                    lab_or_program="Levinson Emerging Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Research funding award",
                    eligibility_majors=["Biology", "Biochemistry", "Bioengineering", "Chemistry", "Physics"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual academic-year cycle; one application shared with WRFF.",
                    keywords=["research award", "life sciences", "funding"],
                ),
                program(
                    "wrff",
                    "Washington Research Foundation Fellowship (UW)",
                    "https://www.washington.edu/undergradresearch/academic-year-programs/wrff/",
                    "An academic-year fellowship funding UW undergraduates conducting "
                    "advanced independent research in science and engineering. Shares its "
                    "application with the Levinson Emerging Scholars Award; applicants are "
                    "encouraged to apply for both.",
                    lab_or_program="WRF Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Research fellowship funding",
                    eligibility_majors=["Engineering", "Computer Science", "Biology", "Chemistry", "Physics"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual academic-year cycle; one application shared with Levinson.",
                    keywords=["research fellowship", "science", "engineering", "funding"],
                ),
                program(
                    "siah",
                    "Summer Institute in the Arts & Humanities (SIAH) (UW)",
                    "https://www.washington.edu/undergradresearch/siah/",
                    "A selective full-time summer cohort program in which UW "
                    "undergraduates design and carry out an independent research or "
                    "creative project in the arts, humanities, and humanistic social "
                    "sciences, supported by a faculty director and a peer community.",
                    lab_or_program="SIAH",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer scholarship",
                    eligibility_majors=["Humanities", "Arts", "Social Sciences"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Annual summer cohort; applications typically due late winter.",
                    keywords=["summer research", "arts", "humanities"],
                ),
                program(
                    "conference_travel_award",
                    "Undergraduate Research Conference Travel Award (UW)",
                    "https://www.washington.edu/undergradresearch/fellowships-institutes-awards/cta/",
                    "Funding that helps UW undergraduate researchers travel to present "
                    "their work at academic and professional conferences. Open to "
                    "undergraduates of any class year and discipline who have research to "
                    "present.",
                    lab_or_program="Conference Travel Award",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Conference travel funding",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["conference", "travel funding", "research"],
                ),
            ],
        },
        # ---- National / open programs (recruit from other schools) --------
        {
            "source_name": "uw_external_programs",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": ["https://www.ipd.uw.edu/undergraduate-research/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "ipd_undergrad",
                    "Institute for Protein Design — Undergraduate Research Program (UW)",
                    "https://www.ipd.uw.edu/undergraduate-research/",
                    "A paid summer research program at UW's Institute for Protein Design "
                    "(David Baker's institute) where undergraduates conduct full-time "
                    "computational and experimental protein-design research in an IPD "
                    "member lab. ~9 weeks at $3,200/month; open to full-time "
                    "undergraduates from any institution worldwide, best suited to "
                    "students finishing their sophomore or junior year, who must be 18+.",
                    organization="Institute for Protein Design, University of Washington",
                    department="Protein Design",
                    lab_or_program="Institute for Protein Design",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$3,200/month for 9 weeks",
                    eligibility_majors=["Biochemistry", "Biology", "Bioengineering", "Computer Science", "Chemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual summer cycle; applications typically due in winter.",
                    keywords=["protein design", "computational biology", "summer research", "REU", "biochemistry"],
                ),
            ],
        },
        # ---- Department / college research --------------------------------
        {
            "source_name": "uw_department_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": ["https://chem.washington.edu/internships-and-summer-research-programs"],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "chem_summer_research",
                    "Chemistry Internships & Summer Research Programs (UW)",
                    "https://chem.washington.edu/internships-and-summer-research-programs",
                    "The Department of Chemistry's hub for undergraduate research "
                    "internships and summer research programs, listing on-campus "
                    "faculty-mentored lab placements and external summer opportunities in "
                    "analytical, organic, inorganic, physical, and materials chemistry.",
                    organization="Department of Chemistry, University of Washington",
                    department="Chemistry",
                    lab_or_program="UW Chemistry Summer Research",
                    opportunity_type="summer_program",
                    paid="unknown",
                    eligibility_majors=["Chemistry", "Biochemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "chemistry", "internship"],
                ),
            ],
        },
        # ---- Career / internship hub --------------------------------------
        {
            "source_name": "uw_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://careers.uw.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center",
                    "Alaska Airlines Career & Internship Center — Undergraduates (UW)",
                    "https://careers.uw.edu/",
                    "UW's central career office: the Handshake job and internship board, "
                    "career coaching, professional-development workshops, career fairs, "
                    "and an Interstride subscription for international students. Open to "
                    "all class years and majors.",
                    organization="Alaska Airlines Career & Internship Center, University of Washington",
                    lab_or_program="Career & Internship Center",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "handshake"],
                ),
            ],
        },
        # ---- Research institutes / labs (cold-email targets) --------------
        {
            "source_name": "uw_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": ["https://www.cs.washington.edu/academics/undergraduate/research-opportunities/"],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "allen_school_research",
                    "Paul G. Allen School (CSE) — Undergraduate Research (UW)",
                    "https://www.cs.washington.edu/academics/undergraduate/research-opportunities/",
                    "The Allen School's guide to getting into computer-science research as "
                    "an undergraduate: identifying faculty by area, the CSE 394/494 "
                    "directed-research courses, and graduate-student-mentored projects "
                    "across AI/ML, systems, theory, HCI, robotics, and security. A strong "
                    "cold-email target for CS/ECE undergraduates.",
                    department="Computer Science & Engineering",
                    lab_or_program="Paul G. Allen School",
                    eligibility_majors=["Computer Science", "Computer Engineering", "Electrical Engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["machine learning", "artificial intelligence", "systems", "join our lab"],
                ),
            ],
        },
    ],
}
