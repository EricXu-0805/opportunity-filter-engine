"""Colgate University campus opportunity-graph config.

Curated seed records of Colgate's undergraduate-research and scholars landscape,
centered on the college's flagship Summer Research and Creative Projects program
(roughly 200 students working full-time with faculty each summer) and its named
endowed institutes and scholars programs: the Picker Interdisciplinary Science
Institute, the Lampert Institute for Civic and Global Affairs, the Upstate
Institute (community-based research fellowships), the Lampert Scholars, the
Alumni Memorial Scholars, the Benton Scholars, the Sophomore Residential
Seminars, and the NSF Research Experiences for Undergraduates (REU) portal.
All URLs curl-verified live (HTTP 200) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → colgate_research_programs (colgate / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_RS = "https://www.colgate.edu/academics/research-scholarship"
_SP = "https://www.colgate.edu/academics/scholars-programs"
_IAS = "https://www.colgate.edu/academics/institutes-advanced-study"

SCHOOL: dict = {
    "school_slug": "colgate",
    "organization": "Colgate University",
    "location": "Hamilton, NY",
    "emit": {
        "campus": ("colgate_research_programs", "colgate", "campus"),
    },
    "sources": [
        {
            "source_name": "colgate_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _RS,
                _SP,
                _IAS,
            ],
            "programs": [
                program(
                    "colgate_summer_research",
                    "Summer Research and Creative Projects (Colgate)",
                    f"{_RS}/summer-research-and-creative-projects",
                    "Colgate's flagship summer program: each summer roughly 200 "
                    "undergraduates work directly and full-time with faculty "
                    "members on collaborative research and creative projects "
                    "across every division, supported by a stipend and campus "
                    "housing, culminating in a fall research showcase.",
                    lab_or_program="Summer Research and Creative Projects",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "any discipline"],
                ),
                program(
                    "colgate_picker",
                    "Picker Interdisciplinary Science Institute (Colgate)",
                    f"{_IAS}/picker-interdisciplinary-science-institute",
                    "The Picker Institute funds and coordinates interdisciplinary "
                    "collaborative research across the natural sciences and "
                    "mathematics, supporting student-faculty research teams, "
                    "shared instrumentation, and summer science fellowships.",
                    lab_or_program="Picker Interdisciplinary Science Institute",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["interdisciplinary science", "faculty mentor",
                              "laboratory research", "STEM"],
                ),
                program(
                    "colgate_upstate_institute",
                    "Upstate Institute Summer Field School (Colgate)",
                    f"{_IAS}/upstate-institute",
                    "The Upstate Institute places students in paid summer "
                    "community-based research fellowships with nonprofit and "
                    "civic organizations across Upstate New York, advancing "
                    "understanding of the region's cultural, social, economic, "
                    "and environmental resources through engaged scholarship.",
                    lab_or_program="Upstate Institute",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["community-based research", "civic engagement",
                              "summer fellowship", "Upstate New York"],
                ),
                program(
                    "colgate_lampert_institute",
                    "Lampert Institute for Civic and Global Affairs (Colgate)",
                    f"{_IAS}/lampert-institute-civic-and-global-affairs",
                    "The Lampert Institute supports student research, internships, "
                    "and policy engagement on pressing civic and global-affairs "
                    "questions, connecting students with faculty and outside "
                    "practitioners.",
                    lab_or_program="Lampert Institute for Civic and Global Affairs",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["public policy", "civic engagement",
                              "global affairs", "research"],
                ),
                program(
                    "colgate_lampert_scholars",
                    "Lampert Scholars (Colgate)",
                    f"{_RS}/lampert-scholars",
                    "A year-long senior scholars program of integrated "
                    "intellectual and professional activities engaging students "
                    "with complex policy issues through close interaction with "
                    "faculty and outside experts and a capstone research project.",
                    lab_or_program="Lampert Scholars",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["senior"],
                    international_friendly="yes",
                    keywords=["policy research", "faculty mentor",
                              "capstone", "scholars program"],
                ),
                program(
                    "colgate_alumni_memorial_scholars",
                    "Alumni Memorial Scholars (Colgate)",
                    f"{_SP}/alumni-memorial-scholars",
                    "Colgate's premier merit scholars program: selected students "
                    "receive dedicated funding for a self-designed independent "
                    "research, creative, or experiential project undertaken with "
                    "faculty guidance, typically over the summer.",
                    lab_or_program="Alumni Memorial Scholars",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["independent research", "merit scholarship",
                              "self-designed project", "faculty mentor"],
                ),
                program(
                    "colgate_benton_scholars",
                    "Benton Scholars (Colgate)",
                    f"{_SP}/benton-scholars",
                    "A cohort-based scholars program for exceptional students "
                    "featuring a globally focused curriculum, shared travel, and "
                    "faculty-mentored inquiry into global leadership and complex "
                    "world problems.",
                    lab_or_program="Benton Scholars",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["global studies", "cohort program",
                              "faculty mentor", "leadership"],
                ),
                program(
                    "colgate_sophomore_seminars",
                    "Sophomore Residential Seminars Program (Colgate)",
                    f"{_RS}/sophomore-residential-seminars-program",
                    "A residential program pairing sophomores in small "
                    "faculty-led seminars with co-curricular research and "
                    "creative activities that extend classroom inquiry into "
                    "mentored scholarly projects.",
                    lab_or_program="Sophomore Residential Seminars",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore"],
                    international_friendly="yes",
                    keywords=["faculty seminar", "residential program",
                              "mentored research", "sophomore"],
                ),
                program(
                    "colgate_nsf_reu",
                    "NSF Research Experiences for Undergraduates (REU) (Colgate)",
                    "https://www.nsf.gov/crssprgm/reu/",
                    "The National Science Foundation's REU program funds "
                    "full-time summer research placements at host sites "
                    "nationwide across the sciences, mathematics, and "
                    "engineering; Colgate students in the natural sciences "
                    "regularly compete for these externally funded positions.",
                    lab_or_program="NSF REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["NSF", "summer research", "STEM",
                              "national program"],
                ),
            ],
        },
    ],
}
