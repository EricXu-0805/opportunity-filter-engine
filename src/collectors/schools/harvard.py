"""Harvard University campus opportunity-graph config.

Curated seed records of Harvard's undergraduate-research landscape, centered
on URAF (the Office of Undergraduate Research and Fellowships) and its funded
programs — HCRP term-time/summer grants, the residential Summer Research
Village programs (PRISE, SHARP and siblings), Herchel Smith, Amgen Scholars —
plus the SEAS REU. URLs verified live (HTTP 200) on 2026-07-15. BLISS's
standalone page 403s (it lives inside the HSURV umbrella) and the Mindich
engaged-scholarship page is gone — neither is wired.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → harvard_research_programs (harvard / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "harvard",
    "organization": "Harvard University",
    "location": "Cambridge, MA",
    "emit": {
        "campus": ("harvard_research_programs", "harvard", "campus"),
    },
    "sources": [
        {
            "source_name": "harvard_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://uraf.harvard.edu/",
                "https://uraf.harvard.edu/summer-research-programs",
                "https://seas.harvard.edu/office-education-outreach-community-programs/research-experience-undergraduates-reu/program-details",
            ],
            "programs": [
                program(
                    "uraf_hub",
                    "URAF — Office of Undergraduate Research and Fellowships (Harvard)",
                    "https://uraf.harvard.edu/",
                    "URAF is Harvard College's central office for undergraduate "
                    "research and national fellowships: research funding and "
                    "advising across every concentration, the summer research "
                    "village, and fellowship advising (Rhodes/Marshall-track). "
                    "The front door to getting funded research at Harvard.",
                    lab_or_program="URAF",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "research funding", "fellowships"],
                ),
                program(
                    "hcrp",
                    "HCRP — Harvard College Research Program",
                    "https://uraf.harvard.edu/hcrp",
                    "HCRP awards merit-based funding for student-initiated "
                    "independent research — term-time and summer — conducted "
                    "with a Harvard-affiliated faculty mentor, across all "
                    "fields. The standard first grant for a student starting "
                    "research at Harvard.",
                    lab_or_program="HCRP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "independent research", "faculty mentorship"],
                ),
                program(
                    "prise",
                    "PRISE — Program for Research in Science and Engineering (Harvard)",
                    "https://uraf.harvard.edu/prise",
                    "PRISE is Harvard's residential summer research community "
                    "for undergraduates in the life, physical/natural, "
                    "engineering, and applied sciences — students conduct "
                    "full-time lab research while living together with weekly "
                    "faculty talks and a capstone symposium.",
                    lab_or_program="PRISE",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "science", "residential community"],
                ),
                program(
                    "sharp",
                    "SHARP — Summer Humanities and Arts Research Program (Harvard)",
                    "https://uraf.harvard.edu/sharp",
                    "SHARP is the humanities-and-arts sibling of PRISE: a "
                    "residential summer program funding full-time undergraduate "
                    "research projects across the arts and humanities with "
                    "faculty and curatorial mentors.",
                    lab_or_program="SHARP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["humanities research", "arts", "summer program"],
                ),
                program(
                    "hsurv",
                    "HSURV — Harvard Summer Undergraduate Research Village",
                    "https://uraf.harvard.edu/summer-research-programs",
                    "The Summer Research Village is the umbrella for Harvard's "
                    "residential summer research programs — PRISE, SHARP, "
                    "BLISS (behavioral/social sciences), SURGH (global health), "
                    "SPUDS (data science), and PCER (education research) — one "
                    "application window, one residential community.",
                    lab_or_program="Summer Research Village",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "residential", "BLISS", "SURGH"],
                ),
                program(
                    "herchel_smith",
                    "Herchel Smith–Harvard Undergraduate Science Research Program",
                    "https://uraf.harvard.edu/herchel-smith-summer-program",
                    "The Herchel Smith program funds Harvard undergraduates for "
                    "full-time summer research in mathematics, engineering, and "
                    "the sciences — generous support for ambitious "
                    "student-designed or lab-based projects, at Harvard or "
                    "beyond.",
                    lab_or_program="Herchel Smith Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["science research", "summer funding"],
                ),
                program(
                    "amgen_harvard",
                    "Amgen Scholars Program at Harvard",
                    "https://uraf.harvard.edu/amgen-scholars",
                    "Harvard's Amgen Scholars site places undergraduates in "
                    "Harvard-affiliated labs for a 10-week funded summer of "
                    "biotech and science research, aimed at students headed "
                    "for PhD or MD-PhD training, with faculty seminars and the "
                    "national Amgen symposium.",
                    lab_or_program="Amgen Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["biotechnology", "summer research", "PhD pipeline"],
                ),
                program(
                    "seas_reu",
                    "SEAS REU — Research Experience for Undergraduates (Harvard)",
                    "https://seas.harvard.edu/office-education-outreach-community-programs/research-experience-undergraduates-reu/program-details",
                    "Harvard SEAS hosts an NSF-style summer Research Experience "
                    "for Undergraduates: full-time engineering and applied-"
                    "science research in SEAS labs with faculty seminars, "
                    "professional development, and a closing symposium.",
                    lab_or_program="SEAS REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    eligibility_majors=["Computer Science", "Electrical Engineering",
                                        "Bioengineering", "Applied Mathematics"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["REU", "engineering research", "summer program"],
                ),
            ],
        },
    ],
}
