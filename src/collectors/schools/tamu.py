"""Texas A&M University campus opportunity-graph config.

Curated seed records of TAMU's undergraduate-research landscape, anchored on
LAUNCH's Office of Undergraduate Research (ugr.tamu.edu) — the URS thesis
program, the two student-run journals, and the NSF-REU summer gateway — plus
the team-based Aggie Research Program (transitioning to Aggie Collaborate),
the Cyclotron Institute's nuclear-physics REU, and the College of Agriculture
& Life Sciences' own Undergraduate Research Scholars. URLs verified live
(HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → tamu_research_programs (tamu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "tamu",
    "organization": "Texas A&M University",
    "location": "College Station, TX",
    "emit": {
        "campus": ("tamu_research_programs", "tamu", "campus"),
    },
    "sources": [
        {
            "source_name": "tamu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://ugr.tamu.edu/",
                "https://aggieresearch.tamu.edu/",
                "https://aglifesciences.tamu.edu/undergraduate-research-scholars/",
                "https://cyclotron.tamu.edu/reu-archive/",
            ],
            "programs": [
                program(
                    "launch_ugr_office",
                    "LAUNCH: Office of Undergraduate Research (Texas A&M)",
                    "https://ugr.tamu.edu/",
                    "Central gateway for undergraduate research at Texas A&M, "
                    "a tier-one land-, sea- and space-grant university "
                    "committed to high-impact practices. Runs the "
                    "Undergraduate Research Ambassadors program, informational "
                    "sessions, and the annual summer poster session, and "
                    "publishes definitions, policies, and getting-started "
                    "guidance for students seeking faculty-mentored research.",
                    lab_or_program="LAUNCH Undergraduate Research",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["undergraduate research", "faculty mentorship",
                              "poster session", "research ambassadors"],
                ),
                program(
                    "urs_thesis_program",
                    "Undergraduate Research Scholars (URS) Thesis Program (Texas A&M)",
                    "https://ugr.tamu.edu/programs/urs/index.html",
                    "Offers motivated undergraduates the opportunity to engage "
                    "in independent research, scholarly inquiry, and creative "
                    "work under faculty mentorship, culminating in an "
                    "undergraduate thesis. Open across disciplines and run by "
                    "the Office of Undergraduate Research; the current cycle "
                    "lists a final application deadline of September 8, 2026.",
                    lab_or_program="Undergraduate Research Scholars",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Final application deadline September 8, 2026.",
                    keywords=["thesis", "independent research",
                              "faculty mentorship", "scholars"],
                ),
                program(
                    "explorations_journal",
                    "Explorations: The Texas A&M Undergraduate Journal",
                    "https://ugr.tamu.edu/programs/explorations/index.html",
                    "A student-led, interdisciplinary publication that "
                    "celebrates original research and creative work of Aggie "
                    "undergraduates from every discipline — from engineering "
                    "and biology to art, history, and performance. Includes a "
                    "student editorial board that undergraduates can join.",
                    lab_or_program="Explorations",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["undergraduate journal", "publication",
                              "interdisciplinary", "editorial board"],
                ),
                program(
                    "journal_law_society",
                    "Texas A&M Undergraduate Journal of Law & Society",
                    "https://ugr.tamu.edu/programs/jls/index.html",
                    "A student-led journal publishing undergraduate research "
                    "in law, government, history, economics, public policy, "
                    "and related topics. Issue 2 was published in spring 2026 "
                    "and is available for download; students can apply to join "
                    "the editorial board.",
                    lab_or_program="Journal of Law & Society",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["law", "public policy", "undergraduate journal",
                              "social science research"],
                ),
                program(
                    "ugr_summer_reu_gateway",
                    "UGR Summer Research Resources — NSF-REU Gateway (Texas A&M)",
                    "https://ugr.tamu.edu/resources/summer.html",
                    "The Office of Undergraduate Research serves as the campus "
                    "gateway for NSF-REU summer programs and other non-NSF "
                    "undergraduate summer research experiences, collecting and "
                    "distributing the campus policies that govern them. Hosts "
                    "a professional-development series and a summer poster "
                    "session for summer researchers.",
                    lab_or_program="Summer Research Resources",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["REU", "summer research", "NSF",
                              "professional development"],
                ),
                program(
                    "aggie_research_program",
                    "Aggie Research Program (transitioning to Aggie Collaborate)",
                    "https://aggieresearch.tamu.edu/",
                    "Team-based research mentoring program that has served "
                    "over 10,000 participants since 2016 by pairing "
                    "undergraduates with graduate-student and postdoc team "
                    "leaders on faculty research projects. The site announces "
                    "the program is expanding and transitioning to Aggie "
                    "Collaborate.",
                    lab_or_program="Aggie Research Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["research teams", "mentoring",
                              "interdisciplinary", "aggie collaborate"],
                ),
                program(
                    "cyclotron_reu",
                    "Cyclotron Institute REU Program (Texas A&M)",
                    "https://cyclotron.tamu.edu/reu-archive/",
                    "Summer Research Experiences for Undergraduates at Texas "
                    "A&M's Cyclotron Institute in nuclear physics and nuclear "
                    "chemistry. The site documents applications for Summer "
                    "2026, previous years' programs, and student publications "
                    "resulting from the program.",
                    lab_or_program="Cyclotron Institute REU",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    eligibility_majors=["Physics", "Chemistry", "Nuclear Engineering"],
                    keywords=["nuclear physics", "REU", "summer research",
                              "accelerator"],
                ),
                program(
                    "aglife_urs",
                    "AgriLife Undergraduate Research Scholars (Texas A&M)",
                    "https://aglifesciences.tamu.edu/undergraduate-research-scholars/",
                    "College of Agriculture and Life Sciences program spanning "
                    "the academic year, with research projects beginning Fall "
                    "2026 and concluding Spring 2027. Culminates in a showcase "
                    "of scholars' work through poster and oral presentations "
                    "at a research symposium.",
                    lab_or_program="AgriLife Undergraduate Research Scholars",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    eligibility_majors=["Animal Science", "Biochemistry",
                                        "Entomology", "Nutrition",
                                        "Ecology and Conservation Biology"],
                    keywords=["agriculture", "life sciences",
                              "research scholars", "symposium"],
                ),
            ],
        },
    ],
}
