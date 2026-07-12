"""Columbia University campus opportunity-graph config.

Curated seed records of Columbia's undergraduate-research landscape: the
Undergraduate Research & Fellowships office (URF) and its scholar programs
(Rabi, Science Research Fellows, Laidlaw, MMUF), the Columbia Undergraduate
Scholars Program, and Amgen Scholars. URLs verified live (HTTP 200) on
2026-07-12 — note urf.columbia.edu and cc-seas.columbia.edu are NOT behind the
Cloudflare challenge that walls the Columbia Sites dept platform, and Amgen's
Columbia subdomain is dead DNS so the national program page is wired instead.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → columbia_research_programs (columbia / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "columbia",
    "organization": "Columbia University",
    "location": "New York, NY",
    "emit": {
        "campus": ("columbia_research_programs", "columbia", "campus"),
    },
    "sources": [
        {
            "source_name": "columbia_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://urf.columbia.edu/",
                "https://www.cc-seas.columbia.edu/scholars",
                "https://amgenscholars.com/university/columbia-university/",
            ],
            "programs": [
                program(
                    "urf_hub",
                    "Columbia Undergraduate Research & Fellowships (URF)",
                    "https://urf.columbia.edu/",
                    "URF is Columbia's central office for undergraduate research "
                    "and competitive fellowships: it runs the annual "
                    "Undergraduate Research Symposium and Rose Research Week, "
                    "administers the scholar programs below, connects students "
                    "with faculty research across the university, and advises on "
                    "national fellowships (Fulbright, Rhodes, and peers).",
                    lab_or_program="Undergraduate Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "fellowships", "research symposium"],
                ),
                program(
                    "cusp",
                    "Columbia Undergraduate Scholars Program (CUSP)",
                    "https://www.cc-seas.columbia.edu/scholars",
                    "CUSP selects Columbia College and SEAS students for a "
                    "four-year scholars community (including the named Davis "
                    "scholars for SEAS) with enhanced academic and cultural "
                    "opportunities, research activities across disciplines, and "
                    "funded internship support.",
                    lab_or_program="Columbia Undergraduate Scholars Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["scholars program", "research community"],
                ),
                program(
                    "rabi_scholars",
                    "I.I. Rabi Scholars Program (Columbia)",
                    "https://urf.columbia.edu/urf/research/rabi",
                    "Founded in 1989 in memory of Nobel laureate I.I. Rabi, the "
                    "program selects incoming Columbia College first-years of "
                    "exceptional promise in the sciences and supports them with "
                    "funded research opportunities throughout their "
                    "undergraduate careers.",
                    lab_or_program="Rabi Scholars",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["science research", "scholars program"],
                ),
                program(
                    "science_research_fellows",
                    "Columbia Science Research Fellows (SRF)",
                    "https://urf.columbia.edu/urf/research/srf",
                    "A four-year research designation for incoming students: "
                    "each Science Research Fellow receives a $10,000 research "
                    "stipend and two guaranteed summer research experiences in "
                    "Columbia faculty laboratories, plus a cohort of fellow "
                    "student researchers.",
                    lab_or_program="Science Research Fellows",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$10,000 research stipend + two guaranteed research summers",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["science research", "summer research", "stipend"],
                ),
                program(
                    "laidlaw",
                    "Laidlaw Undergraduate Research & Leadership Scholarship (Columbia)",
                    "https://urf.columbia.edu/urf/research/laidlaw",
                    "The Laidlaw Scholarship funds up to 25 Columbia "
                    "undergraduates across two consecutive summers around the "
                    "sophomore year — the first devoted to faculty-mentored "
                    "research, the second to leadership-in-action — as part of "
                    "the multi-university Laidlaw Foundation network.",
                    lab_or_program="Laidlaw Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["summer research", "leadership"],
                ),
                program(
                    "mmuf",
                    "Mellon Mays Undergraduate Fellowship at Columbia (MMUF)",
                    "https://urf.columbia.edu/urf/research/mmuf",
                    "Columbia's MMUF chapter (established 1996) provides "
                    "research training, faculty mentorship, and financial "
                    "support for undergraduates aiming at PhDs and the "
                    "professoriate in Mellon-designated fields — about half of "
                    "its alumni have entered doctoral programs.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["humanities research", "PhD pipeline", "mentorship"],
                ),
                program(
                    "amgen_columbia",
                    "Amgen Scholars Program at Columbia University",
                    "https://amgenscholars.com/university/columbia-university/",
                    "Amgen Scholars at Columbia is a summer residential "
                    "research program placing undergraduates from across the "
                    "U.S. in premier Columbia laboratories for hands-on "
                    "biotech/biomedical research, with weekly lab meetings, "
                    "faculty seminars, and the national Amgen Scholars "
                    "Symposium.",
                    lab_or_program="Amgen Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "biotechnology", "biomedical research"],
                ),
            ],
        },
    ],
}
