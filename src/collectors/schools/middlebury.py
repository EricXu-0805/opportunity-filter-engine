"""Middlebury College campus opportunity-graph config.

Curated seed records of Middlebury's undergraduate-research and fellowship
landscape, anchored on the Center for Teaching, Learning, and Research (CTLR),
which runs Undergraduate Research at Middlebury: getting started with a faculty
mentor, summer research assistantships, research-funding grants, and the Spring
Student Symposium where students present their work. Rounded out by the CTLR
nationally-competitive fellowships office, the Molecular Biology & Biochemistry
summer research program, the Franklin Environmental Center's Climate Action
Fellowship, the Privilege & Poverty academic cluster, and the Center for Social
Entrepreneurship fellowship. All URLs verified live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → middlebury_research_programs (middlebury / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_TLR = "https://www.middlebury.edu/teaching-learning-research"
_UGR = f"{_TLR}/student-resources/undergraduate-research"

SCHOOL: dict = {
    "school_slug": "middlebury",
    "organization": "Middlebury College",
    "location": "Middlebury, VT",
    "emit": {
        "campus": ("middlebury_research_programs", "middlebury", "campus"),
    },
    "sources": [
        {
            "source_name": "middlebury_ctlr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _UGR,
                f"{_UGR}/summer",
                f"{_TLR}/student-resources/fellowships",
                f"{_TLR}/spring-student-symposium",
            ],
            "programs": [
                program(
                    "ugr_hub",
                    "Undergraduate Research at Middlebury (CTLR)",
                    _UGR,
                    "The Center for Teaching, Learning, and Research is Middlebury's "
                    "front door to faculty-mentored undergraduate research across every "
                    "discipline — it helps students find a mentor and a project, funds "
                    "research, and showcases results at the Spring Student Symposium. "
                    "Start here to get connected to a faculty research lab.",
                    lab_or_program="CTLR Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "faculty mentorship"],
                ),
                program(
                    "ugr_get_started",
                    "Get Started in Undergraduate Research (Middlebury CTLR)",
                    f"{_UGR}/get-started",
                    "A step-by-step guide for Middlebury students on how to approach a "
                    "professor, join a research group, and shape an independent or "
                    "collaborative research project — the practical on-ramp into a lab "
                    "for students with no prior research experience.",
                    lab_or_program="CTLR Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["getting started", "research mentorship"],
                ),
                program(
                    "ugr_summer",
                    "Summer Undergraduate Research (Middlebury)",
                    f"{_UGR}/summer",
                    "Middlebury funds a full-time summer of faculty-mentored research on "
                    "campus, with a stipend and (typically) housing, across the sciences, "
                    "social sciences, arts, and humanities. Students apply with a faculty "
                    "mentor for a summer research assistantship.",
                    lab_or_program="Summer Undergraduate Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "stipend"],
                ),
                program(
                    "ugr_funding",
                    "Undergraduate Research Funding & Grants (Middlebury CTLR)",
                    f"{_UGR}/apply-funding",
                    "CTLR research grants support Middlebury undergraduates pursuing "
                    "mentored or independent research: senior-thesis project supplements, "
                    "conference travel, and academic-year and summer research funds. Apply "
                    "with a faculty advisor to fund an existing research project.",
                    lab_or_program="CTLR Undergraduate Research Funding",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research funding", "grants"],
                ),
                program(
                    "spring_symposium",
                    "Spring Student Symposium (Middlebury)",
                    f"{_TLR}/spring-student-symposium",
                    "The college-wide Spring Student Symposium is Middlebury's annual "
                    "celebration of student research and creative work, where "
                    "undergraduates present posters, talks, and performances from their "
                    "faculty-mentored projects. A capstone venue for sharing research.",
                    lab_or_program="Spring Student Symposium",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research symposium", "presenting research"],
                ),
                program(
                    "ctlr_fellowships",
                    "Nationally Competitive Fellowships (Middlebury CTLR)",
                    f"{_TLR}/student-resources/fellowships",
                    "The CTLR fellowships office advises Middlebury students and alumni "
                    "on nationally competitive fellowships and scholarships — Fulbright, "
                    "Goldwater, Watson, and more — including research-based awards that "
                    "fund graduate study and independent projects.",
                    lab_or_program="CTLR Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["fellowships", "scholarships"],
                ),
                program(
                    "mbb_summer_research",
                    "Molecular Biology & Biochemistry Summer Research (Middlebury)",
                    "https://www.middlebury.edu/college/academics/"
                    "molecular-biology-biochemistry/resources",
                    "The Molecular Biology & Biochemistry program runs a summer research "
                    "cohort in which students work full-time in a faculty member's lab on "
                    "cell, molecular, and biochemical research, with a stipend and a "
                    "culminating summer research presentation.",
                    lab_or_program="MBB Summer Research",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Molecular Biology and Biochemistry",
                                        "Biology", "Chemistry", "Biochemistry"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "molecular biology"],
                ),
                program(
                    "climate_action_fellowship",
                    "Climate Action Fellowship — Franklin Environmental Center (Middlebury)",
                    "https://www.middlebury.edu/sustainability-environmental-affairs/"
                    "get-involved/climate-action-program/climate-action-fellowship",
                    "The Franklin Environmental Center's Climate Action Fellowship funds "
                    "students to work on applied climate and sustainability projects — "
                    "summer and academic-year — pairing environmental research and "
                    "practice with campus and community partners.",
                    lab_or_program="Climate Action Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    eligibility_majors=["Environmental Studies"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["climate action", "sustainability"],
                ),
                program(
                    "social_entrepreneurship",
                    "Center for Social Entrepreneurship Fellowship (Middlebury)",
                    "https://www.middlebury.edu/social-entrepreneurship",
                    "The Center for Social Entrepreneurship runs a fellowship supporting "
                    "students who design and launch ventures and applied projects tackling "
                    "social and environmental problems, with mentorship, funding, and a "
                    "summer program.",
                    lab_or_program="Center for Social Entrepreneurship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["social entrepreneurship", "applied projects"],
                ),
            ],
        },
    ],
}
