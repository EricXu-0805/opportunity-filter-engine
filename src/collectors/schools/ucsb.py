"""UC Santa Barbara campus opportunity-graph config (third UC-system rollout).

Curated seed records of UCSB's undergraduate-research landscape: the
Undergraduate Research & Creative Activities office (URCA) and its grant,
journal, and colloquium; the Faculty Research Assistance Program (which funds
undergraduate RAs); McNair Scholars; the Center for Science and Engineering
Partnerships (CSEP) STEM programs (EUREKA, MARC, SIMS, Gorman Scholars); the
College of Engineering / College of Creative Studies undergraduate-research
pages; the Materials Research Laboratory RISE internships; and CNSI. Cal-Bridge
is a statewide external consortium (emitted open). URLs verified HTTP-200
(Jul 2026). The high-school Research Mentorship Program and the graduate Bren
School are left out (not undergraduate research).

Emit buckets → (source, school, audience), in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → ucsb_research_programs (ucsb / campus)
    open   → ucsb_external_research (national / open)
    lab    → ucsb_labs              (ucsb / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    DEPARTMENT,
    LAB,
    PROGRAM,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "ucsb",
    "organization": "University of California, Santa Barbara",
    "location": "Santa Barbara, CA",
    "emit": {
        "campus": ("ucsb_research_programs", "ucsb", "campus"),
        "open": ("ucsb_external_research", None, "open"),
        "lab": ("ucsb_labs", "ucsb", "unknown"),
    },
    "sources": [
        {
            "source_name": "ucsb_urca_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": ["https://urca.ucsb.edu/", "https://undergrad.research.ucsb.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "urca_hub",
                    "Undergraduate Research & Creative Activities (URCA) — UC Santa Barbara",
                    "https://urca.ucsb.edu/",
                    "URCA is UC Santa Barbara's campus-wide hub for undergraduate "
                    "research and creative work: grants, the getting-started guides, "
                    "the URCA journal, and the annual poster colloquium. Start here to "
                    "find faculty-mentored research across every major.",
                    lab_or_program="URCA",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "creative activities", "mentorship"],
                ),
                program(
                    "urca_grant",
                    "URCA Grant (UC Santa Barbara)",
                    "https://urca.ucsb.edu/urca-grant/overview",
                    "A competitive funding award for UCSB undergraduates to pursue "
                    "faculty-mentored research or creative projects, plus the "
                    "Chancellor's Award and Hanson Family conference-travel grants.",
                    lab_or_program="URCA",
                    paid="yes",
                    international_friendly="yes",
                    keywords=["research grant", "funding"],
                ),
                program(
                    "urca_frap",
                    "Faculty Research Assistance Program (FRAP) — UC Santa Barbara",
                    "https://urca.ucsb.edu/faculty/frap-grants",
                    "URCA grants to faculty that fund undergraduate research-assistant "
                    "positions — a route into a lab where the RA role is paid through "
                    "the professor's FRAP award.",
                    lab_or_program="URCA",
                    paid="yes",
                    keywords=["research assistant", "faculty-funded"],
                ),
                program(
                    "urca_colloquium",
                    "URCA Poster Colloquium (UC Santa Barbara)",
                    "https://urca.ucsb.edu/urca-week/poster-colloquium",
                    "The annual campus-wide undergraduate research poster showcase "
                    "during URCA Week — a venue to present mentored research and join "
                    "the research community.",
                    lab_or_program="URCA",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["poster colloquium", "presentation"],
                ),
                program(
                    "mcnair",
                    "McNair Scholars Program (UC Santa Barbara)",
                    "https://mcnair.ucsb.edu/",
                    "A federal TRIO program preparing first-generation and "
                    "underrepresented undergraduates for doctoral study through "
                    "mentored research, including a stipend-bearing summer component.",
                    lab_or_program="McNair Scholars",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    keywords=["doctoral preparation", "mentored research"],
                ),
            ],
        },
        {
            "source_name": "ucsb_csep_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://csep.cnsi.ucsb.edu/", "https://csep.cnsi.ucsb.edu/programs"],
            "crawl": STATIC,
            "programs": [
                program(
                    "csep_hub",
                    "Center for Science & Engineering Partnerships (CSEP) — UC Santa Barbara",
                    "https://csep.cnsi.ucsb.edu/",
                    "A CNSI-based hub that coordinates UCSB's STEM undergraduate "
                    "research and access programs — EUREKA, MARC, SIMS, Gorman "
                    "Scholars, LSAMP, and apprentice-researcher tracks.",
                    lab_or_program="CSEP",
                    keywords=["STEM research", "undergraduate programs"],
                ),
                program(
                    "eureka",
                    "EUREKA! Scholars — Summer Research (UC Santa Barbara)",
                    "https://csep.cnsi.ucsb.edu/node/273",
                    "A paid summer research internship for UCSB undergraduates in "
                    "science and engineering, run through CSEP.",
                    lab_or_program="CSEP",
                    opportunity_type="summer_program",
                    paid="yes",
                    preferred_year=["sophomore", "junior"],
                    keywords=["summer research", "STEM"],
                ),
                program(
                    "marc",
                    "MARC Scholars — Maximizing Access to Research Careers (UC Santa Barbara)",
                    "https://csep.cnsi.ucsb.edu/marc",
                    "An NIH-funded program training UCSB undergraduates for biomedical "
                    "PhD study through mentored research and a stipend.",
                    lab_or_program="CSEP",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    keywords=["biomedical research", "NIH"],
                ),
                program(
                    "gorman",
                    "Gorman Scholars Program (UC Santa Barbara)",
                    "https://csep.cnsi.ucsb.edu/node/476",
                    "An academic-year plus 8-week summer mentored-research program for "
                    "UCSB STEM undergraduates in their first three years; ~$3,500 "
                    "summer stipend.",
                    lab_or_program="CSEP",
                    paid="yes",
                    compensation="~$3,500 summer stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["mentored research", "STEM"],
                ),
                program(
                    "sims",
                    "Summer Institute in Mathematics & Science (SIMS) — UC Santa Barbara",
                    "https://csep.cnsi.ucsb.edu/sims",
                    "A summer bridge program preparing incoming UCSB STEM students for "
                    "research and coursework, run through CSEP.",
                    lab_or_program="CSEP",
                    opportunity_type="summer_program",
                    preferred_year=["freshman"],
                    keywords=["summer bridge", "STEM preparation"],
                ),
            ],
        },
        {
            "source_name": "ucsb_college_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://engineering.ucsb.edu/undergraduate/undergraduate-research",
                "https://duels.ucsb.edu/",
                "https://www.ccs.ucsb.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "engineering_ugresearch",
                    "College of Engineering — Undergraduate Research (UC Santa Barbara)",
                    "https://engineering.ucsb.edu/undergraduate/undergraduate-research",
                    "The Robert Mehrabian College of Engineering undergraduate-research "
                    "landing page: how to find a faculty lab and the college's research "
                    "centers that take undergraduates.",
                    department="Engineering",
                    keywords=["engineering research"],
                ),
                program(
                    "duels",
                    "L&S Division of Undergraduate Education (DUELS) — UC Santa Barbara",
                    "https://duels.ucsb.edu/",
                    "The College of Letters & Science undergraduate-education division "
                    "(Math/Life/Physical Sciences and Humanities/Social Sciences) — "
                    "advising and the programs that route students into research.",
                    department="Letters & Science",
                    keywords=["undergraduate education", "advising"],
                ),
                program(
                    "ccs",
                    "College of Creative Studies (CCS) — UC Santa Barbara",
                    "https://www.ccs.ucsb.edu/",
                    "UCSB's research-forward small undergraduate college, where students "
                    "begin original research and creative work early across eight "
                    "majors in the sciences and arts.",
                    department="Creative Studies",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["original research", "creative studies"],
                ),
            ],
        },
        {
            "source_name": "ucsb_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.mrl.ucsb.edu/education/undergraduate-opportunities/rise",
                "https://www.cnsi.ucsb.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "mrl_rise",
                    "Materials Research Laboratory — RISE Internships (UC Santa Barbara)",
                    "https://www.mrl.ucsb.edu/education/undergraduate-opportunities/rise",
                    "The NSF-funded MRL's RISE research internships for UCSB "
                    "undergraduates — a ~$6,000 summer stipend plus $500–1,000 per "
                    "quarter during the academic year.",
                    lab_or_program="Materials Research Laboratory",
                    opportunity_type="summer_program",
                    paid="yes",
                    compensation="~$6,000 summer stipend; $500–1,000/quarter academic year",
                    preferred_year=["sophomore", "junior"],
                    keywords=["materials research", "summer internship"],
                ),
                program(
                    "cnsi",
                    "California NanoSystems Institute (CNSI) — UC Santa Barbara",
                    "https://www.cnsi.ucsb.edu/",
                    "A nanoscience research institute at UCSB that houses CSEP and its "
                    "undergraduate research programs across nanotechnology, materials, "
                    "and bioengineering.",
                    lab_or_program="CNSI",
                    keywords=["nanoscience", "nanotechnology"],
                ),
            ],
        },
        {
            "source_name": "ucsb_external",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": ["https://www.cal-bridge.org/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "cal_bridge",
                    "Cal-Bridge — Physics, Astronomy & Computing PhD Pathway",
                    "https://www.cal-bridge.org/",
                    "A statewide CSU/UC/community-college scholarship and mentoring "
                    "consortium moving underrepresented students into physics, "
                    "astronomy, and computer-science PhD programs. UC Santa Barbara is "
                    "a partner campus; open to students across California.",
                    lab_or_program="Cal-Bridge",
                    paid="yes",
                    preferred_year=["sophomore", "junior"],
                    keywords=["physics", "astronomy", "doctoral pathway"],
                ),
            ],
        },
    ],
}
