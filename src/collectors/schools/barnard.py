"""Barnard College campus opportunity-graph config.

Curated seed records of Barnard's undergraduate-research and fellowship
landscape, centered on the college's flagship Summer Research Institute (SRI)
and its named STEM/leadership research programs and public-service fellowships.
All URLs curl-verified live (HTTP 200) on 2026-07-22.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → barnard_research_programs (barnard / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_BASE = "https://barnard.edu"

SCHOOL: dict = {
    "school_slug": "barnard",
    "organization": "Barnard College",
    "location": "New York, NY",
    "emit": {
        "campus": ("barnard_research_programs", "barnard", "campus"),
    },
    "sources": [
        {
            "source_name": "barnard_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_BASE}/undergraduate-research",
                f"{_BASE}/student-research-programs",
                f"{_BASE}/support-faculty-research",
            ],
            "programs": [
                program(
                    "barnard_sri",
                    "Barnard Summer Research Institute (SRI)",
                    f"{_BASE}/summer-research-institute",
                    "Barnard's flagship summer research program: a paid, full-"
                    "time ten-week experience in which students conduct original "
                    "research one-on-one with a Barnard or Columbia faculty "
                    "mentor across the sciences, social sciences, and humanities, "
                    "with a stipend and a culminating Lida Orzeck '68 poster "
                    "session.",
                    lab_or_program="Summer Research Institute",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "all disciplines"],
                ),
                program(
                    "barnard_sp2",
                    "Science Pathways Scholars Program (SP)² (Barnard)",
                    f"{_BASE}/science-pathways-scholars-program",
                    "A multi-year STEM research and mentoring program for Barnard "
                    "students from backgrounds underrepresented in the sciences, "
                    "providing mentored laboratory research, summer stipends, and "
                    "a cohort community that supports persistence toward science "
                    "careers and graduate study.",
                    lab_or_program="Science Pathways Scholars Program",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["STEM research", "mentoring", "diversity in science",
                              "laboratory research"],
                ),
                program(
                    "barnard_beckman",
                    "Beckman Scholars Program (Barnard)",
                    f"{_BASE}/beckman-scholars",
                    "A prestigious Arnold and Mabel Beckman Foundation program "
                    "funding an intensive, mentored 15-month research experience "
                    "in chemistry, biochemistry, biology, and the allied sciences "
                    "for a small cohort of Barnard scholars, including two "
                    "summers and an academic year of full-time laboratory "
                    "research with a substantial stipend.",
                    lab_or_program="Beckman Scholars Program",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["chemistry", "biochemistry", "mentored research",
                              "laboratory research"],
                ),
                program(
                    "barnard_laidlaw",
                    "Laidlaw Undergraduate Research and Leadership Scholars (Barnard)",
                    f"{_BASE}/laidlaw",
                    "A two-year, funded research-and-leadership scholarship in "
                    "which Barnard students design an independent summer research "
                    "project with a faculty mentor in year one and undertake a "
                    "leadership-in-action project in year two, joining a global "
                    "network of Laidlaw Scholars.",
                    lab_or_program="Laidlaw Scholars Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["independent research", "leadership", "faculty mentor",
                              "any discipline"],
                ),
                program(
                    "barnard_scholars_distinction",
                    "Scholars of Distinction (Barnard)",
                    f"{_BASE}/scholars-distinction",
                    "Barnard's umbrella of merit research and creative-work "
                    "scholar programs recognizing students who pursue sustained, "
                    "faculty-mentored scholarship and original projects across "
                    "the disciplines.",
                    lab_or_program="Scholars of Distinction",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    keywords=["mentored scholarship", "original research",
                              "creative work", "distinction"],
                ),
                program(
                    "barnard_tow",
                    "Tow Foundation Public Service Interns (Barnard)",
                    f"{_BASE}/beyond-barnard/tow-interns",
                    "Funded summer public-service internships administered by "
                    "Beyond Barnard, placing students with nonprofit, government, "
                    "and public-interest organizations and providing a stipend "
                    "that makes unpaid public-service work financially possible.",
                    lab_or_program="Tow Public Service Internships",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["public service", "nonprofit", "summer internship",
                              "stipend"],
                ),
                program(
                    "barnard_liman",
                    "Liman Fellowship Program (Barnard)",
                    f"{_BASE}/beyond-barnard/liman-fellowship-program",
                    "The Arthur Liman Public Interest Program summer fellowship, "
                    "funding a Barnard student to work in public-interest law and "
                    "social-justice organizations, with a stipend and mentoring "
                    "through the Liman network at Yale Law School.",
                    lab_or_program="Liman Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["public interest", "law", "social justice",
                              "summer fellowship"],
                ),
                program(
                    "barnard_zwas_gallen",
                    "Zwas Gallen Community Impact Interns (Barnard)",
                    f"{_BASE}/beyond-barnard/zwas-gallen-community-interns",
                    "A funded Beyond Barnard summer internship program supporting "
                    "students working on community-impact and social-good projects "
                    "with partner organizations, with a stipend for otherwise "
                    "unpaid roles.",
                    lab_or_program="Zwas Gallen Community Impact Internships",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["community impact", "social good", "summer internship",
                              "stipend"],
                ),
                program(
                    "barnard_postbac",
                    "Post-Baccalaureate Fellowship Program (Barnard)",
                    f"{_BASE}/beyond-barnard/post-baccalaureate-fellowship-program",
                    "A year-long post-graduation fellowship placing recent Barnard "
                    "graduates in mentored research, administrative, and program "
                    "roles across the college and affiliated organizations, "
                    "bridging undergraduate study and graduate or professional "
                    "careers.",
                    lab_or_program="Post-Baccalaureate Fellowship",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["senior"],
                    international_friendly="unknown",
                    keywords=["post-baccalaureate", "mentored role", "research",
                              "career development"],
                ),
            ],
        },
    ],
}
