"""Hamilton College campus opportunity-graph config.

Curated seed records of Hamilton's undergraduate-research and student-funding
landscape, centered on the college's summer research programs (the Emerson
Foundation Grant, the NY6 Summer Research Fellowship, the Summer Science
Research Fellowship, the Levitt Center's public-affairs research, Kirkland
Summer Associates, and International Summer Research Funding) plus the
year-long Senior Fellowship Program and the endowed student-project funds
(the Steven Daniel Smallen Fund for Student Creativity and the umbrella
Support for Student Projects funds). URLs render-verified live (HTTP 200,
behind the site's AWS WAF challenge) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → hamilton_research_programs (hamilton / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_SR = "https://www.hamilton.edu/academics/student-research"
_PROGRAMS = f"{_SR}/programs"

SCHOOL: dict = {
    "school_slug": "hamilton",
    "organization": "Hamilton College",
    "location": "Clinton, NY",
    "emit": {
        "campus": ("hamilton_research_programs", "hamilton", "campus"),
    },
    "sources": [
        {
            "source_name": "hamilton_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _SR,
                _PROGRAMS,
                f"{_SR}/support-for-student-projects/support-for-student-projects",
            ],
            "programs": [
                program(
                    "hamilton_emerson",
                    "Emerson Foundation Grant (Hamilton)",
                    f"{_PROGRAMS}/emerson-foundation-grant",
                    "Hamilton's flagship collaborative summer research program: "
                    "students partner with a faculty member on an original "
                    "research project for the summer, receiving a stipend, and "
                    "present their work at the fall Emerson symposium. Open to "
                    "students in any discipline.",
                    lab_or_program="Emerson Foundation Grant",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty mentor", "stipend",
                              "any discipline"],
                ),
                program(
                    "hamilton_ny6",
                    "NY6 Summer Research Fellowship (Hamilton)",
                    f"{_PROGRAMS}/ny6-summer-research-fellowship",
                    "A cross-institutional summer fellowship of the New York Six "
                    "Liberal Arts Consortium: students conduct faculty-mentored "
                    "research at Hamilton or a partner college, with a stipend "
                    "and housing, culminating in a consortium research "
                    "conference.",
                    lab_or_program="NY6 Summer Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "consortium", "faculty mentor",
                              "stipend"],
                ),
                program(
                    "hamilton_summer_science",
                    "Summer Science Research Fellowship (Hamilton)",
                    f"{_PROGRAMS}/math-science/math-and-science-research",
                    "Full-time, faculty-mentored summer research in the natural "
                    "sciences and mathematics, with a stipend and on-campus "
                    "housing, for students in biology, chemistry, computer "
                    "science, geosciences, mathematics, neuroscience, physics, "
                    "and psychology.",
                    lab_or_program="Summer Science Research Fellowship",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "science", "laboratory",
                              "faculty mentor"],
                ),
                program(
                    "hamilton_levitt",
                    "Levitt Center Summer Research (Hamilton)",
                    "https://www.hamilton.edu/academics/centers/levitt",
                    "The Arthur Levitt Public Affairs Center supports "
                    "faculty-mentored summer research on public-policy and "
                    "social-science questions, pairing students with faculty on "
                    "policy-relevant projects and community-engaged research.",
                    lab_or_program="Levitt Public Affairs Center",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["public policy", "social science", "summer research",
                              "faculty mentor"],
                ),
                program(
                    "hamilton_kirkland",
                    "Kirkland Summer Associates (Hamilton)",
                    _PROGRAMS,
                    "The Kirkland Endowment funds Kirkland Summer Associates: "
                    "student research assistantships supporting faculty projects "
                    "in the humanities and arts over the summer, with a stipend.",
                    lab_or_program="Kirkland Summer Associates",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["humanities", "arts", "research assistant",
                              "summer"],
                ),
                program(
                    "hamilton_intl_summer",
                    "International Summer Research Funding (Hamilton)",
                    _PROGRAMS,
                    "Funding for Hamilton students to carry out faculty-mentored "
                    "research abroad over the summer, covering travel and "
                    "project costs for internationally focused scholarship.",
                    lab_or_program="International Summer Research Funding",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["international research", "study abroad",
                              "summer", "travel funding"],
                ),
                program(
                    "hamilton_senior_fellowship",
                    "Senior Fellowship Program (Hamilton)",
                    "https://www.hamilton.edu/academics/seniorfellows",
                    "A competitive program letting a small number of seniors "
                    "devote their entire final year to a single independent "
                    "project of their own design — scholarly, scientific, or "
                    "creative — free of the normal course schedule, working "
                    "closely with a faculty advisor.",
                    lab_or_program="Senior Fellowship Program",
                    opportunity_type="fellowship",
                    paid="unknown",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    keywords=["independent research", "senior project",
                              "faculty advisor", "self-designed"],
                ),
                program(
                    "hamilton_smallen",
                    "Steven Daniel Smallen Fund for Student Creativity (Hamilton)",
                    f"{_SR}/support-for-student-projects/support-for-student-projects",
                    "An endowed fund supporting original student creative and "
                    "scholarly projects — from independent research to artistic "
                    "and interdisciplinary work — with project grants outside "
                    "the regular curriculum.",
                    lab_or_program="Steven Daniel Smallen Fund",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["creative projects", "independent research",
                              "project grant", "interdisciplinary"],
                ),
                program(
                    "hamilton_support_projects",
                    "Support for Student Projects (Hamilton)",
                    f"{_SR}/support-for-student-projects/support-for-student-projects",
                    "Hamilton's umbrella of endowed student-project funds (the "
                    "Casstevens Family Fund, the Ingis Family Fund, and the "
                    "Academic Fund for Seniors) reimbursing costs of "
                    "faculty-sponsored independent research, conference travel, "
                    "and thesis work across disciplines.",
                    lab_or_program="Support for Student Projects",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["research grant", "independent research",
                              "conference travel", "thesis"],
                ),
            ],
        },
    ],
}
