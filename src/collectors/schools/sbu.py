"""Stony Brook University campus opportunity-graph config.

Curated seed records of Stony Brook's undergraduate-research landscape,
centered on URECA (the central Undergraduate Research and Creative
Activities office) and its funded summer tracks — one centralized
application covers URECA Summer, Explorations in STEM and the Velay
Fellowship — plus the CIE-URECA SUNY SOAR partnership, the Garcia Center
summer research scholars, and the university honors programs whose senior
thesis is a built-in faculty-mentored research pathway. URLs verified live
(HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → sbu_research_programs (sbu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "sbu",
    "organization": "Stony Brook University",
    "location": "Stony Brook, NY",
    "emit": {
        "campus": ("sbu_research_programs", "sbu", "campus"),
    },
    "sources": [
        {
            "source_name": "sbu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.stonybrook.edu/ureca/",
                "https://www.stonybrook.edu/garcia/summer-program/",
                "https://www.stonybrook.edu/commcms/university-honors-programs/",
            ],
            "programs": [
                program(
                    "ureca_office",
                    "URECA — Undergraduate Research and Creative Activities (Stony Brook)",
                    "https://www.stonybrook.edu/ureca/",
                    "URECA is Stony Brook's central undergraduate research "
                    "office. It runs 'Get Started' advising (find-a-mentor "
                    "guidance, research-skills workshops, research for "
                    "credit), funding opportunities including a centralized "
                    "summer application, and presentation venues including "
                    "the annual URECA Celebration & VIP Showcase and a Summer "
                    "Symposium. The office also spotlights a Researcher of "
                    "the Month.",
                    lab_or_program="URECA",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["undergraduate research", "mentorship",
                              "research funding", "poster symposium"],
                ),
                program(
                    "ureca_summer",
                    "URECA Summer Program (Stony Brook)",
                    "https://www.stonybrook.edu/ureca/funding-opportunities/apply-for-ureca-support.html",
                    "URECA Summer supports Stony Brook undergraduates doing "
                    "full-time faculty-mentored research, scholarly or "
                    "creative activity for ten weeks on campus (May 26 - "
                    "July 31, 2026). Open to all majors with at least one "
                    "semester of coursework remaining; graduating seniors are "
                    "not eligible. Awards a $5,000 stipend with possible "
                    "supplemental housing support; participants prepare an "
                    "end-of-summer abstract and present at the spring URECA "
                    "poster Celebration.",
                    lab_or_program="URECA Summer",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$5,000 stipend for the ten-week summer",
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note=("One centralized application covers URECA "
                                   "Summer, Explorations in STEM and the Velay "
                                   "Fellowship (deadline March 13, 2026)"),
                    keywords=["summer research", "stipend", "faculty-mentored",
                              "all majors"],
                ),
                program(
                    "explorations_in_stem",
                    "Explorations in STEM (URECA track, Stony Brook)",
                    "https://www.stonybrook.edu/ureca/funding-opportunities/apply-for-ureca-support.html",
                    "PSEG-sponsored URECA summer track to promote interest in "
                    "STEM research and careers. Priority is given to students "
                    "new to research (less than one year of prior experience) "
                    "and to STEM students majoring in electrical, mechanical, "
                    "civil or chemical engineering and/or engineering "
                    "sciences. Ten weeks full-time with a $5,000 stipend; "
                    "requires participation in weekly workshops and an "
                    "abstract/poster at the Summer Symposium.",
                    lab_or_program="Explorations in STEM",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$5,000 stipend for the ten-week summer",
                    preferred_year=["freshman", "sophomore"],
                    deadline_note="Centralized URECA summer application, deadline March 13, 2026",
                    keywords=["STEM", "first research experience",
                              "engineering", "summer stipend"],
                ),
                program(
                    "velay_fellowship",
                    "Velay Fellowship (URECA track, Stony Brook)",
                    "https://www.stonybrook.edu/ureca/funding-opportunities/apply-for-ureca-support.html",
                    "Panaphil Foundation-funded URECA summer track to advance "
                    "women in science. Applicants must be majoring and/or "
                    "doing faculty-mentored research in Astronomy, "
                    "Biochemistry, Biology, Chemistry, Earth & Space "
                    "Sciences, Engineering Chemistry, Geology, and/or "
                    "Physics. Awards a $5,100 stipend; fellows present at the "
                    "Summer Symposium and produce a YouTube video segment "
                    "showcasing their research experience.",
                    lab_or_program="Velay Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$5,100 summer stipend",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Centralized URECA summer application, deadline March 13, 2026",
                    keywords=["women in science", "physical sciences",
                              "summer research", "fellowship"],
                ),
                program(
                    "suny_soar",
                    "SUNY SOAR (CIE-URECA partnership, Stony Brook)",
                    "https://www.stonybrook.edu/ureca/funding-opportunities/other-campus-opportunities.html",
                    "SUNY SOAR is a CIE-URECA partnership program providing "
                    "summer research opportunities for students who are "
                    "first-generation college students or economically "
                    "disadvantaged. The program provides on-campus housing "
                    "plus a stipend and meal allowance.",
                    lab_or_program="SUNY SOAR",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Stipend plus on-campus housing and meal allowance",
                    preferred_year=["freshman", "sophomore"],
                    deadline_note="Application deadline listed as March 24, 2026",
                    keywords=["first-generation", "summer research",
                              "housing", "stipend"],
                ),
                program(
                    "garcia_scholars",
                    "Garcia Center Research Scholars Program (Stony Brook)",
                    "https://www.stonybrook.edu/garcia/summer-program/",
                    "The Garcia Research Scholars Program at the Garcia "
                    "Center for Polymers at Engineered Interfaces is an "
                    "interdisciplinary summer research program pairing "
                    "students with faculty across fields where fundamental "
                    "science enables real-world solutions. Research areas "
                    "include medicine, pharmacology, dentistry, tissue "
                    "engineering, materials design, energy generation and "
                    "storage, mathematical modeling, and computation. A "
                    "stated goal is advancing projects each summer to a level "
                    "students can present and publish.",
                    lab_or_program="Garcia Research Scholars",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["polymers", "materials science",
                              "interdisciplinary", "summer research"],
                ),
                program(
                    "university_honors",
                    "University Honors Programs (Honors College / University Scholars / WISE Honors, Stony Brook)",
                    "https://www.stonybrook.edu/commcms/university-honors-programs/",
                    "Stony Brook's Division of Undergraduate Education runs "
                    "three university honors programs: Honors College, "
                    "University Scholars, and WISE Honors (Women in Science "
                    "and Engineering). Each has its own academics, advising, "
                    "and mentoring structure, and Honors College and WISE "
                    "Honors culminate in a Senior Thesis Project — a built-in "
                    "faculty-mentored research pathway.",
                    lab_or_program="University Honors Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors", "senior thesis", "WISE", "mentoring"],
                ),
            ],
        },
    ],
}
