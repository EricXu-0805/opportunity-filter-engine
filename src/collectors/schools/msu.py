"""Michigan State University campus opportunity-graph config.

Curated seed records of MSU's undergraduate-research landscape, centered on the
Office of Undergraduate Research & Creative Arts (URCA) — its main office, the
summer research programs hub, and the find-opportunities hub — plus the Honors
College research opportunities, the College of Engineering undergraduate-research
office, and the central Office of Research & Innovation undergraduate-research
programs. URLs curl-verified live (HTTP 200) 2026-07-19; the engineering seed
resolves through a redirect to /research/undergraduate-research (the final URL is
stored to avoid the hop).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → msu_research_programs (msu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "msu",
    "organization": "Michigan State University",
    "location": "East Lansing, MI",
    "emit": {
        "campus": ("msu_research_programs", "msu", "campus"),
    },
    "sources": [
        {
            "source_name": "msu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://urca.msu.edu/",
                "https://honorscollege.msu.edu/programs/research-opportunities/",
                "https://research.msu.edu/undergraduate-reseach",
            ],
            "programs": [
                program(
                    "msu_urca_office",
                    "Undergraduate Research & Creative Arts (URCA, Michigan State University)",
                    "https://urca.msu.edu/",
                    "MSU's central Undergraduate Research & Creative Arts office "
                    "helps students across every college find and get started in "
                    "faculty-mentored research and creative projects. It curates "
                    "opportunity listings, funding and forums, and the annual "
                    "University Undergraduate Research and Arts Forum (UURAF).",
                    lab_or_program="Undergraduate Research & Creative Arts",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "creative arts",
                              "research opportunities", "mentorship"],
                ),
                program(
                    "msu_urca_summer",
                    "URCA Summer Research Opportunities (Michigan State University)",
                    "https://urca.msu.edu/summer",
                    "URCA's hub for MSU summer undergraduate research programs, "
                    "including university-run summer research experiences such as "
                    "BRUSH and CMERC. These are full-time, funded summer research "
                    "placements pairing students with faculty mentors.",
                    lab_or_program="Undergraduate Research & Creative Arts",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "funded research",
                              "faculty mentor", "REU"],
                ),
                program(
                    "msu_urca_find",
                    "URCA — Find Research Opportunities (Michigan State University)",
                    "https://urca.msu.edu/find",
                    "URCA's find-opportunities hub points MSU students to on- and "
                    "off-campus research, including Handshake research postings, "
                    "national REU programs, and the Pathways to Science database. "
                    "It is the entry point for locating a lab or project to join.",
                    lab_or_program="Undergraduate Research & Creative Arts",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research listings", "Handshake", "REU",
                              "finding a lab"],
                ),
                program(
                    "msu_honors_research",
                    "Honors College Research Opportunities (Michigan State University)",
                    "https://honorscollege.msu.edu/programs/research-opportunities/",
                    "The MSU Honors College runs signature research pathways for "
                    "its members, including Professorial Assistantships (paid "
                    "faculty-mentored research for incoming students) and Research "
                    "Scholars programming that connects students to funded research "
                    "and creative work.",
                    lab_or_program="Honors College",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["honors", "professorial assistantship",
                              "research scholars", "paid research"],
                ),
                program(
                    "msu_engineering_ugr",
                    "College of Engineering Undergraduate Research (Michigan State University)",
                    "https://engineering.msu.edu/research/undergraduate-research",
                    "The MSU College of Engineering's undergraduate-research office "
                    "connects engineering and computing students with faculty "
                    "research labs, research-for-credit and paid research options, "
                    "and college-level research programs and events.",
                    lab_or_program="College of Engineering",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["engineering research", "faculty labs",
                              "research for credit", "computing"],
                ),
                program(
                    "msu_research_innovation_ugr",
                    "Office of Research & Innovation — Undergraduate Research (Michigan State University)",
                    "https://research.msu.edu/undergraduate-reseach",
                    "MSU's central Office of Research & Innovation lists "
                    "university-wide undergraduate-research programs, including the "
                    "Summer Research Opportunities Program (SROP), NSF REU sites, "
                    "and the MSU Scholars pathways for underrepresented and "
                    "first-generation researchers.",
                    lab_or_program="Office of Research & Innovation",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["SROP", "REU", "MSU Scholars",
                              "undergraduate research programs"],
                ),
            ],
        },
    ],
}
