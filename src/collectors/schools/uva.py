"""University of Virginia campus opportunity-graph config.

Curated seed records of UVA's undergraduate-research landscape, centered on
the Office of Undergraduate Research within the Office of Citizen Scholar
Development (undergraduateresearch.virginia.edu) — its grant portfolio
(Harrison Undergraduate Research Awards, Double Hoo, Kenan Award, the arts
project award) plus the USOAR faculty-matching program, the summer research
"Pizza & Posters" series, the URN conference grants, and the annual
Undergraduate Research Symposium. URLs verified live (headless render past the
Cloudflare interstitial) on 2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uva_research_programs (uva / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_UGR = "https://undergraduateresearch.virginia.edu"

SCHOOL: dict = {
    "school_slug": "uva",
    "organization": "University of Virginia",
    "location": "Charlottesville, VA",
    "emit": {
        "campus": ("uva_research_programs", "uva", "campus"),
    },
    "sources": [
        {
            "source_name": "uva_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergraduateresearch.virginia.edu/",
                "https://undergraduateresearch.virginia.edu/our-opportunities/grants",
            ],
            "programs": [
                program(
                    "uva_office_undergraduate_research",
                    "Office of Undergraduate Research (University of Virginia)",
                    "https://undergraduateresearch.virginia.edu/",
                    "UVA's Office of Undergraduate Research, part of the Office "
                    "of Citizen Scholar Development, is the central hub "
                    "connecting undergraduates to research across every school. "
                    "It administers the university's undergraduate research "
                    "grants, the USOAR faculty-matching program, summer "
                    "research programming, and the annual Undergraduate "
                    "Research Symposium.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research opportunities",
                              "mentorship", "citizen scholars"],
                ),
                program(
                    "uva_harrison_awards",
                    "Harrison Undergraduate Research Awards (University of Virginia)",
                    f"{_UGR}/our-opportunities/grants/harrison-undergraduate-research-awards",
                    "The Harrison Undergraduate Research Awards fund ambitious "
                    "student-designed research projects carried out under "
                    "faculty mentorship, typically over the summer and "
                    "following academic year. Awards provide a research stipend "
                    "plus project funds; recipients present at the UVA "
                    "Undergraduate Research Symposium.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Annual application cycle (fall/early winter).",
                    keywords=["research award", "faculty mentor", "stipend",
                              "self-designed project"],
                ),
                program(
                    "uva_double_hoo",
                    "Double Hoo Research Grant (University of Virginia)",
                    f"{_UGR}/our-opportunities/grants/double-hoo-award",
                    "The Double Hoo Award funds research partnerships that pair "
                    "an undergraduate with a graduate-student mentor on a shared "
                    "project, providing project funding plus a mentorship "
                    "stipend for the graduate partner. It is open to students "
                    "across all disciplines.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["graduate mentor", "research partnership",
                              "cross-disciplinary", "grant"],
                ),
                program(
                    "uva_usoar",
                    "USOAR — Undergraduate Student Opportunities in Academic Research (University of Virginia)",
                    f"{_UGR}/our-opportunities/usoar",
                    "USOAR helps undergraduates with little or no prior research "
                    "experience find and join a faculty research project. "
                    "Students browse posted opportunities and are matched with "
                    "faculty mentors who have agreed to take on undergraduate "
                    "researchers, lowering the barrier to a first research "
                    "position.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["first research experience", "faculty matching",
                              "getting started", "mentored research"],
                ),
                program(
                    "uva_kenan_award",
                    "Kenan Undergraduate Research Award (University of Virginia)",
                    f"{_UGR}/our-opportunities/grants/kenan-award",
                    "The Kenan Award provides funding for undergraduate research "
                    "projects conducted under faculty guidance, supporting "
                    "project expenses and, where applicable, a research stipend. "
                    "It complements the Harrison and Double Hoo grants in UVA's "
                    "undergraduate research funding portfolio.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research funding", "faculty mentor",
                              "project grant"],
                ),
                program(
                    "uva_arts_award",
                    "University Undergraduate Award for Projects in the Arts (University of Virginia)",
                    f"{_UGR}/our-opportunities/grants/university-undergraduate-award-arts-projects",
                    "This award funds undergraduate creative and scholarly "
                    "projects in the arts — studio art, music, drama, creative "
                    "writing, and related fields — supporting materials, "
                    "production, and presentation of original student work under "
                    "faculty mentorship.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["arts", "creative project", "studio",
                              "scholarly project"],
                ),
                program(
                    "uva_pizza_posters",
                    "Pizza & Posters Summer Research Series (University of Virginia)",
                    f"{_UGR}/our-opportunities/pizza-posters",
                    "Pizza & Posters is UVA's summer undergraduate research "
                    "community programming: a recurring series where students "
                    "conducting summer research share their work-in-progress, "
                    "practice presenting posters, and connect with peers and "
                    "mentors across disciplines.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "poster presentation",
                              "research community"],
                ),
                program(
                    "uva_urn_conference_grants",
                    "URN Conference Grants (University of Virginia)",
                    f"{_UGR}/urn-conference-grants",
                    "The Undergraduate Research Network conference grants help "
                    "UVA undergraduates cover the cost of traveling to and "
                    "presenting their research at academic and professional "
                    "conferences, extending mentored research into scholarly "
                    "dissemination.",
                    lab_or_program="Undergraduate Research Network",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "travel grant"],
                ),
                program(
                    "uva_research_symposium",
                    "Undergraduate Research Symposium (University of Virginia)",
                    f"{_UGR}/undergraduate-research-symposium",
                    "The annual Undergraduate Research Symposium is UVA's "
                    "campus-wide showcase where undergraduates from every school "
                    "present the results of their mentored research and creative "
                    "scholarship to the university community.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research symposium", "showcase",
                              "presentation", "capstone"],
                ),
            ],
        },
    ],
}
