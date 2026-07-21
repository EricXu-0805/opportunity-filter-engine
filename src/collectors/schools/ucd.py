"""University of California, Davis campus opportunity-graph config.

Curated seed records of UC Davis's undergraduate-research landscape, centered
on the Undergraduate Research Center (urc.ucdavis.edu) — its Provost's
Undergraduate Fellowship, travel awards, and the annual Undergraduate Research
Conference — plus the center's federally- and privately-funded scholar
pipelines (McNair, UC LEADS, Beckman, MURALS/MURPPS). Program URLs confirmed
from the URC sitemap 2026-07-21 (the pages themselves sit behind UC Davis's
Cloudflare wall, so campus_graph's seed fetch degrades to curated-only — the
program records still emit; see ucd_faculty for the WAF write-up).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ucd_research_programs (ucd / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "ucd",
    "organization": "University of California, Davis",
    "location": "Davis, CA",
    "emit": {
        "campus": ("ucd_research_programs", "ucd", "campus"),
    },
    "sources": [
        {
            "source_name": "ucd_urc_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://urc.ucdavis.edu/research-awards",
                "https://urc.ucdavis.edu/conference",
                "https://urc.ucdavis.edu/programs",
            ],
            "programs": [
                program(
                    "puf_research_award",
                    "Provost's Undergraduate Fellowship (PUF) — UC Davis",
                    "https://urc.ucdavis.edu/research-awards",
                    "The Provost's Undergraduate Fellowship is UC Davis's "
                    "flagship undergraduate research award, administered by the "
                    "Undergraduate Research Center. It funds student-initiated, "
                    "faculty-mentored research, scholarship, and creative "
                    "projects across every discipline, covering supplies, "
                    "travel, and related project costs. PUF is the central "
                    "internal funding route for Davis undergraduates starting "
                    "their own research.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["undergraduate research", "research funding",
                              "faculty-mentored", "any discipline"],
                ),
                program(
                    "urc_travel_awards",
                    "Undergraduate Research Travel Awards — UC Davis",
                    "https://urc.ucdavis.edu/travel-awards",
                    "The Undergraduate Research Center's travel awards fund UC "
                    "Davis undergraduates presenting their research at "
                    "professional and academic conferences, offsetting "
                    "registration, transportation, and lodging. A natural "
                    "follow-on once a student's mentored project has "
                    "presentable results.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Conference registration, travel, and lodging",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "travel funding"],
                ),
                program(
                    "urc_conference",
                    "UC Davis Undergraduate Research, Scholarship and Creative Activities Conference",
                    "https://urc.ucdavis.edu/conference",
                    "The annual URC Conference is UC Davis's campus-wide venue "
                    "for undergraduates to present faculty-mentored research and "
                    "creative work as oral, poster, visual, and performance "
                    "presentations. Open across all disciplines, it is the "
                    "culminating showcase the URC's funding and scholar programs "
                    "feed into each spring.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["research conference", "poster presentation",
                              "oral presentation"],
                ),
                program(
                    "mcnair_scholars",
                    "Ronald E. McNair Scholars Program — UC Davis",
                    "https://urc.ucdavis.edu/mcnair-scholars-program",
                    "The TRIO McNair Scholars Program at UC Davis prepares "
                    "first-generation, low-income, and underrepresented "
                    "undergraduates for doctoral study through faculty-mentored "
                    "research, graduate-school preparation, and a funded summer "
                    "research experience. A standard on-ramp to PhD-track "
                    "research for eligible students.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["McNair", "TRIO", "PhD preparation",
                              "first-generation", "faculty-mentored research"],
                ),
                program(
                    "uc_leads",
                    "UC LEADS — Leadership Excellence through Advanced Degrees (UC Davis)",
                    "https://urc.ucdavis.edu/uc-leads",
                    "UC LEADS identifies upper-division students in science, "
                    "engineering, and mathematics with the potential to succeed "
                    "in doctoral programs, pairing them with two years of "
                    "mentored research (including a funded summer at another UC "
                    "campus), graduate-school preparation, and a stipend. Aimed "
                    "at students who have experienced barriers to advanced "
                    "education.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["STEM", "PhD preparation", "mentored research",
                              "summer research", "stipend"],
                ),
                program(
                    "beckman_scholars",
                    "Beckman Scholars Program — UC Davis",
                    "https://urc.ucdavis.edu/beckman-scholars",
                    "The Arnold and Mabel Beckman Foundation's Beckman Scholars "
                    "Program funds an intensive, ~15-month mentored research "
                    "experience for a small cohort of UC Davis undergraduates in "
                    "chemistry, biochemistry, and the biological and medical "
                    "sciences, with a substantial stipend across two summers and "
                    "the intervening academic year.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="research",
                    paid="stipend",
                    eligibility_majors=["Chemistry", "Biochemistry", "Biology"],
                    preferred_year=["sophomore", "junior"],
                    keywords=["Beckman", "chemistry", "biochemistry",
                              "mentored research", "stipend"],
                ),
                program(
                    "murals_mentorship",
                    "Mentorship for Undergraduate Research in Psychology, Public and Prevention Sciences (MURPPS) — UC Davis",
                    "https://urc.ucdavis.edu/murpps",
                    "MURPPS pairs UC Davis undergraduates with graduate-student "
                    "and faculty mentors for research in psychology and the "
                    "public and prevention sciences, building research skills "
                    "and graduate-school readiness for students from groups "
                    "underrepresented in the field.",
                    lab_or_program="Undergraduate Research Center",
                    opportunity_type="research",
                    eligibility_majors=["Psychology"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["psychology", "mentorship", "research skills",
                              "underrepresented"],
                ),
            ],
        },
    ],
}
