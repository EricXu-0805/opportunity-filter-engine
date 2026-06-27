"""University of Michigan, Ann Arbor campus opportunity-graph config (US-News).

Second school on the generic ``campus_graph`` engine (after Princeton). Curated
seed records of Michigan's undergraduate-research landscape: the Undergraduate
Research Opportunity Program (UROP) hub + its grants, summer fellowships, the
College of Engineering's SURE, Medical School summer research, the career
center, and a few research institutes (LSI, ISR, MCubed).

Two programs are deliberately in the OPEN bucket rather than campus-only: the
Rackham SROP and the Med School M-SURE explicitly recruit students from *other*
institutions, so they're national/open (SROP additionally requires US
citizenship/PR/DACA). Everything else is Michigan-enrollment-gated.

URLs verified against umich.edu (Jun 2026); some lsa/careercenter/isr pages sit
behind a Cloudflare bot wall (live in a browser, 403 to scrapers) — the deep
crawl degrades to the seed for those.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → umich_research_programs (umich / campus)
    open   → umich_external_research (national / open)
    lab    → umich_labs              (umich / unknown)
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
    "school_slug": "umich",
    "organization": "University of Michigan",
    "location": "Ann Arbor, MI",
    "emit": {
        "campus": ("umich_research_programs", "umich", "campus"),
        "open": ("umich_external_research", None, "open"),
        "lab": ("umich_labs", "umich", "unknown"),
    },
    "sources": [
        # ---- Announcements / UROP hub -------------------------------------
        {
            "source_name": "umich_urop_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://lsa.umich.edu/urop",
                "https://lsa.umich.edu/urop/prospective-students.html",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "urop",
                    "Undergraduate Research Opportunity Program (UROP) — Hub (Michigan)",
                    "https://lsa.umich.edu/urop",
                    "UROP is U-M Ann Arbor's central undergraduate research center, "
                    "pairing students with faculty and community mentors across all "
                    "schools and colleges during the September–April academic year. "
                    "Open to all enrolled undergraduates (including transfers); aimed "
                    "primarily at first- and second-year students. Offers work-study "
                    "wages, an academic-credit option, and weekly research seminars.",
                    lab_or_program="UROP",
                    paid="yes",
                    compensation="Work-study wages or academic credit",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
                program(
                    "urop_grants",
                    "UROP Student Program Grants (Michigan)",
                    "https://lsa.umich.edu/urop/current-urop-students/urop-resources/program-grants.html",
                    "Small grants for active UROP students covering research supplies, "
                    "conference and presentation travel, and creative-performance "
                    "costs. The central landing page for UROP research-funding "
                    "announcements.",
                    lab_or_program="UROP Program Grants",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Research / travel grant",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["funding", "research grant", "conference"],
                ),
            ],
        },
        # ---- Signature campus programs ------------------------------------
        {
            "source_name": "umich_research_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://lsa.umich.edu/urop/prospective-students/summer-programs.html"],
            "crawl": STATIC,
            "programs": [
                program(
                    "urop_summer_programs",
                    "UROP Summer Fellowships (Michigan)",
                    "https://lsa.umich.edu/urop/prospective-students/summer-programs.html",
                    "Hub for UROP's full-time summer research fellowships (Biomedical "
                    "& Life Sciences, Engineering, Women & Gender, Detroit "
                    "Community-Engaged, and more), each running ~10–11 weeks. Most pay "
                    "a $3,000–$6,000 stipend for full-time work; students must be 18+ "
                    "and not graduate before December of the program year.",
                    lab_or_program="UROP Summer Fellows",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$3,000–$6,000 summer stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual summer cycle — applications typically due late winter.",
                    keywords=["summer research", "fellowship", "stipend"],
                ),
                program(
                    "biomed_life_sci_fellowship",
                    "UROP Biomedical & Life Sciences Summer Fellowship (Michigan)",
                    "https://lsa.umich.edu/urop/prospective-students/summer-programs/biomedical---life-sciences-summer-fellowship.html",
                    "Full-time summer research fellowship placing current U-M "
                    "undergraduates in biomedical and life-sciences labs, paying a "
                    "$3,000–$6,000 stipend. No prior research experience required; "
                    "open to students who will not graduate before December and are 18+.",
                    department="Biomedical & Life Sciences",
                    lab_or_program="UROP BLSSF",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$3,000–$6,000 summer stipend",
                    eligibility_majors=["Biology", "Biomedical Sciences", "Biochemistry"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "biomedical", "life sciences"],
                ),
            ],
        },
        # ---- National / open programs (recruit from other schools) --------
        {
            "source_name": "umich_external_programs",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": ["https://rackham.umich.edu/prospective-students/srop/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "srop",
                    "Summer Research Opportunity Program (SROP) — Rackham (Michigan)",
                    "https://rackham.umich.edu/prospective-students/srop/",
                    "A 10-week summer program (≈May–July) run by Rackham for "
                    "undergraduates underrepresented in their field, as a pipeline to "
                    "U-M graduate study: faculty-mentored research plus professional "
                    "development. For rising juniors/seniors at institutions other than "
                    "U-M Ann Arbor; requires a 3.0+ GPA and US citizenship, permanent "
                    "residency, or DACA status.",
                    organization="Rackham Graduate School, University of Michigan",
                    lab_or_program="SROP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend + travel/housing",
                    preferred_year=["junior", "senior"],
                    international_friendly="no",
                    deadline_note="Annual summer cycle; applications typically due early February.",
                    keywords=["summer research", "REU", "graduate pipeline"],
                ),
                program(
                    "m_sure",
                    "Michigan Summer Undergraduate Research Experience (M-SURE) — Med School",
                    "https://medschool.umich.edu/departments/molecular-integrative-physiology/education/undergraduate-summer-research-programs/m-sure",
                    "A 12-week full-time program (late May–mid August) in basic and "
                    "translational research on diabetes and metabolic disease, run by "
                    "Molecular & Integrative Physiology. Pays roughly $7,200. Open to "
                    "students enrolled at any degree-granting college or university, "
                    "with preference for those pursuing a research career.",
                    organization="Medical School, University of Michigan",
                    department="Molecular & Integrative Physiology",
                    lab_or_program="M-SURE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="~$7,200 summer stipend",
                    eligibility_majors=["Physiology", "Biomedical Sciences", "Biology"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "biomedical", "physiology", "REU"],
                ),
            ],
        },
        # ---- Department / college research --------------------------------
        {
            "source_name": "umich_department_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://sure.engin.umich.edu/",
                "https://medschool.umich.edu/programs-admissions/non-degree-programs/undergrad-summer-research",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "sure",
                    "Summer Undergraduate Research in Engineering (SURE) — College of Engineering",
                    "https://sure.engin.umich.edu/",
                    "A 10–12 week full-time summer research internship in College of "
                    "Engineering labs for current U-M undergraduates who have finished "
                    "their sophomore or junior year (preference to those with three "
                    "years done). Pays a $6,000 stipend and is geared toward students "
                    "considering an MS/PhD. Applications open in December.",
                    organization="College of Engineering, University of Michigan",
                    department="Engineering",
                    lab_or_program="SURE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 summer stipend",
                    eligibility_majors=["Engineering", "Computer Science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "engineering", "stipend"],
                ),
                program(
                    "med_undergrad_summer_research",
                    "Undergraduate Summer Research Programs — Medical School (Michigan)",
                    "https://medschool.umich.edu/programs-admissions/non-degree-programs/undergrad-summer-research",
                    "The Medical School's umbrella page for undergraduate summer "
                    "research programs (M-SURE, UM-SMART, SURF, and departmental "
                    "programs) in basic and translational biomedical research. Programs "
                    "are full-time, paid, and run ~10–12 weeks; eligibility ranges from "
                    "U-M-only to any institution depending on the program.",
                    organization="Medical School, University of Michigan",
                    department="Medicine",
                    lab_or_program="Med School Summer Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend (varies by program)",
                    eligibility_majors=["Biology", "Biomedical Sciences", "Pre-Health"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "biomedical", "medicine"],
                ),
            ],
        },
        # ---- Career / internship hub --------------------------------------
        {
            "source_name": "umich_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://careercenter.umich.edu/content/undergrads"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center_undergrads",
                    "University Career Center — Undergraduates (Michigan)",
                    "https://careercenter.umich.edu/content/undergrads",
                    "The University Career Center's main hub for undergraduates: "
                    "internship and job search support, the Handshake job board, career "
                    "coaching, and career fairs. Open to all class years and majors.",
                    organization="University Career Center, University of Michigan",
                    lab_or_program="University Career Center",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "handshake"],
                ),
            ],
        },
        # ---- Research institutes / labs (cold-email targets) --------------
        {
            "source_name": "umich_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.lsi.umich.edu/education/undergrads",
                "https://isr.umich.edu/training-opportunities/student-research-opportunities/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "lsi_undergrads",
                    "Life Sciences Institute — Undergraduate Research (Michigan)",
                    "https://www.lsi.umich.edu/education/undergrads",
                    "The LSI hosts ~150 undergraduate and graduate students at a time in "
                    "basic-science labs; undergrads can volunteer, work for credit, be "
                    "hired directly, or be placed via UROP. It also runs paid summer "
                    "fellowships (need-based Rosen Fellows and the Perrigo Summer "
                    "Undergraduate Fellowship, ~$6,000 stipend + housing). A strong "
                    "cold-email target for lab placements.",
                    department="Life Sciences Institute",
                    lab_or_program="LSI",
                    paid="stipend",
                    eligibility_majors=["Biology", "Biochemistry", "Life Sciences"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["life sciences", "join our lab", "summer research"],
                ),
                program(
                    "isr_student_research",
                    "Institute for Social Research (ISR) — Student Research (Michigan)",
                    "https://isr.umich.edu/training-opportunities/student-research-opportunities/",
                    "ISR, the world's largest academic social-science research "
                    "institute, lists research opportunities for students across its "
                    "survey, data-science, and behavioral-science programs. A good "
                    "cold-email target for undergraduates interested in social science, "
                    "survey methodology, and quantitative research.",
                    department="Institute for Social Research",
                    lab_or_program="ISR",
                    eligibility_majors=["Sociology", "Psychology", "Economics", "Data Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["social science", "survey research", "data science"],
                ),
                program(
                    "mcubed",
                    "MCubed — Interdisciplinary Seed Funding (Michigan)",
                    "https://research.umich.edu/mcubed",
                    "MCubed is U-M's interdisciplinary seed-funding program that rapidly "
                    "funds three-faculty cross-disciplinary 'cube' teams with no peer "
                    "review; cubes frequently use the money to hire undergraduate "
                    "researchers. Useful for discovering active, newly funded labs to "
                    "cold-email.",
                    department="U-M Office of Research",
                    lab_or_program="MCubed",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["interdisciplinary", "seed funding", "join our lab"],
                ),
            ],
        },
    ],
}
