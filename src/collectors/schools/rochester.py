"""University of Rochester campus opportunity-graph config.

Curated seed records of Rochester's undergraduate-research landscape, centered
on the Office of Undergraduate Research (its Discover Grant / RIG / RPA
funding routes and summer-programs hub), the Kearns Center's NSF REU + TRIO
McNair + Scholars pipeline, and the Laboratory for Laser Energetics' student
education programs. URLs verified live (HTTP 200) on 2026-07-17.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → rochester_research_programs (rochester / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "rochester",
    "organization": "University of Rochester",
    "location": "Rochester, NY",
    "emit": {
        "campus": ("rochester_research_programs", "rochester", "campus"),
    },
    "sources": [
        {
            "source_name": "rochester_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.rochester.edu/college/ugresearch/opportunities/summer.html",
                "https://www.rochester.edu/college/kearnscenter/undergraduate/reu/index.html",
                "https://www.lle.rochester.edu/education/",
            ],
            "programs": [
                program(
                    "schwartz_discover_grant",
                    "Schwartz Discover Grant for Undergraduate Summer Research (Rochester)",
                    "https://www.rochester.edu/college/ugresearch/funding/discover-grant/index.html",
                    "The Schwartz Discover Grant supports immersive, full-time "
                    "summer research experiences for University of Rochester "
                    "undergraduates in the School of Arts & Sciences, the Hajim "
                    "School of Engineering, and the Eastman School of Music. Its "
                    "stated goal is to help students get involved in research "
                    "early in their academic careers — the flagship internal "
                    "summer-research funding route run by the Office of "
                    "Undergraduate Research.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "research funding",
                              "undergraduate research", "stipend"],
                ),
                program(
                    "research_innovation_grant",
                    "Research and Innovation Grant (RIG) — University of Rochester",
                    "https://www.rochester.edu/college/ugresearch/funding/rig.html",
                    "Research and Innovation Grants are research awards attached "
                    "to admission — awarded only at the time of enrollment and "
                    "not applicable for later. RIG holders redeem the grant to "
                    "fund a research experience during their undergraduate "
                    "years; students without one are directed to the Discover "
                    "Grant for summer research or the College Supplemental Fund "
                    "for academic-year support.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["research grant", "merit award",
                              "undergraduate research"],
                ),
                program(
                    "research_presentation_award",
                    "Research Presentation Awards (RPA) — University of Rochester",
                    "https://www.rochester.edu/college/ugresearch/funding/rpa.html",
                    "Research Presentation Awards fund Rochester undergraduates "
                    "presenting their research at academic conferences, covering "
                    "conference registration, travel, lodging, and food. "
                    "Applications go through the Office of Undergraduate "
                    "Research — a natural follow-on for students whose lab or "
                    "independent work has produced presentable results.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Covers conference registration, travel, lodging, and food",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["conference travel", "research presentation",
                              "travel funding"],
                ),
                program(
                    "our_summer_research_hub",
                    "Office of Undergraduate Research — Summer Research and Internship Opportunities (Rochester)",
                    "https://www.rochester.edu/college/ugresearch/opportunities/summer.html",
                    "The Office of Undergraduate Research maintains this hub of "
                    "formal summer research programs, which generally run 10 "
                    "weeks, provide a stipend, and offer social activities and "
                    "exposure to another campus. It indexes both internal "
                    "Rochester programs and external opportunities at other "
                    "institutions, including abroad; the office itself is the "
                    "central advising point for getting into research.",
                    lab_or_program="Office of Undergraduate Research",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "internship", "REU", "stipend",
                              "research opportunities"],
                ),
                program(
                    "kearns_nsf_reu",
                    "NSF Research Experiences for Undergraduates at Rochester (Kearns Center)",
                    "https://www.rochester.edu/college/kearnscenter/undergraduate/reu/index.html",
                    "The Kearns Center coordinates NSF-funded REU programming at "
                    "the University of Rochester: paid, 10-week summer research "
                    "beginning in late May each year. Funding comes from the "
                    "National Science Foundation and eligibility extends to "
                    "undergraduates from any institution in the United States, "
                    "not just Rochester students — the university's front door "
                    "for REU-style summer research placements.",
                    lab_or_program="Kearns Center",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["NSF REU", "paid summer research",
                              "10-week program"],
                ),
                program(
                    "kearns_mcnair",
                    "Ronald E. McNair Post-Baccalaureate Achievement Program (Rochester TRIO)",
                    "https://www.rochester.edu/college/kearnscenter/undergraduate/mcnair.html",
                    "The TRIO Ronald E. McNair Program at the Kearns Center "
                    "prepares eligible undergraduates for doctoral study through "
                    "research experiences and scholarly support, honoring the "
                    "Challenger astronaut it is named for. It targets "
                    "first-generation, low-income, and underrepresented students "
                    "and pairs them with faculty-mentored research — a standard "
                    "on-ramp to PhD-track research for eligible students.",
                    lab_or_program="Kearns Center",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["McNair", "TRIO", "PhD preparation",
                              "faculty-mentored research", "first-generation"],
                ),
                program(
                    "kearns_scholars",
                    "Kearns Center Scholars Program (Rochester)",
                    "https://www.rochester.edu/college/kearnscenter/undergraduate/scholars.html",
                    "The Kearns Scholars Program supports first-generation "
                    "college students toward graduation and beyond through a "
                    "combination of services including open academic advising. "
                    "It sits alongside the Kearns Center's McNair, SSS, and NSF "
                    "REU programming as the center's core undergraduate support "
                    "track, and Kearns Scholars are a primary pipeline into the "
                    "center's summer research awards.",
                    lab_or_program="Kearns Center",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["first-generation", "scholars program",
                              "academic support", "research pipeline"],
                ),
                program(
                    "lle_undergraduate_education",
                    "Laboratory for Laser Energetics — Student Education Programs (Rochester)",
                    "https://www.lle.rochester.edu/education/",
                    "The Laboratory for Laser Energetics, a national resource on "
                    "Rochester's south campus, brings high school, "
                    "undergraduate, and graduate students to work with mentors "
                    "across inertial confinement fusion, high-energy-density "
                    "physics, laser-plasma interaction, laser and optics "
                    "sciences, and laser technology. LLE has run education "
                    "programs since its founding in 1970 and employs "
                    "undergraduates in real research roles on one of the "
                    "world's most powerful laser facilities.",
                    lab_or_program="Laboratory for Laser Energetics",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["laser physics", "fusion",
                              "high-energy-density physics", "optics",
                              "national lab"],
                ),
            ],
        },
    ],
}
