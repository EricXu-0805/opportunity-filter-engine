"""Swarthmore College campus opportunity-graph config.

Curated seed records of Swarthmore's undergraduate-research and funded-summer
landscape. As a top-10 liberal arts college, Swarthmore's research pipeline is
built on named summer fellowships and student-faculty research grants rather
than large lab centers: the college-wide Summer Opportunities program and
Student & Faculty Research hub, the President's Sustainability Research
Fellowship, the Mellon Mays Undergraduate Fellowship, the Lang Center's
civic/engaged-research grants (FLER, Chester Community Fellowship, Lang
Opportunity Scholarship, Social Impact Summer Scholarship), the Center for
Innovation and Leadership summer fund, and the Summer Scholars Program. All
URLs curl-verified live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → swarthmore_research_programs (swarthmore / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_B = "https://www.swarthmore.edu"

SCHOOL: dict = {
    "school_slug": "swarthmore",
    "organization": "Swarthmore College",
    "location": "Swarthmore, PA",
    "emit": {
        "campus": ("swarthmore_research_programs", "swarthmore", "campus"),
    },
    "sources": [
        {
            "source_name": "swarthmore_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _B + "/research",
                _B + "/academics/student-faculty-research",
                _B + "/summer-opportunities",
                _B + "/lang-center",
            ],
            "programs": [
                program(
                    "swarthmore_summer_opportunities",
                    "Swarthmore Summer Opportunities (Funded Summer Research & Internships)",
                    _B + "/summer-opportunities",
                    "Swarthmore's college-wide portal for funded summer "
                    "opportunities, coordinating the many stipends and "
                    "fellowships that let students spend the summer on faculty "
                    "research, independent projects, or internships. Academic "
                    "departments and programs across the sciences, social "
                    "sciences, humanities, and arts each run summer research "
                    "funding, and the office manages a shared application "
                    "process, eligibility rules, and deadlines so any student "
                    "can find summer support in their field.",
                    lab_or_program="Summer Opportunities",
                    opportunity_type="summer_program",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Most summer funding applications are due in "
                                  "late winter / early spring; deadlines vary "
                                  "by department and program.",
                    keywords=["summer research", "funded summer", "any major",
                              "research stipend"],
                ),
                program(
                    "swarthmore_student_faculty_research",
                    "Student & Faculty Research (Swarthmore College)",
                    _B + "/academics/student-faculty-research",
                    "At Swarthmore, undergraduates collaborate directly with "
                    "faculty on original research across every division — from "
                    "NSF-funded physics and computing projects to fieldwork in "
                    "the social sciences and archival scholarship in the "
                    "humanities. Small classes and no graduate students mean "
                    "undergraduates take on substantive roles as research "
                    "partners, often continuing during the funded summer term "
                    "and toward Honors and senior theses.",
                    lab_or_program="Student & Faculty Research",
                    opportunity_type="research",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["faculty-mentored research", "undergraduate research",
                              "any major", "honors thesis"],
                ),
                program(
                    "swarthmore_psrf",
                    "President's Sustainability Research Fellowship (Swarthmore College)",
                    _B + "/sustainability/presidents-sustainability-research-fellowship",
                    "The President's Sustainability Research Fellowship (PSRF) "
                    "is a multi-semester program in which Swarthmore students "
                    "design and carry out applied sustainability research "
                    "projects — spanning environmental science, policy, social "
                    "justice, and campus operations — mentored by faculty and "
                    "staff and supported by a summer research stipend, "
                    "culminating in a public capstone.",
                    lab_or_program="President's Sustainability Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["sophomore", "junior"],
                    keywords=["sustainability", "environmental research",
                              "applied research", "climate"],
                ),
                program(
                    "swarthmore_mellon_mays",
                    "Mellon Mays Undergraduate Fellowship (Swarthmore College)",
                    _B + "/mellon-mays",
                    "The Mellon Mays Undergraduate Fellowship (MMUF) prepares "
                    "students from underrepresented groups for PhD study and "
                    "academic careers in the humanities and select social and "
                    "natural sciences. Swarthmore fellows receive multi-year "
                    "faculty mentorship, funded summer research, a research "
                    "stipend, conference support, and a scholarly community "
                    "aimed at broadening the range of perspectives in the "
                    "academy.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="unknown",
                    preferred_year=["sophomore", "junior"],
                    keywords=["Mellon Mays", "PhD pathway", "humanities research",
                              "mentored research"],
                ),
                program(
                    "swarthmore_fler_grant",
                    "Faculty-Led Engaged Research (FLER) Grant (Swarthmore College)",
                    _B + "/lang-center/faculty-led-engaged-research-fler-grant",
                    "Administered by the Lang Center for Civic & Social "
                    "Responsibility, Faculty-Led Engaged Research (FLER) grants "
                    "fund faculty-student teams conducting community-based, "
                    "publicly engaged research in partnership with community "
                    "organizations. Students join a faculty member's engaged "
                    "scholarship project — often over the summer — connecting "
                    "academic inquiry with real-world social impact.",
                    lab_or_program="Lang Center for Civic & Social Responsibility",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["engaged research", "community-based research",
                              "faculty-student team", "social impact"],
                ),
                program(
                    "swarthmore_chester_community_fellowship",
                    "Chester Community Fellowship (Swarthmore College)",
                    _B + "/lang-center/chester-community-fellowship",
                    "The Chester Community Fellowship, run through the Lang "
                    "Center, places Swarthmore students in sustained, funded "
                    "summer work with community organizations in nearby Chester, "
                    "Pennsylvania. Fellows pursue engaged-scholarship and "
                    "action-research projects addressing education, health, and "
                    "community development alongside local partners.",
                    lab_or_program="Lang Center for Civic & Social Responsibility",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["community engagement", "Chester", "action research",
                              "social impact"],
                ),
                program(
                    "swarthmore_lang_opportunity_scholarship",
                    "Lang Opportunity Scholarship Program (Swarthmore College)",
                    _B + "/lang-center/lang-opportunity-scholarship-program",
                    "The Lang Opportunity Scholarship supports a small cohort of "
                    "Swarthmore students who design and implement an ambitious "
                    "social-change project addressing a significant community "
                    "need, in the US or abroad. Scholars receive multi-year "
                    "funding, mentorship, and summer support to research, build, "
                    "and sustain their initiative.",
                    lab_or_program="Lang Center for Civic & Social Responsibility",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["social change", "civic engagement", "project grant",
                              "leadership"],
                ),
                program(
                    "swarthmore_social_impact_summer_scholarship",
                    "Social Impact Summer Scholarship (Swarthmore College)",
                    _B + "/lang-center/social-impact-summer-scholarship",
                    "The Lang Center's Social Impact Summer Scholarship funds "
                    "Swarthmore students to spend the summer interning with a "
                    "nonprofit, NGO, or government agency working on a pressing "
                    "social issue, pairing hands-on public-interest experience "
                    "with reflection on engaged citizenship.",
                    lab_or_program="Lang Center for Civic & Social Responsibility",
                    opportunity_type="internship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["social impact", "nonprofit internship",
                              "public interest", "summer stipend"],
                ),
                program(
                    "swarthmore_cil_summer_fund",
                    "Center for Innovation and Leadership Summer Fund (Swarthmore College)",
                    _B + "/center-innovation-leadership/cil-funding",
                    "The Center for Innovation and Leadership (CIL) Summer Fund "
                    "provides stipends for Swarthmore students to pursue "
                    "entrepreneurial ventures, innovation projects, and "
                    "leadership-focused summer work, including research and "
                    "prototyping that turns an idea into a real-world "
                    "initiative.",
                    lab_or_program="Center for Innovation and Leadership",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["innovation", "entrepreneurship", "leadership",
                              "summer project"],
                ),
                program(
                    "swarthmore_summer_scholars_program",
                    "Summer Scholars Program (Swarthmore College)",
                    _B + "/summer-scholars-program",
                    "The Summer Scholars Program is a bridge experience that "
                    "brings incoming and early Swarthmore students to campus "
                    "for an immersive introduction to college-level academic "
                    "work and research skills, with faculty and peer mentorship "
                    "that expands access to Swarthmore's research and Honors "
                    "opportunities.",
                    lab_or_program="Summer Scholars Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    international_friendly="unknown",
                    preferred_year=["freshman"],
                    keywords=["bridge program", "academic preparation",
                              "mentorship", "research skills"],
                ),
            ],
        },
    ],
}
