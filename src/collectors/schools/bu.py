"""Boston University campus opportunity-graph config.

Curated seed records of BU's undergraduate-research landscape, centered on
UROP (the central undergraduate research office) and its cohort programs,
plus the life-science and engineering summer research tracks (SURF, BRITE
REU, STaRS on the Medical Campus, and the Photonics Center's REU/CELL-MET
programs). URLs verified live (HTTP 200) on 2026-07-18.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → bu_research_programs (bu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "bu",
    "organization": "Boston University",
    "location": "Boston, MA",
    "emit": {
        "campus": ("bu_research_programs", "bu", "campus"),
    },
    "sources": [
        {
            "source_name": "bu_research_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://www.bu.edu/urop/",
                "https://www.bu.edu/surf/",
                "https://sites.bu.edu/britereu/",
                "https://www.bu.edu/photonics-programs/",
            ],
            "programs": [
                program(
                    "urop",
                    "Undergraduate Research Opportunities Program (UROP) — Boston University",
                    "https://www.bu.edu/urop/",
                    "BU's central undergraduate research office funds "
                    "faculty-mentored research by full-time BU undergraduates. "
                    "UROP awards competitive research stipends each semester "
                    "and summer, plus separate Travel & Supplies awards; "
                    "students may alternatively do research for academic "
                    "credit or as volunteers. All projects must be supervised "
                    "by a BU faculty member, and the office runs an annual "
                    "undergraduate research symposium and maintains "
                    "mentor-posted opportunity listings.",
                    lab_or_program="UROP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "stipend", "faculty mentor",
                              "summer research", "academic year research"],
                ),
                program(
                    "urop_sankofa",
                    "Sankofa Scholars Undergraduate Research Program (BU UROP)",
                    "https://www.bu.edu/urop/opportunities/sankofa-scholars-undergraduate-research-program/",
                    "A UROP-run cohort program open to first- and second-year "
                    "students across all majors at BU. Scholars do 5-10 hours "
                    "of research per week with established faculty researchers "
                    "during fall and spring semesters, with optional summer "
                    "research. A weekly seminar supports the research, builds "
                    "community, and prepares scholars for graduate school "
                    "admission, and scholars travel to research conferences.",
                    lab_or_program="Sankofa Scholars",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["cohort research program", "early undergraduate",
                              "graduate school preparation", "mentored research"],
                ),
                program(
                    "surf",
                    "Summer Undergraduate Research Fellowship (SURF) — Boston University",
                    "https://www.bu.edu/surf/",
                    "A summer research fellowship in the life sciences at BU "
                    "designed to promote access to research experiences for "
                    "talented undergraduates. Open to students from BU and "
                    "from other institutions, with particular attention to "
                    "students with less access to first-class research "
                    "opportunities. Fellows conduct mentored laboratory "
                    "research in cohorts that have run annually since 2001.",
                    lab_or_program="SURF",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["summer research", "life sciences", "biology",
                              "fellowship"],
                ),
                program(
                    "brite_reu",
                    "BRITE REU — Bioinformatics Research and Interdisciplinary Training Experience (BU)",
                    "https://sites.bu.edu/britereu/",
                    "An NSF REU summer program focused on computational and "
                    "mathematical fundamentals of bioinformatics. Research "
                    "projects span gene regulatory networks, metabolic "
                    "networks, microbial community analysis, synthetic "
                    "biology, enzyme structure and function, machine learning "
                    "for cancer subtype classification, and sequence-analysis "
                    "algorithms. Each student is paired with a Bioinformatics "
                    "faculty mentor and a graduate student mentor, with "
                    "workshops on Python, R, SQL, and the Linux command line.",
                    lab_or_program="BRITE REU",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["bioinformatics", "computational biology",
                              "machine learning", "REU", "summer research"],
                ),
                program(
                    "stars",
                    "Summer Training as Research Scholars (STaRS) — BU Medical Campus",
                    "https://www.bumc.bu.edu/gms/students/summer-training-as-research-scholars-program/",
                    "A summer biomedical research training program run by BU "
                    "Graduate Medical Sciences on the Medical Campus. Scholars "
                    "conduct mentored research in biomedical science labs and "
                    "participate in professional-development programming aimed "
                    "at preparing them for graduate study in the biomedical "
                    "sciences.",
                    lab_or_program="STaRS",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior"],
                    keywords=["biomedical research", "medical campus",
                              "summer program", "graduate school pipeline"],
                ),
                program(
                    "photonics_reu",
                    "Photonics Center Undergraduate Programs — REU & CELL-MET Mentorship (BU)",
                    "https://www.bu.edu/photonics-programs/",
                    "The BU Photonics Center runs undergraduate research "
                    "programming on two tracks: an NSF Research Experiences "
                    "for Undergraduates program for non-BU students and the "
                    "NSF CELL-MET Undergraduate Research Mentorship Program "
                    "for current BU undergrads. Participants work on photonics "
                    "and engineering research projects with listed faculty "
                    "mentors and take part in professional development.",
                    lab_or_program="BU Photonics Center",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    keywords=["photonics", "optics", "engineering research",
                              "REU", "NSF", "mentorship"],
                ),
            ],
        },
    ],
}
