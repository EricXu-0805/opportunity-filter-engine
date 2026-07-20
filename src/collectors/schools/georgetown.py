"""Georgetown University campus opportunity-graph config.

Curated seed records of Georgetown's undergraduate-research landscape,
centered on the Center for Research & Fellowships (CRF, crf.georgetown.edu) —
which runs the Georgetown Undergraduate Research Opportunities Program
(GUROP), the Provost's Undergraduate Research Presentation Awards, the BIG
EAST Undergraduate Research Poster Symposium, an off-campus/REU opportunities
listing, and the university Fellowships Database — plus the College's
undergraduate-research hub. All URLs curl-verified live (HTTP 200) on
2026-07-19.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → georgetown_research_programs (georgetown / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "georgetown",
    "organization": "Georgetown University",
    "location": "Washington, DC",
    "emit": {
        "campus": ("georgetown_research_programs", "georgetown", "campus"),
    },
    "sources": [
        {
            "source_name": "georgetown_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://crf.georgetown.edu/research/research-opportunities/",
                "https://college.georgetown.edu/research/undergraduate-research/",
                "https://crf.georgetown.edu/fellowships/",
            ],
            "programs": [
                program(
                    "georgetown_gurop",
                    "Georgetown Undergraduate Research Opportunities Program (GUROP)",
                    "https://crf.georgetown.edu/research/research-opportunities/gurop/",
                    "GUROP is an undergraduate research assistantship program open "
                    "to students in every Georgetown school (CAS, MSB, SCS, SFS, "
                    "SOH, SON) and the Georgetown University in Qatar campus, in "
                    "any academic discipline. Participating students work under "
                    "the direction of a Georgetown faculty mentor to build their "
                    "skills in scholarly inquiry, earning academic credit for a "
                    "mentored research experience.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "research assistantship",
                              "faculty mentor", "any discipline"],
                ),
                program(
                    "georgetown_crf",
                    "Center for Research & Fellowships (Georgetown)",
                    "https://crf.georgetown.edu/",
                    "The Center for Research & Fellowships (CRF) is Georgetown's "
                    "hub for undergraduate and graduate research engagement and "
                    "nationally competitive fellowships. It advises students on "
                    "finding research opportunities, mentors fellowship "
                    "applicants, and administers GUROP, presentation awards, and "
                    "research symposia.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research advising", "fellowships", "mentorship",
                              "scholarly inquiry"],
                ),
                program(
                    "georgetown_provost_awards",
                    "Provost's Undergraduate Research Presentation Awards (Georgetown)",
                    "https://crf.georgetown.edu/research/research-opportunities/"
                    "provosts-undergraduate-research-presentation-awards/",
                    "The Provost's Undergraduate Research Presentation Awards "
                    "provide funding to help Georgetown undergraduates present "
                    "their original scholarly and creative research at academic "
                    "conferences and professional meetings, defraying travel and "
                    "registration costs.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research funding", "conference travel",
                              "presentation award"],
                ),
                program(
                    "georgetown_big_east_symposium",
                    "BIG EAST Undergraduate Research Poster Symposium (Georgetown)",
                    "https://crf.georgetown.edu/research/research-opportunities/big-east/",
                    "An annual BIG EAST conference research poster symposium that "
                    "showcases undergraduate research across member universities. "
                    "Georgetown undergraduates present posters on their mentored "
                    "research and connect with peers and faculty from across the "
                    "conference.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["poster symposium", "research showcase",
                              "undergraduate research"],
                ),
                program(
                    "georgetown_external_research",
                    "Off-Campus Research Opportunities / REU Listings (Georgetown CRF)",
                    "https://crf.georgetown.edu/research/research-opportunities/"
                    "external-opportunities/",
                    "The Center for Research & Fellowships curates off-campus "
                    "research opportunities for Georgetown undergraduates, "
                    "including NSF Research Experiences for Undergraduates (REU) "
                    "sites, summer research programs, and internships at other "
                    "institutions, national labs, and research organizations.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["REU", "summer research", "off-campus research",
                              "external opportunities"],
                ),
                program(
                    "georgetown_fellowships_database",
                    "Georgetown Fellowships Database (CRF)",
                    "https://crf.georgetown.edu/fellowships/fellowships-database/",
                    "A searchable database of nationally competitive fellowships, "
                    "scholarships, and grants that Georgetown students can apply "
                    "for, spanning research, graduate study, language study, and "
                    "public-service awards, maintained by the Center for Research "
                    "& Fellowships.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["fellowships", "scholarships", "grants",
                              "competitive awards"],
                ),
                program(
                    "georgetown_college_ugr",
                    "Undergraduate Research at Georgetown College (CAS)",
                    "https://college.georgetown.edu/research/undergraduate-research/",
                    "The Georgetown College of Arts & Sciences undergraduate "
                    "research hub encourages students to work alongside faculty "
                    "in the search for and creation of knowledge, pointing to "
                    "departmental research, independent-study pathways, honors "
                    "theses, and mentored projects across the arts, humanities, "
                    "social sciences, and natural sciences.",
                    lab_or_program="College of Arts & Sciences",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "faculty collaboration",
                              "honors thesis", "independent study"],
                ),
                program(
                    "georgetown_research_opportunities_hub",
                    "Research Opportunities Hub (Georgetown CRF)",
                    "https://crf.georgetown.edu/research/research-opportunities/",
                    "The Center for Research & Fellowships' Research Opportunities "
                    "page is the central directory of Georgetown undergraduate "
                    "research programs, funding, presentation awards, and "
                    "symposia, and links students to on- and off-campus mentored "
                    "research options.",
                    lab_or_program="Center for Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research directory", "research funding",
                              "undergraduate research"],
                ),
            ],
        },
    ],
}
