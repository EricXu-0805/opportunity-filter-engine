"""NC State campus opportunity-graph config.

Curated seed records of NC State's undergraduate-research landscape, centered
on the Office of Undergraduate Research (OUR, undergradresearch.dasa.ncsu.edu)
and its funding programs (supply grants, travel awards, Federal Work-Study
research assistantships, the campus symposium series), plus the flagship
scholar cohorts (Park, Goodnight, Caldwell Fellows, University Honors) and the
NASA-funded North Carolina Space Grant headquartered on campus. URLs
curl-verified live (HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ncsu_research_programs (ncsu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "ncsu",
    "organization": "North Carolina State University",
    "location": "Raleigh, NC",
    "emit": {
        "campus": ("ncsu_research_programs", "ncsu", "campus"),
    },
    "sources": [
        {
            "source_name": "ncsu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergradresearch.dasa.ncsu.edu/",
                "https://park.ncsu.edu/",
                "https://goodnight.ncsu.edu/",
                "https://ncspacegrant.ncsu.edu/",
            ],
            "programs": [
                program(
                    "our_office",
                    "Office of Undergraduate Research (NC State)",
                    "https://undergradresearch.dasa.ncsu.edu/",
                    "NC State's central Office of Undergraduate Research "
                    "supports and promotes the undergraduate research "
                    "community with tools, resources, and guidance for "
                    "students, faculty, and staff. Students can follow the "
                    "self-guided Getting Started steps to explore different "
                    "forms of research, or book one-on-one meetings and "
                    "drop-in office hours with a Research Ambassador. The "
                    "office also runs regular workshops such as Crafting a "
                    "Research Poster and graduate-student panels.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research mentoring",
                              "getting started", "research ambassador"],
                ),
                program(
                    "our_project_supply_grants",
                    "OUR Project Supply Grants (NC State)",
                    "https://undergradresearch.dasa.ncsu.edu/project-supply-grants/",
                    "Grants funded by the Office of Undergraduate Research to "
                    "purchase supplies needed for undergraduate research "
                    "projects. Applicants may request up to $500 for research "
                    "supplies and up to $1,000 for their work on the project. "
                    "Applications are accepted for the fall, spring, and "
                    "summer terms, and awardees are encouraged to present "
                    "their results and join professional-development "
                    "workshops.",
                    lab_or_program="OUR Project Supply Grants",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Up to $500 for supplies plus up to $1,000 for project work",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research funding", "supply grant",
                              "research supplies", "undergraduate research"],
                ),
                program(
                    "our_travel_awards",
                    "OUR Travel Awards (NC State)",
                    "https://undergradresearch.dasa.ncsu.edu/travel-awards/",
                    "Cost-sharing awards funded by the Office of Undergraduate "
                    "Research for students attending a research conference who "
                    "need financial assistance with travel to present their "
                    "work. Funds are distributed to the student's mentor or "
                    "home department, which must match the amount and award "
                    "funds through travel reimbursement. Applications are "
                    "accepted on a rolling basis throughout the year, "
                    "including summer.",
                    lab_or_program="OUR Travel Awards",
                    opportunity_type="fellowship",
                    compensation="Cost-shared conference travel reimbursement",
                    preferred_year=["junior", "senior"],
                    deadline_note="Rolling applications year-round",
                    keywords=["conference travel", "research presentation", "travel award"],
                ),
                program(
                    "spring_research_symposium",
                    "Spring Undergraduate Research & Creativity Symposium (NC State)",
                    "https://undergradresearch.dasa.ncsu.edu/symposium/",
                    "Campus-wide symposium where undergraduate researchers "
                    "from across NC State share their work at any stage in "
                    "the process through poster and oral presentations, "
                    "performances, and exhibits. All fields are represented "
                    "and everyone is welcome — it is explicitly pitched at "
                    "students curious about getting involved in research. OUR "
                    "also runs Fall Sidewalk and Summer symposium editions.",
                    lab_or_program="Undergraduate Research & Creativity Symposium",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research symposium", "poster presentation",
                              "undergraduate research", "creativity"],
                ),
                program(
                    "our_fws_research_assistant",
                    "OUR Federal Work-Study Research Assistant Program (NC State)",
                    "https://undergradresearch.dasa.ncsu.edu/our-federal-work-study-research-assistant-positions/",
                    "Uses the U.S. Government's Federal Work-Study program to "
                    "provide an hourly wage to undergraduates conducting "
                    "research under the guidance of their own mentor. "
                    "Applications are accepted for fall, spring, or the "
                    "entire academic year, and participants are encouraged to "
                    "present their results and join professional-development "
                    "workshops.",
                    lab_or_program="OUR Federal Work-Study Research Assistants",
                    opportunity_type="research",
                    paid="yes",
                    compensation="Hourly wage through Federal Work-Study",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["work-study", "paid research", "research assistant"],
                ),
                program(
                    "summer_research_programs",
                    "Find Summer Research Programs — OUR hub (NC State)",
                    "https://undergradresearch.dasa.ncsu.edu/find-summer-research-programs/",
                    "OUR's guide to summer research programs (REUs and "
                    "similar) at NC State and beyond, noting that "
                    "opportunities exist for any field or discipline and can "
                    "help prepare students for graduate school and research "
                    "careers. Aggregates NC State-hosted and external summer "
                    "program listings plus application resources.",
                    lab_or_program="OUR Summer Research Programs",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "REU",
                              "research experience for undergraduates",
                              "graduate school prep"],
                ),
                program(
                    "park_scholarships",
                    "Park Scholarships (NC State)",
                    "https://park.ncsu.edu/",
                    "Four-year scholarship to NC State awarded on the basis "
                    "of outstanding accomplishments and potential in "
                    "scholarship, leadership, service, and character. Park "
                    "Scholars participate in a series of enrichment "
                    "experiences for personal and professional growth, and "
                    "the program maintains an active alumni network as a "
                    "resource for current students.",
                    lab_or_program="Park Scholarships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Four-year full scholarship",
                    preferred_year=["freshman"],
                    keywords=["merit scholarship", "leadership", "service", "full scholarship"],
                ),
                program(
                    "goodnight_scholars",
                    "Goodnight Scholars Program (NC State)",
                    "https://goodnight.ncsu.edu/",
                    "The Goodnight Scholars Program (founded 2008) and "
                    "Goodnight Transfer Scholars Program (founded 2017), "
                    "supported by NC State alumni Jim and Ann Goodnight, "
                    "offer full-tuition scholarships plus comprehensive "
                    "student development programs designed to develop "
                    "scholars into leaders. The programs target STEM and "
                    "education students from North Carolina.",
                    lab_or_program="Goodnight Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Full-tuition scholarship",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["full tuition", "STEM scholarship",
                              "transfer students", "student development"],
                ),
                program(
                    "caldwell_fellows",
                    "Caldwell Fellows Program (NC State)",
                    "https://caldwellfellows.ncsu.edu/",
                    "Leadership-development fellowship that aims to develop "
                    "self-aware, globally-minded students who engage in "
                    "creative, conscientious leadership. Students apply "
                    "during their first year at NC State; the program "
                    "combines scholarship support with experiential "
                    "leadership development and a strong alumni community "
                    "(astronaut Christina Koch is a noted alumna).",
                    lab_or_program="Caldwell Fellows",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman"],
                    keywords=["leadership development", "fellowship", "experiential learning"],
                ),
                program(
                    "university_honors",
                    "University Honors Program (NC State)",
                    "https://honors.dasa.ncsu.edu/",
                    "Challenges academically motivated students to "
                    "investigate contemporary questions and ideas through "
                    "advanced, innovative honors coursework and high-impact "
                    "opportunities. Components include the Honors Forum, "
                    "Honors Seminars, exploration trips, and study abroad — "
                    "an elevated path for intellectually curious students.",
                    lab_or_program="University Honors Program",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors", "seminars", "high-impact learning",
                              "intellectual curiosity"],
                ),
                program(
                    "nc_space_grant",
                    "North Carolina Space Grant (NC State)",
                    "https://ncspacegrant.ncsu.edu/",
                    "NASA-funded grant program headquartered at NC State that "
                    "promotes, develops, and supports aeronautics and "
                    "space-related science, engineering, and technology "
                    "education and training in North Carolina. Partners with "
                    "NASA, industry, nonprofits, and state agencies, and runs "
                    "undergraduate research scholarships and fellowships to "
                    "equip the future aerospace workforce.",
                    lab_or_program="North Carolina Space Grant",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["NASA", "aerospace", "space science",
                              "research scholarship", "STEM funding"],
                ),
            ],
        },
    ],
}
