"""University of Minnesota Twin Cities campus opportunity-graph config.

Curated seed records of UMN's undergraduate-research landscape, centered on
the Office of Undergraduate Research (ugresearch.umn.edu) — UROP and its
international and summer variants, the for-credit Directed Research on-ramp,
and the fall presentation venue — plus the Medical School's LSSURP summer
pipeline and CSE's college research hub. URLs verified live (HTTP 200) on
2026-07-17.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → umn_research_programs (umn / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "umn",
    "organization": "University of Minnesota Twin Cities",
    "location": "Minneapolis, MN",
    "emit": {
        "campus": ("umn_research_programs", "umn", "campus"),
    },
    "sources": [
        {
            "source_name": "umn_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ugresearch.umn.edu/opportunities/urop",
                "https://ugresearch.umn.edu/opportunities/summer",
                "https://med.umn.edu/gps/undergraduate-research/life-sciences-summer",
            ],
            "programs": [
                program(
                    "urop",
                    "Undergraduate Research Opportunities Program (UROP)",
                    "https://ugresearch.umn.edu/opportunities/urop",
                    "UROP is UMN's flagship campus-wide undergraduate research "
                    "program: undergraduates from every college and major "
                    "partner with a faculty member on a research or creative "
                    "project, with a stipend plus a supplies/expenses "
                    "allowance. Projects run during the academic year or "
                    "summer and require a faculty mentor and a written "
                    "proposal; peer drop-in hours and proposal-writing "
                    "resources are provided.",
                    lab_or_program="UROP",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Stipend plus a supplies/expenses allowance",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Next deadline October 5, 2026 for Spring 2027 projects.",
                    keywords=["undergraduate research", "faculty mentor",
                              "research funding", "stipend", "creative projects",
                              "proposal"],
                ),
                program(
                    "iurop",
                    "International UROP (I-UROP)",
                    "https://ugresearch.umn.edu/opportunities/iurop",
                    "The International Undergraduate Research Opportunities "
                    "Program is a scholarship promoting learning-abroad "
                    "research: it funds students enrolled in select "
                    "credit-bearing education-abroad programs that include a "
                    "research project. Administered jointly with the Learning "
                    "Abroad Center, it targets students who want to combine "
                    "study abroad with mentored research and offsets the cost "
                    "of the research-focused abroad experience.",
                    lab_or_program="I-UROP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["research abroad", "study abroad", "scholarship",
                              "international", "learning abroad", "funding"],
                ),
                program(
                    "summer_research_programs",
                    "Summer Research Programs (Office of Undergraduate Research)",
                    "https://ugresearch.umn.edu/opportunities/summer",
                    "Each summer hundreds of undergraduates participate in "
                    "University of Minnesota campus-wide summer research "
                    "programs, drawing students from institutions across the "
                    "nation. The Office of Undergraduate Research maintains a "
                    "clearinghouse of paid summer research positions both at "
                    "UMN and at REU-style programs nationwide — the central "
                    "listing point for full-time mentored summer research "
                    "placements.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "REU", "paid research",
                              "full-time", "mentored research", "summer program"],
                ),
                program(
                    "directed_research_study",
                    "Directed Research / Directed Study",
                    "https://ugresearch.umn.edu/opportunities/directed-study",
                    "Directed Research (or Directed Study) lets undergraduates "
                    "earn academic credit by working in a lab or field setting "
                    "under a faculty member's guidance. Each college "
                    "administers its own registration process, so students "
                    "coordinate with their advisor and the supervising "
                    "instructor to set scope and credits — the standard "
                    "for-credit on-ramp into a faculty research group.",
                    lab_or_program="Directed Research",
                    opportunity_type="research",
                    paid="no",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["directed research", "directed study", "for credit",
                              "lab experience", "faculty guidance", "field research"],
                ),
                program(
                    "fall_ur_symposium",
                    "Fall Undergraduate Research Symposium",
                    "https://ugresearch.umn.edu/presentation-opportunities/fall-symposium",
                    "The Fall Virtual Undergraduate Research Symposium is a "
                    "University-wide venue where UMN undergraduates present "
                    "their research, scholarly, and creative projects to the "
                    "campus community. Presenters prepare posters or talks in "
                    "the format that best represents their work, with "
                    "structured guidance for preparing and delivering "
                    "presentations — a low-barrier way to gain presentation "
                    "experience and share results.",
                    lab_or_program="Fall Undergraduate Research Symposium",
                    opportunity_type="research",
                    paid="no",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research symposium", "poster presentation",
                              "undergraduate research", "showcase",
                              "scholarly projects", "presentation"],
                ),
                program(
                    "lssurp",
                    "Life Sciences Summer Undergraduate Research Program (LSSURP)",
                    "https://med.umn.edu/gps/undergraduate-research/life-sciences-summer",
                    "LSSURP is a competitive, mentored summer research program "
                    "running since 1989 that places undergraduates in "
                    "University of Minnesota life-sciences and biomedical labs "
                    "for a full-time summer research experience with faculty "
                    "mentorship. It targets students considering graduate "
                    "study in the biological, biomedical, and health sciences "
                    "and includes professional-development programming.",
                    lab_or_program="LSSURP",
                    opportunity_type="summer_program",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Applications due early February.",
                    keywords=["life sciences", "biomedical research",
                              "summer program", "mentorship",
                              "graduate school prep", "lab research"],
                ),
                program(
                    "cse_undergraduate_research",
                    "CSE Undergraduate Research (College of Science & Engineering)",
                    "https://cse.umn.edu/college/collegiate-life/undergraduate-research",
                    "The College of Science & Engineering's undergraduate "
                    "research hub lays out the on-ramps for CSE students to "
                    "get involved in research — working directly with faculty, "
                    "joining lab groups, and pursuing funded projects. It "
                    "points students to UROP, directed study, and departmental "
                    "opportunities within engineering, computing, and the "
                    "physical sciences.",
                    lab_or_program="CSE Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["engineering research", "computer science",
                              "faculty labs", "hands-on", "STEM research",
                              "undergraduate research"],
                ),
            ],
        },
    ],
}
