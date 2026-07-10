"""Johns Hopkins University campus opportunity-graph config (US-News Top-50 rollout).

Curated, live-verified seed of Johns Hopkins University's undergraduate-research landscape on the
generic ``campus_graph`` engine: the central undergraduate-research office, its
signature programs/fellowships/summer research, per-school research pipelines,
the career center, and research-institute cold-email targets. Every URL was
fetch-verified (HTTP 200 + real content) on 2026-07-08.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> jhu_research_programs (jhu / campus)
    open   -> jhu_external_research (national / open)
    lab    -> jhu_labs              (jhu / unknown)
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
    "school_slug": "jhu",
    "organization": "Johns Hopkins University",
    "location": "Baltimore, MD",
    "emit": {
        "campus": ("jhu_research_programs", "jhu", "campus"),
        "open": ("jhu_external_research", None, "open"),
        "lab": ("jhu_labs", "jhu", "unknown"),
    },
    "sources": [
        {
            "source_name": "jhu_announcement_campus",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://hour.jhu.edu/",
                "https://hour.jhu.edu/present/real/",
                "https://hour.jhu.edu/opportunities/aplinternships/",
                "https://krieger.jhu.edu/ursca/national-programs/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "hour_hub",
                    "Hopkins Office for Undergraduate Research (HOUR) \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/",
                    "Central hub for undergraduate research at Johns Hopkins, serving "
                    "Krieger, Whiting, and Peabody undergraduates. Administers PURA, Summer "
                    "PURA, the Catalyst Award, the BDP Summer Program, the Hu Institute "
                    "Summer Fellowship, and the REAL Showcase, and points students to the "
                    "ForagerOne opportunity database. Offers virtual office hours (Mon\u2013Thu "
                    "3\u20134pm ET) and step-by-step guides for getting started in research.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="HOUR",
                    compensation="Varies by program",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Varies by program; PURA closes Sept 1, summer awards typically close in spring",
                    keywords=["undergraduate research", "funding", "HOUR", "ForagerOne", "research hub"],
                ),
                program(
                    "real_showcase",
                    "REAL Showcase (formerly DREAMS) \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/present/real/",
                    "Twice-yearly (fall and spring) university-wide showcase where any "
                    "Hopkins undergraduate presents research, creative work, internships, "
                    "study abroad, honors projects, or community initiatives. Successor to "
                    "the long-running DREAMS undergraduate research day; runs virtually with "
                    "posters, slide decks, recorded performances, and gallery formats. A key "
                    "venue for networking and discovering labs that host undergraduates.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="REAL Showcase",
                    paid="no",
                    compensation="None (presentation venue)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Registration each fall and spring semester via Symposium platform",
                    keywords=["research symposium", "DREAMS", "poster session", "presentation", "showcase"],
                ),
                program(
                    "hour_apl_research_internships",
                    "Research Internships @APL (HOUR gateway) \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/opportunities/aplinternships/",
                    "HOUR's gateway page connecting Hopkins undergraduates to paid "
                    "internships at the Johns Hopkins Applied Physics Laboratory, with "
                    "Hopkins undergraduates receiving first consideration for many roles. "
                    "Fields include engineering and analysis, AI/ML, and cybersecurity; all "
                    "college interns receive competitive pay and paid holidays. HOUR does not "
                    "administer the programs \u2014 applications go through APL directly.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="Research Internships @APL",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Competitive hourly pay plus paid holidays",
                    eligibility_majors=["engineering", "computer science", "physics", "mathematics", "data science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Rolling via APL careers portal",
                    keywords=["APL", "applied physics laboratory", "paid internship", "defense research", "AI"],
                ),
                program(
                    "ursca_national_programs",
                    "URSCA National Research Programs hub \u2014 Johns Hopkins Krieger School",
                    "https://krieger.jhu.edu/ursca/national-programs/",
                    "Krieger School hub cataloging national summer research pathways "
                    "connected to Hopkins: the Amgen Scholars Program (~10 students annually "
                    "in STEM), NSF Research Experiences for Undergraduates across biology, "
                    "physics, nanotech, and bioengineering, the Leadership Alliance SR-EIP "
                    "residential program, PhD PATHS for students from minority-serving "
                    "institutions (paused summer 2026), and the Richard Macksey National "
                    "Undergraduate Humanities Research Symposium. Programs feature stipends, "
                    "housing, mentorship, and professional development.",
                    organization="Johns Hopkins University",
                    department="Krieger School of Arts and Sciences",
                    lab_or_program="URSCA National Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipends and housing vary by program",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Most national summer programs close January\u2013February",
                    keywords=["Amgen Scholars", "REU", "Leadership Alliance", "national programs", "humanities symposium"],
                ),
            ],
        },
        {
            "source_name": "jhu_career_campus",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://imagine.jhu.edu/resources/internship-programs/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "imagine_internship_programs",
                    "Imagine Center Internship Programs hub (Life Design Lab) \u2014 Johns Hopkins University",
                    "https://imagine.jhu.edu/resources/internship-programs/",
                    "Career-pipeline hub from JHU's Imagine Center/Life Design Lab cataloging "
                    "internship programs for Hopkins undergraduates: Community Impact "
                    "Internships (paid nonprofit/government placements in Baltimore), CLE "
                    "Undergraduate Business Internships (~25 sponsored per year), BME Your "
                    "Turn to Intern, MCEH healthcare engineering internships, Host a Jay "
                    "alumni shadowing, JUMP/Hop-In funded summer work, RISE@APL research "
                    "internships, the JHMI Summer Internship Program, and policy and "
                    "film/media pathways. Useful single entry point for paid experiential "
                    "opportunities beyond the lab.",
                    organization="Johns Hopkins University",
                    department="Imagine Center / Life Design Lab",
                    lab_or_program="Internship Programs",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Varies; several programs are paid or sponsored",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Varies by program; many recruit in fall and intersession",
                    keywords=["career pipeline", "paid internships", "Life Design Lab", "community impact", "experiential learning"],
                ),
            ],
        },
        {
            "source_name": "jhu_department_campus",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://engineering.jhu.edu/research/undergraduate-research-opportunities/",
                "https://krieger.jhu.edu/ursca/",
                "https://krieger.jhu.edu/publichealth/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "wse_undergraduate_research",
                    "Whiting School of Engineering Undergraduate Research Opportunities \u2014 Johns Hopkins University",
                    "https://engineering.jhu.edu/research/undergraduate-research-opportunities/",
                    "Whiting School hub listing engineering research pathways: RISE@APL, "
                    "PURA, PROPEL, the Vredenburg Travel Fund, and BDP fellowships, plus "
                    "summer REUs open to external students (CSMR robotics, INBT nanobio, "
                    "PARADIM materials, Rosetta Commons, BioREU, JSALT language technology, "
                    "and HEMI/MICA Extreme Arts). Notes that 70% of Hopkins undergraduates "
                    "take part in research, including with School of Medicine clinicians and "
                    "APL researchers.",
                    organization="Johns Hopkins University",
                    department="Whiting School of Engineering",
                    lab_or_program="WSE Undergraduate Research",
                    compensation="Varies by program",
                    eligibility_majors=["engineering", "computer science", "biomedical engineering", "materials science", "applied mathematics"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Varies by program",
                    keywords=["engineering research", "REU", "Whiting", "research hub", "summer research"],
                ),
                program(
                    "ksas_ursca",
                    "Office of Undergraduate Research, Scholarly & Creative Activity (URSCA) \u2014 Johns Hopkins Krieger School",
                    "https://krieger.jhu.edu/ursca/",
                    "The Krieger School's research office promoting equity and excellence in "
                    "undergraduate research across humanities, social sciences, and natural "
                    "sciences. Runs the Dean's ASPIRE Grant, the University Undergraduate "
                    "Research Fellowship, the Undergraduate Research Ambassadors "
                    "peer-mentoring program, and the Louis E. Goodman Award for creative "
                    "work. Also curates national program pathways such as Leadership Alliance "
                    "SR-EIP and REUs.",
                    organization="Johns Hopkins University",
                    department="Krieger School of Arts and Sciences",
                    lab_or_program="URSCA",
                    compensation="Varies by program",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Varies by program",
                    keywords=["URSCA", "arts and sciences", "research office", "peer mentoring", "funding"],
                ),
                program(
                    "public_health_studies",
                    "Public Health Studies Undergraduate Program \u2014 Johns Hopkins University",
                    "https://krieger.jhu.edu/publichealth/",
                    "Krieger School undergraduate major run in collaboration with the "
                    "Bloomberg School of Public Health, with a required Applied Experience "
                    "placing students in fieldwork with public health professionals. Many "
                    "students join ongoing research projects at the Bloomberg School, and the "
                    "honors program requires an independent research thesis mentored by JHU "
                    "faculty; seniors take graduate courses at BSPH. The program bulletin "
                    "board also relays HOUR summer research opportunities.",
                    organization="Johns Hopkins University",
                    department="Krieger School of Arts and Sciences \u2014 Public Health Studies",
                    lab_or_program="Public Health Studies",
                    compensation="Varies by placement",
                    eligibility_majors=["public health"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applied Experience arranged individually; honors thesis in senior year",
                    keywords=["public health", "applied experience", "epidemiology", "honors thesis", "Bloomberg School"],
                ),
            ],
        },
        {
            "source_name": "jhu_lab_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.jhuapl.edu/careers/internships",
                "https://hemi.jhu.edu/opportunities/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "apl_college_internships",
                    "Johns Hopkins Applied Physics Laboratory College Internships (incl. CIRCUIT)",
                    "https://www.jhuapl.edu/careers/internships",
                    "APL's college internship portal for paid summer and year-round positions "
                    "across mission areas including civil space flight, cyber operations, "
                    "national security, AI/ML, and materials science. Interns receive "
                    "competitive pay, paid holidays, and networking; eligibility requires a "
                    "3.0+ GPA and full-time enrollment the semester after the internship, and "
                    "many APL roles require U.S. citizenship for security clearance. The "
                    "CIRCUIT program (yearlong cohort-based research community with a "
                    "full-time summer at APL and ~$5,000 stipend, open to all majors) is "
                    "administered through this portal \u2014 its former st",
                    organization="Johns Hopkins University Applied Physics Laboratory",
                    department="APL Careers",
                    lab_or_program="APL Internships / CIRCUIT",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Competitive pay and paid holidays; CIRCUIT historically ~$5,000 summer stipend",
                    eligibility_majors=["engineering", "computer science", "physics", "mathematics", "data science", "all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Rolling applications via APL careers site; summer positions post in fall/winter",
                    keywords=["APL", "CIRCUIT", "paid internship", "national security", "space"],
                ),
                program(
                    "hemi_internships",
                    "Hopkins Extreme Materials Institute (HEMI) Internships & Opportunities \u2014 Johns Hopkins University",
                    "https://hemi.jhu.edu/opportunities/",
                    "HEMI hosts multiple internship programs placing high school and "
                    "undergraduate students in HEMI-affiliated labs studying materials and "
                    "structures under extreme conditions. Flagship undergraduate offering is "
                    "the HEMI/MICA Extreme Arts Summer Internship blending materials science "
                    "with creative practice; the page also features the V_f_Ox summer "
                    "internship and AEOP high school program, with interns presenting at "
                    "HEMI's annual poster session. HEMI faculty span Whiting, Krieger, and "
                    "APL.",
                    organization="Johns Hopkins University",
                    department="Hopkins Extreme Materials Institute",
                    lab_or_program="HEMI Internship Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Varies by program; summer internships are typically funded",
                    eligibility_majors=["materials science", "mechanical engineering", "physics", "art"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Varies by program; summer cycles typically close in winter/spring",
                    keywords=["extreme materials", "HEMI", "MICA", "Extreme Arts", "materials science internship"],
                ),
            ],
        },
        {
            "source_name": "jhu_program_campus",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://hour.jhu.edu/opportunities/pura/",
                "https://hour.jhu.edu/opportunities/summerpura/",
                "https://hour.jhu.edu/opportunities/catalyst/",
                "https://hour.jhu.edu/opportunities/bdpsp/",
                "https://hour.jhu.edu/opportunities/husummer/",
                "https://engineering.jhu.edu/about/outreach-and-belonging/hopkins-engineering-propel/",
                "https://engineering.jhu.edu/research/spur-apl/rise-apl/",
                "https://engineering.jhu.edu/ug-academic/engagement/vredenburg/",
                "https://krieger.jhu.edu/ursca/projects/aspire-grant/",
                "https://krieger.jhu.edu/ursca/projects/uurf/",
                "https://www.bme.jhu.edu/academics/bme-design/undergraduate-design-team/",
                "https://www.hopkinsmedicine.org/som/pathway/summer-internship-program",
                "https://csmsip.cellbio.jhmi.edu/",
                "https://publichealth.jhu.edu/about/inclusion-diversity-anti-racism-and-equity-idare/diversity-summer-internship-program-for-undergraduates",
                "https://johnshopkinsustar.com/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "jhu_ustar",
                    "Hopkins USTAR — Undergraduate Scholars Training in Aging Research",
                    "https://johnshopkinsustar.com/",
                    "A two-summer, mentor-guided research-training experience at the Johns "
                    "Hopkins Bloomberg School of Public Health focused on aging research — "
                    "Alzheimer's disease and related dementias — and on addressing health "
                    "disparities. Builds research competencies and professional skills for "
                    "undergraduates in MSTEM (medicine, science, technology, engineering, "
                    "math) fields, especially students underrepresented in aging research.",
                    organization="Johns Hopkins University",
                    department="Bloomberg School of Public Health",
                    lab_or_program="USTAR",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend (two-summer training program)",
                    eligibility_majors=["Public Health", "Biology", "Neuroscience",
                                        "Psychology", "Biostatistics", "Epidemiology"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Applications due late January (Jan 24 for the 2025 cohort)",
                    keywords=["aging research", "Alzheimer's", "dementia", "public health",
                              "health disparities", "two-summer", "USTAR"],
                ),
                program(
                    "pura",
                    "Provost's Undergraduate Research Award (PURA) \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/opportunities/pura/",
                    "Endowed award (est. 1993 via the Hodson Trust) providing a $3,000 "
                    "fellowship for independent research, scholarly, or creative projects "
                    "under a mentor from any Hopkins division, center, or institute. Open to "
                    "all registered Krieger, Whiting, and Peabody undergraduates in good "
                    "academic standing who are not graduating before May of the award year. "
                    "Applications from first-generation and limited-income students are "
                    "especially encouraged.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="PURA",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$3,000 fellowship",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications due September 1 (11:59 pm), including mentor letters",
                    keywords=["PURA", "provost award", "independent research", "fellowship", "creative projects"],
                ),
                program(
                    "summer_pura",
                    "Summer PURA \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/opportunities/summerpura/",
                    "Summer edition of the Provost's Undergraduate Research Award supporting "
                    "full-time independent summer research projects under a Hopkins mentor. "
                    "Open to registered Krieger, Whiting, and Peabody freshmen, sophomores, "
                    "and juniors in good academic standing (seniors excluded). Requires a "
                    "research resume, project proposal, and mentor support letter.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="Summer PURA",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer research fellowship stipend (amount not listed on page)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Spring application deadline; check HOUR site for current cycle",
                    keywords=["summer research", "PURA", "fellowship", "mentored research"],
                ),
                program(
                    "hour_catalyst_award",
                    "HOUR Catalyst Award \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/opportunities/catalyst/",
                    "Seed funding of up to $1,000 (requested in $100 increments) for "
                    "early-stage undergraduate projects that advance human health and "
                    "wellbeing. Open to registered Krieger, Whiting, and Peabody "
                    "undergraduates in good standing not graduating before December of the "
                    "award year; projects cannot be class assignments or capstones. Awardees "
                    "present findings at a REAL Showcase within one year.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="Catalyst Award",
                    paid="no",
                    compensation="Up to $1,000 in project funding",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling/periodic; see HOUR site for current cycle",
                    keywords=["seed funding", "health", "catalyst", "project grant", "early-stage"],
                ),
                program(
                    "bdp_summer_program",
                    "BDP Summer Program (Bloomberg Distinguished Professorships) \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/opportunities/bdpsp/",
                    "Ten-week, full-time (35\u201340 hrs/week) summer research fellowship placing "
                    "Hopkins undergraduates in the labs and research groups of Bloomberg "
                    "Distinguished Professors, with a $6,000 stipend. Established in 2018; "
                    "more than 130 students have participated. Open to registered Krieger, "
                    "Whiting, and Peabody undergraduates in good standing; applicants select "
                    "up to 3 BDPs of interest.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="BDP Summer Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 stipend for 10 weeks",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Spring deadline; program runs roughly June 1 \u2013 Aug 15",
                    keywords=["Bloomberg Distinguished Professors", "summer fellowship", "interdisciplinary", "mentored research"],
                ),
                program(
                    "hu_institute_summer_fellowship",
                    "Hu Institute Foundation Summer Research Fellowship \u2014 Johns Hopkins University",
                    "https://hour.jhu.edu/opportunities/husummer/",
                    "HOUR-administered summer fellowship for independent projects in "
                    "molecular, cell, or computational research advancing genome-scale "
                    "understanding. Open to registered Krieger and Whiting freshmen through "
                    "juniors in good academic standing; applications from underserved and "
                    "underrepresented students are especially welcomed. Requires a research "
                    "resume, proposal, and mentor letter; awardees present at a REAL event "
                    "within a year.",
                    organization="Johns Hopkins University",
                    department="Hopkins Office for Undergraduate Research",
                    lab_or_program="Hu Institute Foundation Summer Research Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer fellowship stipend (amount not listed on page)",
                    eligibility_majors=["biology", "molecular biology", "computational biology", "biomedical engineering", "chemistry"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Spring deadline; see HOUR site for current cycle",
                    keywords=["genomics", "molecular biology", "computational research", "summer fellowship"],
                ),
                program(
                    "propel",
                    "Hopkins Engineering PROPEL Summer Research Program \u2014 Johns Hopkins University",
                    "https://engineering.jhu.edu/about/outreach-and-belonging/hopkins-engineering-propel/",
                    "Fully funded eight-week residential summer research program (May 27 \u2013 "
                    "July 24, 2026) at the Whiting School for undergraduates from other U.S. "
                    "colleges, providing faculty-mentored research, graduate-school "
                    "preparation workshops, housing, meal plan, competitive stipend, and "
                    "round-trip travel. Priority to rising juniors and seniors with a 3.0+ "
                    "GPA; students from under-resourced backgrounds and institutions with "
                    "limited research opportunities are strongly encouraged. F-1 "
                    "international students already enrolled at U.S. universities are "
                    "eligible alongside U.S. citizens and permanent residents.",
                    organization="Johns Hopkins University",
                    department="Whiting School of Engineering",
                    lab_or_program="PROPEL",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Competitive stipend plus housing, meal plan, and round-trip travel",
                    eligibility_majors=["engineering", "computer science", "materials science", "biomedical engineering", "STEM"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="2026 applications closed; opens each winter with decisions by early April",
                    keywords=["PROPEL", "summer research", "visiting students", "graduate school prep", "fully funded"],
                ),
                program(
                    "rise_apl",
                    "RISE@APL Research Internships \u2014 Johns Hopkins University",
                    "https://engineering.jhu.edu/research/spur-apl/rise-apl/",
                    "Paid 8\u201312 week summer research internships (late May through August) "
                    "placing Whiting and Krieger undergraduate and graduate students on "
                    "APL-sponsored research projects across the Laboratory's mission areas. "
                    "Requires a 3.0+ GPA and enrollment in the following fall semester; apply "
                    "with resume and unofficial transcript through the APL careers site. "
                    "Applications are rolling, with early consideration for those applying by "
                    "March 31.",
                    organization="Johns Hopkins University",
                    department="Whiting School of Engineering",
                    lab_or_program="RISE@APL",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Paid internship (competitive APL intern pay)",
                    eligibility_majors=["engineering", "computer science", "physics", "applied mathematics", "data science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Rolling; apply by March 31 for early consideration",
                    keywords=["RISE", "APL", "paid research internship", "mission areas", "summer"],
                ),
                program(
                    "vredenburg_travel_fund",
                    "Vredenburg Travel Fund \u2014 Johns Hopkins University (Whiting School)",
                    "https://engineering.jhu.edu/ug-academic/engagement/vredenburg/",
                    "Funds Whiting engineering sophomores and juniors to design a 6\u20139 week "
                    "international summer experience \u2014 research, internship (paid or unpaid), "
                    "or service project \u2014 applying their engineering skills abroad. Projects "
                    "funded up to $10,000 (typically $5,000\u2013$8,000) covering airfare, "
                    "housing, and food. Recipients present at a public poster session the "
                    "following fall; engineering must be the applicant's primary major.",
                    organization="Johns Hopkins University",
                    department="Whiting School of Engineering",
                    lab_or_program="Vredenburg Travel Fund",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Up to $10,000 (typical $5,000\u2013$8,000) for international experience costs",
                    eligibility_majors=["engineering"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications open early November; submissions due late February for the following summer",
                    keywords=["international research", "travel fund", "engineering abroad", "internship funding"],
                ),
                program(
                    "deans_aspire_grant",
                    "Dean's ASPIRE Grant \u2014 Johns Hopkins Krieger School",
                    "https://krieger.jhu.edu/ursca/projects/aspire-grant/",
                    "Grants of $500\u2013$5,000 supporting independent research projects by "
                    "Krieger School undergraduates in the humanities, natural sciences, and "
                    "social sciences, usable over a full year for travel, equipment, "
                    "supplies, and data collection (student stipends allowed if essential to "
                    "the project). First-years, sophomores, and juniors may apply; seniors "
                    "are not eligible. Recent cycle: pre-application December 21, final "
                    "application January 25.",
                    organization="Johns Hopkins University",
                    department="Krieger School of Arts and Sciences",
                    lab_or_program="Dean's ASPIRE Grant",
                    paid="stipend",
                    compensation="$500\u2013$5,000 research grant; stipend permitted if essential",
                    eligibility_majors=["humanities", "social sciences", "natural sciences"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Pre-application late December; final application late January",
                    keywords=["ASPIRE", "research grant", "independent project", "arts and sciences"],
                ),
                program(
                    "university_undergraduate_research_fellowship",
                    "University Undergraduate Research Fellowship (formerly Woodrow Wilson Fellowship) \u2014 Johns Hopkins Krieger Scho",
                    "https://krieger.jhu.edu/ursca/projects/uurf/",
                    "Prestigious three-year fellowship selecting about 10 Krieger School "
                    "students in their first year to carry out a sustained independent "
                    "research project, with up to $12,000 in funding for travel, equipment, "
                    "archives, or lab costs. Renamed in 2024 from the Woodrow Wilson "
                    "Undergraduate Research Fellowship. Fellows must remain KSAS majors, "
                    "though interdisciplinary research across Hopkins divisions is "
                    "encouraged.",
                    organization="Johns Hopkins University",
                    department="Krieger School of Arts and Sciences",
                    lab_or_program="University Undergraduate Research Fellowship",
                    opportunity_type="fellowship",
                    paid="no",
                    compensation="Up to $12,000 over three years for research costs",
                    eligibility_majors=["humanities", "social sciences", "natural sciences"],
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    deadline_note="Selection occurs during students' first year; check URSCA for current cycle",
                    keywords=["fellowship", "three-year research", "Woodrow Wilson", "independent research", "first-year"],
                ),
                program(
                    "bme_undergraduate_design_team",
                    "BME Undergraduate Design Team \u2014 Johns Hopkins University",
                    "https://www.bme.jhu.edu/academics/bme-design/undergraduate-design-team/",
                    "The nation's first longitudinal team-based medical device design program "
                    "(founded 1998), supporting ~20 teams of five to eight BME undergraduates "
                    "per year through an 18-month cycle from clinical problem to tested "
                    "prototype and Design Day. Teams work with medtech design and "
                    "commercialization experts and clinical mentors, learning regulatory, IP, "
                    "and business skills. Outcomes since 2001 include 250+ device projects, "
                    "40 provisional patents, 16 startups, and $2M+ in external funding; JHU "
                    "BME students can apply as early as spring of their first year.",
                    organization="Johns Hopkins University",
                    department="Department of Biomedical Engineering (Whiting School)",
                    lab_or_program="BME Design Team",
                    paid="no",
                    compensation="Course credit; project resources and mentorship",
                    eligibility_majors=["biomedical engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Team selection each spring semester",
                    keywords=["medical devices", "design team", "prototyping", "BME", "translational"],
                ),
                program(
                    "som_summer_internship_program",
                    "Johns Hopkins School of Medicine Summer Internship Program (SIP)",
                    "https://www.hopkinsmedicine.org/som/pathway/summer-internship-program",
                    "Umbrella of ~10-week, full-time summer biomedical research internships "
                    "at the School of Medicine (2026: May 24\u2013August 1) with stipends of "
                    "$3,000\u2013$5,750 and free housing. Sub-programs include BSI-SIP basic "
                    "science tracks, NeuroSIP, SUPerKS kidney science (U.S. citizens/PR, 3.0+ "
                    "GPA), CSM SIP for low-income/first-generation students, and ICM "
                    "computational medicine. Open to current undergraduates at U.S. colleges; "
                    "concurrent coursework or employment is prohibited.",
                    organization="Johns Hopkins University School of Medicine",
                    department="School of Medicine Pathway Programs",
                    lab_or_program="Summer Internship Program (SIP)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$3,000\u2013$5,750 stipend plus free housing",
                    eligibility_majors=["biology", "neuroscience", "chemistry", "biomedical engineering", "public health", "computer science"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="2026 applications closed; cycles typically open in fall with winter deadlines",
                    keywords=["biomedical research", "SIP", "medical school", "summer internship", "stipend"],
                ),
                program(
                    "csm_sip",
                    "Careers in Science and Medicine Summer Internship Program (CSM SIP) \u2014 Johns Hopkins School of Medicine",
                    "https://csmsip.cellbio.jhmi.edu/",
                    "The undergraduate component of the Johns Hopkins Initiative for Careers "
                    "in Science and Medicine: a ~10-week mentored summer research experience "
                    "modeled on a first-year graduate lab rotation, with a minimum $3,000 "
                    "stipend and free housing. Targets low-income (<200% federal poverty "
                    "level), educationally under-resourced, and first-generation students "
                    "interested in science, medicine, and public health careers. Includes "
                    "professional development, networking, and a closing research "
                    "presentation; some scholars continue into the Doctoral Development "
                    "Program.",
                    organization="Johns Hopkins University School of Medicine",
                    department="Department of Cell Biology / CSM Initiative",
                    lab_or_program="CSM SIP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Minimum $3,000 stipend plus free housing",
                    eligibility_majors=["biology", "chemistry", "neuroscience", "public health", "pre-med"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Summer 2027 applications open fall 2026",
                    keywords=["first-generation", "low-income", "biomedical research", "pipeline", "summer internship"],
                ),
                program(
                    "bsph_diversity_summer_internship",
                    "Diversity Summer Internship Program (DSIP) \u2014 Johns Hopkins Bloomberg School of Public Health",
                    "https://publichealth.jhu.edu/about/inclusion-diversity-anti-racism-and-equity-idare/diversity-summer-internship-program-for-undergraduates",
                    "Eight-week summer program (2026: May 31\u2013July 24) giving undergraduates a "
                    "graduate-level mentored research experience in biomedical or public "
                    "health fields at the Bloomberg School, with a $3,000 stipend and "
                    "provided housing. Applicants must have completed two years of study "
                    "(preference for those with 1\u20132 years remaining) and be U.S. citizens or "
                    "permanent residents. Decisions are released late March to mid-April.",
                    organization="Johns Hopkins Bloomberg School of Public Health",
                    department="Office of Inclusion, Diversity, Anti-Racism and Equity",
                    lab_or_program="DSIP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$3,000 stipend plus housing (transportation and meals not covered)",
                    eligibility_majors=["public health", "biology", "epidemiology", "biostatistics", "social sciences"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="2026 closed; 2027 applications open fall 2026",
                    keywords=["public health research", "DSIP", "diversity", "summer internship", "Bloomberg School"],
                ),
            ],
        },
        {
            "source_name": "jhu_program_lab",
            "source_type": PROGRAM,
            "emit": "lab",
            "seeds": [
                "https://inbt.jhu.edu/nanobio-reu/",
                "https://lcsr.jhu.edu/reu/",
                "https://bioethics.jhu.edu/education-training/mentorship/",
                "https://snfagora.jhu.edu/curricular-programs/ba-in-moral-political-economy/undergraduate-summer-internship-program/",
                "https://snfagora.jhu.edu/for-students/research-assistants-program/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "inbt_nanobio_reu",
                    "INBT NanoBio Research Experience for Undergraduates \u2014 Johns Hopkins Institute for NanoBioTechnology",
                    "https://inbt.jhu.edu/nanobio-reu/",
                    "NSF-funded nine-week summer REU (early June\u2013early August, running since "
                    "2008) placing visiting undergraduates in Hopkins nanobiotechnology labs "
                    "working on cancer therapies, regenerative engineering, diagnostics, and "
                    "cell programming. Provides a stipend, paid housing, and travel "
                    "allowance. Restricted to U.S. citizens/permanent residents from "
                    "institutions other than JHU, with a 3.5 GPA minimum and at least "
                    "freshman year completed; apply via the NSF ETAP platform.",
                    organization="Johns Hopkins University",
                    department="Institute for NanoBioTechnology",
                    lab_or_program="NanoBio REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU stipend plus paid housing and travel allowance",
                    eligibility_majors=["biomedical engineering", "chemical engineering", "materials science", "biology", "chemistry", "physics"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Applications open November 1 and close February 1 for the following summer",
                    keywords=["REU", "nanobiotechnology", "NSF", "summer research", "cancer research"],
                ),
                program(
                    "lcsr_csmr_reu",
                    "Computational Sensing and Medical Robotics (CSMR) REU \u2014 Johns Hopkins LCSR",
                    "https://lcsr.jhu.edu/reu/",
                    "Intensive ten-week NSF-funded summer REU (2026: May 26\u2013August 1) in the "
                    "Laboratory for Computational Sensing and Robotics, pairing each student "
                    "with a faculty supervisor and graduate mentor on projects in surgical "
                    "robotics, medical imaging, and assistive devices across ECE, MechE, BME, "
                    "and CS. Historically provides a $5,000 stipend plus summer housing, with "
                    "training in technical communication and research ethics. Open to U.S. "
                    "citizens/permanent residents who have completed freshman year with at "
                    "least one semester of engineering coursework.",
                    organization="Johns Hopkins University",
                    department="Laboratory for Computational Sensing and Robotics",
                    lab_or_program="CSMR REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,000 stipend plus summer housing (NSF-funded)",
                    eligibility_majors=["electrical engineering", "mechanical engineering", "biomedical engineering", "computer science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="2026 cycle closed; 2027 applications open fall 2026",
                    keywords=["robotics", "REU", "medical robotics", "computational sensing", "surgical"],
                ),
                program(
                    "berman_genomics_society_mentorship",
                    "Genomics and Society Mentorship Program (GSMP) \u2014 Johns Hopkins Berman Institute of Bioethics",
                    "https://bioethics.jhu.edu/education-training/mentorship/",
                    "A 15-month hybrid program beginning with a 10-week summer internship "
                    "($5,000 stipend) researching the ethical, legal, and social implications "
                    "(ELSI) of genomics, mentored by Berman Institute bioethics faculty. "
                    "Trainees take foundational courses in the Berman Summer Institute, join "
                    "weekly journal clubs and seminars, and continue mentored work through "
                    "the academic year. Open to full-time college students who have completed "
                    "at least one year; aims to broaden participation in ELSI research.",
                    organization="Johns Hopkins University",
                    department="Berman Institute of Bioethics",
                    lab_or_program="Genomics and Society Mentorship Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,000 stipend",
                    eligibility_majors=["bioethics", "biology", "philosophy", "public health", "genomics"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications typically due February 1 for the summer cohort",
                    keywords=["bioethics", "genomics", "ELSI", "mentorship", "summer internship"],
                ),
                program(
                    "snf_agora_summer_internship",
                    "Undergraduate Summer Internship Program \u2014 SNF Agora Institute, Johns Hopkins University",
                    "https://snfagora.jhu.edu/curricular-programs/ba-in-moral-political-economy/undergraduate-summer-internship-program/",
                    "Competitive, fully paid ten-week (40 hrs/week) summer internships run by "
                    "the Center for Economy and Society at SNF Agora and the Center on Global "
                    "Poverty, placing students with international development organizations "
                    "in Washington, D.C. such as the World Bank, IFPRI, CGIAR, and the "
                    "International Rice Research Institute. Interns earn a competitive salary "
                    "and register for a 1-credit summer course. Open to JHU undergraduates "
                    "with a declared Moral & Political Economy major; Summer 2026 deadline "
                    "was March 1.",
                    organization="Johns Hopkins University",
                    department="SNF Agora Institute",
                    lab_or_program="CES/CGP Undergraduate Summer Internship Program",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Competitive salary for 10 weeks full-time",
                    eligibility_majors=["moral and political economy", "economics", "political science"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications due March 1 with decisions by March 15",
                    keywords=["international development", "World Bank", "democracy", "policy internship", "Washington DC"],
                ),
                program(
                    "snf_agora_research_assistants",
                    "Research Assistants Program \u2014 SNF Agora Institute, Johns Hopkins University",
                    "https://snfagora.jhu.edu/for-students/research-assistants-program/",
                    "Connects JHU students with SNF Agora faculty and fellows as research "
                    "assistants on projects about democracy and civic life, with priority to "
                    "Krieger School students. Funding is provided whenever possible but "
                    "varies by project, and volunteer positions also exist. Students submit a "
                    "CV via a Google Form and are contacted directly as project openings "
                    "arise.",
                    organization="Johns Hopkins University",
                    department="SNF Agora Institute",
                    lab_or_program="Research Assistants Program",
                    compensation="Funding varies by project; some positions volunteer",
                    eligibility_majors=["political science", "sociology", "economics", "international studies", "all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; matched as faculty projects open",
                    keywords=["democracy", "civic engagement", "research assistant", "social science"],
                ),
            ],
        },
        {
            "source_name": "jhu_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://theleadershipalliance.org/summer-research-early-identification-program",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "leadership_alliance_sreip_jhu",
                    "Leadership Alliance Summer Research Early Identification Program (SR-EIP) \u2014 Johns Hopkins sites",
                    "https://theleadershipalliance.org/summer-research-early-identification-program",
                    "National fully funded 8\u201311 week residential summer research program "
                    "preparing undergraduates for PhD and MD-PhD applications, with stipend, "
                    "housing, and travel support and a capstone presentation at the "
                    "Leadership Alliance National Symposium. Johns Hopkins participates as a "
                    "host site through the Bloomberg School of Public Health, School of "
                    "Medicine, and Krieger School. Class-year eligibility varies by site "
                    "(rising sophomores through rising seniors); applications open November 1 "
                    "and close in early February.",
                    organization="The Leadership Alliance",
                    department="Johns Hopkins participating sites (BSPH, SOM, KSAS)",
                    lab_or_program="SR-EIP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend plus housing and travel (varies by site)",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Opens November 1; due early February (2026 cycle: February 3)",
                    keywords=["Leadership Alliance", "SR-EIP", "PhD pipeline", "summer research", "national program"],
                ),
            ],
        },
    ],
}
