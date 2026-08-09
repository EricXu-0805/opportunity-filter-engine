"""Northwestern University campus opportunity-graph config (US-News Top-50 rollout).

Curated, live-verified seed of Northwestern University's undergraduate-research landscape on the
generic ``campus_graph`` engine: the central undergraduate-research office, its
signature programs/fellowships/summer research, per-school research pipelines,
the career center, and research-institute cold-email targets. Every URL was
fetch-verified (HTTP 200 + real content) on 2026-07-08.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> northwestern_research_programs (northwestern / campus)
    open   -> northwestern_external_research (national / open)
    lab    -> northwestern_labs              (northwestern / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    DEPARTMENT,
    LAB,
    PROGRAM,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "northwestern",
    "organization": "Northwestern University",
    "location": "Evanston, IL",
    "emit": {
        "campus": ("northwestern_research_programs", "northwestern", "campus"),
        "open": ("northwestern_external_research", None, "open"),
        "lab": ("northwestern_labs", "northwestern", "unknown"),
    },
    "sources": [
        {
            "source_name": "northwestern_announcement_campus",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://undergradresearch.northwestern.edu/",
                "https://www.mccormick.northwestern.edu/students/undergraduate/research-opportunities/summer-programs.html",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nu_our_hub",
                    "Northwestern Office of Undergraduate Research (OUR)",
                    "https://undergradresearch.northwestern.edu/",
                    "Central hub for undergraduate research at Northwestern, providing "
                    "advising and funding to hundreds of students annually for independent "
                    "research and creative projects in all fields. Gateway to AYURG, SURG, "
                    "URAP, Conference Travel Grants, the Circumnavigator Grant, and the "
                    "Emerging Scholars Program. Staff help students develop interests, find "
                    "faculty mentors, write grant proposals, and present research.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Office of Undergraduate Research",
                    compensation="Varies by program",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Program-specific deadlines; see individual grant pages",
                    keywords=["undergraduate research", "funding hub", "grants", "faculty mentorship", "all disciplines"],
                ),
                program(
                    "nu_mccormick_summer_programs",
                    "Northwestern McCormick Summer Research Programs List",
                    "https://www.mccormick.northwestern.edu/students/undergraduate/research-opportunities/summer-programs.html",
                    "McCormick's curated list of summer research options for engineering "
                    "undergraduates, including the NU Physical Sciences-Oncology Center "
                    "program, MRSEC REU, TGS Summer Research Opportunity Program, McCormick "
                    "Summer Research Awards, and study-abroad research routes (DAAD RISE "
                    "Germany, ThinkSwiss). Useful announcement page for discovering multiple "
                    "pipelines at once.",
                    organization="Northwestern University",
                    department="McCormick School of Engineering",
                    lab_or_program="Summer Research Programs",
                    opportunity_type="summer_program",
                    compensation="Varies by program",
                    eligibility_majors=["engineering", "computer science", "physical sciences"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Varies by program",
                    keywords=["summer research", "program list", "REU", "study abroad research"],
                ),
            ],
        },
        {
            "source_name": "northwestern_career_campus",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nu_tgs_srop",
                    "Northwestern Summer Research Opportunity Program (SROP)",
                    "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/",
                    "Eight-week summer research program (June 15 - Aug 7, 2026) run by The "
                    "Graduate School for sophomores and juniors from colleges across the U.S. "
                    "who intend to pursue a PhD. Provides a $6,500 stipend, round-trip "
                    "transportation, on-campus housing, a graduate mentor, professional "
                    "development workshops, and a Northwestern graduate application fee "
                    "waiver; all research fields are open. Requires U.S. citizenship or "
                    "permanent residency and a 3.5+ GPA.",
                    organization="Northwestern University",
                    department="The Graduate School",
                    lab_or_program="SROP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,500 stipend + housing + transportation + fee waiver",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Applications open November 1 annually; early submission encouraged",
                    keywords=["PhD pipeline", "visiting students", "summer research", "graduate school", "all fields"],
                ),
            ],
        },
        {
            "source_name": "northwestern_department_campus",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://www.mccormick.northwestern.edu/students/undergraduate/research-opportunities/",
                "https://baker.northwestern.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nu_mccormick_research_hub",
                    "Northwestern McCormick Undergraduate Research Opportunities",
                    "https://www.mccormick.northwestern.edu/students/undergraduate/research-opportunities/",
                    "McCormick School of Engineering's hub for getting undergraduates into "
                    "research: guidance on finding labs and emailing professors, links to "
                    "summer research programs, research grants and awards, and peer advising. "
                    "Students can start as early as freshman year; Responsible Conduct of "
                    "Research training is required.",
                    organization="Northwestern University",
                    department="McCormick School of Engineering",
                    lab_or_program="Office of Undergraduate Engineering",
                    compensation="Varies by program",
                    eligibility_majors=["engineering", "computer science", "applied math", "materials science", "biomedical engineering", "chemical engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Grant deadlines typically 3-6 months before award period",
                    keywords=["engineering research", "lab placement", "hub", "peer advising"],
                ),
                program(
                    "nu_baker_program_hub",
                    "Northwestern Weinberg Baker Program in Undergraduate Research",
                    "https://baker.northwestern.edu/",
                    "Weinberg College's undergraduate research office, funded by the Dean's "
                    "Office and alumni, offering grants for independent research, creative "
                    "work, and conference presentations. Umbrella for WCAS Summer Grants, "
                    "Academic Year Grants, and Conference Travel Grants, plus guidance on "
                    "research assistant positions and 399 independent-study credit.",
                    organization="Northwestern University",
                    department="Weinberg College of Arts and Sciences",
                    lab_or_program="Baker Program in Undergraduate Research",
                    compensation="Varies by grant",
                    eligibility_majors=["arts and sciences", "humanities", "social sciences", "natural sciences"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Grant-specific deadlines; applications via soap.northwestern.edu",
                    keywords=["Weinberg", "research grants", "independent study", "hub"],
                ),
            ],
        },
        {
            "source_name": "northwestern_lab_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.ipr.northwestern.edu/who-we-are/students-postdocs/summer-undergraduate-research-assistant-program/",
                "https://ciera.northwestern.edu/opportunities-for-undergraduates/reu/",
                "https://mrsec.northwestern.edu/education/undergraduate-opportunities.html",
                "https://mrsec.northwestern.edu/education/undergraduate-opportunities.html",
                "https://www.iinano.org/reu/",
                "https://syntheticbiology.northwestern.edu/education/nsf-undergraduate-research-experience-reu.html",
                "https://clp.northwestern.edu/education/undergraduate-research-programs/summer-scholars/",
                "https://clp.northwestern.edu/education/undergraduate-research-programs/lambert/",
                "https://clp.northwestern.edu/education/undergraduate-research-programs/caurs/",
                "https://buffett.northwestern.edu/programs/undergraduate-opportunities/undergraduate-research-fellowship-program/",
                "https://naise.northwestern.edu/resources/students/undergraduate-student-opportunities/",
                "https://www.cancer.northwestern.edu/research/education-training/summer-research/lyric.html",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nu_ipr_sura",
                    "Northwestern IPR Summer Undergraduate Research Assistants (SURA)",
                    "https://www.ipr.northwestern.edu/who-we-are/students-postdocs/summer-undergraduate-research-assistant-program/",
                    "10-week summer program (since 1998) placing Northwestern first-years, "
                    "sophomores, and juniors with Institute for Policy Research faculty on "
                    "policy-relevant social science research. Pays $18.00/hour for up to 350 "
                    "hours (roughly 35 hours/week). International students with an eligible "
                    "F-1 visa may apply; matching typically happens March-May and housing is "
                    "not provided.",
                    organization="Northwestern University",
                    department="Institute for Policy Research",
                    lab_or_program="SURA Program",
                    opportunity_type="summer_program",
                    paid="yes",
                    compensation="$18.00/hour, up to 350 hours (~$6,300)",
                    eligibility_majors=["social sciences", "economics", "political science", "sociology", "psychology", "statistics"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="2026 applications closed; annual cycle with matches made March-May",
                    keywords=["policy research", "social science", "paid RA", "IPR", "summer"],
                ),
                program(
                    "nu_ciera_reu",
                    "Northwestern CIERA REU in Astrophysics",
                    "https://ciera.northwestern.edu/opportunities-for-undergraduates/reu/",
                    "Nine-week NSF-funded summer research experience at Northwestern's Center "
                    "for Interdisciplinary Exploration and Research in Astrophysics, with a "
                    "$6,300 stipend. Projects connect astronomy with applied math, chemistry, "
                    "earth and planetary science, electrical engineering, computer science, "
                    "and physics, plus programming and science-communication workshops. "
                    "Highly competitive (recently ~22 spots from 600+ applications); open to "
                    "undergraduates nationwide.",
                    organization="Northwestern University",
                    department="CIERA (Center for Interdisciplinary Exploration and Research",
                    lab_or_program="CIERA REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,300 over nine weeks",
                    eligibility_majors=["physics", "astronomy", "applied math", "computer science", "electrical engineering", "chemistry"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Annual winter deadline; check REU portal linked from CIERA site",
                    keywords=["astrophysics", "REU", "NSF", "summer research", "computational"],
                ),
                program(
                    "nu_mrsec_reu",
                    "Northwestern MRSEC Materials Science REU",
                    "https://mrsec.northwestern.edu/education/undergraduate-opportunities.html",
                    "Nine-week summer REU (June 15 - Aug 14, 2026) at Northwestern's "
                    "Materials Research Science and Engineering Center, spanning 30+ faculty "
                    "across 7 departments working on nanoscale and bioprogrammable materials. "
                    "Participants receive $6,000 plus on-campus housing and a travel "
                    "allowance. Restricted to U.S. citizens or permanent residents per NSF "
                    "rules; targets rising juniors and seniors, typical admitted GPA above "
                    "3.5.",
                    organization="Northwestern University",
                    department="Materials Research Science and Engineering Center (MRSEC)",
                    lab_or_program="MRSEC REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 + on-campus housing + travel allowance",
                    eligibility_majors=["materials science", "chemistry", "physics", "engineering", "biology"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Deadline Feb 13 for Summer 2026 (annual mid-February cycle)",
                    keywords=["materials science", "nanotechnology", "REU", "NSF", "synthetic biology"],
                ),
                program(
                    "nu_mrsec_uri",
                    "Northwestern MRSEC Academic-Year Undergraduate Research Internship (URI)",
                    "https://mrsec.northwestern.edu/education/undergraduate-opportunities.html",
                    "Academic-year internship pairing Northwestern science and engineering "
                    "undergraduates with MRSEC faculty mentors for materials research at "
                    "$15/hour, 10-20 hours per week. Open to U.S. citizens or permanent "
                    "residents; recent cohorts include about six undergraduate researchers. "
                    "Listed on the same MRSEC undergraduate opportunities page as the summer "
                    "REU.",
                    organization="Northwestern University",
                    department="Materials Research Science and Engineering Center (MRSEC)",
                    lab_or_program="MRSEC Undergraduate Research Internship",
                    paid="yes",
                    compensation="$15/hour, 10-20 hours/week during academic year",
                    eligibility_majors=["materials science", "chemistry", "physics", "engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Applications due late October for the academic-year cohort (Oct 31 in recent cycle)",
                    keywords=["academic year", "paid internship", "materials", "Northwestern students"],
                ),
                program(
                    "nu_iin_nanotech_reu",
                    "Northwestern International Institute for Nanotechnology REU",
                    "https://www.iinano.org/reu/",
                    "Nine-week summer nanotechnology REU (mid-June to mid-August) hosted by "
                    "Northwestern's International Institute for Nanotechnology, with a $6,300 "
                    "stipend, round-trip airfare, meal plan, and dorm housing. Includes "
                    "lectures, an Argonne National Laboratory field trip, writing workshop, "
                    "and a closing research symposium. Applicants must be 18+, U.S. citizens "
                    "or permanent residents, majoring in physical sciences or engineering "
                    "with at least one year left in their degree.",
                    organization="Northwestern University",
                    department="International Institute for Nanotechnology",
                    lab_or_program="IIN Nanotechnology REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,300 + airfare + meal plan + housing",
                    eligibility_majors=["chemistry", "physics", "materials science", "engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Deadline Feb 9, 2026 for Summer 2026 (annual early-February cycle)",
                    keywords=["nanotechnology", "REU", "NSF", "summer research", "Argonne"],
                ),
                program(
                    "nu_synbreu",
                    "Northwestern SynBREU \u2014 Synthetic Biology REU",
                    "https://syntheticbiology.northwestern.edu/education/nsf-undergraduate-research-experience-reu.html",
                    "NSF-funded 10-week summer program at Northwestern's Center for Synthetic "
                    "Biology supporting ten undergraduates in independent lab or "
                    "computational synthetic biology projects (biosensors, self-healing "
                    "materials, gene therapy delivery). Provides a $7,000 stipend plus room "
                    "and board support, meal plan, and travel for non-Chicagoland students. "
                    "Open to U.S. citizens, nationals, or permanent residents from all majors "
                    "who have completed their first year; students from non-PhD institutions "
                    "especially encouraged.",
                    organization="Northwestern University",
                    department="Center for Synthetic Biology",
                    lab_or_program="SynBREU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$7,000 + room and board + travel expenses",
                    eligibility_majors=["biology", "chemical engineering", "biomedical engineering", "chemistry", "computer science", "all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="2026 cohort closed; 2027 applications open November 2026",
                    keywords=["synthetic biology", "REU", "NSF", "biosensors", "wet lab"],
                ),
                program(
                    "nu_clp_summer_scholars",
                    "Northwestern CLP Summer Scholars Program",
                    "https://clp.northwestern.edu/education/undergraduate-research-programs/summer-scholars/",
                    "10-week full-time summer research program at the Chemistry of Life "
                    "Processes Institute, pairing Northwestern undergraduates with "
                    "CLP-affiliated faculty across 23+ departments at the interface of "
                    "chemistry, biology, medicine, and engineering. Award is $5,000 ($4,500 "
                    "stipend + $500 research expenses); culminates in a poster at the CLP "
                    "research forum. 82% of alumni pursue advanced degrees and scholars have "
                    "co-authored 45+ papers.",
                    organization="Northwestern University",
                    department="Chemistry of Life Processes Institute",
                    lab_or_program="CLP Summer Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,000 ($4,500 stipend + $500 supplies)",
                    eligibility_majors=["chemistry", "biology", "biomedical engineering", "physics", "chemical engineering"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications due mid-April (page shows a prior cycle; confirm current dates with CLP)",
                    keywords=["interdisciplinary", "chemical biology", "summer stipend", "Northwestern students"],
                ),
                program(
                    "nu_clp_lambert_fellowship",
                    "Northwestern CLP Lambert Fellowship",
                    "https://clp.northwestern.edu/education/undergraduate-research-programs/lambert/",
                    "CLP's most prestigious undergraduate award: multi-year (2+ year) funding "
                    "for hands-on laboratory research for rising sophomore and junior "
                    "Chemistry majors, mentored by CLP faculty. Worth $7,500 annually ($4,500 "
                    "summer stipend, $1,000 conference travel, $1,000 materials, plus "
                    "academic-year support); two fellows funded per year.",
                    organization="Northwestern University",
                    department="Chemistry of Life Processes Institute",
                    lab_or_program="Lambert Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$7,500/year for 2+ years",
                    eligibility_majors=["chemistry"],
                    preferred_year=["freshman", "sophomore"],
                    deadline_note="Applications due mid-April (page shows a prior cycle; confirm current dates with CLP)",
                    keywords=["chemistry majors", "multi-year fellowship", "lab research", "conference travel"],
                ),
                program(
                    "nu_clp_caurs_award",
                    "Northwestern CLP Undergraduate Research Award (CAURS)",
                    "https://clp.northwestern.edu/education/undergraduate-research-programs/caurs/",
                    "$1,000 award supporting interdisciplinary research with a CLP faculty "
                    "member, covering scientific supplies plus registration and travel to the "
                    "Chicago Area Undergraduate Research Symposium. Recipients complete two "
                    "or more quarters of research and present at CAURS; preference to rising "
                    "juniors and seniors, one award per year.",
                    organization="Northwestern University",
                    department="Chemistry of Life Processes Institute",
                    lab_or_program="CLP CAURS Award",
                    paid="stipend",
                    compensation="$1,000 grant",
                    eligibility_majors=["chemistry", "biology", "biomedical engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Applications due late October (page shows a prior cycle; confirm current dates with CLP)",
                    keywords=["symposium", "research supplies", "interdisciplinary", "academic year"],
                ),
                program(
                    "nu_buffett_research_fellowship",
                    "Northwestern Buffett Undergraduate Research Fellowship",
                    "https://buffett.northwestern.edu/programs/undergraduate-opportunities/undergraduate-research-fellowship-program/",
                    "Paid research assistantships embedding first-, second-, and third-year "
                    "students in faculty members' international and global research projects "
                    "(recently 28 students across 18 departments and six schools). Fellows "
                    "earn $16.60/hour for up to 250 summer hours, may continue up to three "
                    "academic-year quarters for up to $4,150 total, and do substantive "
                    "research rather than administrative work. No prior research experience "
                    "required.",
                    organization="Northwestern University",
                    department="Roberta Buffett Institute for Global Affairs",
                    lab_or_program="Buffett Undergraduate Research Fellowship",
                    opportunity_type="fellowship",
                    paid="yes",
                    compensation="$16.60/hour, up to 250 summer hours; up to $4,150 total with academic year",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Annual application deadline March 15, via SOAP portal",
                    keywords=["global affairs", "international research", "paid RA", "faculty projects", "interdisciplinary"],
                ),
                program(
                    "nu_naise_undergrad",
                    "Northwestern-Argonne Institute (NAISE) Undergraduate Opportunities",
                    "https://naise.northwestern.edu/resources/students/undergraduate-student-opportunities/",
                    "Hub for undergraduate research through the Northwestern + Argonne "
                    "Institute for Scientific and Engineering Excellence, including a 9-week "
                    "summer research experience for Northwestern undergraduates "
                    "(international students welcome) in areas like automated discovery, "
                    "environmental sensing, 5G, and materials imaging. Also links DOE "
                    "pipeline programs at Argonne National Laboratory (SULI, EERE Robotics, "
                    "Student Research Participation) which require U.S. citizenship/permanent "
                    "residency and a 3.0 GPA. Page content may lag the current cycle; contact "
                    "naise@northwestern.edu.",
                    organization="Northwestern University",
                    department="Northwestern-Argonne Institute of Science and Engineering (N",
                    lab_or_program="NAISE Summer Research Experience",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend (amount varies by program; REU-style support reported ~$5,750 + housing/",
                    eligibility_majors=["engineering", "computer science", "physics", "chemistry", "materials science", "environmental science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Cycles vary by program; page shows an older cohort \u2014 verify current openings with NAISE",
                    keywords=["Argonne", "national laboratory", "DOE", "computation", "energy"],
                ),
                program(
                    "nu_lurie_cancer_summer_internship",
                    "Northwestern Lurie Cancer Center Undergraduate Summer Research Internship",
                    "https://www.cancer.northwestern.edu/research/education-training/summer-research/lyric.html",
                    "Eight-week full-time summer internship (June 15 - Aug 7, 2026; 35-40 "
                    "hrs/week) in cancer research labs at the Robert H. Lurie Comprehensive "
                    "Cancer Center, spanning cell/molecular biology, immunology, genomics, "
                    "bioinformatics, population science, and health disparities. Interns "
                    "receive a $6,000 taxable stipend, mentoring, and career seminars but "
                    "arrange their own housing. Open to college freshmen through seniors with "
                    "strong biological/health science records; U.S. citizens or permanent "
                    "residents only.",
                    organization="Northwestern University",
                    department="Feinberg School of Medicine - Robert H. Lurie Comprehensive ",
                    lab_or_program="Lurie Cancer Center Undergraduate Summer Research Internship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 for 8 weeks (taxable; no housing)",
                    eligibility_majors=["biology", "chemistry", "biomedical engineering", "neuroscience", "health sciences"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Apply by Feb 16, 2026; recommendations Feb 23; decisions Mar 27",
                    keywords=["cancer research", "biomedical", "Feinberg", "summer internship", "wet lab"],
                ),
            ],
        },
        {
            "source_name": "northwestern_program_campus",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://undergradresearch.northwestern.edu/funding/ayurg/",
                "https://undergradresearch.northwestern.edu/academic-year-urg-advanced/",
                "https://undergradresearch.northwestern.edu/funding/surg/",
                "https://undergradresearch.northwestern.edu/summer-urg-advanced/",
                "https://undergradresearch.northwestern.edu/urap/",
                "https://undergradresearch.northwestern.edu/funding/ctg/",
                "https://undergradresearch.northwestern.edu/funding/circumnavigator-grant/",
                "https://undergradresearch.northwestern.edu/funding/emerging-scholars/",
                "https://www.mccormick.northwestern.edu/students/undergraduate/research-opportunities/grants-awards.html",
                "https://www.mccormick.northwestern.edu/biomedical/academics/undergraduate/research-opportunities/summer-research-awards.html",
                "https://baker.northwestern.edu/grants/summer-grants.html",
                "https://baker.northwestern.edu/grants/academic-year-grants.html",
                "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/index.html",
                "https://www.cancer.northwestern.edu/research/education-training/summer-research/index.html",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nu_srop",
                    "Northwestern Summer Research Opportunity Program (SROP)",
                    "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/index.html",
                    "Northwestern's flagship eight-week summer research experience for "
                    "sophomores and juniors from across the U.S., in ANY field — social "
                    "sciences, humanities, physical/chemical/biological sciences, math, and "
                    "engineering. Students are matched to a faculty mentor by research "
                    "interest, do full-time research, and attend weekly workshops on writing, "
                    "the GRE, and the graduate-school process. Aimed at students planning a "
                    "PhD (or MD/PhD, JD/PhD). Includes a stipend, round-trip travel to "
                    "Chicago, university housing, and a meal subsidy.",
                    organization="Northwestern University",
                    department="The Graduate School",
                    lab_or_program="SROP",
                    paid="stipend",
                    compensation="Stipend + round-trip travel + housing + meal subsidy",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Applications open Nov 1 for the following summer; U.S. citizen/permanent resident, GPA ≥ 3.5, PhD-bound",
                    keywords=["summer research", "SROP", "PhD pipeline", "faculty mentor", "all fields", "stipend"],
                ),
                program(
                    "nu_feinberg_lurie_summer",
                    "Feinberg / Lurie Cancer Center Summer Research Program",
                    "https://www.cancer.northwestern.edu/research/education-training/summer-research/index.html",
                    "Mentored summer cancer-research experience at Northwestern's Robert H. "
                    "Lurie Comprehensive Cancer Center (Feinberg School of Medicine), pairing "
                    "undergraduates with cancer-biology, oncology, and translational-research "
                    "labs. Full-time bench or clinical/translational research over the summer "
                    "with professional-development programming for students considering "
                    "biomedical PhD or MD/PhD paths.",
                    organization="Northwestern University",
                    department="Feinberg School of Medicine — Lurie Cancer Center",
                    lab_or_program="Lurie Cancer Center Summer Research",
                    paid="stipend",
                    compensation="Summer stipend",
                    eligibility_majors=["Biology", "Biochemistry", "Neuroscience",
                                        "Chemistry", "Cancer Biology", "Molecular Biosciences"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Applications typically due late winter/early spring for the summer cohort",
                    keywords=["cancer research", "oncology", "Feinberg", "Lurie", "summer research", "translational"],
                ),
                program(
                    "nu_ayurg",
                    "Northwestern Academic Year Undergraduate Research Grant (AYURG)",
                    "https://undergradresearch.northwestern.edu/funding/ayurg/",
                    "Up to $1,000 for research expenses on an independent academic-year "
                    "project in any field, tied to an approved for-credit course such as an "
                    "independent study, thesis seminar, or capstone. Open to current "
                    "Northwestern undergraduates including SPS and NU-Qatar students; "
                    "international students eligible. International travel projects may "
                    "request up to 50% of airfare in addition.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="AYURG",
                    paid="stipend",
                    compensation="Up to $1,000 expense grant (+up to 50% of airfare for international travel)",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="2026-27 deadlines: Oct 13, Nov 10, Jan 19, Feb 16 (11:59 PM CST, no extensions)",
                    keywords=["academic year", "research grant", "independent study", "thesis", "all majors"],
                ),
                program(
                    "nu_ayurg_advanced",
                    "Northwestern Academic Year URG Advanced",
                    "https://undergradresearch.northwestern.edu/academic-year-urg-advanced/",
                    "Follow-on grant of up to $1,000 for students who have already received "
                    "an Academic Year URG, funding continued or new research expenses. "
                    "Requires enrollment in an independent study or honors thesis course "
                    "during the grant year and a project aligned with the student's home "
                    "school. Application mirrors AYURG: two-page proposal, Gantt chart, "
                    "budget, and faculty endorsement.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Academic Year URG Advanced",
                    paid="stipend",
                    compensation="Up to $1,000 expense grant",
                    eligibility_majors=["all"],
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Four deadlines per academic year (Oct, Nov, Jan, Feb); prior AYURG required",
                    keywords=["academic year", "advanced grant", "honors thesis", "repeat funding"],
                ),
                program(
                    "nu_surg",
                    "Northwestern Summer Undergraduate Research Grant (SURG)",
                    "https://undergradresearch.northwestern.edu/funding/surg/",
                    "$4,000 stipend for eight weeks of full-time independent summer research "
                    "in any field under a faculty mentor. Open to current Northwestern "
                    "undergraduates including SPS and NU-Qatar students, first-time SURG "
                    "applicants only; international students eligible. Students may not take "
                    "classes or hold internships during the eight project weeks.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="SURG",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$4,000 for 8 weeks (+up to 50% airfare for international travel)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Summer 2027 deadline: Friday, March 5 (11:59 PM CST); decisions mid-late April",
                    keywords=["summer research", "stipend", "independent project", "all majors", "faculty mentor"],
                ),
                program(
                    "nu_surg_advanced",
                    "Northwestern Summer URG Advanced",
                    "https://undergradresearch.northwestern.edu/summer-urg-advanced/",
                    "$4,000 stipend for a second eight-week summer of full-time research, for "
                    "students who previously received an OUR Summer URG. Project must align "
                    "with the student's home school; McCormick students who already held both "
                    "a URG and a McCormick Summer Grant are ineligible. Cannot fund language "
                    "study, established institutional programs, study abroad, or internships.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Summer URG Advanced",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$4,000 for 8 weeks",
                    eligibility_majors=["all"],
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Summer 2026 deadline was Friday, March 13 (11:59 PM CST); annual mid-March cycle",
                    keywords=["summer research", "advanced grant", "repeat funding", "stipend"],
                ),
                program(
                    "nu_urap",
                    "Northwestern Undergraduate Research Assistant Program (URAP)",
                    "https://undergradresearch.northwestern.edu/urap/",
                    "Paid academic-year research assistantships ($16.60/hour, typically up to "
                    "100 hours / $1,660) pairing students who are new to research with "
                    "faculty mentors. Students apply either as faculty pre-selected "
                    "candidates or through an open job search via the Student Opportunities "
                    "Application Portal with a resume and four short essays. Great entry "
                    "point for students without prior research experience; international "
                    "students may apply but need an SSN before starting work.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="URAP",
                    paid="yes",
                    compensation="$16.60/hour, up to ~100 hours ($1,660)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="2026-27: pre-selected materials due Oct 6, 2026; open job search applications Oct 26 - Nov 8, 2026",
                    keywords=["research assistant", "paid", "beginners", "hourly", "faculty-initiated"],
                ),
                program(
                    "nu_conference_travel_grant",
                    "Northwestern Conference Travel Grant (CTG)",
                    "https://undergradresearch.northwestern.edu/funding/ctg/",
                    "Funds 50% of expenses (up to $500) for undergraduates presenting their "
                    "research at conferences or creative work at juried competitions. "
                    "Applicant must be the primary presenter and apply after acceptance but "
                    "before the event; one grant per academic year. Rolling deadlines with a "
                    "June 1 final cutoff.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Conference Travel Grants",
                    paid="stipend",
                    compensation="50% of expenses, up to $500",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Rolling; final deadline June 1 each year; apply before the conference",
                    keywords=["conference travel", "presentation", "reimbursement", "rolling deadline"],
                ),
                program(
                    "nu_circumnavigator_grant",
                    "Northwestern Circumnavigators Travel-Study Grant",
                    "https://undergradresearch.northwestern.edu/funding/circumnavigator-grant/",
                    "$10,000 grant for a solo around-the-world summer research project: at "
                    "least 10 continuous weeks of travel through 5+ countries on 3+ "
                    "continents, crossing every meridian. Open to juniors (any discipline) "
                    "who will return as full-time undergraduates; winners blog twice weekly "
                    "and produce a 50+ page research paper. Co-sponsored with the "
                    "Circumnavigators Club Chicago chapter.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Circumnavigators Travel-Study Grant",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$10,000 travel-study grant",
                    eligibility_majors=["all"],
                    preferred_year=["junior"],
                    deadline_note="Application due Nov 13 (11:59 PM CST); interviews early January",
                    keywords=["global travel", "independent research", "juniors only", "travel grant", "circumnavigation"],
                ),
                program(
                    "nu_emerging_scholars",
                    "Northwestern Emerging Scholars Program",
                    "https://undergradresearch.northwestern.edu/funding/emerging-scholars/",
                    "15-month cohort research program for first-year students in the arts, "
                    "humanities, journalism, and social sciences (non-lab fields). Pays "
                    "$4,000 per summer for two summers plus $750/quarter during sophomore "
                    "year, with on-campus housing the first summer. Students start as "
                    "research assistants to faculty mentors and transition to independent "
                    "projects, with weekly summer workshops and monthly academic-year "
                    "workshops.",
                    organization="Northwestern University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Emerging Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$4,000/summer x2 + $750/quarter sophomore year; first-summer housing",
                    eligibility_majors=["arts", "humanities", "journalism", "social sciences"],
                    preferred_year=["freshman"],
                    deadline_note="Applications due mid-March (March 14, 2027 for next cohort)",
                    keywords=["first-year", "humanities", "social science", "cohort", "mentored research"],
                ),
                program(
                    "nu_mccormick_summer_award",
                    "Northwestern McCormick Summer Research Award",
                    "https://www.mccormick.northwestern.edu/students/undergraduate/research-opportunities/grants-awards.html",
                    "Competitive award of up to $5,000 ($4,500 living stipend + up to $500 "
                    "research expenses) for roughly 8 weeks of full-time summer research "
                    "mentored by a Northwestern faculty member. Only McCormick-enrolled "
                    "students are eligible; no summer classes during the award period, and "
                    "priority goes to students without prior McCormick or OUR summer funding.",
                    organization="Northwestern University",
                    department="McCormick School of Engineering",
                    lab_or_program="McCormick Summer Research Award",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$4,500 stipend + up to $500 expenses",
                    eligibility_majors=["engineering", "computer science", "applied math", "materials science", "biomedical engineering", "chemical engineering"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="2026 deadline: 5:00 PM Monday, April 6, 2026 (annual early-April cycle)",
                    keywords=["engineering", "summer stipend", "faculty mentor", "McCormick"],
                ),
                program(
                    "nu_bme_summer_research_grant",
                    "Northwestern BME Summer Undergraduate Research Grants",
                    "https://www.mccormick.northwestern.edu/biomedical/academics/undergraduate/research-opportunities/summer-research-awards.html",
                    "Competitive $5,400 awards for BME undergraduates to spend nine weeks "
                    "(June 15 - Aug 14) full-time in a Biomedical Engineering faculty lab, "
                    "with a commitment to continue via BME 499 the following academic year. "
                    "The Michael Jaharis Undergraduate Research Fellowship provides "
                    "equivalent support for one student in pharmaceutical sciences "
                    "(cell/viral therapeutics, immunoengineering, drug delivery). Students "
                    "may simultaneously apply for URG and McCormick Summer Research Awards.",
                    organization="Northwestern University",
                    department="McCormick School of Engineering - Biomedical Engineering",
                    lab_or_program="BME Summer Undergraduate Research Grants / Jaharis Fellowshi",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,400 for 9 weeks",
                    eligibility_majors=["biomedical engineering"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Rolling acceptance; applications close April 6, 2026",
                    keywords=["biomedical engineering", "summer lab", "stipend", "Jaharis fellowship"],
                ),
                program(
                    "nu_wcas_summer_grant",
                    "Northwestern WCAS Summer Grant (Baker Program)",
                    "https://baker.northwestern.edu/grants/summer-grants.html",
                    "$4,000 stipend for Weinberg first-years, sophomores, and juniors to "
                    "conduct eight continuous weeks of summer research or creative work with "
                    "a faculty supervisor. Weinberg must be the home school; no summer "
                    "classes or overlapping research grants allowed, and priority goes to "
                    "rising seniors doing thesis-style independent work. Shorter 6-7 week "
                    "projects may receive prorated stipends.",
                    organization="Northwestern University",
                    department="Weinberg College of Arts and Sciences",
                    lab_or_program="WCAS Summer Grants",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$4,000 for 8 weeks (prorated for 6-7 weeks)",
                    eligibility_majors=["arts and sciences", "humanities", "social sciences", "natural sciences"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="2026 portal: April 15 - May 1 (11:59 PM); faculty endorsements due May 8",
                    keywords=["Weinberg", "summer stipend", "senior thesis", "faculty supervision"],
                ),
                program(
                    "nu_weinberg_academic_year_grant",
                    "Northwestern Weinberg Academic Year Research Grant (Baker Program)",
                    "https://baker.northwestern.edu/grants/academic-year-grants.html",
                    "Up to $1,000 for Weinberg undergraduates doing original research or "
                    "creative work under close faculty supervision during the academic year, "
                    "covering supplies, data collection, and travel (not equipment). Students "
                    "typically apply first to the Provost's Office URG before this Weinberg "
                    "fund; decisions come within about two weeks of a complete application.",
                    organization="Northwestern University",
                    department="Weinberg College of Arts and Sciences",
                    lab_or_program="Weinberg Academic Year Grants",
                    paid="stipend",
                    compensation="Up to $1,000 expense grant",
                    eligibility_majors=["arts and sciences", "humanities", "social sciences", "natural sciences"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Application window Sept 16, 2025 - April 1, 2026 (rolling decisions)",
                    keywords=["academic year", "Weinberg", "expense grant", "creative work"],
                ),
            ],
        },
    ],
}
