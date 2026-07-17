"""University of Florida campus opportunity-graph config.

Curated seed records of UF's undergraduate-research landscape, centered on
the Center for Undergraduate Research (CUR, cur.aa.ufl.edu) and its program
family — University Scholars, Emerging Scholars, URSP, REPU, SUIRP, the
Newcastle exchange — plus the TRiO-funded McNair Scholars program. URLs
verified live (HTTP 200) on 2026-07-17 by the recon pass.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uf_research_programs (uf / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "uf",
    "organization": "University of Florida",
    "location": "Gainesville, FL",
    "emit": {
        "campus": ("uf_research_programs", "uf", "campus"),
    },
    "sources": [
        {
            "source_name": "uf_cur_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://cur.aa.ufl.edu/",
                "https://mcnair.aa.ufl.edu/",
            ],
            "programs": [
                program(
                    "cur_hub",
                    "UF Center for Undergraduate Research (CUR)",
                    "https://cur.aa.ufl.edu/",
                    "The Center for Undergraduate Research is UF's central hub "
                    "for connecting students with undergraduate research and "
                    "professional development opportunities. It runs the "
                    "Research Expo, Research Week, and best-paper awards, "
                    "maintains a Canvas page with weekly opportunity updates, "
                    "and is the gateway to the University Scholars, Emerging "
                    "Scholars, URSP, and SUIRP programs.",
                    lab_or_program="Center for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research opportunities",
                              "mentorship"],
                ),
                program(
                    "university_scholars",
                    "University Scholars Program (UF)",
                    "https://cur.aa.ufl.edu/programs-university-scholars-program/",
                    "University Scholars commit 8-10 hours per week to a "
                    "research project under the guidance of UF faculty, "
                    "registering for research credit in the mentor's "
                    "department each semester. Participating colleges and "
                    "academic centers review applications each spring; the "
                    "program is positioned as a capstone to a UF student's "
                    "academic career.",
                    lab_or_program="University Scholars Program",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    keywords=["faculty-mentored research", "research credit",
                              "capstone"],
                ),
                program(
                    "emerging_scholars",
                    "Emerging Scholars Program (UF)",
                    "https://cur.aa.ufl.edu/emerging-scholars-program/",
                    "An entry-level research program encouraging early "
                    "undergraduates to add a research experience during their "
                    "freshman or sophomore year, with a stipend attached. "
                    "Applications run in the fall with decisions announced "
                    "mid-January.",
                    lab_or_program="Emerging Scholars Program",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["entry-level research", "stipend",
                              "early undergraduate"],
                ),
                program(
                    "ursp",
                    "University Research Scholars Program (URSP, UF)",
                    "https://cur.aa.ufl.edu/programs-university-research-scholars-program/",
                    "An invitation-only program that introduces scholars to "
                    "academic research from the start of their UF career: it "
                    "surveys the breadth of research at UF, prepares students "
                    "to join the research community, assists in finding "
                    "research positions, and provides networking with "
                    "distinguished faculty plus leadership experience.",
                    lab_or_program="University Research Scholars Program",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    deadline_note="Invitation-only; extended at admission.",
                    keywords=["invitation-only", "research onboarding",
                              "networking"],
                ),
                program(
                    "repu",
                    "Research Excellence Program for Undergraduates (REPU, UF)",
                    "https://cur.aa.ufl.edu/programs-research-excellence-program-for-undergraduates/",
                    "A recognition track for UF students who accumulate "
                    "significant research experience during their "
                    "undergraduate studies. Students document completion of "
                    "program requirements on a CUR-supervised Canvas page "
                    "throughout their research career.",
                    lab_or_program="Research Excellence Program",
                    opportunity_type="research",
                    preferred_year=["junior", "senior"],
                    keywords=["research recognition", "transcript distinction"],
                ),
                program(
                    "suirp",
                    "Summer Undergraduate International Research Program (SUIRP, UF)",
                    "https://cur.aa.ufl.edu/summer-undergraduate-international-research-program/",
                    "Open to UF students in any discipline; awardees receive "
                    "up to $5,000 to cover travel and living expenses for "
                    "summer research abroad. Past scholars have conducted "
                    "research in Uganda, Argentina, France, and Italy.",
                    lab_or_program="SUIRP",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Up to $5,000 for travel and living expenses",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications close February 15, 2026.",
                    keywords=["international research", "summer research",
                              "research funding"],
                ),
                program(
                    "mcnair",
                    "Ronald E. McNair Scholars Program (UF)",
                    "https://mcnair.aa.ufl.edu/",
                    "A U.S. Department of Education TRiO-funded "
                    "post-baccalaureate achievement program supporting "
                    "undergraduates from first-generation and low-income "
                    "backgrounds on the path to doctoral study, with faculty "
                    "and graduate mentors, an advisory council, and cohorts "
                    "of current scholars at UF.",
                    lab_or_program="McNair Scholars Program",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["first-generation", "TRiO", "PhD preparation",
                              "mentored research"],
                ),
                program(
                    "newcastle_exchange",
                    "Research in Newcastle — UF-Newcastle Summer Exchange",
                    "https://cur.aa.ufl.edu/research-in-newcastle/",
                    "A pilot summer research exchange with Newcastle "
                    "University in England launching Summer B 2026: UF "
                    "students conduct research with Newcastle faculty while "
                    "Newcastle students join labs across UF's campus. "
                    "Accepted students choose from a range of research "
                    "projects.",
                    lab_or_program="Research in Newcastle",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["international exchange", "summer research",
                              "Newcastle University"],
                ),
            ],
        },
    ],
}
