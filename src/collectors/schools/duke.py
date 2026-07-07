"""Duke University campus opportunity-graph config (US-News rollout).

Curated seed of Duke's undergraduate-research landscape: the Undergraduate
Research Support Office (URS) hub, the signature interdisciplinary programs
(Bass Connections, Data+), the Career Center, and a couple of research
institutes. URLs verified against duke.edu (Jul 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> duke_research_programs (duke / campus)
    open   -> duke_external_research (national / open)
    lab    -> duke_labs              (duke / unknown)
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
    "school_slug": "duke",
    "organization": "Duke University",
    "location": "Durham, NC",
    "emit": {
        "campus": ("duke_research_programs", "duke", "campus"),
        "open": ("duke_external_research", None, "open"),
        "lab": ("duke_labs", "duke", "unknown"),
    },
    "sources": [
        {
            "source_name": "duke_urs_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": ["https://undergraduateresearch.duke.edu/"],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "urs_hub",
                    "Undergraduate Research Support Office (URS) — Hub (Duke)",
                    "https://undergraduateresearch.duke.edu/",
                    "Duke's central office for undergraduate research: independent-study "
                    "grants, summer research fellowships, conference travel awards, and "
                    "faculty-mentor matching across all schools. Start here to find a "
                    "program by class year and field.",
                    lab_or_program="Undergraduate Research Support",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship", "research grant"],
                ),
            ],
        },
        {
            "source_name": "duke_signature_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://bassconnections.duke.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "bass_connections",
                    "Bass Connections — Interdisciplinary Research Teams (Duke)",
                    "https://bassconnections.duke.edu/",
                    "Year-long interdisciplinary research teams pairing undergraduates, "
                    "graduate students, and faculty on real-world problems across five "
                    "themes (Brain & Society, Energy, Global Health, Information & "
                    "Society, Race & Society). Paid summer extensions available.",
                    lab_or_program="Bass Connections",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["interdisciplinary research", "team science"],
                ),
                program(
                    "data_plus",
                    "Data+ — Summer Data Research (Duke)",
                    "https://bigdata.duke.edu/data-summer-program/",
                    "A 10-week summer program where undergraduates work in small teams on "
                    "data-driven research projects with faculty and graduate mentors. Pays "
                    "a stipend; open to Duke students from any major.",
                    lab_or_program="Data+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Data Science", "Statistics", "Computer Science"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["data science", "summer research", "stipend"],
                ),
            ],
        },
        {
            "source_name": "duke_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://careerhub.students.duke.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_center",
                    "Duke Career Center — Internships & Research",
                    "https://careerhub.students.duke.edu/",
                    "Duke's Career Center connects undergraduates to internships, research "
                    "assistantships, and funded summer experiences, with advising and the "
                    "campus job board. Open to all class years and majors.",
                    organization="Duke Career Center",
                    lab_or_program="Career Center",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "research assistant"],
                ),
            ],
        },
        {
            "source_name": "duke_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": ["https://nicholas.duke.edu/"],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "nicholas_environment",
                    "Nicholas School of the Environment — Undergraduate Research (Duke)",
                    "https://nicholas.duke.edu/",
                    "The Nicholas School hosts undergraduate research in environmental "
                    "science, ecology, climate, and marine science (including the Duke "
                    "Marine Lab), a strong cold-email target for field and lab placements.",
                    department="Nicholas School of the Environment",
                    lab_or_program="Nicholas School",
                    eligibility_majors=["Environmental Science", "Ecology", "Marine Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["environment", "ecology", "climate", "marine science"],
                ),
            ],
        },
        # --- Harvested program catalog (Jul 2026): every live-verified
        # undergraduate-research program, fellowship, and institute. ---
        {
            "source_name": "duke_catalog_announcement_campus",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://undergraduateresearch.duke.edu/urs-funding-opportunities",
                "https://bassconnections.duke.edu/summer-programs/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "urs_office",
                    "Duke Undergraduate Research Support (URS) Office \u2014 Funding Opportunities Hub",
                    "https://undergraduateresearch.duke.edu/urs-funding-opportunities",
                    "Central hub of the Duke Undergraduate Research Support Office listing all "
                    "URS funding awards open to Duke undergraduates across disciplines. From "
                    "here students can find independent-study grants, research assistantships, "
                    "conference-travel grants, and summer fellowships. It is the main starting "
                    "point for any Duke undergraduate seeking mentored-research funding or "
                    "guidance.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="URS Funding Opportunities",
                    paid="stipend",
                    compensation="Varies by award (grants and stipends)",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Multiple deadlines throughout the year depending on the specific award",
                    keywords=["undergraduate research", "funding", "grants", "URS", "Duke"],
                ),
                program(
                    "bass_connections_summer",
                    "Duke Bass Connections \u2014 Summer Research Programs",
                    "https://bassconnections.duke.edu/summer-programs/",
                    "Bass Connections' portfolio of interdisciplinary summer research programs "
                    "where undergraduates work in mentored teams \u2014 Data+, Climate+, Story+, the "
                    "Summer Neuroscience Program, and Global Health Student Research Training. "
                    "Open to Duke students across all majors; most are 6\u201310 weeks with "
                    "stipends. A single directory to compare Duke's team-based summer research "
                    "options.",
                    organization="Duke University",
                    department="Bass Connections / Office of Interdisciplinary Programs",
                    lab_or_program="Bass Connections Summer Programs",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipends vary by program (6\u201310 weeks)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Duke undergraduates; most deadlines in February.",
                    keywords=["Bass Connections", "interdisciplinary", "team research", "Data+", "Climate+"],
                ),
            ],
        },
        {
            "source_name": "duke_catalog_department_campus",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://ousf.duke.edu/",
                "https://medschool.duke.edu/research/summer-undergraduate-research-opportunities",
                "https://pratt.duke.edu/academics/undergrad/research/",
                "https://nicholas.duke.edu/academics/undergraduate-programs",
                "https://sanford.duke.edu/academics/undergraduate-program/current-students/research-assistantships/",
                "https://physics.duke.edu/undergraduate/current-students/undergraduate-research",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "ousf_fellowship_advising",
                    "Duke Office of University Scholars and Fellows (Fellowship Advising)",
                    "https://ousf.duke.edu/",
                    "Duke's central office advising undergraduates and recent alumni on "
                    "nationally competitive scholarships and fellowships (e.g., Goldwater, "
                    "Fulbright, Rhodes, Marshall), many of which fund research. Provides "
                    "guidance, campus nomination processes, and application support. A key "
                    "resource for research-oriented students pursuing external funding and "
                    "awards.",
                    organization="Duke University",
                    department="Office of University Scholars and Fellows (OUSF)",
                    lab_or_program="Fellowship Advising",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Deadlines vary by scholarship/fellowship",
                    keywords=["fellowship advising", "national scholarships", "OUSF", "Goldwater", "Fulbright"],
                ),
                program(
                    "som_summer_ug",
                    "Duke School of Medicine \u2014 Summer Undergraduate Research Opportunities",
                    "https://medschool.duke.edu/research/summer-undergraduate-research-opportunities",
                    "The School of Medicine's central listing of paid summer undergraduate "
                    "research programs across basic and biomedical sciences \u2014 including Amgen "
                    "Scholars, the Pratt Engineering REU, PRIME-Cancer, SROP, STAR, and RESURP. "
                    "Use it to compare programs by eligibility (many require US citizenship), "
                    "stipend, housing, and research area before applying. A good directory for "
                    "premed and PhD-bound undergraduates.",
                    organization="Duke University School of Medicine",
                    department="School of Medicine, Office of Research",
                    lab_or_program="Summer Undergraduate Research Opportunities directory",
                    paid="stipend",
                    compensation="Varies by program",
                    eligibility_majors=["biology", "biochemistry", "biomedical sciences", "neuroscience", "premed"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Directory page; deadlines vary by individual program (most in Jan\u2013Feb).",
                    keywords=["School of Medicine", "biomedical", "summer research", "directory", "basic sciences"],
                ),
                program(
                    "pratt_ug_research",
                    "Duke Pratt School of Engineering \u2014 Undergraduate Research",
                    "https://pratt.duke.edu/academics/undergrad/research/",
                    "The Pratt engineering research office page describing how undergraduates "
                    "get involved in faculty labs during the year and summer, including "
                    "independent study, Pratt Fellows, and the summer NSF REU. Covers "
                    "biomedical, civil/environmental, electrical/computer, and mechanical "
                    "engineering & materials science. Starting point for engineering students "
                    "seeking mentored research and summer stipends.",
                    organization="Duke University",
                    department="Pratt School of Engineering",
                    lab_or_program="Pratt Undergraduate Research",
                    paid="stipend",
                    compensation="Varies (Pratt Fellows and summer research provide stipends)",
                    eligibility_majors=["biomedical engineering", "civil engineering", "environmental engineering", "electrical engineering", "computer engineering", "mechanical engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling for lab placements; summer REU deadlines typically in January.",
                    keywords=["engineering", "Pratt", "undergraduate research", "Pratt Fellows", "labs"],
                ),
                program(
                    "nicholas_ug",
                    "Duke Nicholas School of the Environment \u2014 Undergraduate Programs & Research",
                    "https://nicholas.duke.edu/academics/undergraduate-programs",
                    "The Nicholas School's undergraduate hub covering environmental "
                    "sciences/policy and marine science majors and the research pathways "
                    "attached to them, including faculty-mentored research, the Duke Marine "
                    "Lab, and scholars programs (Rachel Carson, Repass-Rodgers, Scholars in "
                    "Marine Medicine). Entry point for students seeking environmental, ecology, "
                    "and coastal/marine research plus summer funding.",
                    organization="Duke University",
                    department="Nicholas School of the Environment",
                    lab_or_program="Nicholas School Undergraduate Programs",
                    paid="stipend",
                    compensation="Varies; scholars programs and Stanback fellowships provide funding",
                    eligibility_majors=["environmental science", "environmental policy", "marine science", "earth science", "ecology"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling for faculty research; scholars programs have spring deadlines.",
                    keywords=["environment", "marine science", "ecology", "Nicholas School", "conservation"],
                ),
                program(
                    "sanford_ra",
                    "Duke Sanford School of Public Policy \u2014 Undergraduate Research Assistantships",
                    "https://sanford.duke.edu/academics/undergraduate-program/current-students/research-assistantships/",
                    "Sanford's listing of faculty research-assistant positions for "
                    "undergraduate public policy students, funded in part by the Eads Family "
                    "Undergraduate Research Endowment. Students apply directly to a faculty "
                    "project (e.g., health services, caregiving, veterans/community engagement) "
                    "with a resume and statement of interest; positions are paid at the Sanford "
                    "hourly rate. Summer Eads funding requires the student to reside in North "
                    "Carolina.",
                    organization="Duke University",
                    department="Sanford School of Public Policy",
                    lab_or_program="Research Assistantships / Eads Family Undergraduate Research",
                    paid="yes",
                    compensation="Paid at Sanford hourly rate; Eads endowment funds summer RA work",
                    eligibility_majors=["public policy", "political science", "economics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling \u2014 apply directly to posted faculty positions. Summer Eads funding requires residing in NC.",
                    keywords=["public policy", "research assistant", "Sanford", "Eads", "faculty research"],
                ),
                program(
                    "physics_ug_research",
                    "Duke Department of Physics \u2014 Undergraduate Research",
                    "https://physics.duke.edu/undergraduate/current-students/undergraduate-research",
                    "The Physics department page describing how undergraduates join research "
                    "groups (nuclear/particle, high-energy, condensed matter, biophysics, "
                    "atomic/optical, cosmology) for independent study, senior theses, and "
                    "summer research, including the TUNL REU and Fellowships. Starting point "
                    "for physics and applied-physics students seeking mentored research and "
                    "summer funding at Duke.",
                    organization="Duke University",
                    department="Department of Physics",
                    lab_or_program="Physics Undergraduate Research",
                    paid="stipend",
                    compensation="Varies; summer fellowships and REU provide stipends",
                    eligibility_majors=["physics", "astronomy", "engineering physics", "mathematics"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling for group placements; summer fellowship/REU deadlines in spring.",
                    keywords=["physics", "undergraduate research", "senior thesis", "condensed matter", "biophysics"],
                ),
            ],
        },
        {
            "source_name": "duke_catalog_lab_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://nicholasinstitute.duke.edu/",
                "https://kenan.ethics.duke.edu/undergraduate-student-programs/",
                "https://robotics.pratt.duke.edu/students",
                "https://tunl.duke.edu/education/reu",
                "https://dibs.duke.edu/",
                "https://ssri.duke.edu/",
                "https://globalhealth.duke.edu/",
                "https://kenan.ethics.duke.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nicholas_institute",
                    "Nicholas Institute for Energy, Environment & Sustainability",
                    "https://nicholasinstitute.duke.edu/",
                    "Duke's environmental policy institute; hosts student research assistants "
                    "working on energy, climate, and sustainability policy analysis.",
                    organization="Duke University",
                    department="Nicholas Institute",
                    lab_or_program="Nicholas Institute",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["institute", "undergraduate research"],
                ),
                program(
                    "kenan_ethics_undergrad",
                    "Kenan Institute for Ethics \u2014 Undergraduate Student Programs \u2014 Duke University",
                    "https://kenan.ethics.duke.edu/undergraduate-student-programs/",
                    "The Kenan Institute for Ethics hosts a portfolio of undergraduate programs "
                    "\u2014 including certificates, fellowships, immersive projects, and applied "
                    "research on ethics and social change. Open to Duke undergraduates across "
                    "majors interested in ethics, moral leadership, and interdisciplinary "
                    "inquiry. Individual programs vary in structure and funding; some carry "
                    "stipends or project support.",
                    organization="Duke University",
                    department="Kenan Institute for Ethics",
                    lab_or_program="Kenan Institute for Ethics \u2014 Undergraduate Student Programs",
                    compensation="Varies by program; some fellowships/projects carry stipends",
                    eligibility_majors=["all", "ethics", "philosophy", "public policy"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Deadlines vary by individual program",
                    keywords=["ethics", "moral leadership", "fellowships", "certificate", "interdisciplinary"],
                ),
                program(
                    "robotics_students",
                    "Duke Robotics \u2014 Undergraduate Research & Prospective Students \u2014 Duke University",
                    "https://robotics.pratt.duke.edu/students",
                    "This Duke Robotics hub points undergraduates toward robotics research by "
                    "contacting individual faculty who accept undergrads into their labs, plus "
                    "a robotics certificate, undergraduate courses, senior design capstones, "
                    "and the Duke Robotics Club (RoboSub autonomous underwater vehicle "
                    "competition). Open to Duke undergraduates interested in robotics and "
                    "autonomy. Research is arranged directly with faculty labs rather than "
                    "through a single formal application, so funding varies by lab.",
                    organization="Duke University",
                    department="Pratt School of Engineering \u2014 Robotics (MEMS)",
                    lab_or_program="Duke Robotics",
                    compensation="Varies by faculty lab; arranged directly with mentor",
                    eligibility_majors=["mechanical engineering", "electrical engineering", "computer science", "engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="No central deadline; contact individual faculty directly",
                    keywords=["robotics", "autonomy", "faculty labs", "RoboSub", "capstone"],
                ),
                program(
                    "tunl_reu",
                    "TUNL / Duke Physics NSF REU (Nuclear & Particle Physics)",
                    "https://tunl.duke.edu/education/reu",
                    "A 10-week NSF REU at the Triangle Universities Nuclear Laboratory and "
                    "Duke, with research, lectures, and social activities. Students choose "
                    "nuclear/particle physics at TUNL or high-energy particle physics with the "
                    "Duke HEP group \u2014 HEP participants spend ~6 of the 10 weeks at CERN. Open "
                    "to undergraduates (US citizens/permanent residents); provides a stipend "
                    "and housing.",
                    organization="Duke University / Triangle Universities Nuclear Laboratory / NSF",
                    department="Department of Physics",
                    lab_or_program="TUNL REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + housing (10 weeks)",
                    eligibility_majors=["physics", "astronomy", "engineering physics", "mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="NSF REU: US citizens/permanent residents. Applications typically due in February.",
                    keywords=["physics", "nuclear physics", "particle physics", "NSF REU", "TUNL"],
                ),
                program(
                    "dibs",
                    "Duke Institute for Brain Sciences (DIBS) \u2014 Undergraduate Research",
                    "https://dibs.duke.edu/",
                    "Duke's interdisciplinary neuroscience institute connects undergraduates "
                    "with labs across psychology, neurobiology, and biomedical engineering, and "
                    "runs research programs and events for students. A strong cold-email target "
                    "for brain-science lab placements.",
                    organization="Duke University",
                    department="Duke Institute for Brain Sciences",
                    lab_or_program="Duke Institute for Brain Sciences",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["institute", "undergraduate research"],
                ),
                program(
                    "ssri",
                    "Social Science Research Institute (SSRI) \u2014 Undergraduate Research",
                    "https://ssri.duke.edu/",
                    "Duke's hub for interdisciplinary social science research; hosts "
                    "undergraduate research assistants and data-focused projects across "
                    "education, health policy, and human development.",
                    organization="Duke University",
                    department="Social Science Research Institute",
                    lab_or_program="Social Science Research Institute",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["institute", "undergraduate research"],
                ),
                program(
                    "dghi",
                    "Duke Global Health Institute \u2014 Undergraduate Research",
                    "https://globalhealth.duke.edu/",
                    "DGHI engages undergraduates in global health research through mentored "
                    "projects, fieldwork opportunities, and its student research support "
                    "programs.",
                    organization="Duke University",
                    department="Duke Global Health Institute",
                    lab_or_program="Duke Global Health Institute",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["institute", "undergraduate research"],
                ),
                program(
                    "kenan_ethics",
                    "Kenan Institute for Ethics \u2014 Undergraduate Research",
                    "https://kenan.ethics.duke.edu/",
                    "The Kenan Institute for Ethics runs undergraduate fellowships and mentored "
                    "research on ethics across disciplines, including student research teams.",
                    organization="Duke University",
                    department="Kenan Institute for Ethics",
                    lab_or_program="Kenan Institute for Ethics",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["institute", "undergraduate research"],
                ),
            ],
        },
        {
            "source_name": "duke_catalog_program_campus",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://undergraduateresearch.duke.edu/T-SUMR",
                "https://undergraduateresearch.duke.edu/opportunity/biological-sciences-undergraduate-research-fellowship-bsurf",
                "https://undergraduateresearch.duke.edu/SURF",
                "https://undergraduateresearch.duke.edu/duke-prime-cancer-research-program",
                "https://undergraduateresearch.duke.edu/opportunity/reach-equity-summer-undergraduate-research-program-resurp",
                "https://undergraduateresearch.duke.edu/opportunity/summer-research-internship-toxicology-and-environmental-health",
                "https://undergraduateresearch.duke.edu/urs-independent-study-grants",
                "https://undergraduateresearch.duke.edu/urs-assistantships",
                "https://undergraduateresearch.duke.edu/urs-conference-grants",
                "https://undergraduateresearch.duke.edu/TRI-Path",
                "https://undergraduateresearch.duke.edu/opportunity/deans-summer-research-fellowships",
                "https://undergraduateresearch.duke.edu/honors-theses",
                "https://undergraduateresearch.duke.edu/program-ii-research-funds",
                "https://focus.duke.edu/",
                "https://bigdata.duke.edu/participate/data-plus/",
                "https://fhi.duke.edu/education/story/",
                "https://bigdata.duke.edu/participate/climate-plus/",
                "https://codeplus.duke.edu/",
                "https://scienceandsociety.duke.edu/huang-fellows-program/",
                "https://undergraduateresearch.duke.edu/opportunity/duke-national-academy-engineering-grand-challenge-scholar-program",
                "https://pratt.duke.edu/academics/undergrad/research/pratt-fellows/",
                "https://dcri.org/education/dukes-star-program",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "tsumr_trinity_research",
                    "Trinity Summer Undergraduate Mentored Research (T-SUMR) Fellowship \u2014 Duke University",
                    "https://undergraduateresearch.duke.edu/T-SUMR",
                    "T-SUMR is a summer fellowship supporting Trinity College of Arts & "
                    "Sciences undergraduates in full-time faculty-mentored research across the "
                    "arts, humanities, social sciences, and natural sciences. Open to "
                    "continuing Duke Trinity undergraduates who secure a faculty mentor. "
                    "Fellows receive a summer stipend to pursue focused research, often as a "
                    "bridge to a senior thesis.",
                    organization="Duke University",
                    department="Trinity College of Arts & Sciences / Undergraduate Research ",
                    lab_or_program="Trinity Summer Undergraduate Mentored Research (T-SUMR)",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Summer research stipend",
                    eligibility_majors=["arts", "humanities", "social sciences", "natural sciences", "all"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically due in spring for summer",
                    keywords=["Trinity College", "mentored research", "summer", "faculty mentor", "thesis prep"],
                ),
                program(
                    "bsurf",
                    "Duke BSURF \u2014 Biological Sciences Undergraduate Research Fellowship",
                    "https://undergraduateresearch.duke.edu/opportunity/biological-sciences-undergraduate-research-fellowship-bsurf",
                    "A highly selective 8-week summer fellowship placing rising-sophomore Duke "
                    "students in a biological or biomedical science lab (in Arts & Sciences "
                    "departments or School of Medicine basic-science labs) to do hands-on "
                    "mentored research. Includes cohort professional-development workshops on "
                    "reading papers, research ethics, and science communication. Provides a "
                    "$4,000 stipend plus on-campus housing; students commit full-time with no "
                    "other classes or jobs.",
                    organization="Duke University",
                    department="Department of Biology / School of Medicine basic sciences",
                    lab_or_program="BSURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$4,000 stipend + on-campus housing (8 weeks)",
                    eligibility_majors=["biology", "biological sciences", "neuroscience", "biomedical sciences"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="For rising sophomores (current Duke first-years); application in the spring semester.",
                    keywords=["biology", "summer research", "fellowship", "rising sophomore", "lab placement"],
                ),
                program(
                    "surf",
                    "Duke SURF \u2014 Summer Undergraduate Research Fellowship",
                    "https://undergraduateresearch.duke.edu/SURF",
                    "Duke's flagship 8-week paid summer research fellowship for rising "
                    "sophomores, pairing students with faculty mentors to learn research skills "
                    "as a cohort. Provides a stipend plus campus housing; students work "
                    "full-time on research. Note: the Biological & Brain Sciences arm of SURF "
                    "did not run in Summer 2026, so confirm which tracks are active for the "
                    "current cycle.",
                    organization="Duke University",
                    department="Undergraduate Research Support Office",
                    lab_or_program="SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + on-campus housing (8 weeks)",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="For rising sophomores; spring application. Biological & Brain Sciences arm did not run in Summer 202",
                    keywords=["summer research", "fellowship", "rising sophomore", "faculty mentor", "stipend"],
                ),
                program(
                    "prime_cancer",
                    "Duke PRIME-Cancer Research Program",
                    "https://undergraduateresearch.duke.edu/duke-prime-cancer-research-program",
                    "A summer undergraduate research program focused on cancer biology and "
                    "oncology, giving students mentored research in Duke Cancer "
                    "Institute-affiliated labs plus professional development toward biomedical "
                    "PhD/MD careers. Paid; aimed at undergraduates interested in cancer "
                    "research. Confirm eligibility and dates on the application page.",
                    organization="Duke University School of Medicine",
                    department="Duke Cancer Institute / School of Medicine",
                    lab_or_program="PRIME-Cancer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend",
                    eligibility_majors=["biology", "biochemistry", "biomedical sciences", "chemistry"],
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Spring application; check page for citizenship requirements and dates.",
                    keywords=["cancer", "oncology", "biomedical", "summer research", "PhD pipeline"],
                ),
                program(
                    "resurp",
                    "Duke REACH Equity Summer Undergraduate Research Program (RESURP)",
                    "https://undergraduateresearch.duke.edu/opportunity/reach-equity-summer-undergraduate-research-program-resurp",
                    "An 8-week summer program from the Duke Center for Research to Advance "
                    "Healthcare Equity (REACH Equity) for rising juniors and seniors, combining "
                    "a mentored health-disparities research project with clinical shadowing and "
                    "training in the causes of racial/ethnic disparities in care. Paid. Note "
                    "the program has not run every year, so verify the current cycle's status.",
                    organization="Duke University School of Medicine",
                    department="Duke Center for REACH Equity",
                    lab_or_program="RESURP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend (8 weeks)",
                    eligibility_majors=["public health", "biology", "premed", "sociology", "psychology"],
                    preferred_year=["junior", "senior"],
                    deadline_note="Rising juniors/seniors; deadline ~mid-February. Did not run in some recent years \u2014 confirm status.",
                    keywords=["health equity", "health disparities", "clinical research", "shadowing", "summer"],
                ),
                program(
                    "tox_env_health_reu",
                    "Duke Summer Research Internship in Toxicology & Environmental Health",
                    "https://undergraduateresearch.duke.edu/opportunity/summer-research-internship-toxicology-and-environmental-health",
                    "A summer research internship placing undergraduates in Duke labs studying "
                    "toxicology and environmental health, spanning environmental sciences, "
                    "biology, and biomedical toxicology. Provides mentored bench/field research "
                    "and professional development for students considering environmental-health "
                    "or biomedical graduate study. Paid; check the page for eligibility and "
                    "dates.",
                    organization="Duke University",
                    department="Nicholas School / Integrated Toxicology & Environmental Heal",
                    lab_or_program="Summer Research Internship in Toxicology & Environmental Hea",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend",
                    eligibility_majors=["environmental science", "biology", "toxicology", "chemistry", "public health"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Spring application; check page for citizenship requirements.",
                    keywords=["toxicology", "environmental health", "summer research", "internship", "biomedical"],
                ),
                program(
                    "urs_independent_study",
                    "Duke URS Independent Study Award",
                    "https://undergraduateresearch.duke.edu/urs-independent-study-grants",
                    "A URS grant that funds Duke undergraduates conducting faculty-mentored "
                    "independent research during the academic year, supporting project costs "
                    "such as materials, supplies, and travel. Open to students across "
                    "disciplines who are enrolled in an independent-study or directed-research "
                    "course. It helps students pursue original projects that go beyond regular "
                    "coursework.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="URS Independent Study Grant",
                    paid="stipend",
                    compensation="Grant funds for research expenses",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications accepted on a per-semester basis",
                    keywords=["independent study", "research grant", "academic year", "URS", "Duke"],
                ),
                program(
                    "urs_assistantship",
                    "Duke URS Assistantship Award",
                    "https://undergraduateresearch.duke.edu/urs-assistantships",
                    "A URS award that funds Duke undergraduates working as research assistants "
                    "on a faculty member's ongoing project during the academic year. Designed "
                    "for students who want mentored research experience and a stipend while "
                    "contributing to a professor's lab or scholarly work. Open across "
                    "disciplines.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="URS Assistantship",
                    paid="stipend",
                    compensation="Stipend for research assistant work",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications accepted on a per-semester basis",
                    keywords=["research assistant", "assistantship", "faculty mentor", "URS", "Duke"],
                ),
                program(
                    "urs_conference_award",
                    "Duke URS Conference Award",
                    "https://undergraduateresearch.duke.edu/urs-conference-grants",
                    "A URS travel grant that reimburses Duke undergraduates for costs of "
                    "presenting their research at academic or professional conferences. Open to "
                    "students across disciplines who have been accepted to present (poster or "
                    "talk) at a recognized conference. It supports the dissemination stage of "
                    "the undergraduate research experience.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="URS Conference Grant",
                    paid="stipend",
                    compensation="Travel grant / reimbursement for conference costs",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; apply before conference travel",
                    keywords=["conference travel", "presentation", "research dissemination", "URS", "Duke"],
                ),
                program(
                    "tri_path",
                    "Duke TRInity PATHways to Research (TRI-PATH) Program",
                    "https://undergraduateresearch.duke.edu/TRI-Path",
                    "A cohort program that introduces Duke Trinity College undergraduates \u2014 "
                    "especially those newer to research or from underrepresented backgrounds \u2014 "
                    "to the process of finding and starting faculty-mentored research. It "
                    "provides structured guidance, mentoring, and a pathway into subsequent "
                    "research funding. Aimed at earlier-year students building research "
                    "readiness.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="TRInity PATHways to Research (TRI-PATH)",
                    paid="stipend",
                    compensation="Program support / stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="See program page for cohort application dates",
                    keywords=["research pathways", "cohort program", "underrepresented", "Trinity College", "Duke"],
                ),
                program(
                    "dsrf",
                    "Duke Deans' Summer Research Fellowship (DSRF)",
                    "https://undergraduateresearch.duke.edu/opportunity/deans-summer-research-fellowships",
                    "A competitive summer fellowship, funded by the Duke deans, that provides "
                    "undergraduates with a stipend to conduct faculty-mentored research over "
                    "the summer. Open across disciplines to students with a defined research "
                    "project and mentor. Supports full-time summer scholarly work.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="Deans' Summer Research Fellowship (DSRF)",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Summer stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Spring deadline for the following summer",
                    keywords=["summer research", "deans fellowship", "stipend", "DSRF", "Duke"],
                ),
                program(
                    "honors_theses",
                    "Duke Honors Theses / Graduation with Distinction",
                    "https://undergraduateresearch.duke.edu/honors-theses",
                    "Information hub for Duke undergraduates pursuing a senior honors thesis "
                    "and Graduation with Distinction, the capstone of independent "
                    "faculty-mentored research in their major. Explains the thesis process, "
                    "timelines, and how it connects to URS funding. Primarily for juniors and "
                    "seniors undertaking a year-long research project.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="Honors Theses / Graduation with Distinction",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Departmental thesis timelines apply (typically begins junior year)",
                    keywords=["honors thesis", "graduation with distinction", "capstone research", "Duke"],
                ),
                program(
                    "program_ii_research_funds",
                    "Duke Program II Research Funds",
                    "https://undergraduateresearch.duke.edu/program-ii-research-funds",
                    "Research funding available specifically to Duke Program II students \u2014 "
                    "undergraduates who design their own interdisciplinary degree \u2014 to support "
                    "projects tied to their individualized curriculum. Provides grant support "
                    "for the independent scholarly work central to a Program II course of "
                    "study. Restricted to enrolled Program II students.",
                    organization="Duke University",
                    department="Undergraduate Research Support (URS) Office",
                    lab_or_program="Program II Research Funds",
                    paid="stipend",
                    compensation="Research grant funds",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="For enrolled Program II students; see page for timing",
                    keywords=["Program II", "interdisciplinary", "research funding", "self-designed major", "Duke"],
                ),
                program(
                    "focus_program",
                    "Duke FOCUS Program (First-Year Interdisciplinary Clusters)",
                    "https://focus.duke.edu/",
                    "A first-semester living-learning program in which Duke first-year students "
                    "take small interdisciplinary seminar clusters closely tied to faculty "
                    "research, dining and living alongside faculty and peers. It is a common "
                    "early entry point into Duke's research community, connecting freshmen to "
                    "professors who mentor undergraduate research. Open to incoming first-year "
                    "students.",
                    organization="Duke University",
                    department="FOCUS Program / Trinity College of Arts & Sciences",
                    lab_or_program="FOCUS Program",
                    paid="no",
                    preferred_year=["freshman"],
                    international_friendly="yes",
                    deadline_note="Enrollment during first-year onboarding (summer before matriculation)",
                    keywords=["FOCUS", "first-year", "interdisciplinary", "faculty seminars", "living-learning"],
                ),
                program(
                    "data_plus_x",
                    "Data+ Summer Research Program \u2014 Duke University",
                    "https://bigdata.duke.edu/participate/data-plus/",
                    "Data+ is a 10-week full-time summer program where undergraduates work in "
                    "small teams on data-driven research projects across many fields, guided by "
                    "faculty and graduate mentors. Open to Duke undergraduates from any major; "
                    "no prior data-science experience required for many projects. Participants "
                    "receive a summer stipend; applications generally close in late "
                    "winter/early spring.",
                    organization="Duke University",
                    department="Rhodes Information Initiative at Duke (iiD)",
                    lab_or_program="Data+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend for 10-week full-time participation",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically close late winter / early spring for summer",
                    keywords=["data science", "summer research", "team projects", "10-week", "quantitative"],
                ),
                program(
                    "story_plus",
                    "Story+ Summer Humanities Research Program \u2014 Duke University",
                    "https://fhi.duke.edu/education/story/",
                    "Story+ is a 6-week paid summer program in which undergraduate and graduate "
                    "students work in small teams on interdisciplinary humanities, arts, and "
                    "interpretive social-science research projects, led by faculty, librarians, "
                    "archivists, or nonprofit partners. Open to Duke undergraduates interested "
                    "in storytelling-driven research across disciplines. All undergraduate "
                    "researchers receive a competitive stipend paid in two installments during "
                    "the summer.",
                    organization="Duke University",
                    department="Franklin Humanities Institute (FHI)",
                    lab_or_program="Story+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Competitive summer stipend paid in two installments",
                    eligibility_majors=["humanities", "arts", "social sciences", "all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Page notes a prior pause; check FHI for current cycle dates",
                    keywords=["humanities", "storytelling", "arts", "6-week", "team research"],
                ),
                program(
                    "climate_plus",
                    "Climate+ Summer Research Program \u2014 Duke University",
                    "https://bigdata.duke.edu/participate/climate-plus/",
                    "Climate+ is a full-time, 10-week summer research experience in which teams "
                    "of undergraduates from a variety of majors, plus a graduate student "
                    "project manager, marshal, analyze, and visualize data to tackle a climate "
                    "challenge. Open to Duke undergraduates across disciplines interested in "
                    "climate and data. Modeled on Data+, participation is a full-time summer "
                    "commitment; check the page for the current stipend and application cycle.",
                    organization="Duke University",
                    department="Rhodes Information Initiative at Duke (iiD)",
                    lab_or_program="Climate+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Full-time 10-week summer program (stipend-based, per iiD summer programs)",
                    eligibility_majors=["all", "environmental science", "data science"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically open winter/spring for summer cohort",
                    keywords=["climate", "data science", "summer research", "10-week", "team projects"],
                ),
                program(
                    "code_plus",
                    "Code+ Summer Program \u2014 Duke University",
                    "https://codeplus.duke.edu/",
                    "Code+ is a 10-week summer program where undergraduate teams build real "
                    "software and technology solutions with mentorship from Duke's Office of "
                    "Information Technology and industry professionals, emphasizing hands-on "
                    "development over pure research. Open to Duke undergraduates interested in "
                    "software engineering, product, and design; no expert-level experience "
                    "required. Participants receive a summer stipend and work full-time "
                    "on-campus.",
                    organization="Duke University",
                    department="Office of Information Technology (OIT)",
                    lab_or_program="Code+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend for full-time 10-week participation",
                    eligibility_majors=["computer science", "engineering", "all"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically open winter/spring for summer cohort",
                    keywords=["software development", "technology", "summer program", "10-week", "product design"],
                ),
                program(
                    "huang_fellows",
                    "Huang Fellows Program \u2014 Duke Science & Society",
                    "https://scienceandsociety.duke.edu/huang-fellows-program/",
                    "The Huang Fellows Program is a selective cohort experience for first-year "
                    "Duke students that combines a paid summer research placement in a science "
                    "or engineering lab with seminars on the ethical and societal dimensions of "
                    "science. Open to rising sophomores (applicants in their first year) across "
                    "STEM interests. Fellows receive a summer research stipend and continue "
                    "with programming into the following year.",
                    organization="Duke University",
                    department="Duke Science & Society",
                    lab_or_program="Huang Fellows",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Summer research stipend",
                    eligibility_majors=["biology", "engineering", "chemistry", "STEM", "all"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="Applications open to first-year students, typically due in spring",
                    keywords=["science and society", "ethics", "lab research", "first-year", "cohort"],
                ),
                program(
                    "grand_challenge_scholars",
                    "NAE Grand Challenge Scholars Program \u2014 Duke Pratt School of Engineering",
                    "https://undergraduateresearch.duke.edu/opportunity/duke-national-academy-engineering-grand-challenge-scholar-program",
                    "Duke's chapter of the National Academy of Engineering Grand Challenge "
                    "Scholars Program guides engineering undergraduates through a curriculum "
                    "built around research, interdisciplinary study, entrepreneurship, global "
                    "engagement, and service tied to the NAE Grand Challenges. Open primarily "
                    "to Pratt engineering undergraduates who complete the program's five "
                    "competencies. Structured as a multi-year enrichment track rather than a "
                    "single paid placement.",
                    organization="Duke University",
                    department="Pratt School of Engineering",
                    lab_or_program="NAE Grand Challenge Scholars Program",
                    compensation="Program track; research funding varies by placement",
                    eligibility_majors=["engineering", "biomedical engineering", "mechanical engineering", "electrical engineering", "computer engineering"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Rolling enrollment; complete five competencies over multiple years",
                    keywords=["engineering", "grand challenges", "NAE", "interdisciplinary", "entrepreneurship"],
                ),
                program(
                    "pratt_research_fellows",
                    "Pratt Research Fellows Program \u2014 Duke Pratt School of Engineering",
                    "https://pratt.duke.edu/academics/undergrad/research/pratt-fellows/",
                    "The Pratt Research Fellows Program is a two-year, faculty-mentored "
                    "independent research experience for Duke engineering undergraduates, "
                    "culminating in a distinction thesis. Open to Pratt engineering students "
                    "who begin in their sophomore/junior years and commit to sustained "
                    "research. Fellows can access summer research funding and present their "
                    "work; it is designed for students aiming at research careers or graduate "
                    "study.",
                    organization="Duke University",
                    department="Pratt School of Engineering",
                    lab_or_program="Pratt Research Fellows",
                    paid="stipend",
                    compensation="Summer research funding available; distinction thesis track",
                    eligibility_majors=["engineering", "biomedical engineering", "mechanical engineering", "electrical engineering", "civil engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically in spring of sophomore/junior year",
                    keywords=["engineering", "faculty-mentored", "thesis", "two-year", "independent research"],
                ),
                program(
                    "star_program",
                    "Duke STAR \u2014 Summer Training in Academic Research (DCRI)",
                    "https://dcri.org/education/dukes-star-program",
                    "A 5-week in-person summer program run by the Duke Clinical Research "
                    "Institute giving high-school, undergraduate, and medical students hands-on "
                    "experience in research methodology and scientific writing. Participants "
                    "work in teams matched with Duke faculty mentors on an original "
                    "hypothesis-driven project. Open to all class years with no prior research "
                    "required (US citizen); paid.",
                    organization="Duke Clinical Research Institute (Duke University)",
                    department="Duke Clinical Research Institute",
                    lab_or_program="STAR Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend (5-week program)",
                    eligibility_majors=["all", "premed", "public health", "biology"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="US citizen; open to all years, no prior research needed. Spring application.",
                    keywords=["clinical research", "DCRI", "research methodology", "scientific writing", "summer"],
                ),
            ],
        },
        {
            "source_name": "duke_catalog_program_campus_3",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://undergraduateresearch.duke.edu/opportunity/rachel-carson-scholars-program",
                "https://nicholasinstitute.duke.edu/climate-plus",
                "https://bassconnections.duke.edu/summer-programs/summer-neuroscience-program/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "rachel_carson_scholars",
                    "Duke Rachel Carson Scholars Program (Marine Science)",
                    "https://undergraduateresearch.duke.edu/opportunity/rachel-carson-scholars-program",
                    "A scholars program giving Duke undergraduates faculty-mentored independent "
                    "research in marine science and conservation, with at least one semester "
                    "(or summer) spent at the Duke University Marine Laboratory in Beaufort, "
                    "NC. Scholars get small seminars, mentorship, professional development, and "
                    "funding for research, conference travel, and travel courses. For students "
                    "aiming to become marine conservation leaders.",
                    organization="Duke University",
                    department="Nicholas School of the Environment / Duke Marine Lab",
                    lab_or_program="Rachel Carson Scholars Program",
                    paid="stipend",
                    compensation="Funding for research, conference travel, and travel courses",
                    eligibility_majors=["marine science", "biology", "environmental science", "ecology"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Duke undergraduates; spring application. Requires at least one term at the Marine Lab.",
                    keywords=["marine science", "conservation", "Duke Marine Lab", "Beaufort", "scholars"],
                ),
                program(
                    "climate_plus_x",
                    "Duke Climate+ Summer Research Program",
                    "https://nicholasinstitute.duke.edu/climate-plus",
                    "A 10-week summer program (a Bass Connections/Nicholas Institute-affiliated "
                    "data experience) in which small teams of Duke undergraduates tackle "
                    "interdisciplinary climate-related research projects with faculty and "
                    "project sponsors. Suited to students across majors interested in climate, "
                    "energy, sustainability, and data. Provides a stipend; runs late May to "
                    "late July alongside Data+.",
                    organization="Duke University",
                    department="Nicholas Institute for Energy, Environment & Sustainability",
                    lab_or_program="Climate+",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend (10 weeks)",
                    eligibility_majors=["all", "environmental science", "data science", "engineering", "economics", "public policy"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Duke undergraduates; application deadline in February (aligned with Data+).",
                    keywords=["climate", "sustainability", "energy", "data science", "Bass Connections"],
                ),
                program(
                    "summer_neuroscience",
                    "Duke Summer Neuroscience Program (SNP)",
                    "https://bassconnections.duke.edu/summer-programs/summer-neuroscience-program/",
                    "An 8-week summer research experience (Bass Connections-affiliated) letting "
                    "undergraduates jump-start their Graduation with Distinction senior theses "
                    "by working one-on-one with faculty mentors in neuroscience labs. The full "
                    "program is open to rising juniors and seniors who are declared "
                    "Neuroscience majors; provides a stipend. Includes cohort programming in "
                    "research methods and communication.",
                    organization="Duke University",
                    department="Department of Neurobiology / Bass Connections",
                    lab_or_program="Summer Neuroscience Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend (8 weeks)",
                    eligibility_majors=["neuroscience"],
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Full program for declared rising-junior/senior Neuroscience majors; spring application.",
                    keywords=["neuroscience", "senior thesis", "faculty mentor", "Bass Connections", "summer research"],
                ),
            ],
        },
        {
            "source_name": "duke_catalog_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://undergraduateresearch.duke.edu/amgen-scholars-program-duke",
                "https://undergraduateresearch.duke.edu/opportunity/duke-engineering-research-opportunities-through-pratt-school",
                "https://nicholas.duke.edu/marinelab/research/reu",
                "https://ousf.duke.edu/award/goldwater-scholarship/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "amgen_scholars",
                    "Amgen Scholars Program at Duke",
                    "https://undergraduateresearch.duke.edu/amgen-scholars-program-duke",
                    "An intensive 10-week summer research experience (mid-May to late July) in "
                    "biotechnology and drug discovery, matching scholars with a Duke faculty "
                    "mentor for independent lab research plus visits to Research Triangle Park "
                    "biotech/pharma, seminars, and PhD/MD-PhD prep. Open to US "
                    "citizens/permanent residents at accredited US institutions who are "
                    "sophomores, juniors, or non-graduating seniors with a GPA of 3.2+ and "
                    "interest in a research PhD or MD-PhD. Provides a stipend, housing, and "
                    "travel.",
                    organization="Duke University / Amgen Foundation",
                    department="Undergraduate Research Support Office",
                    lab_or_program="Amgen Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + housing + travel (10 weeks)",
                    eligibility_majors=["biology", "biochemistry", "chemistry", "biomedical engineering", "neuroscience", "science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="US citizens/permanent residents only; GPA 3.2+. Summer 2026 ran May 18\u2013July 24; deadline was early F",
                    keywords=["Amgen", "biotechnology", "drug discovery", "PhD pipeline", "national program"],
                ),
                program(
                    "pratt_gc_reu",
                    "Duke Pratt Engineering REU \u2014 Grand Challenges of Engineering",
                    "https://undergraduateresearch.duke.edu/opportunity/duke-engineering-research-opportunities-through-pratt-school",
                    "An NSF-funded summer Research Experience for Undergraduates hosted by "
                    "Pratt in which students spend ~9 weeks living on the Duke campus doing "
                    "authentic engineering research toward the Grand Challenges of Engineering "
                    "(e.g., reverse-engineer the brain, engineer better medicines, provide "
                    "clean water, secure cyberspace), ending in a research symposium. Aimed at "
                    "rising juniors and seniors (US citizens/permanent residents); provides a "
                    "stipend and housing.",
                    organization="Duke University / National Science Foundation",
                    department="Pratt School of Engineering",
                    lab_or_program="REU for Meeting the Grand Challenges",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + on-campus housing (~9 weeks)",
                    eligibility_majors=["biomedical engineering", "electrical engineering", "mechanical engineering", "materials science", "computer science", "engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="NSF REU: US citizens/permanent residents. Applications open late fall, close in January. (Program's ",
                    keywords=["NSF REU", "engineering", "Grand Challenges", "Pratt", "summer research"],
                ),
                program(
                    "marine_lab_reu",
                    "Duke University Marine Laboratory NSF REU (Beaufort, NC)",
                    "https://nicholas.duke.edu/marinelab/research/reu",
                    "An NSF Research Experience for Undergraduates at the Duke Marine Lab in "
                    "Beaufort supporting ~9 students for a 10-week independent research project "
                    "in estuarine and coastal marine systems (sensory "
                    "physiology/ecology/behavior, molecular biology/genetics, or "
                    "coastal/estuarine physical processes), with seminars, field trips, and "
                    "training in scientific writing and ethics. Open to rising "
                    "sophomores\u2013seniors (US citizens/permanent residents); includes stipend, "
                    "dorm housing, and meals. Confirm whether a cohort is offered this year.",
                    organization="Duke University / National Science Foundation",
                    department="Nicholas School of the Environment / Duke Marine Lab",
                    lab_or_program="Marine Lab REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + dormitory housing + meals (10 weeks)",
                    eligibility_majors=["marine science", "biology", "ecology", "oceanography", "environmental science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="NSF REU: US citizens/permanent residents. No 2026 cohort per NSF listing \u2014 confirm current status.",
                    keywords=["NSF REU", "marine science", "coastal", "estuarine", "Beaufort"],
                ),
                program(
                    "goldwater_scholarship",
                    "Goldwater Scholarship (Duke / OUSF)",
                    "https://ousf.duke.edu/award/goldwater-scholarship/",
                    "The Duke advising page for the national Barry Goldwater Scholarship, which "
                    "funds sophomores and juniors committed to research careers in STEM (up to "
                    "$7,500/year toward tuition, fees, room, and board). Requires U.S. "
                    "citizenship or permanent residency and demonstrated research achievement; "
                    "Duke requires a campus nomination before the national competition. The "
                    "2026 cycle deadline is November 6, 2026.",
                    organization="Barry Goldwater Scholarship Foundation / Duke OUSF (advising)",
                    department="Office of University Scholars and Fellows (OUSF)",
                    lab_or_program="Goldwater Scholarship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Up to $7,500 per academic year toward tuition, fees, room, and board",
                    eligibility_majors=["Mathematics", "Natural Sciences", "Engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Requires campus nomination; 2026 cycle deadline Nov 6, 2026",
                    keywords=["Goldwater Scholarship", "STEM research", "national scholarship", "OUSF", "Duke"],
                ),
            ],
        },
    ],
}
