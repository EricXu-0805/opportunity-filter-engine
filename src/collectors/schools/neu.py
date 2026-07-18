"""Northeastern University campus opportunity-graph config.

Curated seed records of Northeastern's undergraduate-research landscape,
centered on the Undergraduate Research & Fellowships (URF) office — its
searchable research-opportunities portal, the PEAK Fellowships award ladder,
the AJC Merit Research Scholarship (research through Northeastern's signature
co-op cycle) and national-fellowship advising — plus the college-level routes
(Khoury's three research pathways, the Marine Science Center summer
internship, CaNCURE cancer-nanomedicine co-ops) and the John Martinson Honors
Program. URLs curl-verified live (HTTP 200) on 2026-07-18; cancure.sites
redirects to its canonical cancurecancer.org home (final 200).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → neu_research_programs (neu / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "neu",
    "organization": "Northeastern University",
    "location": "Boston, MA",
    "emit": {
        "campus": ("neu_research_programs", "neu", "campus"),
    },
    "sources": [
        {
            "source_name": "neu_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://undergraduate.northeastern.edu/research/",
                "https://www.khoury.northeastern.edu/undergraduate-research/",
                "https://cos.northeastern.edu/marinescience/msc-summer-internship/",
            ],
            "programs": [
                program(
                    "urf_research_opportunities",
                    "Undergraduate Research & Fellowships — Research Opportunities Portal (Northeastern)",
                    "https://undergraduate.northeastern.edu/research/research-opportunities/search/",
                    "Northeastern's central Undergraduate Research & Fellowships "
                    "(URF) office runs a searchable portal where faculty post "
                    "open research and creative-endeavor positions across the "
                    "disciplines. Postings typically refresh at the start of "
                    "each semester and stay live until the faculty member's "
                    "expiration date. The office also guides students through "
                    "discovering a question, making the project happen, and "
                    "presenting the results.",
                    lab_or_program="Undergraduate Research & Fellowships",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "faculty mentors",
                              "research postings", "creative endeavor"],
                ),
                program(
                    "peak_fellowships",
                    "PEAK Fellowships — Project-Based Exploration for the Advancement of Knowledge (Northeastern)",
                    "https://undergraduate.northeastern.edu/research/awards/peak-fellowships-overview/",
                    "The PEAK Fellowships are a progressively structured "
                    "sequence of funded undergraduate research awards — from "
                    "Base Camp for beginners establishing themselves, through "
                    "the Summit and Trail-Blazer tiers for advanced independent "
                    "projects, plus Shout-It-Out support for presenting "
                    "results. Awards fund research and creative endeavor "
                    "through the academic year and summer. Applicants complete "
                    "a preliminary questionnaire through the URF office, and "
                    "each tier has its own eligibility, benefits, and "
                    "selection criteria.",
                    lab_or_program="PEAK Fellowships",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research funding", "fellowship", "PEAK",
                              "independent project", "summer research"],
                ),
                program(
                    "ajc_merit_research_scholarship",
                    "AJC Merit Research Scholarship (Northeastern)",
                    "https://undergraduate.northeastern.edu/research/awards/ajc-merit-research-scholarship/",
                    "The AJC Merit Research Scholarship funds students to do "
                    "research through Northeastern's signature co-op cycle: "
                    "candidates either apply to a posted AJC Merit Research "
                    "Scholarship co-op project or propose a co-op they build "
                    "with a mentor. For the Summer-Fall 2026 cycle the "
                    "Northeastern deadline was 02/27/2026, and the seventh "
                    "cohort of AJC Merit Research Scholars began co-ops this "
                    "year.",
                    lab_or_program="AJC Merit Research Scholarship",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Summer-Fall 2026 cycle deadline was 02/27/2026; annual cycle.",
                    keywords=["research co-op", "funded research", "merit scholarship"],
                ),
                program(
                    "cancure",
                    "CaNCURE — Cancer Nanomedicine Co-ops for Undergraduate Research Experience (Northeastern)",
                    "https://cancure.sites.northeastern.edu/",
                    "CaNCURE bills itself as the world's first undergraduate "
                    "research program in cancer nanomedicine, providing "
                    "hands-on research co-ops in how nanomedicine is used to "
                    "detect and treat cancer. Trainees are paired with mentors "
                    "and produce research publications and videos tracked on "
                    "the program site.",
                    lab_or_program="CaNCURE",
                    department="Bouvé College of Health Sciences",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    eligibility_majors=["Bioengineering", "Biology", "Chemistry",
                                       "Health Science", "Pharmacy"],
                    keywords=["cancer", "nanomedicine", "co-op",
                              "biomedical research", "NIH"],
                ),
                program(
                    "john_martinson_honors",
                    "John Martinson Honors Program (Northeastern)",
                    "https://honors.northeastern.edu/",
                    "The John Martinson Honors Program, housed under Education "
                    "Innovation in the Office of the Chancellor, creates "
                    "student-centered experiential education experiences tied "
                    "to defined program outcomes. Honors students get access "
                    "to innovative project and research opportunities "
                    "highlighted through its Honors Spotlights.",
                    lab_or_program="John Martinson Honors Program",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["honors", "experiential learning",
                              "undergraduate research"],
                ),
                program(
                    "khoury_undergraduate_research",
                    "Khoury College Undergraduate Research — Honors in the Discipline / research co-op / independent study",
                    "https://www.khoury.northeastern.edu/undergraduate-research/",
                    "Khoury College channels undergraduate research through "
                    "three distinct pathways: the Honors in the Discipline "
                    "program, a paid research co-op, or independent study for "
                    "credit. Students collaborate directly with Khoury faculty "
                    "researchers on complex research problems, preparing for "
                    "industry and graduate programs.",
                    lab_or_program="Khoury Undergraduate Research",
                    department="Khoury College of Computer Sciences",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    eligibility_majors=["Computer Science", "Cybersecurity",
                                       "Data Science"],
                    keywords=["computer science", "research co-op",
                              "honors in the discipline", "independent study"],
                ),
                program(
                    "msc_summer_internship",
                    "Marine Science Center Summer Research Internship (Northeastern)",
                    "https://cos.northeastern.edu/marinescience/msc-summer-internship/",
                    "The Department of Marine and Environmental Sciences and "
                    "the Marine Science Center offer Summer Research "
                    "Internships for Northeastern undergraduates at the Nahant "
                    "coastal campus, with Summer 2026 applications due Friday, "
                    "February 13th. Research areas span behavioral and "
                    "evolutionary ecology, climate change and ocean "
                    "acidification, coastal marine ecology, marine molecular "
                    "biology and genomics, and coral reef ecology.",
                    lab_or_program="Marine Science Center",
                    department="Department of Marine and Environmental Sciences",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior"],
                    eligibility_majors=["Marine and Environmental Sciences", "Biology"],
                    deadline_note="Summer 2026 applications were due Friday, February 13; annual cycle.",
                    keywords=["marine science", "summer research", "internship",
                              "ecology", "ocean"],
                ),
                program(
                    "urf_fellowships_scholarships",
                    "URF Fellowships & Scholarships Advising (Northeastern)",
                    "https://undergraduate.northeastern.edu/research/fellowships-scholarships/",
                    "The URF office maintains a searchable database of "
                    "national fellowships and scholarships (Rhodes, Marshall, "
                    "Schwarzman, Knight-Hennessy, Fulbright, Goldwater and "
                    "more) and advises Northeastern candidates through campus "
                    "deadlines and endorsement processes. Recent results "
                    "include 20 NSF GRFP awardees plus multiple Goldwater "
                    "Scholars and Fulbright awardees.",
                    lab_or_program="Undergraduate Research & Fellowships",
                    opportunity_type="fellowship",
                    preferred_year=["junior", "senior"],
                    keywords=["fellowships", "scholarships", "Fulbright",
                              "Goldwater", "NSF GRFP", "advising"],
                ),
            ],
        },
    ],
}
