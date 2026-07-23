"""Kenyon College campus opportunity-graph config.

Curated seed records of Kenyon's undergraduate summer-research landscape,
centered on its faculty-mentored Summer Scholars programs (the oldest being
Summer Science Scholars) and a cluster of named, endowed scholar/fellow tracks
across the divisions, plus two Ohio Five / Ohio State research partnerships.
Every Kenyon program runs up to 10 weeks over the summer and pairs a student
with a faculty mentor on a collaborative project. URLs curl-verified live
(HTTP 200) on 2026-07-22.

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> kenyon_research_programs (kenyon / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_SR = "https://www.kenyon.edu/academics/student-research"

SCHOOL: dict = {
    "school_slug": "kenyon",
    "organization": "Kenyon College",
    "location": "Gambier, OH",
    "emit": {
        "campus": ("kenyon_research_programs", "kenyon", "campus"),
    },
    "sources": [
        {
            "source_name": "kenyon_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_SR}/",
                f"{_SR}/summer/",
            ],
            "programs": [
                program(
                    "kenyon_summer_scholars",
                    "Kenyon Summer Scholars",
                    f"{_SR}/summer-scholars/",
                    "Kenyon Summer Scholars team up with faculty mentors during "
                    "the summer months on collaborative projects in the social "
                    "sciences, fine arts, and humanities, spending up to 10 weeks "
                    "on a research project. Funded by Kenyon and a grant from the "
                    "Beulah Kahler Foundation.",
                    lab_or_program="Summer Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "faculty mentor",
                              "social sciences", "humanities"],
                ),
                program(
                    "kenyon_summer_science_scholars",
                    "Summer Science Scholars (Kenyon)",
                    f"{_SR}/summer-science-scholars/",
                    "Kenyon's oldest student-faculty mentored summer program, "
                    "supporting more than 30 student-faculty pairs in the natural "
                    "sciences for up to 10 weeks of full-time laboratory and field "
                    "research.",
                    lab_or_program="Summer Science Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["summer research", "natural sciences",
                              "laboratory", "faculty mentor"],
                ),
                program(
                    "kenyon_cascade_scholars",
                    "Cascade Science Scholars (Kenyon)",
                    f"{_SR}/cascade/",
                    "An early-research program for first-year and second-year "
                    "students in the natural sciences who have no previous "
                    "research experience; scholars work up to 10 weeks over the "
                    "summer within faculty-student research teams supported by the "
                    "Summer Science program.",
                    lab_or_program="Cascade Science Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    keywords=["early research", "natural sciences",
                              "no experience required", "faculty mentor"],
                ),
                program(
                    "kenyon_community_engaged",
                    "Community-Engaged Summer Scholars (Kenyon)",
                    f"{_SR}/community-engaged-summer-research-opportunities/",
                    "The Community-Engaged Summer Scholars program brings students "
                    "and faculty together to perform community-focused research, "
                    "spending up to 10 weeks over the summer on the project.",
                    lab_or_program="Community-Engaged Summer Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["community-engaged research", "summer research",
                              "faculty mentor", "public engagement"],
                ),
                program(
                    "kenyon_csad_democracy",
                    "CSAD Democracy Scholars (Kenyon)",
                    f"{_SR}/csad-democracy-scholars-program/",
                    "Through the Center for the Study of American Democracy, "
                    "students collaborate closely with faculty as full "
                    "participants on a fundamental question, text, or theme of "
                    "American liberal democracy, for up to 10 weeks in the summer.",
                    lab_or_program="CSAD Democracy Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["American democracy", "political theory",
                              "faculty mentor", "summer research"],
                ),
                program(
                    "kenyon_tw_smith_freedom",
                    "Thomas W. Smith Future of Freedom Scholars (Kenyon)",
                    f"{_SR}/thomas-w-smith-future-of-freedom-scholars/",
                    "Students work closely with faculty to explore issues related "
                    "to the classical liberal freedoms — the rights in the Bill of "
                    "Rights, the rule of law, and the free market — and their "
                    "implications for liberal democracy, for up to 10 weeks in the "
                    "summer, supported by the Thomas W. Smith Foundation.",
                    lab_or_program="Future of Freedom Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["liberal democracy", "political theory",
                              "rule of law", "summer research"],
                ),
                program(
                    "kenyon_farm_fellow",
                    "Kenyon Farm Fellow Program",
                    f"{_SR}/farm-fellow-program/",
                    "A STEM-related student-faculty summer research fellowship "
                    "using the resources of the Kenyon Farm; the fellow works up "
                    "to 10 weeks with a STEM faculty mentor and the Farm's staff "
                    "and volunteers. Funded by the Diane Elam '80 and Nancy "
                    "Donohue Endowment for Kenyon Farm Fellows.",
                    lab_or_program="Farm Fellow Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["agricultural research", "sustainability",
                              "STEM", "faculty mentor"],
                ),
                program(
                    "kenyon_sustainability_scholars",
                    "ENVS Sustainability Scholars (Kenyon)",
                    f"{_SR}/sustainability-scholars-program/",
                    "Environmental studies majors pursue faculty-mentored research "
                    "on climate change or sustainability for up to 10 weeks in the "
                    "summer, working with staff from the Brown Family Environmental "
                    "Center, Kokosing Nature Preserve, Philander Chase Conservancy, "
                    "or the Kenyon Farm.",
                    lab_or_program="Sustainability Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["sustainability", "climate change",
                              "environmental studies", "summer research"],
                ),
                program(
                    "kenyon_adams_legal",
                    "John W. Adams Summer Scholars in Socio-Legal Studies (Kenyon)",
                    f"{_SR}/john-w-adams-summer-scholars-program-in-socio-legal-studies/",
                    "Supports the design and execution of original law-related "
                    "research; scholars receive stipends, summer housing "
                    "allowances, and funds for research materials, established by "
                    "the Foundation for Law, Justice, and Society.",
                    lab_or_program="Adams Summer Legal Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["socio-legal studies", "law and society",
                              "original research", "summer research"],
                ),
                program(
                    "kenyon_osu_pelotonia",
                    "Kenyon/OSU/Pelotonia Cancer Research Scholars",
                    f"{_SR}/osu-pelotonia/",
                    "Six undergraduates are selected each year for a competitive "
                    "10-week summer research project at Ohio State's James Cancer "
                    "Center, participating in studies on metastatic cancer "
                    "treatment and clinical management.",
                    lab_or_program="OSU/Pelotonia Cancer Research Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["cancer research", "biomedical research",
                              "off-campus", "summer research"],
                ),
                program(
                    "kenyon_ohio5_osu",
                    "Ohio Five / OSU Summer Undergraduate Research (Kenyon)",
                    "https://u.osu.edu/ohio5sure/",
                    "Ohio State University and the Five Colleges of Ohio co-sponsor "
                    "20 paid 10-week summer research internships in biochemistry, "
                    "chemistry, mathematics, physics, and statistics, pairing "
                    "interns from Kenyon and the other Ohio Five colleges with OSU "
                    "faculty and culminating in a public research forum.",
                    lab_or_program="Ohio 5/OSU Research Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["STEM research", "off-campus", "consortium",
                              "summer research"],
                ),
            ],
        },
    ],
}
