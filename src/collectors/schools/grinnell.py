"""Grinnell College campus opportunity-graph config.

Curated seed records of Grinnell's undergraduate-research landscape, centered
on the college's flagship Mentored Advanced Project (MAP) — a semester or
summer research/creative project designed and carried out one-on-one with a
faculty mentor — plus its named research centers and fellowships: the Center
for Science in the Liberal Arts (CSLA, which funds summer science MAPs), the
Mellon Mays Undergraduate Fellowship, the Data Analysis and Social Inquiry Lab
(DASIL), the Rosenfield Program in Public Affairs, the Center for the
Humanities, the Center for Prairie Studies, the Wilson Center for Innovation
and Leadership, and the Center for Careers, Life, and Service (CLS) summer
funding hub. URLs curl-verified live (HTTP 200) on 2026-07-22.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → grinnell_research_programs (grinnell / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_BASE = "https://www.grinnell.edu"
_RES = f"{_BASE}/academics/experience/research"
_CP = f"{_BASE}/academics/centers-programs"

SCHOOL: dict = {
    "school_slug": "grinnell",
    "organization": "Grinnell College",
    "location": "Grinnell, IA",
    "emit": {
        "campus": ("grinnell_research_programs", "grinnell", "campus"),
    },
    "sources": [
        {
            "source_name": "grinnell_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _RES,
                _CP,
            ],
            "programs": [
                program(
                    "grinnell_map",
                    "Mentored Advanced Project (MAP)",
                    f"{_RES}/map",
                    "Grinnell's flagship undergraduate research experience: a "
                    "MAP is a substantial scholarly or creative project that a "
                    "student designs and carries out one-on-one with a faculty "
                    "mentor, during the academic year or as a full-time, "
                    "stipended summer project, in any discipline, often "
                    "culminating in a conference presentation or publication.",
                    lab_or_program="Mentored Advanced Project",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["mentored research", "faculty mentor",
                              "any discipline", "summer research"],
                ),
                program(
                    "grinnell_csla",
                    "Center for Science in the Liberal Arts (CSLA) — Summer Research",
                    f"{_CP}/csla",
                    "The CSLA supports and funds student-faculty collaborative "
                    "research in the sciences, including full-time summer "
                    "science MAPs, research equipment and travel grants, and "
                    "interdisciplinary science programming across the natural "
                    "sciences and mathematics.",
                    lab_or_program="Center for Science in the Liberal Arts",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer research", "science", "faculty mentor",
                              "STEM"],
                ),
                program(
                    "grinnell_mmuf",
                    "Mellon Mays Undergraduate Fellowship (Grinnell)",
                    f"{_RES}/mmuf",
                    "A selective multi-year fellowship preparing students from "
                    "groups underrepresented in the professoriate for PhD study "
                    "and academic careers, providing a mentored research "
                    "program, stipends, and support in the humanities, arts, "
                    "and select social sciences.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["mentored research", "humanities",
                              "diversity in research", "PhD preparation"],
                ),
                program(
                    "grinnell_dasil",
                    "Data Analysis and Social Inquiry Lab (DASIL)",
                    f"{_CP}/data-analysis-and-social-inquiry-lab",
                    "DASIL supports data-driven research across the social "
                    "sciences and humanities, hiring and mentoring student "
                    "research assistants and MAP students in quantitative "
                    "methods, GIS, data visualization, and social-science "
                    "data analysis.",
                    lab_or_program="Data Analysis and Social Inquiry Lab",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["data analysis", "social science", "quantitative",
                              "research assistant"],
                ),
                program(
                    "grinnell_rosenfield",
                    "Rosenfield Program in Public Affairs, International "
                    "Relations, and Human Rights",
                    f"{_CP}/rosenfield",
                    "The Rosenfield Program sponsors student research, symposia, "
                    "and mentored projects in public affairs, international "
                    "relations, and human rights, and funds student "
                    "participation in policy-related scholarship and events.",
                    lab_or_program="Rosenfield Program",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["public affairs", "international relations",
                              "human rights", "policy"],
                ),
                program(
                    "grinnell_humanities_center",
                    "Center for the Humanities — Student Research",
                    f"{_CP}/humanities",
                    "The Center for the Humanities funds and hosts "
                    "faculty-mentored student research, humanities MAPs, and "
                    "scholarly programming, connecting students with mentors "
                    "across literature, history, philosophy, religion, and the "
                    "arts.",
                    lab_or_program="Center for the Humanities",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["humanities", "faculty mentor", "mentored research",
                              "any discipline"],
                ),
                program(
                    "grinnell_prairie_studies",
                    "Center for Prairie Studies — Research and Internships",
                    f"{_CP}/prairie-studies",
                    "The Center for Prairie Studies supports interdisciplinary "
                    "student research, mentored projects, and internships "
                    "focused on the tallgrass prairie, agriculture, "
                    "environment, and rural life of the American Midwest.",
                    lab_or_program="Center for Prairie Studies",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["prairie", "environment", "interdisciplinary",
                              "field research"],
                ),
                program(
                    "grinnell_wilson",
                    "Wilson Center for Innovation and Leadership — Fellowships",
                    f"{_CP}/wilson",
                    "The Donald and Winifred Wilson Center for Innovation and "
                    "Leadership offers fellowships, grants, and mentored "
                    "projects supporting student ventures, social innovation, "
                    "and applied leadership work over the summer and academic "
                    "year.",
                    lab_or_program="Wilson Center for Innovation and Leadership",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["innovation", "entrepreneurship", "leadership",
                              "social impact"],
                ),
                program(
                    "grinnell_cls_summer",
                    "Center for Careers, Life, and Service (CLS) — Summer Funding",
                    f"{_BASE}/after-grinnell/cls",
                    "The CLS administers summer funding, internship grants, and "
                    "experiential-learning stipends that let students pursue "
                    "research, internships, and service projects — including "
                    "off-campus and international placements — with financial "
                    "support.",
                    lab_or_program="Center for Careers, Life, and Service",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer funding", "internship", "experiential "
                              "learning", "stipend"],
                ),
            ],
        },
    ],
}
