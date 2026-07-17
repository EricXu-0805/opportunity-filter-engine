"""UMass Amherst campus opportunity-graph config.

Curated seed records of the UMass Amherst undergraduate-research landscape,
centered on OURS (the centralized Office of Undergraduate Research and
Studies), the PROPEL opportunity-rounds platform, the Commonwealth Honors
College thesis/MassURC track, and the college-level research entry points
(CNS Lee SIP, CICS, Engineering, Biology). URLs verified live (HTTP 200) on
2026-07-17.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → umass_research_programs (umass / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "umass",
    "organization": "University of Massachusetts Amherst",
    "location": "Amherst, MA",
    "emit": {
        "campus": ("umass_research_programs", "umass", "campus"),
    },
    "sources": [
        {
            "source_name": "umass_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.umass.edu/ours/",
                "https://propel.umass.edu/",
                "https://www.umass.edu/engineering/research/undergraduate-research",
                "https://www.cics.umass.edu/research/undergraduate-research-opportunities",
            ],
            "programs": [
                program(
                    "ours_office",
                    "Office of Undergraduate Research and Studies (OURS) — UMass Amherst",
                    "https://www.umass.edu/ours/",
                    "OURS is UMass Amherst's centralized undergraduate-research "
                    "office, a branch of the Learning Resource Center. It helps "
                    "students in all disciplines, at every stage, find and access "
                    "on- and off-campus research and scholarly opportunities "
                    "year-round, and supports them through the application "
                    "process. It runs advising appointments, a Canvas 'Research "
                    "Readiness' workshop, and hires student Research Mentors.",
                    lab_or_program="OURS",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research advising",
                              "scholarly opportunities", "all disciplines",
                              "research readiness"],
                ),
                program(
                    "ours_search_opportunities",
                    "OURS Search for Opportunities (UMass Amherst)",
                    "https://www.umass.edu/ours/search-opportunities",
                    "OURS's searchable platform for finding undergraduate "
                    "research experiences matched to a student's academic "
                    "interests. It aggregates campus research openings across "
                    "departments so students can browse and filter "
                    "opportunities; a companion 'Learn How to Use Search' guide "
                    "walks students through the tool.",
                    lab_or_program="OURS",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research opportunities", "opportunity search",
                              "undergraduate research database"],
                ),
                program(
                    "propel",
                    "PROPEL — Undergraduate Opportunity Rounds (UMass Amherst)",
                    "https://propel.umass.edu/",
                    "PROPEL is a UMass platform that promotes equitable access "
                    "to academic, research, teaching, and experiential-learning "
                    "opportunities, framing undergraduate research as a "
                    "High-Impact Practice. Faculty post projects in timed "
                    "application 'rounds' (e.g. projects starting each term) and "
                    "students apply directly through the dedicated platform.",
                    lab_or_program="PROPEL",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research placement", "teaching assistantship",
                              "experiential learning", "faculty projects",
                              "application rounds"],
                ),
                program(
                    "lee_sip",
                    "William Lee Science Impact Program (Lee SIP) — UMass CNS",
                    "https://www.umass.edu/natural-sciences/research/undergraduate-research/william-lee-science-impact-program",
                    "Lee SIP is a College of Natural Sciences Research "
                    "Experience for Undergraduates (REU) designed to expand and "
                    "broaden participation in undergraduate research. Lee SIP "
                    "Scholars are mentored directly by research faculty, work "
                    "within a research team, and take part in "
                    "professional-development workshops, building a supported "
                    "pathway into a science research career.",
                    lab_or_program="Lee SIP",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["REU", "natural sciences", "research mentorship",
                              "broadening participation", "professional development",
                              "research team"],
                ),
                program(
                    "cics_undergrad_research",
                    "CICS Undergraduate Research Opportunities (UMass Amherst)",
                    "https://www.cics.umass.edu/research/undergraduate-research-opportunities",
                    "The Manning College of Information & Computer Sciences "
                    "program for undergraduates to experience computing research "
                    "while building connections with faculty and graduate "
                    "students who share their interests. It targets students "
                    "excited about generating new knowledge and communicating "
                    "findings, connecting them to CS research groups.",
                    lab_or_program="CICS Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Computer Science", "Informatics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["computer science", "computing research",
                              "faculty mentorship", "research groups", "CICS"],
                ),
                program(
                    "honors_thesis",
                    "Commonwealth Honors College Honors Thesis (UMass Amherst)",
                    "https://www.umass.edu/honors/honors-thesis",
                    "The Honors Thesis lets students undertake original thinking "
                    "and work closely with faculty mentors on advanced research "
                    "topics or creative endeavors, producing a substantial study "
                    "of a carefully defined question or problem. Projects may be "
                    "critical, experimental, applied, or creative, and are the "
                    "capstone of the Commonwealth Honors College experience.",
                    lab_or_program="Commonwealth Honors College",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    keywords=["honors thesis", "capstone research",
                              "faculty mentor", "original research",
                              "creative project"],
                ),
                program(
                    "massurc",
                    "Massachusetts Undergraduate Research Conference (MassURC)",
                    "https://www.umass.edu/honors/organizations/massachusetts-undergraduate-research-conference",
                    "MassURC is an annual statewide undergraduate research "
                    "conference hosted at UMass Amherst by the Commonwealth "
                    "Honors College (MassURC 2026 is April 17, 2026). It brings "
                    "together undergraduates from across the commonwealth to "
                    "present research and creative work through posters and "
                    "talks, giving students a venue to share findings and build "
                    "presentation experience.",
                    lab_or_program="Commonwealth Honors College",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research conference", "poster presentation",
                              "statewide", "undergraduate research showcase"],
                ),
                program(
                    "eng_undergrad_research",
                    "Riccio College of Engineering Undergraduate Research (UMass Amherst)",
                    "https://www.umass.edu/engineering/research/undergraduate-research",
                    "The College of Engineering's undergraduate-research hub "
                    "connects motivated engineering students to the college's "
                    "wide array of disciplines and research specialties at the "
                    "Commonwealth's flagship public research university. It "
                    "frames research participation as a deeply rewarding "
                    "component of the undergraduate engineering program and "
                    "points students to faculty labs and specialties.",
                    lab_or_program="Engineering Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Mechanical Engineering", "Electrical Engineering",
                                        "Civil Engineering", "Chemical Engineering",
                                        "Biomedical Engineering", "Industrial Engineering"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["engineering research", "faculty labs",
                              "research specialties"],
                ),
                program(
                    "biology_research_opportunities",
                    "Biology Department Undergraduate Research Opportunities (UMass Amherst)",
                    "https://www.umass.edu/biology/research/research-opportunities",
                    "The Department of Biology encourages all Biology majors to "
                    "pursue research experiences in its laboratories as part of "
                    "scientific training, and coordinates with OURS to help "
                    "students find and access research opportunities on and off "
                    "campus. It serves as the departmental entry point into "
                    "life-sciences lab research.",
                    lab_or_program="Biology Undergraduate Research",
                    opportunity_type="research",
                    eligibility_majors=["Biology"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["biology", "life sciences", "lab research",
                              "scientific training", "research laboratories"],
                ),
            ],
        },
    ],
}
