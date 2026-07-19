"""University of Georgia campus opportunity-graph config.

Curated seed records of UGA's undergraduate-research landscape, centered on
CURO (the Center for Undergraduate Research Opportunities, run by the Morehead
Honors College) — its Research Award / Summer Fellowship / Honors Scholarship
funding routes and the annual CURO Symposium — plus the Foundation Fellowship's
research grants and the NSF Population Biology of Infectious Diseases REU at
the Odum School / CEID. URLs verified live (HTTP 200) on 2026-07-18.

Deferred (from the 2026-07-18 recon):
* Nanotechnology & Biomedicine REU (reu.engr.uga.edu) — site is live but its
  newest cohort pages are 2017/2018; recurrence unverifiable, so it stays out
  until a current cycle appears.
* reu.uga.edu / a central REU hub — does not exist; CURO is the campus portal.
* Innovation District — entrepreneurship ecosystem, not a recurring
  undergraduate research program.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uga_research_programs (uga / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "uga",
    "organization": "University of Georgia",
    "location": "Athens, GA",
    "emit": {
        "campus": ("uga_research_programs", "uga", "campus"),
    },
    "sources": [
        {
            "source_name": "uga_curo_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://curo.uga.edu/",
                "https://curo.uga.edu/students/curo-research-award/",
                "https://reu.ecology.uga.edu/",
            ],
            "programs": [
                program(
                    "curo_research_award",
                    "CURO Research Award — University of Georgia",
                    "https://curo.uga.edu/students/curo-research-award/",
                    "The Center for Undergraduate Research Opportunities awards "
                    "500 scholarships of $1,000 each year to University of "
                    "Georgia undergraduates conducting faculty-mentored "
                    "research in any discipline. The award covers one semester "
                    "(fall, spring, or summer) and qualifies for Experiential "
                    "Learning credit when the student presents at the spring "
                    "CURO Symposium — UGA's flagship on-ramp into paid "
                    "undergraduate research.",
                    lab_or_program="Center for Undergraduate Research Opportunities (CURO)",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$1,000 scholarship for one semester",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Per-semester deadlines (e.g. November 1 for spring)",
                    keywords=["undergraduate research", "research scholarship",
                              "faculty-mentored", "any discipline", "stipend"],
                ),
                program(
                    "curo_summer_fellowship",
                    "CURO Summer Research Fellowship — University of Georgia",
                    "https://curo.uga.edu/students/summer-research-fellowship/",
                    "The CURO Summer Research Fellowship supports intensive, "
                    "immersive faculty-mentored research over the summer, "
                    "pairing a $3,000 scholarship with collaborative "
                    "workshops, lectures, and cohort events. Open to any UGA "
                    "undergraduate who remains enrolled through the following "
                    "spring term — the deepest of CURO's funding routes.",
                    lab_or_program="Center for Undergraduate Research Opportunities (CURO)",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="$3,000 scholarship",
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Annual application, deadline March 15",
                    keywords=["summer research", "fellowship", "cohort",
                              "faculty-mentored", "stipend"],
                ),
                program(
                    "curo_honors_scholarship",
                    "CURO Honors Scholarship — University of Georgia",
                    "https://curo.uga.edu/students/curo-honors-scholarship/",
                    "UGA's top undergraduate research scholarship, offered "
                    "jointly by the Morehead Honors College and CURO: $3,000 "
                    "per year, renewable for up to four years. Awarded to "
                    "incoming first-year students interested in research in "
                    "any field — prior research experience is not required, "
                    "but recipients engage in faculty-mentored research each "
                    "year to renew.",
                    lab_or_program="Morehead Honors College / CURO",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$3,000/year, renewable up to four years",
                    preferred_year=["freshman"],
                    keywords=["honors scholarship", "first-year",
                              "undergraduate research", "renewable award"],
                ),
                program(
                    "curo_symposium",
                    "CURO Symposium — University of Georgia",
                    "https://curo.uga.edu/symposium/",
                    "The annual campus-wide CURO Symposium is where UGA "
                    "undergraduates present faculty-mentored research as oral "
                    "or poster presentations, with Best Paper Awards across "
                    "disciplines. Presenting here also completes the "
                    "Experiential Learning requirement attached to the CURO "
                    "Research Award and counts toward the CURO Graduation "
                    "Distinction — the natural endpoint for a semester of "
                    "campus research.",
                    lab_or_program="Center for Undergraduate Research Opportunities (CURO)",
                    opportunity_type="research",
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Annual; presenter application opens early January",
                    keywords=["research symposium", "poster presentation",
                              "oral presentation", "best paper award"],
                ),
                program(
                    "curo_graduation_distinction",
                    "CURO Graduation Distinction — University of Georgia",
                    "https://curo.uga.edu/students/graduation-distinction/",
                    "A transcript research credential earned by completing "
                    "nine hours of CURO research course credit (4960R–4990R), "
                    "a CURO thesis course, and a presentation at the CURO "
                    "Symposium. The structured course sequence turns sustained "
                    "lab or independent work into graded credit and a thesis — "
                    "the multi-year research track for UGA undergraduates.",
                    lab_or_program="Center for Undergraduate Research Opportunities (CURO)",
                    opportunity_type="research",
                    paid="no",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["graduation distinction", "research course credit",
                              "undergraduate thesis", "research track"],
                ),
                program(
                    "foundation_fellowship",
                    "Foundation Fellowship — University of Georgia",
                    "https://honors.uga.edu/scholarships/prospective-students/foundation-fellowship/",
                    "UGA's premier academic scholarship, administered by the "
                    "Morehead Honors College: an annual stipend of $15,050 "
                    "in-state (plus Zell Miller) or $25,900 out-of-state, with "
                    "dedicated research and conference grants and fully funded "
                    "travel-study on top. Fellows get structured support for "
                    "undergraduate research alongside the scholarship — "
                    "awarded to incoming students via the Honors application.",
                    lab_or_program="Morehead Honors College",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$15,050/yr in-state + Zell Miller; $25,900/yr out-of-state; research and conference grants",
                    preferred_year=["freshman"],
                    deadline_note="Annual application, deadline November 1",
                    keywords=["Foundation Fellowship", "merit scholarship",
                              "research grants", "conference travel",
                              "travel-study"],
                ),
                program(
                    "ecology_infectious_disease_reu",
                    "Population Biology of Infectious Diseases REU — University of Georgia",
                    "https://reu.ecology.uga.edu/",
                    "A nine-week NSF-funded summer REU at the intersection of "
                    "quantitative and experimental infectious-disease biology, "
                    "hosted with UGA's Center for the Ecology of Infectious "
                    "Diseases. Students design experimental, computational or "
                    "modeling, and synthesis projects with faculty mentors. "
                    "Open to undergraduates from across the country; US "
                    "citizenship or permanent residency is required by NSF.",
                    lab_or_program="Odum School of Ecology / Center for the Ecology of Infectious Diseases",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="no",
                    preferred_year=["sophomore", "junior"],
                    deadline_note="Annual summer cohort; projects posted each January",
                    keywords=["NSF REU", "infectious disease", "ecology",
                              "quantitative biology", "summer research"],
                ),
            ],
        },
    ],
}
