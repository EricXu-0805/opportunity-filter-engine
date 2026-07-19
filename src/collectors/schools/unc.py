"""University of North Carolina at Chapel Hill campus opportunity-graph config.

Curated seed records of UNC-CH's undergraduate-research landscape, centered on
the Office for Undergraduate Research (OUR, our.unc.edu) — its SURF summer
fellowship, the Amgen Scholars summer program, the Carolina Research Scholars
Program (CRSP), the Graduate Research Consultant (GRC) course-embedded model,
OUR funding (summer award, travel grants, work-study research), and the
Undergraduate Research Ambassadors — plus the Chancellor's Science Scholars
STEM cohort and Honors Carolina. URLs curl-verified live (HTTP 200) on
2026-07-19.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> unc_research_programs (unc / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "unc",
    "organization": "University of North Carolina at Chapel Hill",
    "location": "Chapel Hill, NC",
    "emit": {
        "campus": ("unc_research_programs", "unc", "campus"),
    },
    "sources": [
        {
            "source_name": "unc_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://our.unc.edu/",
                "https://chancellorssciencescholars.unc.edu/",
                "https://honorscarolina.unc.edu/",
            ],
            "programs": [
                program(
                    "unc_office_undergraduate_research",
                    "Office for Undergraduate Research (UNC-Chapel Hill)",
                    "https://our.unc.edu/",
                    "UNC-Chapel Hill's Office for Undergraduate Research (OUR) "
                    "helps students of all majors and years find, fund, and "
                    "present research and creative scholarship. It maintains a "
                    "database of research opportunities and research-exposure "
                    "courses, connects students with faculty mentors, and "
                    "administers awards, fellowships, and the campus "
                    "undergraduate research symposium.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "faculty mentorship",
                              "research opportunities", "any major"],
                ),
                program(
                    "unc_surf",
                    "Summer Undergraduate Research Fellowship (SURF, UNC-Chapel Hill)",
                    "https://our.unc.edu/fund/surf/",
                    "SURF provides UNC undergraduates a fellowship to pursue "
                    "full-time faculty-mentored research or creative work over "
                    "the summer, with a stipend supporting an intensive, "
                    "self-designed project. Applicants submit a research "
                    "proposal developed with their faculty mentor.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Applications typically due in the spring "
                                  "semester for the following summer.",
                    keywords=["summer research", "fellowship", "stipend",
                              "faculty mentor"],
                ),
                program(
                    "unc_amgen_scholars",
                    "Amgen Scholars Program (UNC-Chapel Hill)",
                    "https://our.unc.edu/amgen-scholars/",
                    "UNC is a host site for the national Amgen Scholars Program, "
                    "a fully-funded summer research experience in science and "
                    "biotechnology for undergraduates. Scholars conduct "
                    "hands-on research in a UNC faculty lab, attend a national "
                    "symposium, and receive a stipend plus housing and travel "
                    "support.",
                    lab_or_program="Amgen Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="U.S. citizen / national / permanent-resident "
                                  "eligibility; February application window.",
                    keywords=["Amgen Scholars", "summer research",
                              "biotechnology", "life sciences"],
                ),
                program(
                    "unc_crsp",
                    "Carolina Research Scholars Program (CRSP, UNC-Chapel Hill)",
                    "https://our.unc.edu/find/crsp/",
                    "Open to students of any major, CRSP recognizes "
                    "undergraduates who complete a structured set of research "
                    "engagement requirements — attending research-skills "
                    "workshops, conducting mentored research, and presenting "
                    "their work — with a transcript-visible research scholar "
                    "designation.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research recognition", "research skills",
                              "any major", "professional development"],
                ),
                program(
                    "unc_grc",
                    "Graduate Research Consultant Program (GRC, UNC-Chapel Hill)",
                    "https://our.unc.edu/grc/",
                    "The GRC program embeds graduate-student research "
                    "consultants in undergraduate courses so students get "
                    "hands-on mentoring on discipline-specific research methods "
                    "within a class research project — a structured entry point "
                    "into research for students not yet in a lab.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["course-based research", "research methods",
                              "graduate mentorship"],
                ),
                program(
                    "unc_our_summer_award",
                    "OUR Summer Undergraduate Research Award (UNC-Chapel Hill)",
                    "https://our.unc.edu/fund/summer-award/",
                    "A competitively-awarded OUR grant funding a UNC "
                    "undergraduate's summer research or creative project, "
                    "reviewed jointly by the Office for Undergraduate Research "
                    "and Summer School. Recipients pursue mentored research "
                    "full-time over the summer with financial support.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Spring application deadline for summer funding.",
                    keywords=["summer research", "research funding",
                              "creative work"],
                ),
                program(
                    "unc_research_travel_funding",
                    "Undergraduate Research Travel Funding (UNC-Chapel Hill)",
                    "https://our.unc.edu/fund/travel-funding/",
                    "OUR travel grants reimburse UNC undergraduates for costs "
                    "of presenting their research or creative scholarship at "
                    "academic conferences and professional meetings, supporting "
                    "students in sharing their mentored work beyond campus.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["conference travel", "research presentation",
                              "travel grant"],
                ),
                program(
                    "unc_research_ambassadors",
                    "Undergraduate Research Ambassadors (UNC-Chapel Hill)",
                    "https://our.unc.edu/ambassadors/",
                    "Undergraduate Research Ambassadors are experienced "
                    "student researchers who help peers get started in research "
                    "— running outreach, workshops, and one-on-one advising "
                    "through the Office for Undergraduate Research.",
                    lab_or_program="Office for Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["peer mentorship", "research outreach",
                              "student leadership"],
                ),
                program(
                    "unc_chancellors_science_scholars",
                    "Chancellor's Science Scholars Program (UNC-Chapel Hill)",
                    "https://chancellorssciencescholars.unc.edu/",
                    "Modeled on the Meyerhoff Scholars Program, Chancellor's "
                    "Science Scholars supports undergraduates pursuing research "
                    "careers in STEM through a cohort community, summer research "
                    "bridge experiences, faculty mentoring, and preparation for "
                    "graduate study and research fellowships.",
                    lab_or_program="Chancellor's Science Scholars",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["STEM", "research careers", "cohort program",
                              "faculty mentoring"],
                ),
                program(
                    "unc_honors_carolina",
                    "Honors Carolina (UNC-Chapel Hill)",
                    "https://honorscarolina.unc.edu/",
                    "Honors Carolina offers high-achieving undergraduates "
                    "small honors courses, faculty-mentored honors thesis "
                    "research, fellowships and enrichment funding, and access "
                    "to research and experiential-learning opportunities across "
                    "disciplines.",
                    lab_or_program="Honors Carolina",
                    opportunity_type="fellowship",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["honors", "honors thesis", "enrichment funding",
                              "interdisciplinary"],
                ),
            ],
        },
    ],
}
