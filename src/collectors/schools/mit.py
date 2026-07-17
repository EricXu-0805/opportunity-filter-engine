"""MIT campus opportunity-graph config.

Curated seed records of MIT's undergraduate-research landscape, anchored on
UROP — the original undergraduate research program (1969) — plus SuperUROP,
the graduate-pipeline MSRP, and the practice/impact programs students use to
get into labs and projects. URLs verified live (HTTP 200) on 2026-07-15.
Note superurop.eecs.mit.edu is dead DNS — the canonical host is
superurop.mit.edu; msrp.mit.edu redirects to a SlideRoom application portal,
so the OGE info page is wired instead. MIT's Amgen Scholars hosting has
ended (all candidate URLs dead) — deliberately not wired.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → mit_research_programs (mit / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

SCHOOL: dict = {
    "school_slug": "mit",
    "organization": "Massachusetts Institute of Technology",
    "location": "Cambridge, MA",
    "emit": {
        "campus": ("mit_research_programs", "mit", "campus"),
    },
    "sources": [
        {
            "source_name": "mit_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                "https://urop.mit.edu/",
                "https://superurop.mit.edu/",
                "https://oge.mit.edu/msrp/",
            ],
            "programs": [
                program(
                    "urop",
                    "UROP — Undergraduate Research Opportunities Program (MIT)",
                    "https://urop.mit.edu/",
                    "UROP is MIT's flagship undergraduate research program — "
                    "running since 1969, it cultivates research partnerships "
                    "between undergraduates and faculty in every department, "
                    "year-round, for pay, academic credit, or as a volunteer. "
                    "Most MIT students do at least one UROP; students propose a "
                    "project directly with a supervisor or answer posted "
                    "openings.",
                    lab_or_program="UROP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "faculty mentorship", "paid research"],
                ),
                program(
                    "superurop",
                    "SuperUROP — Advanced Undergraduate Research Opportunities Program (MIT)",
                    "https://superurop.mit.edu/",
                    "SuperUROP is a yearlong, publication-oriented research "
                    "experience for MIT juniors and seniors: a scholar "
                    "designation, an accompanying two-term seminar, and a "
                    "research project deep enough to produce a publishable "
                    "result or prototype, applied to per academic-year cohort.",
                    lab_or_program="SuperUROP",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    keywords=["advanced research", "publication", "scholar program"],
                ),
                program(
                    "msrp",
                    "MSRP — MIT Summer Research Program",
                    "https://oge.mit.edu/msrp/",
                    "MSRP places non-MIT undergraduates in MIT laboratories "
                    "for a funded summer research internship with faculty "
                    "mentorship, aimed at preparing and recruiting talented "
                    "students — especially from underrepresented backgrounds — "
                    "for graduate school.",
                    lab_or_program="MIT Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "graduate pipeline"],
                ),
                program(
                    "upop",
                    "UPOP — Undergraduate Practice Opportunities Program (MIT)",
                    "https://upop.mit.edu/",
                    "UPOP is MIT's yearlong professional-development program "
                    "for sophomores: a team training workshop, mentoring, and "
                    "career-skills curriculum that leads into a summer "
                    "internship — the bridge between coursework and practice.",
                    lab_or_program="UPOP",
                    opportunity_type="internship",
                    preferred_year=["sophomore"],
                    international_friendly="yes",
                    keywords=["professional development", "internship"],
                ),
                program(
                    "misti",
                    "MISTI — MIT International Science and Technology Initiatives",
                    "https://misti.mit.edu/",
                    "MISTI matches MIT students with tailored internship, "
                    "research, and teaching placements abroad through its "
                    "country and regional programs — fully funded international "
                    "experiences connected to MIT's research network.",
                    lab_or_program="MISTI",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["international", "global internships", "research abroad"],
                ),
                program(
                    "sandbox",
                    "MIT Sandbox Innovation Fund",
                    "https://sandbox.mit.edu/",
                    "MIT Sandbox provides seed funding (up to ~$25k), tailored "
                    "mentoring, and entrepreneurship education for "
                    "student-initiated venture ideas — open to any MIT student "
                    "team exploring an innovation.",
                    lab_or_program="MIT Sandbox",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["entrepreneurship", "seed funding", "innovation"],
                ),
                program(
                    "edgerton",
                    "Edgerton Center — Student Projects and Shops (MIT)",
                    "https://edgerton.mit.edu/",
                    "The Edgerton Center is MIT's hands-on maker home: student "
                    "shops, engineering fabrication support, and long-running "
                    "student project teams (rocketry, solar racing, and more) "
                    "where undergraduates build real hardware.",
                    lab_or_program="Edgerton Center",
                    opportunity_type="research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["maker", "student teams", "engineering projects"],
                ),
                program(
                    "pkg",
                    "PKG Center — Social Impact Internships and Fellowships (MIT)",
                    "https://pkgcenter.mit.edu/",
                    "The Priscilla King Gray Center runs MIT's social-impact "
                    "internships, fellowships, and public-service project "
                    "programs, funding students to apply their skills to "
                    "community and public-interest work.",
                    lab_or_program="PKG Center",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["social impact", "public service", "fellowship"],
                ),
            ],
        },
    ],
}
