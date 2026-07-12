"""Caltech campus opportunity-graph config (US-News Top-50 rollout).

Curated, live-verified seed of Caltech's undergraduate-research landscape on
the generic ``campus_graph`` engine: the Student-Faculty Programs office (SFP)
and its flagship SURF/WAVE/Amgen programs, the JPL internship pipeline, the
first-year bridge and academic-year funding channels, and the institutes
(KNI, Beckman, Resnick, Chen, IQIM, IPAC) that host undergraduates as
cold-email targets. Every URL was fetch-verified (HTTP 200 + real content) on
2026-07-09; discontinued programs (MURF — folded into WAVE) were dropped.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> caltech_research_programs (caltech / campus)
    open   -> caltech_external_research (national / open)
    lab    -> caltech_labs              (caltech / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    LAB,
    PROGRAM,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "caltech",
    "organization": "California Institute of Technology",
    "location": "Pasadena, CA",
    "emit": {
        "campus": ("caltech_research_programs", "caltech", "campus"),
        "open": ("caltech_external_research", None, "open"),
        "lab": ("caltech_labs", "caltech", "unknown"),
    },
    "sources": [
        {
            "source_name": "caltech_announcement_campus",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://sfp.caltech.edu/undergraduate-research/programs",
                "https://www.admissions.caltech.edu/why-caltech/research",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "sfp_hub",
                    "Student-Faculty Programs (SFP) — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs",
                    "Caltech's central office for undergraduate research, administering "
                    "SURF, SURF@JPL, WAVE Fellows, Amgen Scholars, Rising Tide, the "
                    "visiting-student VURP pathway, exchange programs, and the research "
                    "communication competitions. More than 90% of Caltech undergraduates "
                    "do research before graduating, and SFP is the front door: it runs "
                    "the application systems, mentor matching, seminar programming, and "
                    "the end-of-summer SURF Seminar Days.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="SFP",
                    compensation="Varies by program",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Varies by program; SURF closes March 1, WAVE January 9",
                    keywords=["undergraduate research", "SURF", "research hub", "summer research", "SFP"],
                ),
                program(
                    "caltech_research_expectation",
                    "Undergraduate Research at Caltech (research overview)",
                    "https://www.admissions.caltech.edu/why-caltech/research",
                    "At Caltech undergraduate research is an expectation, not an "
                    "exception: more than 90% of undergraduates participate in research "
                    "before graduating, and roughly half begin in their first year. The "
                    "campus hosts 50+ research centers and institutes, including five "
                    "NASA facilities, and students join labs through SURF, academic-year "
                    "research for credit, senior theses, and direct arrangements with "
                    "faculty. A useful orientation page for students planning their "
                    "research path into any of the six divisions.",
                    organization="California Institute of Technology",
                    department="Undergraduate Admissions",
                    lab_or_program="Undergraduate Research",
                    paid="unknown",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Informational; see SURF and academic-year channels",
                    keywords=["undergraduate research", "research culture", "orientation", "Caltech"],
                ),
            ],
        },
        {
            "source_name": "caltech_program_campus",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://ccid.caltech.edu/buildcommunity/signature-programs/fsri",
                "https://sfp.caltech.edu/undergraduate-research/programs/off-campus-surf",
                "https://sfp.caltech.edu/undergraduate-research/programs/exchange_programs",
                "https://sfp.caltech.edu/undergraduate-research/programs/academic_year_opps",
                "https://deans.caltech.edu/Grants_Funding/gwhfund",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "fsri",
                    "First-Year Success Research Institute (FSRI) — Caltech",
                    "https://ccid.caltech.edu/buildcommunity/signature-programs/fsri",
                    "Summer residential bridge program for incoming Caltech first-years "
                    "run by the Center for Inclusion and Diversity: a comprehensive "
                    "orientation combining an academic program (asynchronous 'Math 0' "
                    "transition-to-proofs modules plus a four-week synchronous "
                    "component), a mentored research project, and a living-learning "
                    "community whose programming continues through the academic year. "
                    "Selection prioritizes students who would most benefit — for "
                    "example strong admits without prior college-level research access. "
                    "All major expenses (travel, housing, meals, field trips) are "
                    "covered.",
                    organization="California Institute of Technology",
                    department="Caltech Center for Inclusion and Diversity",
                    lab_or_program="FSRI",
                    opportunity_type="summer_program",
                    paid="no",
                    compensation="All major expenses covered (travel, housing, meals)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    deadline_note="Applications via Beaver Breakroom from February; due April 27",
                    keywords=["bridge program", "first-year", "residential", "mentored research", "FSRI"],
                ),
                program(
                    "off_campus_surf",
                    "Off-Campus SURF — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/off-campus-surf",
                    "Lets Caltech students take their Summer Undergraduate Research "
                    "Fellowship to a mentor at another university in the US or abroad. "
                    "Requires attending a fall/winter info session and securing a "
                    "Caltech faculty associate mentor in a similar research area; the "
                    "standard SURF application, eligibility, and deliverables apply. "
                    "SFP cost-shares the award with the external mentor's institution, "
                    "which also covers research costs; students arrange visas, travel, "
                    "and housing. In-person only, excluding locations under State "
                    "Department Level 3+ travel advisories.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="Off-Campus SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Standard SURF award ($8,110 in 2026), cost-shared with host",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="SURF cycle — March 1; info session attendance required",
                    keywords=["off-campus", "research abroad", "SURF", "external mentor"],
                ),
                program(
                    "surf_exchange_iceland",
                    "SURF Exchange Program (University of Iceland) — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/exchange_programs",
                    "SFP-administered research exchange with the University of Iceland. "
                    "Caltech applicants submit an application, personal statement, two "
                    "faculty recommendations, and transcript, interview in March, and "
                    "file a project plan with the host mentor by mid-May; the summer "
                    "then runs as a full-time ten-week SURF with the standard reports "
                    "plus a fall Seminar Day talk. Students handle visas, travel, and "
                    "housing. Inbound students from partner institutions (Iceland and "
                    "several Cambridge colleges) apply through their home universities.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="SURF Exchange",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="SURF-level support; student covers travel/visa/housing",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Application due early March (2026: March 2, 5pm)",
                    keywords=["exchange", "Iceland", "international research", "SURF"],
                ),
                program(
                    "academic_year_research",
                    "Academic-Year Undergraduate Research (credit, thesis, or pay) — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/academic_year_opps",
                    "Term-time research channels at Caltech: research for academic "
                    "credit (offered by most options), the senior thesis (original "
                    "faculty-mentored research with a scholarly write-up and oral exam), "
                    "and paid research positions in faculty labs with rates set by work "
                    "type and class level — Federal and Caltech Work Study can "
                    "subsidize positions. Students cannot receive both credit and pay "
                    "for the same work. Entry is through the research option's advisor "
                    "or directly with a faculty member; many students continue their "
                    "SURF projects into the academic year.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="Academic-Year Research",
                    paid="yes",
                    compensation="Hourly pay (rate by class level) or academic credit",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling — arranged with faculty each term",
                    keywords=["academic year", "research for credit", "senior thesis", "paid research", "work study"],
                ),
                program(
                    "housner_fund",
                    "George W. Housner Student Discovery Fund — Caltech",
                    "https://deans.caltech.edu/Grants_Funding/gwhfund",
                    "Endowed fund (from earthquake-engineering pioneer George W. "
                    "Housner) that finances undergraduate scholarly activity outside "
                    "the SURF award structure: independent research projects (including "
                    "SURF continuations), technical club and organization projects, "
                    "conference travel to present research, and independent study. "
                    "Individual or group proposals are accepted at any time and "
                    "reviewed four times a year by a committee of the Associate Dean, "
                    "two faculty members, and two undergraduates.",
                    organization="California Institute of Technology",
                    department="Undergraduate Deans' Office",
                    lab_or_program="Housner Student Discovery Fund",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Project grants (amounts vary by proposal)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; committee decisions four times per year",
                    keywords=["research funding", "conference travel", "student grants", "independent study"],
                ),
                program(
                    "perpall_competition",
                    "Doris S. Perpall SURF Speaking Competition — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/communication-competitions/doris-s-perpall-surf-speaking-competition",
                    "Thirty-plus-year-old competition judging the oral presentation of "
                    "SURF research, endowed by Robert C. Perpall (BS '52, MS '56) in "
                    "memory of his wife. SURF fellows compete in rounds through the "
                    "fall; finalists present to a campus-wide audience. Sibling "
                    "competitions cover posters (Gee Family SURF Poster Competition) "
                    "and technical writing (Bonsall Prize). A strong incentive layer "
                    "on top of the SURF experience for students building research "
                    "communication skills.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="Perpall Speaking Competition",
                    opportunity_type="fellowship",
                    paid="no",
                    compensation="Prize awards",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Follows each SURF cycle (fall rounds)",
                    keywords=["science communication", "speaking competition", "SURF", "prize"],
                ),
            ],
        },
        {
            "source_name": "caltech_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://sfp.caltech.edu/undergraduate-research/programs/surf",
                "https://sfp.caltech.edu/undergraduate-research/programs/wavefellows",
                "https://sfp.caltech.edu/undergraduate-research/programs/amgen_scholars",
                "https://labcit.ligo.caltech.edu/LIGO_web/students/SURF/",
                "https://www.jpl.nasa.gov/edu/internships/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "surf",
                    "Summer Undergraduate Research Fellowships (SURF) — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/surf",
                    "Caltech's flagship undergraduate research program since 1979 and "
                    "one of the Institute's 'crown jewels'. Modeled on the grant-seeking "
                    "process: students define a project with a Caltech mentor, write a "
                    "research proposal, and faculty review proposals and recommend "
                    "awards. Fellows do ten weeks of full-time, in-person research, "
                    "submit two interim reports, an abstract, and a final technical "
                    "paper, and present at SURF Seminar Days — the benchmark for a "
                    "suitable project is publication potential in refereed literature. "
                    "Open to Caltech students (GPA 2.0+) AND visiting undergraduates "
                    "from other institutions (GPA 2.5+); international students can be "
                    "sponsored on F-1/J-1 visas for on-campus SURF.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$8,110 for ten weeks (2026)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="March 1 (proposal + two recommendations via SFP Online)",
                    keywords=["SURF", "summer research", "stipend", "visiting students", "proposal-based", "STEM"],
                ),
                program(
                    "surf_jpl",
                    "SURF@JPL — Caltech / NASA Jet Propulsion Laboratory",
                    "https://sfp.caltech.edu/undergraduate-research/programs/surfjpl",
                    "The JPL arm of SURF: ten weeks of summer research under mentors at "
                    "NASA's Jet Propulsion Laboratory. Students develop a project and "
                    "proposal with a JPL mentor; JPL technical staff review proposals "
                    "and recommend awards. The summer ends with a technical paper and "
                    "an oral presentation, with weekly Caltech/JPL seminars, writing "
                    "workshops, student-faculty dinners, and field trips along the way. "
                    "Open to Caltech and visiting STEM undergraduates; restricted to "
                    "US citizens and permanent residents (JPL requirement).",
                    organization="California Institute of Technology / NASA JPL",
                    department="Student-Faculty Programs",
                    lab_or_program="SURF@JPL",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$9,600 for ten weeks (2026)",
                    eligibility_majors=["engineering", "physics", "astronomy", "computer science", "geology", "all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="March 1 (SURF cycle)",
                    keywords=["JPL", "NASA", "space", "summer research", "stipend"],
                ),
                program(
                    "wave_fellows",
                    "WAVE Fellows Program — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/wavefellows",
                    "Ten-week summer research program for non-Caltech STEM "
                    "undergraduates seriously considering PhD programs, designed to "
                    "increase the visibility and accessibility of Caltech doctoral "
                    "study. Applicants name several possible mentors; fellows develop "
                    "the project with their matched mentor and deliver interim reports, "
                    "an abstract, a final paper, and a Seminar Day presentation. "
                    "Partner institutes (KNI, Resnick, Chen, IQIM, and corporate "
                    "sponsors) fund named fellowships selected from the WAVE pool. "
                    "Successor to the former MURF program.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="WAVE Fellows",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 (2026) plus campus housing and ~$1,000 dining/travel supplement",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="January 9 (two faculty recommendations + transcript); US citizen/PR/DACA",
                    keywords=["WAVE", "visiting students", "PhD pipeline", "diversity", "summer research"],
                ),
                program(
                    "amgen_scholars_caltech",
                    "Amgen Scholars Program — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/amgen_scholars",
                    "Caltech site of the national Amgen Scholars Program: visiting "
                    "undergraduates spend ten weeks doing research in biology, "
                    "chemistry, and biotechnology under leading scientists, with the "
                    "mentor secured before application. The program prepares scholars "
                    "for PhD and MD-PhD study through seminars, workshops, the "
                    "mid-summer national Amgen conference, and networking; interim "
                    "reports, an abstract, a technical report, and a Seminar Day talk "
                    "are required. Scholars live in provided campus housing.",
                    organization="California Institute of Technology / Amgen Foundation",
                    department="Student-Faculty Programs",
                    lab_or_program="Amgen Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$6,000 stipend (2026) + $610 dining card + housing + travel",
                    eligibility_majors=["biology", "chemistry", "bioengineering", "biochemistry", "neuroscience"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="February 1; sophomores through non-graduating seniors, GPA 3.2+",
                    keywords=["Amgen Scholars", "biotechnology", "biology", "chemistry", "visiting students"],
                ),
                program(
                    "ligo_surf",
                    "LIGO SURF (NSF REU site) — Caltech",
                    "https://labcit.ligo.caltech.edu/LIGO_web/students/SURF/",
                    "Intensive summer program in gravitational-wave astronomy run by "
                    "the LIGO Laboratory (Caltech/MIT) and funded in part as an NSF "
                    "REU. Projects span detector development, modeling and data "
                    "analysis, metrology, optics, lasers, controls, electronics, "
                    "machine learning, and signal processing, at the Caltech campus and "
                    "the LIGO Hanford and Livingston observatories. Applications go "
                    "directly to LIGO via NSF ETAP rather than the SURF application; "
                    "fellows may live with the Caltech SURF community. Notably open to "
                    "students at US and foreign institutions.",
                    organization="LIGO Laboratory (Caltech/MIT)",
                    department="LIGO Laboratory",
                    lab_or_program="LIGO SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend plus some travel funding",
                    eligibility_majors=["physics", "astronomy", "engineering", "computer science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications via NSF ETAP, November through early January",
                    keywords=["LIGO", "gravitational waves", "NSF REU", "physics", "astronomy"],
                ),
                program(
                    "quantum_surf",
                    "QuantumSURF — Caltech",
                    "https://quantumsurf.caltech.edu/",
                    "Themed summer fellowship placing students in experimental quantum "
                    "science and technology groups at Caltech, open to Caltech and "
                    "non-Caltech undergraduates. Students apply through SURF or WAVE "
                    "(same requirements and stipends) after contacting participating "
                    "professors and preparing a proposal; the program adds collective "
                    "meetings, lab tours, faculty interactions, and blogging on the "
                    "IQIM 'Quantum Frontiers' blog. Recent cohorts of ~20 mix Caltech "
                    "students with visitors from other universities.",
                    organization="California Institute of Technology",
                    department="Institute for Quantum Information and Matter",
                    lab_or_program="QuantumSURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Via SURF ($8,110) or WAVE ($6,000 + housing)",
                    eligibility_majors=["physics", "applied physics", "electrical engineering", "computer science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Rides the SURF (March 1) or WAVE (January 9) application",
                    keywords=["quantum computing", "quantum information", "experimental physics", "IQIM"],
                ),
                program(
                    "kni_surf_the_wave",
                    "KNI SURF-the-WAVE Prize Fellowships — Caltech",
                    "https://www.kni.caltech.edu/programs/kni-surf-the-wave-fellowships",
                    "Kavli Nanoscience Institute prize for non-Caltech undergraduates "
                    "doing nanoscience summer research who plan STEM PhDs. Fellows are "
                    "selected from the regular WAVE applicant pool (no separate "
                    "application) and announced in late January; the award covers the "
                    "full WAVE salary and stipends and adds KNI community programming "
                    "plus complimentary access to the KNI Laboratory — a 7,500 sq ft "
                    "multi-user nanofabrication and characterization facility. Cohorts "
                    "have run annually since 2019.",
                    organization="California Institute of Technology",
                    department="Kavli Nanoscience Institute",
                    lab_or_program="KNI SURF-the-WAVE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Full WAVE support + KNI Laboratory access",
                    eligibility_majors=["physics", "applied physics", "materials science", "electrical engineering", "chemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Via WAVE — January 9",
                    keywords=["nanoscience", "nanofabrication", "cleanroom", "WAVE", "Kavli"],
                ),
                program(
                    "rsi_wave",
                    "RSI-WAVE Fellowships (Resnick Sustainability Institute) — Caltech",
                    "https://resnick.caltech.edu/programs/fellowships",
                    "Ten-week immersive fellowship for non-Caltech undergraduates "
                    "planning sustainability-focused PhDs, run by the Resnick "
                    "Sustainability Institute on top of the WAVE program. Fellows join "
                    "groups working on renewable energy and CO2 reduction, fresh "
                    "water, climate mitigation and adaptation, and biosphere "
                    "sustainability, as part of the WAVE cohort; applicants explore "
                    "RSI-funded faculty to pick their WAVE advisors.",
                    organization="California Institute of Technology",
                    department="Resnick Sustainability Institute",
                    lab_or_program="RSI-WAVE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="WAVE terms ($6,000 + housing + supplement)",
                    eligibility_majors=["environmental science", "chemistry", "chemical engineering", "materials science", "mechanical engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Via WAVE — January 9",
                    keywords=["sustainability", "climate", "renewable energy", "water", "WAVE"],
                ),
                program(
                    "brainwave",
                    "Chen Institute BrainWAVE Fellowship — Caltech",
                    "https://neuroscience.caltech.edu/education/brainwave-fellowship-program/brainwave-fellows-2026",
                    "Supports non-Caltech undergraduates intent on neuroscience PhDs "
                    "for ten-week summer projects in Caltech neuroscience labs. "
                    "Fellows are selected from the WAVE applicant pool and matched "
                    "with Tianqiao and Chrissy Chen Institute-affiliated mentors "
                    "(recent cohorts worked with groups including David Anderson, "
                    "Carlos Lois, Linda Hsieh-Wilson, and Markus Meister). Annual "
                    "cohorts of roughly four to six since 2021.",
                    organization="California Institute of Technology",
                    department="Tianqiao and Chrissy Chen Institute for Neuroscience",
                    lab_or_program="BrainWAVE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="WAVE terms ($6,000 + housing + supplement)",
                    eligibility_majors=["neuroscience", "biology", "psychology", "computer science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Via WAVE — January 9",
                    keywords=["neuroscience", "BrainWAVE", "Chen Institute", "WAVE"],
                ),
                program(
                    "rising_tide",
                    "Rising Tide Program (Caltech–Pasadena City College)",
                    "https://sfp.caltech.edu/undergraduate-research/programs/rising-tide",
                    "Six-week summer research-techniques training program for Pasadena "
                    "City College undergraduates with little or no research experience "
                    "and strong interest in chemistry or biology. Training is led by "
                    "Caltech graduate students and postdocs across synthetic and "
                    "analytical chemistry, computational chemistry, and biochemistry, "
                    "plus science communication and professional development; "
                    "participants earn a certificate. The program encourages "
                    "first-generation and geographically underrepresented students and "
                    "accepts all eligible applicants (faculty nomination required).",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="Rising Tide",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$4,886 for six weeks (2026)",
                    eligibility_majors=["chemistry", "biology", "biochemistry"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="April (2026: April 17); PCC students with faculty nomination",
                    keywords=["community college", "research training", "chemistry", "biology", "certificate"],
                ),
                program(
                    "vurp",
                    "Visiting Undergraduate Research Program (VURP / FlexVURP) — Caltech",
                    "https://sfp.caltech.edu/undergraduate-research/programs/vurp",
                    "Year-round pathway for non-Caltech undergraduates to do research "
                    "at Caltech while enrolled elsewhere — external honors theses, gap-"
                    "period research stays, and term-time visits outside the summer "
                    "program structure. Requires the sponsorship of a Caltech faculty "
                    "member, who arranges funding at or above SFP's minimum weekly "
                    "level; applications go through SFP at least 10–12 weeks before "
                    "the planned visit. A FlexVURP variant covers part-time "
                    "arrangements. Functionally a formalized cold-email-the-lab "
                    "channel with SFP handling logistics.",
                    organization="California Institute of Technology",
                    department="Student-Faculty Programs",
                    lab_or_program="VURP",
                    paid="stipend",
                    compensation="Arranged by sponsoring lab (SFP minimum weekly funding level)",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Rolling — apply 10–12 weeks before the visit",
                    keywords=["visiting students", "year-round research", "faculty sponsorship", "honors thesis"],
                ),
                program(
                    "jpl_summer_internship",
                    "JPL Summer Internship Program — NASA Jet Propulsion Laboratory",
                    "https://www.jpl.nasa.gov/edu/internships/apply/jpl-summer-internship-program/",
                    "Ten-week full-time summer internships at JPL for undergraduate "
                    "and graduate STEM students: mentored, designated projects that "
                    "contribute to real NASA/JPL missions, plus tours, lectures, and "
                    "career advisement. Interns start May–June and receive a monetary "
                    "award in monthly disbursements, with a housing/travel allowance "
                    "for students whose school is more than 50 miles from the lab. "
                    "Caltech's SFP office provides campus housing access for JPL "
                    "interns.",
                    organization="NASA Jet Propulsion Laboratory",
                    department="JPL Academic Engagement Office",
                    lab_or_program="JPL Summer Internship Program",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Monetary award in monthly disbursements + housing/travel allowance if eligible",
                    eligibility_majors=["engineering", "computer science", "physics", "astronomy", "geology", "mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Summer applications due around March; GPA 3.0+ required",
                    keywords=["JPL", "NASA", "internship", "paid", "space"],
                ),
                program(
                    "jpl_year_round",
                    "JPL Year-Round Internship Program — NASA Jet Propulsion Laboratory",
                    "https://www.jpl.nasa.gov/edu/internships/apply/jpl-year-round-internship-program/",
                    "Part-time and full-time internships at JPL during the academic "
                    "year and summer for undergraduate and graduate STEM students, "
                    "with mentored projects and enrichment activities. The first term "
                    "must run at least ten weeks (later terms are flexible) and the "
                    "student's school must permit off-campus independent study. "
                    "Interns receive a weekly monetary award; eligible full-time "
                    "interns get a housing/travel allowance.",
                    organization="NASA Jet Propulsion Laboratory",
                    department="JPL Academic Engagement Office",
                    lab_or_program="JPL Year-Round Internship Program",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Weekly monetary award; housing/travel allowance for eligible full-time interns",
                    eligibility_majors=["engineering", "computer science", "physics", "astronomy", "mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Rolling; GPA 3.0+ (3.5 preferred)",
                    keywords=["JPL", "academic year", "internship", "paid", "NASA"],
                ),
                program(
                    "jpl_visiting_student",
                    "JPL Visiting Student Research Program (JVSRP) — NASA JPL",
                    "https://www.jpl.nasa.gov/edu/internships/apply/jpl-visiting-student-research-program/",
                    "Research at JPL for students funded by third-party sponsors — "
                    "governments, universities, or foundations — and the main JPL "
                    "route for internationally funded students. Participants join "
                    "mentored, designated projects with the same enrichment "
                    "programming as other interns. Requires proof of at least "
                    "$2,400/month in sponsor support, international health and "
                    "accident insurance, pursuit of a STEM degree, and a 3.0+ GPA.",
                    organization="NASA Jet Propulsion Laboratory",
                    department="JPL Academic Engagement Office",
                    lab_or_program="JVSRP",
                    opportunity_type="internship",
                    paid="no",
                    compensation="Third-party sponsor funding required (≥$2,400/month)",
                    eligibility_majors=["engineering", "computer science", "physics", "astronomy", "mathematics"],
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling",
                    keywords=["JPL", "visiting researcher", "third-party funding", "international"],
                ),
                program(
                    "jpl_internships_portal",
                    "JPL Internships portal + NASA Space Grant at JPL",
                    "https://www.jpl.nasa.gov/edu/internships/",
                    "JPL's central internship portal: opportunities year-round, "
                    "minimum ten-week terms, 3.0+ GPA and college enrollment required, "
                    "US citizenship or permanent residency for most programs, and "
                    "summer applications due around March. Also the gateway to NASA "
                    "Space Grant placements at JPL — ten summer weeks at the lab for "
                    "US citizens at Space Grant-affiliated schools, with state "
                    "consortium competitions generally each January. Caltech "
                    "administers housing and support for Space Grant and JPLSIP "
                    "students via SFP.",
                    organization="NASA Jet Propulsion Laboratory",
                    department="JPL Academic Engagement Office",
                    lab_or_program="JPL Internships",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Varies by program",
                    eligibility_majors=["engineering", "computer science", "physics", "astronomy", "geology", "mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Summer cycle ~March; Space Grant state deadlines ~January",
                    keywords=["JPL", "NASA", "Space Grant", "internships portal", "aerospace"],
                ),
            ],
        },
        {
            "source_name": "caltech_lab_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.kni.caltech.edu/",
                "https://beckmaninstitute.caltech.edu/",
                "https://neuroscience.caltech.edu/",
                "https://resnick.caltech.edu/",
                "https://www.ipac.caltech.edu/page/students",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "kni",
                    "Kavli Nanoscience Institute (KNI) — Caltech",
                    "https://www.kni.caltech.edu/",
                    "Caltech's nanoscience hub spanning nanoscale electronics and "
                    "photonics, quantum matter and technology, bio/medical "
                    "engineering, additive manufacturing, and sustainability, built "
                    "around the KNI Laboratory — a 7,500 sq ft multi-user "
                    "nanofabrication and characterization facility. Hosts "
                    "undergraduates through SURF placements in KNI-affiliated labs and "
                    "the SURF-the-WAVE prize fellowships, and runs the Catalyst Award "
                    "and KNI-Wheatley Scholars. A prime cold-email target for "
                    "nanofabrication-oriented SURF proposals.",
                    organization="California Institute of Technology",
                    department="Kavli Nanoscience Institute",
                    lab_or_program="KNI",
                    compensation="Via SURF/WAVE placements or lab arrangement",
                    eligibility_majors=["applied physics", "materials science", "electrical engineering", "chemistry", "bioengineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; SURF/WAVE cycles for summer",
                    keywords=["nanoscience", "nanofabrication", "cleanroom", "quantum", "photonics"],
                ),
                program(
                    "beckman_institute",
                    "Beckman Institute — Caltech",
                    "https://beckmaninstitute.caltech.edu/",
                    "Multi-disciplinary center (est. 1989 with Beckman Foundation "
                    "support) inventing methods, instrumentation, and materials for "
                    "the chemical and biological sciences. Its resource centers — "
                    "biological imaging, catalysis and chemical synthesis, EPR, flow "
                    "cytometry, protein expression, X-ray crystallography, cryo-EM, "
                    "the Laser Resource Center, the Molecular Observatory, and the "
                    "Proteome Exploration Laboratory — are where many undergraduate "
                    "projects touch world-class instrumentation. No standalone "
                    "undergrad program: join via SURF/WAVE placements in affiliated "
                    "labs or direct contact with PIs.",
                    organization="California Institute of Technology",
                    department="Beckman Institute",
                    lab_or_program="Beckman Institute",
                    compensation="Via SURF/WAVE placements or lab arrangement",
                    eligibility_majors=["chemistry", "biology", "biochemistry", "bioengineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; SURF/WAVE cycles for summer",
                    keywords=["instrumentation", "cryo-EM", "imaging", "proteomics", "chemical biology"],
                ),
                program(
                    "rosen_center",
                    "Rosen Bioengineering Center — Caltech",
                    "https://rosen.caltech.edu/",
                    "Caltech's bioengineering integration hub, spanning bioimaging, "
                    "bioinspired design, biomechanics, biomedical devices, molecular "
                    "and tissue engineering, molecular medicine, molecular "
                    "programming, and synthetic and systems biology. Funds the "
                    "Biotechnology Training Program and pilot research grants; its "
                    "undergraduate page explicitly routes students to SURF and "
                    "academic-year research in affiliated labs, making the center's "
                    "faculty list an efficient cold-email map for bioengineering-"
                    "focused proposals.",
                    organization="California Institute of Technology",
                    department="Rosen Bioengineering Center",
                    lab_or_program="Rosen Center",
                    compensation="Via SURF placements or lab arrangement",
                    eligibility_majors=["bioengineering", "biology", "chemical engineering", "computer science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; SURF cycle for summer",
                    keywords=["bioengineering", "synthetic biology", "biomedical devices", "molecular programming"],
                ),
                program(
                    "chen_institute",
                    "Tianqiao and Chrissy Chen Institute for Neuroscience — Caltech",
                    "https://neuroscience.caltech.edu/",
                    "Caltech's neuroscience institute, spanning molecular through "
                    "social and decision neuroscience. Runs the BrainWAVE summer "
                    "fellowship for visiting undergraduates, graduate and postdoc "
                    "fellowships, Innovator Grants, and the DataSAI neuroscience "
                    "summer schools. Undergraduates enter Chen-affiliated labs via "
                    "SURF, WAVE/BrainWAVE, or direct faculty contact; the institute's "
                    "faculty roster is the natural cold-email list for neuroscience "
                    "research at Caltech.",
                    organization="California Institute of Technology",
                    department="Chen Institute for Neuroscience",
                    lab_or_program="Chen Institute",
                    compensation="Via SURF/WAVE/BrainWAVE placements or lab arrangement",
                    eligibility_majors=["neuroscience", "biology", "psychology", "computer science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; WAVE (Jan 9) / SURF (Mar 1) for summer",
                    keywords=["neuroscience", "systems neuroscience", "decision science", "Chen Institute"],
                ),
                program(
                    "resnick_institute",
                    "Resnick Sustainability Institute — Caltech",
                    "https://resnick.caltech.edu/",
                    "Caltech's sustainability hub covering renewable energy and CO2 "
                    "reduction, fresh water, climate mitigation and adaptation, and "
                    "biosphere sustainability. Funds Explorer and Impact grants, the "
                    "Rocket Fund, the Water and Environment Lab, and the Human Impacts "
                    "Database, and hosts undergraduates through RSI-WAVE fellowships "
                    "and SURF placements in RSI-funded faculty labs — those faculty "
                    "are prime cold-email targets for sustainability proposals.",
                    organization="California Institute of Technology",
                    department="Resnick Sustainability Institute",
                    lab_or_program="Resnick Institute",
                    compensation="Via SURF/WAVE placements or lab arrangement",
                    eligibility_majors=["environmental science", "chemistry", "chemical engineering", "materials science", "mechanical engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; WAVE/SURF cycles for summer",
                    keywords=["sustainability", "renewable energy", "climate", "water"],
                ),
                program(
                    "ipac_students",
                    "IPAC student research — Caltech",
                    "https://www.ipac.caltech.edu/page/students",
                    "IPAC is Caltech's NASA astrophysics and planetary science data "
                    "center, operating science and archive centers for missions "
                    "including Euclid, SPHEREx, ZTF, NEOWISE, and the Roman Space "
                    "Telescope plus the NASA Exoplanet Science Institute. Its "
                    "students page describes hosting undergraduates through SURF and "
                    "WAVE; applicants should identify an IPAC science-staff mentor "
                    "first via the staff directory. Research is data-rich astronomy — "
                    "surveys, time-domain, exoplanets, and archival science.",
                    organization="California Institute of Technology",
                    department="IPAC",
                    lab_or_program="IPAC",
                    compensation="Via SURF/WAVE placements",
                    eligibility_majors=["astronomy", "physics", "computer science", "data science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="SURF (Mar 1) / WAVE (Jan 9) cycles; contact a mentor first",
                    keywords=["astronomy", "NASA data", "exoplanets", "surveys", "IPAC"],
                ),
                program(
                    "iqim",
                    "Institute for Quantum Information and Matter (IQIM) — Caltech",
                    "https://iqim.caltech.edu/",
                    "NSF Physics Frontiers Center for quantum information and matter "
                    "(home to John Preskill and collaborators), spanning quantum "
                    "computation, quantum matter, AMO physics, and quantum metrology. "
                    "Undergraduates join IQIM-affiliated groups through SURF, WAVE "
                    "(IQIM is a listed WAVE sponsor), and QuantumSURF; the institute's "
                    "group directory is the canonical map of Caltech quantum labs for "
                    "cold-email outreach.",
                    organization="California Institute of Technology",
                    department="Institute for Quantum Information and Matter",
                    lab_or_program="IQIM",
                    compensation="Via SURF/WAVE/QuantumSURF placements",
                    eligibility_majors=["physics", "applied physics", "electrical engineering", "computer science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; SURF/WAVE cycles for summer",
                    keywords=["quantum information", "quantum matter", "NSF center", "quantum computing"],
                ),
                program(
                    "qse_directory",
                    "QSE@Caltech undergraduate opportunities directory",
                    "https://qse.caltech.edu/qseopportunities/undergrad",
                    "The cleanest live index of every undergraduate route into "
                    "Caltech quantum science and engineering research: SURF, WAVE, "
                    "QuantumSURF, and VURP, with links to the participating QSE "
                    "research groups. Useful both as a formal-channel guide and as an "
                    "efficient target list for students cold-emailing quantum labs "
                    "directly.",
                    organization="California Institute of Technology",
                    department="Quantum Science and Engineering",
                    lab_or_program="QSE@Caltech",
                    compensation="Via linked programs",
                    eligibility_majors=["physics", "applied physics", "electrical engineering", "computer science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="See linked program cycles",
                    keywords=["quantum science", "directory", "research groups", "quantum engineering"],
                ),
            ],
        },
    ],
}
