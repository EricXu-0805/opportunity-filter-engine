"""University of Pennsylvania campus opportunity-graph config (US-News Top-50 rollout).

Curated, live-verified seed of Penn's undergraduate-research landscape on the
generic ``campus_graph`` engine: CURF (the Center for Undergraduate Research &
Fellowships) and its PURM/SHIP/grant programs, the scholars communities and
dual-degree research programs (Vagelos MLS, VIPER, LSM, Rachleff), per-school
research pipelines (Wharton SPUR/SIRE, Nursing ONR/Hillman, PSOM SUIP, LDI
SUMR, MindCORE), the NSF REU sites Penn hosts (LRSM MRSEC, Chemistry
CatResDev, IoT4Ag; Singh paused for 2026), and the institute cold-email
targets (GRASP, Wharton Behavioral Lab). Every URL was fetch-verified
(HTTP 200 + real content) on 2026-07-09; dead programs (GfFMUR, SUNFEST,
Wharton MoreThanData) were dropped.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> upenn_research_programs (upenn / campus)
    open   -> upenn_external_research (national / open)
    lab    -> upenn_labs              (upenn / unknown)
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
    "school_slug": "upenn",
    "organization": "University of Pennsylvania",
    "location": "Philadelphia, PA",
    "emit": {
        "campus": ("upenn_research_programs", "upenn", "campus"),
        "open": ("upenn_external_research", None, "open"),
        "lab": ("upenn_labs", "upenn", "unknown"),
    },
    "sources": [
        {
            "source_name": "upenn_announcement_campus",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://curf.upenn.edu/content/penn-undergraduate-research-mentoring-program-purm",
                "https://curf.upenn.edu/content/summer-humanities-internship-program-ship",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "purm",
                    "Penn Undergraduate Research Mentoring Program (PURM) — University of Pennsylvania",
                    "https://curf.upenn.edu/content/penn-undergraduate-research-mentoring-program-purm",
                    "Penn's flagship summer research program, run by CURF since 2007. "
                    "PURM places students completing their first or second year into "
                    "ten-week, full-time summer research positions under a standing "
                    "Penn faculty member in any school; no prior research experience "
                    "is required and mentorship is an explicit program goal, with "
                    "students included in all phases of the research process. "
                    "Students apply directly to faculty-posted projects listed each "
                    "cycle on the CURF site, and participants present at CURF's Fall "
                    "Research Expo. Explicitly open to international students.",
                    organization="University of Pennsylvania",
                    department="Center for Undergraduate Research & Fellowships",
                    lab_or_program="PURM",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,000 award for the ten-week summer",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="Mid-February annually",
                    keywords=["summer research", "faculty mentored", "first-year", "PURM", "paid"],
                ),
                program(
                    "ship",
                    "Summer Humanities Internship Program (SHIP) — University of Pennsylvania",
                    "https://curf.upenn.edu/content/summer-humanities-internship-program-ship",
                    "Funds roughly 25 summer research internships each year for Penn "
                    "undergraduates in the humanities and social sciences, jointly "
                    "supported by the College of Arts and Sciences and CURF. Interns "
                    "work full-time for ten weeks in cultural, historical, or "
                    "archival settings — museums, archives, and cultural "
                    "organizations — in person or hybrid (fully remote placements are "
                    "no longer considered). Interns are discouraged from taking "
                    "summer courses or other paid work during the ten weeks.",
                    organization="University of Pennsylvania",
                    department="Center for Undergraduate Research & Fellowships",
                    lab_or_program="SHIP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,500 award for the ten-week internship",
                    eligibility_majors=["humanities", "history", "english", "art history", "sociology"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Late February annually",
                    keywords=["humanities", "archival research", "museums", "summer internship", "paid"],
                ),
            ],
        },
        {
            "source_name": "upenn_program_campus",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://curf.upenn.edu/content/college-alumni-society-undergraduate-research-grant",
                "https://curf.upenn.edu/content/vagelos-undergraduate-research-grant",
                "https://curf.upenn.edu/scholars-programs/university-scholars",
                "https://undergrad-inside.wharton.upenn.edu/research/spur/",
                "https://www.viper.upenn.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "cas_research_grant",
                    "College Alumni Society Undergraduate Research Grants — University of Pennsylvania",
                    "https://curf.upenn.edu/content/college-alumni-society-undergraduate-research-grant",
                    "A family of twelve alumni-endowed grants supporting research and "
                    "scholarly work by College of Arts and Sciences undergraduates. "
                    "Students submit one common application with a faculty "
                    "recommendation and proposals are automatically allocated to the "
                    "appropriate named fund; a CURF-designated faculty committee "
                    "evaluates them. Grants run in both fall and spring cycles and "
                    "defray research expenses such as materials, travel, and project "
                    "costs for independent or faculty-mentored work.",
                    organization="University of Pennsylvania",
                    department="Center for Undergraduate Research & Fellowships",
                    lab_or_program="College Alumni Society Grants",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Research expense grants, typically up to $1,000",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Fall deadline mid-October; spring deadline mid-March",
                    keywords=["research grant", "arts and sciences", "independent research", "expenses"],
                ),
                program(
                    "vagelos_research_grant",
                    "Vagelos Undergraduate Research Grant — University of Pennsylvania",
                    "https://curf.upenn.edu/content/vagelos-undergraduate-research-grant",
                    "Formerly the Nassau Fund Award, this CURF grant funds outstanding "
                    "independent scholarly projects conducted during the academic "
                    "year. Open to full-time undergraduates in all four of Penn's "
                    "undergraduate schools and to research in any field; funds cover "
                    "materials and supplies, travel, and other project costs. "
                    "Applications with a faculty recommendation are reviewed by a "
                    "CURF faculty committee; recent awards ranged from $200 to the "
                    "$1,000 maximum.",
                    organization="University of Pennsylvania",
                    department="Center for Undergraduate Research & Fellowships",
                    lab_or_program="Vagelos Undergraduate Research Grant",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Up to $1,000 per award",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Mid-October annually",
                    keywords=["research grant", "independent research", "academic year", "all schools"],
                ),
                program(
                    "pores_fellowship",
                    "PORES Student Research Fellowship — University of Pennsylvania",
                    "https://curf.upenn.edu/content/penn-program-opinion-research-and-election-studies-student-research-fellowship",
                    "PORES — the Penn Program on Opinion Research and Election "
                    "Studies — is an undergraduate research program in the Political "
                    "Science department focused on data-driven understanding of US "
                    "political outcomes through public-opinion survey research and "
                    "poll analysis. The paid Student Research Fellowship runs each "
                    "semester and over the summer, pairing undergraduates with PORES "
                    "faculty; fellows get polling-science training, specialized "
                    "courses, mentoring, and hands-on work with industry partners "
                    "including election-night analysis.",
                    organization="University of Pennsylvania",
                    department="Department of Political Science",
                    lab_or_program="PORES",
                    paid="yes",
                    compensation="Paid hourly research fellowship",
                    eligibility_majors=["political science", "data science", "statistics", "communication"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Early November for the listed cycle; semester and summer cohorts",
                    keywords=["political science", "polling", "election data", "paid fellowship"],
                ),
                program(
                    "jewish_studies_awards",
                    "Jewish Studies Research Awards (Goldfein, Brenner, Schwartz) — University of Pennsylvania",
                    "https://curf.upenn.edu/content/goldfein-research-awards",
                    "Each fall and spring, Penn's Jewish Studies Program offers the "
                    "Goldfein Research Awards, Brenner Special Opportunity Awards, "
                    "and Schwartz Awards to undergraduate and graduate students for "
                    "research projects and study programs related to Jewish studies. "
                    "Funding supports travel, research materials, and other "
                    "research-related costs; projects must represent original "
                    "research conducted after proposal approval, documented in a "
                    "short progress report.",
                    organization="University of Pennsylvania",
                    department="Jewish Studies Program",
                    lab_or_program="Jewish Studies Research Awards",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Research expense awards (amounts vary by fund)",
                    eligibility_majors=["religious studies", "history", "near eastern studies", "all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Fall and spring cycles",
                    keywords=["Jewish studies", "research award", "travel funding", "humanities"],
                ),
                program(
                    "university_scholars",
                    "University Scholars Program — University of Pennsylvania",
                    "https://curf.upenn.edu/scholars-programs/university-scholars",
                    "CURF's research-intensive scholars community: undergraduates "
                    "with demonstrated research commitment join a cross-disciplinary "
                    "cohort with dedicated research funding streams, faculty council "
                    "mentorship, and regular research conversations. Scholars develop "
                    "the ability to run consequential independent research projects "
                    "and communicate their premises, approaches, and implications to "
                    "expert and non-expert audiences; research is defined in its "
                    "broadest sense across all fields. Current Penn students apply "
                    "competitively after matriculation.",
                    organization="University of Pennsylvania",
                    department="Center for Undergraduate Research & Fellowships",
                    lab_or_program="University Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Access to dedicated UScholars research funding",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual application cycle",
                    keywords=["scholars community", "independent research", "research funding", "interdisciplinary"],
                ),
                program(
                    "benjamin_franklin_scholars",
                    "Benjamin Franklin Scholars — University of Pennsylvania",
                    "https://curf.upenn.edu/scholars-programs/benjamin-franklin-scholars",
                    "A four-school honors community administered by CURF for "
                    "students who share a passion for broad intellectual "
                    "exploration. BFS enriches members' education through dedicated "
                    "seminars, extracurricular programming, and integration of "
                    "knowledge across disciplines alongside specialized study; "
                    "members access program funding opportunities and a scholarly "
                    "community that feeds into Penn's research ecosystem. Admission "
                    "is via selection at admission or on-campus application.",
                    organization="University of Pennsylvania",
                    department="Center for Undergraduate Research & Fellowships",
                    lab_or_program="Benjamin Franklin Scholars",
                    opportunity_type="fellowship",
                    paid="unknown",
                    compensation="Program funding opportunities for members",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="Annual application cycles",
                    keywords=["honors community", "seminars", "interdisciplinary", "scholars program"],
                ),
                program(
                    "realarts",
                    "RealArts@Penn Summer Internships — University of Pennsylvania",
                    "https://web.sas.upenn.edu/realartsatpenn/",
                    "Curated paid summer internships in the creative industries for "
                    "Penn undergraduates of any major, run out of the SAS/Kelly "
                    "Writers House ecosystem. For Summer 2026 RealArts sponsors "
                    "seventeen internships in journalism, publishing, museums, "
                    "music, television, film, and theatre, with placements including "
                    "Philadelphia Magazine, The FADER, the Guggenheim Museum, Museum "
                    "of the Moving Image, Spiegel & Grau, and Warner Bros. Theatre "
                    "Ventures across Philadelphia, New York, Montana, and Los "
                    "Angeles. Each internship pairs a stipend with industry mentors.",
                    organization="University of Pennsylvania",
                    department="School of Arts & Sciences",
                    lab_or_program="RealArts@Penn",
                    opportunity_type="internship",
                    paid="stipend",
                    compensation="$5,000 stipend per internship",
                    eligibility_majors=["english", "communication", "fine arts", "cinema & media studies", "all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual application; internships announced each December",
                    keywords=["arts", "media", "paid internship", "creative industries", "summer"],
                ),
                program(
                    "rachleff_scholars",
                    "Rachleff Scholars Program — Penn Engineering",
                    "https://academics.engineering.upenn.edu/ugrad/scholars/rachleff-scholars-program/",
                    "Penn Engineering's selective undergraduate research scholars "
                    "program, offering early and sustained research engagement with "
                    "standing faculty across all six SEAS departments. Each scholar "
                    "completes a required ten-week paid Summer Research Experience on "
                    "campus (typically after sophomore year) under a standing faculty "
                    "mentor, two course units of honors coursework, and community "
                    "activities such as industry site visits and research symposia. "
                    "Admits a small cohort of rising sophomores with at least a 3.4 "
                    "GPA, targeting students headed for research careers.",
                    organization="University of Pennsylvania",
                    department="School of Engineering & Applied Science",
                    lab_or_program="Rachleff Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Paid ten-week summer research experience",
                    eligibility_majors=["engineering", "computer science", "bioengineering"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="Spring of first year (sophomore-selection cycle)",
                    keywords=["engineering", "scholars program", "summer research", "honors", "selective"],
                ),
                program(
                    "viper",
                    "Vagelos Integrated Program in Energy Research (VIPER) — University of Pennsylvania",
                    "https://www.viper.upenn.edu/",
                    "Selective dual-degree program between the School of Arts and "
                    "Sciences and Penn Engineering focused on energy research. "
                    "Students earn two bachelor's degrees (a science major and an "
                    "engineering major) and conduct sustained, funded research in "
                    "energy science and technology with Penn faculty, including "
                    "stipend-supported summer research beginning after the first "
                    "year. Cohorts are small and research-intensive; admission is "
                    "through the first-year undergraduate admissions process.",
                    organization="University of Pennsylvania",
                    department="SAS + SEAS (dual degree)",
                    lab_or_program="VIPER",
                    paid="stipend",
                    compensation="Stipend-supported summer research through program funding",
                    eligibility_majors=["physics", "chemistry", "materials science", "chemical engineering", "mechanical engineering"],
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    deadline_note="With Penn undergraduate admissions (ED/RD)",
                    keywords=["energy research", "dual degree", "engineering", "summer research"],
                ),
                program(
                    "lsm",
                    "Life Sciences & Management (LSM) Program — University of Pennsylvania",
                    "https://lsm.upenn.edu/",
                    "Selective dual-degree program of the College of Arts and "
                    "Sciences and the Wharton School training students at the "
                    "interface of life sciences and management. Students earn a BA in "
                    "a life science and a BS in Economics from Wharton; the program "
                    "emphasizes novel research across Penn's hundreds of biological "
                    "and biomedical labs plus a required internship and capstone, "
                    "targeting careers in health care, biomedical R&D, and the "
                    "management of life-science organizations. Admission is via the "
                    "first-year admissions process into a small cohort.",
                    organization="University of Pennsylvania",
                    department="SAS + Wharton (dual degree)",
                    lab_or_program="LSM",
                    paid="unknown",
                    compensation="Program-supported research and internship experiences",
                    eligibility_majors=["biology", "biochemistry", "neuroscience", "business economics"],
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    deadline_note="With Penn undergraduate admissions",
                    keywords=["life sciences", "management", "dual degree", "biomedical research"],
                ),
                program(
                    "vagelos_mls",
                    "Vagelos Scholars Program in the Molecular Life Sciences — University of Pennsylvania",
                    "https://vagelosmls.sas.upenn.edu/",
                    "Founded in 1997 with support from Roy and Diana Vagelos, this "
                    "highly selective SAS scholars program takes roughly 35 students "
                    "per year into a rigorous curriculum combining chemistry, "
                    "biology, mathematics, and physics. Scholars double-major in "
                    "molecular life sciences fields and pursue mentored research with "
                    "groups on or near campus, with stipend-supported research during "
                    "the summers after their second and third years. Graduates go on "
                    "to doctoral study across the life and physical sciences.",
                    organization="University of Pennsylvania",
                    department="School of Arts & Sciences",
                    lab_or_program="Vagelos MLS",
                    paid="stipend",
                    compensation="Stipend-supported summer research after 2nd and 3rd years",
                    eligibility_majors=["biochemistry", "chemistry", "biophysics", "physics", "biology"],
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    deadline_note="With admissions / program application cycle",
                    keywords=["molecular life sciences", "scholars program", "summer research stipend", "selective"],
                ),
                program(
                    "wharton_spur",
                    "Wharton Summer Program for Undergraduate Research (SPUR)",
                    "https://undergrad-inside.wharton.upenn.edu/research/spur/",
                    "Gives highly motivated Wharton undergraduates the opportunity "
                    "to develop, design, and complete an independent research "
                    "project over ten summer weeks under a Wharton faculty advisor. "
                    "Students must spend at least 20 hours per week on the project, "
                    "may not hold substantial outside employment or more than one "
                    "concurrent summer course, and meet regularly with their "
                    "advisor. Projects may be theoretical or applied, quantitative "
                    "or qualitative, and culminate in research papers published on "
                    "ScholarlyCommons@Penn.",
                    organization="University of Pennsylvania",
                    department="The Wharton School",
                    lab_or_program="SPUR",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Taxable award of up to $6,000, paid in installments",
                    eligibility_majors=["finance", "management", "marketing", "accounting", "statistics", "business economics"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Late March annually",
                    keywords=["business research", "independent research", "summer", "paid", "Wharton"],
                ),
                program(
                    "wharton_sire",
                    "Wharton Social Impact Research Experience (SIRE)",
                    "https://undergrad-inside.wharton.upenn.edu/research/sire/",
                    "Awards supporting summer research by Wharton undergraduates on "
                    "topics that promote both economic and social value, domestically "
                    "or abroad. The Wharton Undergraduate Division offers up to ten "
                    "awards per year; students design and carry out projects under "
                    "Wharton faculty guidance, culminating in oral presentations and "
                    "written papers posted on ScholarlyCommons@Penn plus a blog "
                    "requirement. The award reimburses approved travel and lodging "
                    "in two installments.",
                    organization="University of Pennsylvania",
                    department="The Wharton School",
                    lab_or_program="SIRE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Taxable award of up to $6,000 for approved travel/lodging",
                    eligibility_majors=["business economics", "finance", "management", "public policy"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Spring application cycle",
                    keywords=["social impact", "business research", "summer", "travel funding", "Wharton"],
                ),
                program(
                    "ppps",
                    "Penn Program for Public Service (PPPS) Summer Internship",
                    "https://www.nettercenter.upenn.edu/what-we-do/programs/ppps",
                    "An eleven-week summer program of the Netter Center for Community "
                    "Partnerships immersing 10–12 Penn undergraduates in real-world "
                    "problem solving in West Philadelphia. Its core is an "
                    "action-oriented Academically Based Community Service seminar on "
                    "urban university-community relations in which each intern "
                    "researches a strategic problem in West Philadelphia, combined "
                    "with 30+ hours per week working in a university-assisted "
                    "community school program.",
                    organization="University of Pennsylvania",
                    department="Netter Center for Community Partnerships",
                    lab_or_program="PPPS",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="$13.00/hour for internship hours",
                    eligibility_majors=["education", "sociology", "urban studies", "all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Early admission late October; regular admission late January",
                    keywords=["community-based research", "public service", "West Philadelphia", "summer internship"],
                ),
                program(
                    "kleinman_seminar",
                    "Kleinman Center Undergraduate Climate & Energy Policy Seminar",
                    "https://kleinmanenergy.upenn.edu/education/undergraduate-seminar/",
                    "A competitive cohort of undergraduate student fellows hosted by "
                    "the Kleinman Center for Energy Policy at the Weitzman School of "
                    "Design. Admitted students attend four to six seminars per "
                    "semester, meeting energy researchers from across campus as they "
                    "discuss the findings and policy implications of recent research. "
                    "Offered in both fall and spring semesters from 2026-27, with an "
                    "online application requiring a resume and short materials.",
                    organization="University of Pennsylvania",
                    department="Kleinman Center for Energy Policy",
                    lab_or_program="Climate & Energy Policy Seminar",
                    opportunity_type="fellowship",
                    paid="unknown",
                    eligibility_majors=["environmental science", "public policy", "political science", "economics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications each semester",
                    keywords=["energy policy", "climate", "seminar fellowship", "policy research"],
                ),
                program(
                    "kleinman_grants",
                    "Kleinman Center Student Grants — University of Pennsylvania",
                    "https://kleinmanenergy.upenn.edu/education/student-grants/",
                    "The Kleinman Center has funded more than 200 Penn student grants "
                    "supporting energy-policy-relevant research, conference travel, "
                    "stipends for otherwise-unpaid internships, events, and student "
                    "projects. Grants are offered four times per year (deadlines "
                    "September 1, November 1, February 1, and April 1) and are open "
                    "to individual Penn students and student groups, with decisions "
                    "within 15 days of each deadline.",
                    organization="University of Pennsylvania",
                    department="Kleinman Center for Energy Policy",
                    lab_or_program="Kleinman Student Grants",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Grant amounts vary by funding type",
                    eligibility_majors=["environmental science", "public policy", "engineering", "economics", "all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Quarterly: Sep 1, Nov 1, Feb 1, Apr 1",
                    keywords=["energy policy", "student grants", "research funding", "travel"],
                ),
                program(
                    "perry_world_house_fellows",
                    "Perry World House — World House Student Fellows",
                    "https://perryworldhouse.upenn.edu/opportunities/student-opportunities/world-house-student-fellows/",
                    "Perry World House's flagship undergraduate engagement "
                    "initiative: a year-long experiential fellowship in global policy "
                    "research. Each year 25–30 fellows are competitively selected "
                    "from Penn's four undergraduate schools (roughly 120 applicants), "
                    "directed by a Political Science faculty member. Fellows work in "
                    "small teams on a year-long policy project producing "
                    "policy-relevant research on a global issue under faculty "
                    "supervision, with individualized research and career mentoring.",
                    organization="University of Pennsylvania",
                    department="Perry World House",
                    lab_or_program="World House Student Fellows",
                    opportunity_type="fellowship",
                    paid="unknown",
                    eligibility_majors=["political science", "international relations", "economics", "all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications open each spring for the following year",
                    keywords=["global policy", "fellowship", "policy research", "international affairs"],
                ),
                program(
                    "casi_programs",
                    "CASI Student Programs (Center for the Advanced Study of India)",
                    "https://casi.sas.upenn.edu/studentprograms",
                    "The Center for the Advanced Study of India offers fully-funded "
                    "summer internships in India for Penn students, placing them with "
                    "nonprofits and companies working on public health, rural "
                    "development, environmental sustainability, education, gender, "
                    "and social enterprise. CASI also awards Summer Research Funds — "
                    "travel grants for Penn students pursuing independent research on "
                    "India's politics, society, economy, and international relations. "
                    "Annual winter/spring application cycles.",
                    organization="University of Pennsylvania",
                    department="Center for the Advanced Study of India",
                    lab_or_program="CASI Student Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Fully-funded internships; research travel funds",
                    eligibility_majors=["south asia studies", "international relations", "economics", "all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual cycle, typically winter/early spring",
                    keywords=["India", "international research", "funded internship", "travel grant"],
                ),
                program(
                    "penn_museum_exhibition",
                    "Penn Museum Student Exhibition Internship",
                    "https://www.penn.museum/learn/penn-students/student-exhibition-internship",
                    "A paid year-long internship for three Penn undergraduates to "
                    "create a real exhibition with Penn Museum staff, covering "
                    "planning, development, design, fabrication, and installation. "
                    "Interns experience curatorial, content-development, "
                    "administrative, and design work in a major museum, then "
                    "implement educational programs and events after the exhibition "
                    "opens. The 2026-27 student exhibition topic is the Ramayana.",
                    organization="University of Pennsylvania",
                    department="Penn Museum",
                    lab_or_program="Student Exhibition Internship",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Paid year-long internship",
                    eligibility_majors=["anthropology", "art history", "history", "classical studies"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Mid-April annually",
                    keywords=["museum", "curation", "exhibition", "paid internship"],
                ),
                program(
                    "wolf_humanities_fellows",
                    "Wolf Humanities Center Undergraduate Fellowships — University of Pennsylvania",
                    "https://wolfhumanities.upenn.edu/fellowships/undergraduate-research-fellowships",
                    "The Wolf Humanities Center, Penn's hub for interdisciplinary "
                    "humanities research, appoints undergraduate Fellows of the "
                    "Undergraduate Humanities Forum each year to conduct research "
                    "related to the Center's annual topic. Fellows join a community "
                    "including faculty, postdoctoral, and doctoral fellows, workshop "
                    "each other's writing in fellowship seminars, and present at the "
                    "spring research conference. Regular fellows receive $1,500 "
                    "($2,000 for Executive Board and Social Media Research Fellows).",
                    organization="University of Pennsylvania",
                    department="Wolf Humanities Center",
                    lab_or_program="Undergraduate Humanities Forum",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$1,500 award ($2,000 for board fellows), paid in two installments",
                    eligibility_majors=["english", "history", "philosophy", "art history", "humanities"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications close late March / early April",
                    keywords=["humanities", "research fellowship", "annual theme", "interdisciplinary"],
                ),
                program(
                    "penn_grip",
                    "Penn Global Research & Internship Program (GRIP)",
                    "https://global.upenn.edu/pennabroad/grip/",
                    "Penn Abroad places outstanding undergraduate and graduate "
                    "students in 8–12 week summer internships and research positions "
                    "abroad with companies, nonprofits, and universities. Placements "
                    "include dedicated research positions under international "
                    "researchers and faculty PIs at partner universities; students "
                    "browse cohort, direct, and research placements in Penn's "
                    "PASSPORT system. The program provides guaranteed funding awards "
                    "to accepted students to offset travel and internship expenses.",
                    organization="University of Pennsylvania",
                    department="Penn Abroad (Penn Global)",
                    lab_or_program="GRIP",
                    opportunity_type="internship",
                    paid="stipend",
                    compensation="Guaranteed funding award offsetting travel/expenses",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Early January annually",
                    keywords=["international", "research abroad", "summer internship", "funded"],
                ),
                program(
                    "nursing_onr",
                    "Penn Nursing Student Research / Office of Nursing Research",
                    "https://www.nursing.upenn.edu/our-expertise/research/student-research/",
                    "Penn Nursing's hub for student research: students from "
                    "first-year undergraduates onward work alongside "
                    "nursing-science researchers with financial and logistical "
                    "support through the school's research centers and the Office of "
                    "Nursing Research. Penn Nursing is one of the few US nursing "
                    "schools with a dedicated nursing research lab where students "
                    "conduct lab procedures, and many students win national research "
                    "grants in partnership with faculty. The entry point for "
                    "research assistantships and mentored projects in nursing "
                    "science.",
                    organization="University of Pennsylvania",
                    department="School of Nursing",
                    lab_or_program="Office of Nursing Research",
                    paid="unknown",
                    compensation="Varies by project and center",
                    eligibility_majors=["nursing"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling / project-dependent",
                    keywords=["nursing science", "student research", "research centers", "mentored research"],
                ),
                program(
                    "hillman_scholars",
                    "Hillman Scholars Program in Nursing Innovation (BSN-to-PhD) — Penn Nursing",
                    "https://hillmanscholars.org/about/",
                    "An accelerated, integrated BSN-to-PhD pathway training nurse "
                    "scientists who drive health care transformation; Penn Nursing "
                    "was the inaugural site. Scholars are simultaneously "
                    "undergraduate and PhD students as early as junior year (or on "
                    "entry to the accelerated second-degree BSN), earning doctoral "
                    "credits while completing the BSN and finishing the PhD in about "
                    "three further years. Penn adds a Clinical Nurse Fellowship with "
                    "the University of Pennsylvania Health System and pilot research "
                    "awards for scholars.",
                    organization="University of Pennsylvania",
                    department="School of Nursing",
                    lab_or_program="Hillman Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Foundation-funded scholar support; pilot research awards",
                    eligibility_majors=["nursing"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Annual internal application via Penn Nursing",
                    keywords=["nursing", "BSN-PhD", "research training", "health innovation"],
                ),
            ],
        },
        {
            "source_name": "upenn_career_campus",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://careerservices.upenn.edu/channels/research/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_research_community",
                    "Penn Career Services — Research Career Community",
                    "https://careerservices.upenn.edu/channels/research/",
                    "Career Services' research community page aggregates tools, job "
                    "boards, sample Handshake postings, professional associations, "
                    "and resources for Penn students seeking research roles across "
                    "fields. It points students to targeted Handshake searches "
                    "(login-gated), LinkedIn/MyPenn alumni networking, and curated "
                    "lists of research programs including PPPS and GRIP. A hub and "
                    "directory rather than a program itself.",
                    organization="University of Pennsylvania",
                    department="Career Services",
                    lab_or_program="Research Career Community",
                    paid="unknown",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling listings",
                    keywords=["career services", "research jobs", "Handshake", "directory"],
                ),
            ],
        },
        {
            "source_name": "upenn_department_open",
            "source_type": DEPARTMENT,
            "emit": "open",
            "seeds": [
                "https://www.med.upenn.edu/research-trainee-affairs/suip/",
                "https://ldi.upenn.edu/education/penn-ldi-training-programs/sumr/",
                "https://mindcore.sas.upenn.edu/research/summer/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "suip",
                    "Summer Undergraduate Internship Program (SUIP) — Penn Medicine",
                    "https://www.med.upenn.edu/research-trainee-affairs/suip/",
                    "A prestigious ten-week immersive summer research experience at "
                    "the Perelman School of Medicine for undergraduates nationwide "
                    "aspiring to PhD or MD-PhD study in the biomedical sciences. "
                    "Interns are paired with a Principal Investigator by shared "
                    "research interests and get hands-on laboratory training, "
                    "scientific seminars, professional development workshops, and "
                    "graduate-school preparation, culminating in the SUIP Symposium. "
                    "The program especially encourages applicants with limited prior "
                    "research access, and includes affiliate tracks such as SUIP-CCI "
                    "(Center for Cellular Immunotherapies).",
                    organization="University of Pennsylvania",
                    department="Perelman School of Medicine",
                    lab_or_program="SUIP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,500 stipend",
                    eligibility_majors=["biology", "biochemistry", "neuroscience", "chemistry", "bioengineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Winter cycle (early February) for a June start; US citizens/PRs",
                    keywords=["biomedical research", "summer internship", "PhD pipeline", "paid", "national"],
                ),
                program(
                    "sumr",
                    "SUMR — Summer Undergraduate Mentored Research Program (Penn LDI)",
                    "https://ldi.upenn.edu/education/penn-ldi-training-programs/sumr/",
                    "Founded in 2000 by the Leonard Davis Institute of Health "
                    "Economics and Wharton's Health Care Management Department, SUMR "
                    "introduces talented undergraduates to health services research, "
                    "population health, and clinical epidemiology, with a mission of "
                    "advancing health equity. Scholars work full-time on mentored "
                    "research with Penn faculty, attend the AcademyHealth Annual "
                    "Research Meeting, and present at the End-of-SUMR symposium. "
                    "About 425 alumni over 25 years; most continue into health-care "
                    "careers and graduate study.",
                    organization="University of Pennsylvania",
                    department="Leonard Davis Institute of Health Economics",
                    lab_or_program="SUMR",
                    opportunity_type="summer_program",
                    paid="yes",
                    compensation="$20/hour for 40 hours/week",
                    eligibility_majors=["health care management", "economics", "biology", "public policy", "statistics"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Winter application cycle (January–February)",
                    keywords=["health services research", "health equity", "paid summer research", "mentored"],
                ),
                program(
                    "mindcore_fellowship",
                    "MindCORE Summer Fellowship Program — University of Pennsylvania",
                    "https://mindcore.sas.upenn.edu/research/summer/",
                    "A paid ten-week summer program run by MindCORE, Penn's hub for "
                    "the integrative study of the mind, open to both Penn and "
                    "non-Penn undergraduates. Fellows are matched with MindCORE "
                    "faculty mentors by research interest, start with a one-week "
                    "workshop on interdisciplinary cognitive science, then do nine "
                    "weeks of mentored research with weekly research lunches, "
                    "faculty seminars, ethics and technical training, and a final "
                    "poster or presentation.",
                    organization="University of Pennsylvania",
                    department="MindCORE",
                    lab_or_program="MindCORE Summer Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Paid fellowship",
                    eligibility_majors=["psychology", "neuroscience", "linguistics", "computer science", "philosophy"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Winter application cycle for summer start",
                    keywords=["cognitive science", "neuroscience", "psychology", "paid summer fellowship", "open to non-Penn"],
                ),
            ],
        },
        {
            "source_name": "upenn_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://www.lrsm.upenn.edu/outreach/reu/",
                "https://web.sas.upenn.edu/reu-pennchemistry/",
                "https://iot4ag.us/reu-program/",
                "https://www.penn.museum/learn/penn-students/summer-internship-program",
                "https://monell.org/science-apprenticeship-program/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "lrsm_reu",
                    "LRSM / Penn MRSEC Research Experience for Undergraduates (REU)",
                    "https://www.lrsm.upenn.edu/outreach/reu/",
                    "The Laboratory for Research on the Structure of Matter, Penn's "
                    "NSF-supported Materials Research Science and Engineering "
                    "Center, offers up to twenty Summer Research Fellowships to "
                    "undergraduates from colleges across the United States majoring "
                    "in science or engineering. Students spend ten weeks on "
                    "individual materials-research projects under Penn faculty "
                    "supervision in chemistry, physics, biochemistry, biophysics, "
                    "materials science, or engineering, with weekly faculty lectures "
                    "and hands-on workshops, ending in research presentations.",
                    organization="University of Pennsylvania",
                    department="Laboratory for Research on the Structure of Matter",
                    lab_or_program="LRSM REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$7,000 for the ten-week program",
                    eligibility_majors=["materials science", "physics", "chemistry", "engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Applications open November, close in winter (NSF REU rules)",
                    keywords=["NSF REU", "materials science", "MRSEC", "paid summer research"],
                ),
                program(
                    "penn_chem_reu",
                    "Penn Chemistry REU (CatResDev) — University of Pennsylvania",
                    "https://web.sas.upenn.edu/reu-pennchemistry/",
                    "Established in 2021, Penn Chemistry's NSF REU on 'Novel "
                    "Techniques and Applications in Catalyst Research Development "
                    "and Molecular Dynamics' hosts ten undergraduates for a ten-week "
                    "summer research experience. Eleven faculty researchers in "
                    "catalysis and molecular dynamics offer projects in methods "
                    "development, catalyst development and testing, synthetic "
                    "applications, and theory; the program deliberately targets "
                    "undergraduates with limited previous laboratory experience.",
                    organization="University of Pennsylvania",
                    department="Department of Chemistry",
                    lab_or_program="CatResDev REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU stipend",
                    eligibility_majors=["chemistry", "biochemistry", "chemical engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="November 1 – January 15 annually via Interfolio; GPA 3.0+",
                    keywords=["NSF REU", "chemistry", "catalysis", "summer research"],
                ),
                program(
                    "singh_reu",
                    "Singh Center for Nanotechnology REU — University of Pennsylvania",
                    "https://www.nano.upenn.edu/reu/",
                    "A ten-week summer program giving undergraduates hands-on "
                    "nanoscale research in the Singh Center's four major facilities: "
                    "the Quattrone Nanofabrication Facility, Nanoscale "
                    "Characterization Facility, Scanning and Local Probe Facility, "
                    "and Material Property Measurement Facility. Students match to "
                    "projects in Penn faculty labs, gain experience in experimental "
                    "design and communication, and attend the national NNCI REU "
                    "Convocation. NOTE: paused for 2026 — the page directs "
                    "applicants to Penn's LRSM REU, which can access Singh "
                    "facilities; retained for future cycles.",
                    organization="University of Pennsylvania",
                    department="Singh Center for Nanotechnology",
                    lab_or_program="Singh Center REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$7,000 stipend + housing + up to $500 travel (in operating years)",
                    eligibility_majors=["materials science", "electrical engineering", "physics", "chemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Paused for 2026; winter cycle in operating years",
                    keywords=["nanotechnology", "NSF REU", "nanofabrication", "paused-2026"],
                ),
                program(
                    "iot4ag_reu",
                    "IoT4Ag REU — NSF ERC for the Internet of Things for Precision Agriculture",
                    "https://iot4ag.us/reu-program/",
                    "The NSF Engineering Research Center for the Internet of Things "
                    "for Precision Agriculture, led by Penn Engineering with Purdue, "
                    "UC Merced, and the University of Florida, runs a summer REU in "
                    "which undergraduates work with graduate students and faculty on "
                    "food-energy-water security research: distributable sensors, "
                    "autonomous robotics, energy and communication devices, "
                    "AI-driven digital twins of crops, and human-centered decision "
                    "interfaces. The successor opportunity that SUNFEST's site "
                    "points sensor-technology applicants to.",
                    organization="University of Pennsylvania",
                    department="IoT4Ag Engineering Research Center",
                    lab_or_program="IoT4Ag REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU stipend",
                    eligibility_majors=["electrical engineering", "computer science", "mechanical engineering", "environmental science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Late February annually",
                    keywords=["NSF REU", "precision agriculture", "sensors", "robotics", "IoT"],
                ),
                program(
                    "penn_museum_summer",
                    "Penn Museum Summer Internship Program",
                    "https://www.penn.museum/learn/penn-students/summer-internship-program",
                    "The Penn Museum's nine-week, 300-hour paid summer internship "
                    "provides mentorship, training, and career development for "
                    "undergraduates, recent graduates, and graduate students from "
                    "any college or university. Interns take departmental placements "
                    "(curatorial sections, conservation, archives, education) "
                    "combined with the weekly Museum Practice Program lecture series "
                    "and museum field trips. The Museum actively seeks interns from "
                    "first-generation and low-income backgrounds; interns become "
                    "temporary Penn employees.",
                    organization="University of Pennsylvania",
                    department="Penn Museum",
                    lab_or_program="Summer Internship Program",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="$17/hour for 300 hours (~$5,100)",
                    eligibility_majors=["anthropology", "art history", "history", "classical studies", "museum studies"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Applications December 15 – February 8",
                    keywords=["museum careers", "archaeology", "anthropology", "paid internship", "open to non-Penn"],
                ),
                program(
                    "monell_msap",
                    "Dr. Charis Eng Monell Science Apprenticeship Program (MSAP)",
                    "https://monell.org/science-apprenticeship-program/",
                    "The Monell Chemical Senses Center's paid summer research "
                    "apprenticeship, running for over 40 years, stimulates interest "
                    "in biomedical science particularly among groups "
                    "underrepresented in science. Apprentices complete eight weeks "
                    "of paid, full-time structured research in Monell labs (taste, "
                    "smell, chemosensation) plus scientific lectures, communication "
                    "training, research ethics, and career exploration. Accepts high "
                    "school and undergraduate students from the greater Philadelphia "
                    "area.",
                    organization="Monell Chemical Senses Center",
                    department="Monell Chemical Senses Center",
                    lab_or_program="MSAP",
                    opportunity_type="summer_program",
                    paid="yes",
                    compensation="Paid full-time for eight weeks",
                    eligibility_majors=["biology", "neuroscience", "psychology", "chemistry"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Annual spring application; Philadelphia-region students",
                    keywords=["chemosensory science", "biomedical", "paid apprenticeship", "Philadelphia"],
                ),
                program(
                    "wistar_undergrad",
                    "Wistar Institute Undergraduate Programs",
                    "https://www.wistar.org/education-training/undergraduate-programs/",
                    "The Wistar Institute, the nation's first independent biomedical "
                    "research institute (on Penn's campus), runs a portfolio of "
                    "undergraduate training programs: the Undergraduate Biomedical "
                    "Technician Training Program, a Wistar REU with hands-on "
                    "molecular and cellular biology training and research on TP53 "
                    "and other Wistar science, a Cheyney University collaboration, "
                    "the Life Science Innovation biotech-entrepreneurship course, "
                    "and the week-long NIIMBL eXperience. Students train in Wistar's "
                    "genomics, proteomics, bioinformatics, and imaging facilities.",
                    organization="The Wistar Institute",
                    department="Education & Training",
                    lab_or_program="Wistar Undergraduate Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Varies by program (REU and technician training are supported)",
                    eligibility_majors=["biology", "biochemistry", "bioengineering", "chemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Program-dependent annual cycles",
                    keywords=["cancer biology", "biomedical training", "REU", "biotech"],
                ),
            ],
        },
        {
            "source_name": "upenn_lab_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.grasp.upenn.edu/",
                "https://wbl.wharton.upenn.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "grasp_lab",
                    "GRASP Lab (General Robotics, Automation, Sensing & Perception) — Penn Engineering",
                    "https://www.grasp.upenn.edu/",
                    "Penn Engineering's flagship robotics institute, spanning "
                    "perception, autonomous aerial and ground robots, manipulation, "
                    "machine learning, and multi-robot systems across the MEAM, ESE, "
                    "and CIS departments. GRASP has no standalone REU (SUNFEST, its "
                    "former sensor-technologies REU, ended after 2023), but GRASP "
                    "faculty routinely host Penn undergraduates through PURM, "
                    "Rachleff Scholars, academic-year independent study, and direct "
                    "lab positions — making it a prime cold-email target for "
                    "robotics-interested students. The site lists faculty, labs, and "
                    "current research for identifying mentors.",
                    organization="University of Pennsylvania",
                    department="School of Engineering & Applied Science",
                    lab_or_program="GRASP Lab",
                    compensation="Lab-dependent (via PURM, work-study, or faculty funding)",
                    eligibility_majors=["robotics", "computer science", "electrical engineering", "mechanical engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling / faculty-dependent",
                    keywords=["robotics", "autonomy", "perception", "cold-email", "faculty labs"],
                ),
                program(
                    "wharton_behavioral_lab",
                    "Wharton Behavioral Lab — University of Pennsylvania",
                    "https://wbl.wharton.upenn.edu/",
                    "The Wharton Behavioral Lab provides staff, technology, and lab "
                    "space supporting faculty and student research on how people "
                    "think, act, and make decisions, recruiting participants and "
                    "running behavioral experiments. For undergraduates it is both a "
                    "gateway into behavioral research operations (experiment "
                    "support and RA exposure via faculty projects) and a paid "
                    "participant pool — study sessions pay $15/hour. Wharton "
                    "students doing SPUR/SIRE projects run studies through the lab, "
                    "which holds monthly open office hours for researchers.",
                    organization="University of Pennsylvania",
                    department="The Wharton School",
                    lab_or_program="Wharton Behavioral Lab",
                    compensation="Study participation $15/hour; RA arrangements via faculty",
                    eligibility_majors=["business economics", "psychology", "marketing", "management"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Rolling",
                    keywords=["behavioral science", "decision making", "experiments", "lab"],
                ),
            ],
        },
    ],
}
