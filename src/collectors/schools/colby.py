"""Colby College campus opportunity-graph config.

Curated seed records of Colby's undergraduate-research landscape, centered on
the college's flagship summer research program (the Colby Undergraduate Summer
Research Retreat on Mayflower Hill) and its named scholar programs, the
year-long Senior Scholars independent-research capstone, the Colby Achievement
Program in the Sciences early-research bridge, the Colby Liberal Arts Symposium
showcase, and the DavisConnects funding portal. Program URLs were verified live
on 2026-07-23 via a single headless render (the colby.edu site is fully
Cloudflare-walled to plain HTTP requests, so plain curl returns a 403
interstitial; the rendered pages resolve to real 200s).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> colby_research_programs (colby / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_RES = "https://www.colby.edu/academics/research"

SCHOOL: dict = {
    "school_slug": "colby",
    "organization": "Colby College",
    "location": "Waterville, ME",
    "emit": {
        "campus": ("colby_research_programs", "colby", "campus"),
    },
    "sources": [
        {
            "source_name": "colby_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.colby.edu/research/",
                f"{_RES}/",
            ],
            "programs": [
                program(
                    "colby_cusrr",
                    "Colby Undergraduate Summer Research Retreat (CUSRR)",
                    f"{_RES}/colby-undergraduate-summer-research-retreat/",
                    "Colby's flagship summer research experience on Mayflower "
                    "Hill: students spend the summer in full-time, "
                    "faculty-mentored scholarly research across the sciences, "
                    "social sciences, humanities, and arts, culminating in the "
                    "Summer Research Retreat where all students engaged in "
                    "scholarly activity on campus present their work.",
                    lab_or_program="Colby Undergraduate Summer Research Retreat",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor",
                              "any discipline", "on-campus research"],
                ),
                program(
                    "colby_caps",
                    "Colby Achievement Program in the Sciences (CAPS)",
                    f"{_RES}/colby-achievement-program-in-the-sciences/",
                    "An early-research summer bridge program offering hands-on "
                    "research experiences in biology, chemistry, environmental "
                    "science, and other scientific disciplines to incoming "
                    "students, introducing them to faculty-mentored laboratory "
                    "research before their first year at Colby.",
                    lab_or_program="Colby Achievement Program in the Sciences",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman"],
                    international_friendly="unknown",
                    keywords=["science research", "laboratory", "faculty mentor",
                              "early research"],
                ),
                program(
                    "colby_senior_scholars",
                    "Senior Scholars Program (Colby)",
                    "https://www.colby.edu/academics/departments-and-programs/"
                    "independent-major/senior-scholars/",
                    "A year-long independent research or creative project "
                    "undertaken by selected seniors in any discipline, working "
                    "closely with a faculty mentor and culminating in a "
                    "substantial scholarly thesis or body of creative work.",
                    lab_or_program="Senior Scholars Program",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["senior"],
                    international_friendly="yes",
                    keywords=["independent research", "thesis", "faculty mentor",
                              "any discipline"],
                ),
                program(
                    "colby_clas",
                    "Colby Liberal Arts Symposium (CLAS)",
                    f"{_RES}/colby-liberal-arts-symposium/",
                    "An annual college-wide symposium at which Colby students "
                    "present research, scholarship, and creative work across "
                    "every academic discipline — a venue for undergraduates to "
                    "share and discuss the results of mentored and independent "
                    "research with the campus community.",
                    lab_or_program="Colby Liberal Arts Symposium",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research symposium", "any discipline",
                              "student scholarship", "creative work"],
                ),
                program(
                    "colby_bunche_scholars",
                    "Bunche Scholars Program (Colby)",
                    "https://afa.colby.edu/academics/scholar-programs/"
                    "bunche-scholars/",
                    "A scholar program supporting students committed to "
                    "diversity and academic excellence, pairing them with "
                    "faculty mentors and connecting them to mentored research "
                    "and enrichment opportunities across their time at Colby.",
                    lab_or_program="Bunche Scholars",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["scholar program", "faculty mentor",
                              "diversity in research", "mentoring"],
                ),
                program(
                    "colby_presidential_scholars",
                    "Presidential Scholars Program (Colby)",
                    "https://afa.colby.edu/academics/scholar-programs/"
                    "presidential-scholars/",
                    "A merit scholar program recognizing academically "
                    "distinguished students and providing access to enrichment, "
                    "faculty mentoring, and research opportunities throughout "
                    "their undergraduate studies at Colby.",
                    lab_or_program="Presidential Scholars",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["scholar program", "merit", "faculty mentor",
                              "enrichment"],
                ),
                program(
                    "colby_pulver_science_scholars",
                    "Pulver Science Scholars Program (Colby)",
                    "https://afa.colby.edu/academics/scholar-programs/"
                    "pulver-science-scholars/",
                    "A scholar program supporting students pursuing the natural "
                    "sciences, connecting them with faculty mentors and "
                    "mentored laboratory research opportunities in the sciences "
                    "at Colby.",
                    lab_or_program="Pulver Science Scholars",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["science research", "scholar program",
                              "faculty mentor", "laboratory"],
                ),
                program(
                    "colby_davisconnects",
                    "DavisConnects Research Funding (Colby)",
                    "https://davisconnects.colby.edu/",
                    "DavisConnects provides every Colby student with funding and "
                    "advising for research, internships, and global experiences, "
                    "including grants that support faculty-mentored and "
                    "independent research projects on campus and beyond.",
                    lab_or_program="DavisConnects",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research funding", "grant", "internship",
                              "faculty mentor"],
                ),
            ],
        },
    ],
}
