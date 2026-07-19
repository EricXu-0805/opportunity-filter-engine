"""Arizona State University campus opportunity-graph config.

Curated seed records of ASU's undergraduate-research landscape: the two
campus-wide hubs — the Fulton Undergraduate Research Initiative (FURI, the Ira
A. Fulton Schools of Engineering's flagship mentored-research + stipend
program) and the Office of the Provost's UResearch hub — plus the National
Scholarships office's REU gateway, two department-anchored NSF summer REUs
(School of Molecular Sciences; School of Mathematical & Statistical Sciences),
and Barrett, The Honors College (its required mentored thesis / creative
project). URLs verified live 2026-07-19 (all HTTP 200 under a browser
user-agent; the FURI engineering subdomain sits behind a Cloudflare UA gate
that 200s a real browser).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → asu_research_programs (asu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "asu",
    "organization": "Arizona State University",
    "location": "Tempe, AZ",
    "emit": {
        "campus": ("asu_research_programs", "asu", "campus"),
    },
    "sources": [
        {
            "source_name": "asu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://provost.asu.edu/uresearch",
                "https://onsa.asu.edu/scholarship/research-experiences-undergraduates-reu",
                "https://barretthonors.asu.edu/",
            ],
            "programs": [
                program(
                    "asu_furi",
                    "Fulton Undergraduate Research Initiative (FURI, Arizona State University)",
                    "https://students.engineering.asu.edu/furi/",
                    "FURI is the Ira A. Fulton Schools of Engineering's flagship "
                    "undergraduate research program. Students design a "
                    "self-directed, faculty-mentored research or "
                    "entrepreneurship project and receive a stipend "
                    "(about $1,500 per semester) plus a supplies budget (about "
                    "$400), culminating in a campus research symposium. Open to "
                    "engineering undergraduates across all Fulton Schools.",
                    lab_or_program="Ira A. Fulton Schools of Engineering",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "engineering",
                              "faculty mentor", "research stipend"],
                ),
                program(
                    "asu_uresearch",
                    "ASU UResearch — Undergraduate Research Hub (Arizona State University)",
                    "https://provost.asu.edu/uresearch",
                    "UResearch, run out of the Office of the Provost, is ASU's "
                    "campus-wide hub for undergraduate research. It aggregates "
                    "research and creative-project opportunities across every "
                    "college, helps students find faculty mentors and funding, "
                    "and connects them to programs, symposia, and getting-started "
                    "resources regardless of major.",
                    lab_or_program="Office of the Provost — UResearch",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "research opportunities",
                              "faculty mentor", "any major"],
                ),
                program(
                    "asu_reu_gateway",
                    "Research Experiences for Undergraduates (REU) at ASU (Office of National Scholarships Advisement)",
                    "https://onsa.asu.edu/scholarship/research-experiences-undergraduates-reu",
                    "ASU's Office of National Scholarships Advisement guide to "
                    "NSF-funded Research Experiences for Undergraduates (REU) "
                    "programs — typically paid, full-time summer research "
                    "placements at host institutions nationwide. Covers how REU "
                    "sites work, eligibility, and application strategy for ASU "
                    "students seeking a summer research experience.",
                    lab_or_program="Office of National Scholarships Advisement",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["NSF REU", "summer research", "paid research",
                              "national scholarships"],
                ),
                program(
                    "asu_sms_summer_reu",
                    "School of Molecular Sciences Summer REU (Arizona State University)",
                    "https://sms.asu.edu/SummerREU",
                    "An NSF-funded 10-week summer Research Experience for "
                    "Undergraduates in ASU's School of Molecular Sciences, "
                    "focused on sustainable chemistry and catalysis. "
                    "Participants join a faculty research group and receive a "
                    "stipend plus housing support; open to undergraduates "
                    "nationally, including students from institutions without "
                    "strong research infrastructure.",
                    lab_or_program="School of Molecular Sciences",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["chemistry", "catalysis", "summer research",
                              "stipend and housing"],
                ),
                program(
                    "asu_somss_reu",
                    "SoMSS Research Experiences for Undergraduates (Arizona State University)",
                    "https://math.asu.edu/research/undergraduate-research/research-experiences-undergraduates-reus",
                    "The School of Mathematical and Statistical Sciences hosts "
                    "summer Research Experiences for Undergraduates in "
                    "mathematics and statistics, including the (AM)² REU in "
                    "applied mathematics. Cohorts work on faculty-led research "
                    "problems over the summer with a stipend, building toward "
                    "conference presentations and publications.",
                    lab_or_program="School of Mathematical and Statistical Sciences",
                    opportunity_type="summer_program",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["mathematics", "statistics", "applied mathematics",
                              "summer REU"],
                ),
                program(
                    "asu_barrett_honors_thesis",
                    "Barrett, The Honors College — Mentored Honors Thesis (Arizona State University)",
                    "https://barretthonors.asu.edu/",
                    "Barrett, The Honors College is ASU's honors college; every "
                    "Barrett student completes a required mentored honors thesis "
                    "or creative project — an in-depth, faculty-directed piece "
                    "of original undergraduate research or creative work across "
                    "any discipline, defended before a committee. Barrett "
                    "provides thesis funding, workshops, and mentor matching.",
                    lab_or_program="Barrett, The Honors College",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["honors thesis", "mentored research",
                              "creative project", "any major"],
                ),
            ],
        },
    ],
}
