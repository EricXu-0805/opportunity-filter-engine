"""Virginia Tech campus opportunity-graph config.

Curated seed records of Virginia Tech's undergraduate-research landscape,
centered on the Office of Undergraduate Research (OUR) — its summer research
programming, the Undergraduate Research Excellence Program (UREP), and the
student funding hub — plus the Fralin Life Sciences fellowships (Summer
Undergraduate Research Fellowship and the First-Year FURF), the MAOP Summer
Research Internship access pathway, the Hume Center for National Security and
Technology, and the Honors College. URLs curl-verified live (HTTP 200) on
2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → vt_research_programs (vt / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "vt",
    "organization": "Virginia Tech",
    "location": "Blacksburg, VA",
    "emit": {
        "campus": ("vt_research_programs", "vt", "campus"),
    },
    "sources": [
        {
            "source_name": "vt_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.research.undergraduate.vt.edu/",
                "https://www.maop.vt.edu/scholarship-support-and-summer-programs/sri-program.html",
                "https://hume.vt.edu/",
            ],
            "programs": [
                program(
                    "vt_office_undergraduate_research",
                    "Office of Undergraduate Research (Virginia Tech)",
                    "https://www.research.undergraduate.vt.edu/",
                    "Virginia Tech's central Office of Undergraduate Research "
                    "promotes, enhances, and expands undergraduate research "
                    "opportunities across campus. It runs summer research "
                    "programming, the First-Year Fralin Undergraduate Research "
                    "Fellowship, and the Undergraduate Research Excellence "
                    "Program (UREP), plus featured funding, an ambassadors "
                    "program, and a Discovery LAUNCHpad for getting started.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research opportunities",
                              "mentorship", "funding"],
                ),
                program(
                    "vt_summer_research_programming",
                    "Summer Research Programming at Virginia Tech",
                    "https://www.research.undergraduate.vt.edu/research-and-engagement/student-research-and-engagement/summer-research.html",
                    "Hub for summer undergraduate research at Virginia Tech, "
                    "with tracks for students and for faculty running summer "
                    "programs. It covers research expectations and guidelines, "
                    "a weekly professional development series, and culminates "
                    "in the campus-wide Summer Research Conference.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "professional development",
                              "research conference"],
                ),
                program(
                    "vt_urep",
                    "Undergraduate Research Excellence Program (UREP, Virginia Tech)",
                    "https://www.research.undergraduate.vt.edu/recognition/undergraduate-research-excellence-program.html",
                    "Launched in Spring 2018, UREP is open to any undergraduate "
                    "in any major. It connects students with undergraduate "
                    "research resources and support, lets them track their "
                    "research journey, and provides formal recognition "
                    "(including transcript-visible acknowledgment) for "
                    "engagement in undergraduate research.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research recognition", "research tracking", "any major"],
                ),
                program(
                    "vt_fralin_surf",
                    "Fralin Summer Undergraduate Research Fellowship (SURF, Virginia Tech)",
                    "https://www.research.undergraduate.vt.edu/research-and-engagement/student-research-and-engagement/research-opportunities/virginia-tech-research-opportunities/fralin-summer-undergraduate-research-fellowship.html",
                    "A 10-week full-time summer training program giving "
                    "motivated Virginia Tech undergraduates the opportunity to "
                    "engage in research; open to Virginia Tech students only. "
                    "The 2026 program runs late May through the end of July, "
                    "with an early-March student application deadline.",
                    lab_or_program="Fralin Life Sciences Institute",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Student application deadline early March (annual).",
                    keywords=["life sciences", "summer fellowship",
                              "full-time research", "Fralin"],
                ),
                program(
                    "vt_first_year_furf",
                    "First-Year Fralin Undergraduate Research Fellowship (Virginia Tech)",
                    "https://www.research.undergraduate.vt.edu/research-and-engagement/student-research-and-engagement/research-opportunities/virginia-tech-research-opportunities/first-year-furf.html",
                    "Funded by the Fralin Life Sciences Institute and open to "
                    "Virginia Tech students only, this fellowship pairs "
                    "first-year students with faculty mentors for a research "
                    "experience, with separate info tracks for students and "
                    "faculty.",
                    lab_or_program="Fralin Life Sciences Institute",
                    opportunity_type="research",
                    preferred_year=["freshman"],
                    keywords=["first-year research", "life sciences",
                              "faculty mentor", "fellowship"],
                ),
                program(
                    "vt_maop_sri",
                    "MAOP Undergraduate Summer Research Internship (SRI, Virginia Tech)",
                    "https://www.maop.vt.edu/scholarship-support-and-summer-programs/sri-program.html",
                    "A 10-week summer research internship run by Virginia "
                    "Tech's Mentorship & Academic Outreach Programs (MAOP). "
                    "Interns pursue a selected research project while building "
                    "professional and leadership skills through weekly "
                    "workshops; MAOP supports students committed to academic "
                    "excellence.",
                    lab_or_program="Mentorship & Academic Outreach Programs",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer internship", "mentorship",
                              "professional development", "access programs"],
                ),
                program(
                    "vt_our_student_funding",
                    "OUR Student Funding & Support (Virginia Tech)",
                    "https://www.research.undergraduate.vt.edu/funding-and-support/student-funding-and-support.html",
                    "The Office of Undergraduate Research's student funding hub "
                    "lists scholarships, a travel grant for presenting "
                    "research, free research poster printing, and work-study "
                    "research options, and links to college research grants "
                    "and Handshake for research positions.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["travel grant", "scholarships", "poster printing",
                              "research funding"],
                ),
                program(
                    "vt_hume_center",
                    "Hume Center for National Security and Technology (Virginia Tech)",
                    "https://hume.vt.edu/",
                    "The Hume Center leads the Virginia Tech National Security "
                    "Institute's education programs focused on cybersecurity, "
                    "autonomy, and resilience challenges for the national "
                    "security community. It offers student opportunities "
                    "including a seminar series and research programs.",
                    lab_or_program="Hume Center for National Security and Technology",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["national security", "cybersecurity", "autonomy",
                              "student programs"],
                ),
                program(
                    "vt_honors_college",
                    "Virginia Tech Honors College",
                    "https://honorscollege.vt.edu/",
                    "The Honors College is Virginia Tech's platform for "
                    "educational innovation, building on more than four decades "
                    "of honors education. It provides honors academics with "
                    "their own requirements and admission pathways, equipping "
                    "high-achieving students across all majors.",
                    lab_or_program="Honors College",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors", "academic enrichment", "interdisciplinary"],
                ),
            ],
        },
    ],
}
