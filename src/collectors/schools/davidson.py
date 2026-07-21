"""Davidson College campus opportunity-graph config.

Curated seed records of Davidson's undergraduate-research landscape, centered
on the college's flagship summer program (the Davidson Research Initiative) and
its named endowed fellowships and grants: the Abernethy Endowment Grant, the
Kemp Scholars Program, the Davidson Research Network (health-sciences summer
placements), the R. Craig and Sheila Yoder Applied Research Fellowship, the
Research in Science Experience (RISE) early-research program for rising
sophomores, the DRI partnership for students from regional HBCUs, and the
NSF Research Experiences for Undergraduates (REU) portal. URLs curl-verified
live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → davidson_research_programs (davidson / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_UGR = "https://www.davidson.edu/academics/research-opportunities/undergraduate-research"

SCHOOL: dict = {
    "school_slug": "davidson",
    "organization": "Davidson College",
    "location": "Davidson, NC",
    "emit": {
        "campus": ("davidson_research_programs", "davidson", "campus"),
    },
    "sources": [
        {
            "source_name": "davidson_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _UGR,
                "https://www.davidson.edu/academics/research-opportunities",
            ],
            "programs": [
                program(
                    "davidson_dri",
                    "Davidson Research Initiative (DRI)",
                    f"{_UGR}/davidson-research-initiative",
                    "Davidson's flagship summer research program: students "
                    "receive a stipend for eight to ten weeks of full-time "
                    "collaborative research with a faculty or staff mentor, in "
                    "any discipline, plus summer housing and a research-methods "
                    "training component, culminating in a fall symposium.",
                    lab_or_program="Davidson Research Initiative",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "any discipline"],
                ),
                program(
                    "davidson_abernethy",
                    "Abernethy Endowment Grant (Davidson)",
                    f"{_UGR}/abernethy-endowment-grant",
                    "Endowed grants (averaging about $2,000, ranging up to "
                    "$5,900) funding independent student research projects "
                    "during the academic year or summer, in the United States "
                    "or abroad, across any field of study.",
                    lab_or_program="Abernethy Endowment",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "independent research",
                              "any discipline", "study abroad"],
                ),
                program(
                    "davidson_kemp",
                    "Kemp Scholars Program (Davidson)",
                    f"{_UGR}/kemp-scholars-program",
                    "The Kemp Endowment supports independent student research "
                    "in any discipline, in the United States or abroad, "
                    "pairing scholars with faculty mentors for a self-designed "
                    "project.",
                    lab_or_program="Kemp Scholars",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["independent research", "faculty mentor",
                              "any discipline", "scholarship"],
                ),
                program(
                    "davidson_rise",
                    "Research in Science Experience (RISE) (Davidson)",
                    f"{_UGR}/research-science-experience",
                    "An early-research summer program for rising sophomores "
                    "interested in careers in science or medicine, introducing "
                    "students to faculty-mentored laboratory research in the "
                    "natural sciences.",
                    lab_or_program="Research in Science Experience",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["early research", "science", "laboratory",
                              "faculty mentor"],
                ),
                program(
                    "davidson_research_network",
                    "Davidson Research Network (DRN)",
                    f"{_UGR}/davidson-research-network",
                    "An off-campus summer research experience of roughly eight "
                    "weeks for Davidson students planning careers in the health "
                    "sciences, placing students in research labs at partner "
                    "institutions.",
                    lab_or_program="Davidson Research Network",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["health sciences", "summer research",
                              "off-campus", "biomedical"],
                ),
                program(
                    "davidson_yoder",
                    "R. Craig and Sheila Yoder Applied Research Fellowship (Davidson)",
                    f"{_UGR}/r-craig-and-sheila-yoder-applied-research-fellowship",
                    "Supports one student each summer for applied research "
                    "conducted jointly with a Davidson faculty member and an "
                    "external mentor, bridging academic and real-world "
                    "research.",
                    lab_or_program="Yoder Applied Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["applied research", "faculty mentor",
                              "external mentor", "summer"],
                ),
                program(
                    "davidson_dri_hbcu",
                    "DRI for Historically Black Colleges and Universities (Davidson)",
                    f"{_UGR}/davidson-research-initiative/"
                    "dri-historically-black-colleges-and-universities",
                    "A Davidson Research Initiative partnership inviting rising "
                    "juniors and seniors from regional Historically Black "
                    "Colleges and Universities to a mentored summer research "
                    "experience at Davidson.",
                    lab_or_program="Davidson Research Initiative",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["summer research", "HBCU", "faculty mentor",
                              "diversity in research"],
                ),
                program(
                    "davidson_nsf_reu",
                    "NSF Research Experiences for Undergraduates (REU) (Davidson)",
                    f"{_UGR}/nsf-research-experience-undergraduates",
                    "Davidson's portal to the National Science Foundation's "
                    "Research Experiences for Undergraduates program — funded "
                    "summer research placements at host sites nationwide across "
                    "science, math, and engineering fields.",
                    lab_or_program="NSF REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["NSF", "summer research", "STEM",
                              "national program"],
                ),
            ],
        },
    ],
}
