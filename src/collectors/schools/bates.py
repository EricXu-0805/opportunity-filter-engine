"""Bates College campus opportunity-graph config.

Curated seed records of Bates's undergraduate-research landscape, centered on
the college's Summer Research Fellowships and its named endowed summer grants
and fellowships administered through the Office of the Dean of the Faculty
(Phillips, Otis, Hoffman, Bouley-Creasy, Technos), plus the academic-year
research grants, the environmentally focused internships, the Harward Center's
community-engagement fellowships, the Center for Purposeful Work internships,
and the sustainability office's Green Innovation Grant. Every URL was
curl-verified live (HTTP 200) on 2026-07-23.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → bates_research_programs (bates / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_SR = "https://www.bates.edu/academics/student-research"

SCHOOL: dict = {
    "school_slug": "bates",
    "organization": "Bates College",
    "location": "Lewiston, ME",
    "emit": {
        "campus": ("bates_research_programs", "bates", "campus"),
    },
    "sources": [
        {
            "source_name": "bates_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                f"{_SR}/",
                f"{_SR}/summer/",
                f"{_SR}/summer-grants-summary/",
                "https://www.bates.edu/academics/research-opportunities/",
            ],
            "programs": [
                program(
                    "bates_summer_research_fellowships",
                    "Bates Summer Research Fellowships (SRF)",
                    f"{_SR}/summer/summer-research-fellowships/",
                    "Bates's flagship summer research program: fellows undertake "
                    "a project under the direction of a Bates faculty advisor (or "
                    "a specialist at another institution), devoting at least eight "
                    "weeks of full-time work (~40 hours/week) to research, broadly "
                    "defined to include artistic practice, and receive a summer "
                    "stipend.",
                    lab_or_program="Summer Research Fellowships",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["summer research", "faculty advisor", "stipend",
                              "any discipline"],
                ),
                program(
                    "bates_phillips_fellowship",
                    "Phillips Student Fellowships (Bates)",
                    f"{_SR}/summer-grants-summary/phillips-student-fellowships/",
                    "Endowed fellowships supporting purposeful, independent "
                    "student-designed exploration and research in international "
                    "and other culturally distinct settings, inspired by the "
                    "Watson Fellowship model and funded by the bequest of "
                    "President Charles F. Phillips and Evelyn M. Phillips.",
                    lab_or_program="Phillips Student Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["independent research", "international",
                              "self-designed project", "fellowship"],
                ),
                program(
                    "bates_otis_fellowship",
                    "Otis Fellowships (Bates)",
                    f"{_SR}/summer-grants-summary/otis/",
                    "Fellowships in memory of Phil Otis '95 that fund summer "
                    "projects exploring the natural world and humanity's "
                    "relationship to the environment, encouraging innovative "
                    "study of and reflection on the consequences of human action "
                    "for other living things.",
                    lab_or_program="Otis Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["environment", "nature", "summer research",
                              "sustainability"],
                ),
                program(
                    "bates_hoffman_grant",
                    "Hoffman Research Support Grant (Bates)",
                    f"{_SR}/summer-grants-summary/hoffman-research-support-grant/",
                    "Grants supporting students in all disciplines engaged in "
                    "summer research: funds can cover travel to a research site, "
                    "research supplies, or other project expenses, and may be "
                    "combined with other sources of support such as a faculty "
                    "research grant.",
                    lab_or_program="Hoffman Research Support Grant",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "summer research", "any discipline",
                              "research travel"],
                ),
                program(
                    "bates_bouley_creasy_fund",
                    "Bouley-Creasy Fund for Earth and Climate Sciences (Bates)",
                    f"{_SR}/summer-grants-summary/bouley-fund-for-geology/",
                    "Endowed funds enabling juniors in the Department of Earth and "
                    "Climate Sciences to support senior thesis research, "
                    "established in memory of Bruce Bouley and John Creasy.",
                    lab_or_program="Bouley-Creasy Fund",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["junior"],
                    international_friendly="unknown",
                    keywords=["earth sciences", "climate science", "thesis research",
                              "geology"],
                ),
                program(
                    "bates_technos_fellowship",
                    "Technos International Week Fellowship (Bates)",
                    f"{_SR}/summer-grants-summary/technos-international-week-in-japan/",
                    "A fully funded fellowship sending selected Bates students to "
                    "Technos International Week in Japan for a cross-cultural "
                    "exchange program alongside students from around the world.",
                    lab_or_program="Technos International Week",
                    opportunity_type="fellowship",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["international", "Japan", "cultural exchange",
                              "fellowship"],
                ),
                program(
                    "bates_environmental_internship",
                    "Bates Environmental Internships",
                    f"{_SR}/summer/bates-environmental-internship/",
                    "Funded summer internships placing students with "
                    "environmental organizations and research projects, giving "
                    "hands-on experience in conservation, environmental science, "
                    "and sustainability fieldwork.",
                    lab_or_program="Bates Environmental Internships",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["environment", "internship", "conservation",
                              "sustainability"],
                ),
                program(
                    "bates_academic_year_grants",
                    "Academic Year Research Grants (Bates)",
                    f"{_SR}/academic-year/",
                    "Grants supporting student research conducted during the "
                    "academic year across all disciplines, funding project "
                    "expenses, materials, and research-related travel in "
                    "collaboration with a faculty mentor.",
                    lab_or_program="Academic Year Research Grants",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["research grant", "academic year", "faculty mentor",
                              "any discipline"],
                ),
                program(
                    "bates_harward_fellowships",
                    "Harward Center Community-Engaged Summer Fellowships (Bates)",
                    "https://www.bates.edu/harward/paid-positions/",
                    "Paid summer fellowships through the Harward Center for "
                    "Community Partnerships, placing students in community-engaged "
                    "research and project work with local organizations in "
                    "Lewiston-Auburn and beyond.",
                    lab_or_program="Harward Center Fellowships",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["community-engaged", "civic research", "summer",
                              "public interest"],
                ),
                program(
                    "bates_purposeful_work_internships",
                    "Purposeful Work Internship Program (Bates)",
                    "https://www.bates.edu/purposeful-work/purposeful-work-internships-2/",
                    "The Center for Purposeful Work funds summer internships "
                    "across industries and nonprofits, providing a stipend so "
                    "students can pursue substantive, career-exploring experiences "
                    "regardless of whether the host site pays.",
                    lab_or_program="Purposeful Work Internships",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["internship", "career exploration", "stipend",
                              "professional experience"],
                ),
                program(
                    "bates_green_innovation_grant",
                    "Bates Green Innovation Grant",
                    "https://www.bates.edu/sustainability/bates-green-innovation-grant/",
                    "A sustainability-office grant program funding student, "
                    "faculty, and staff proposals that solve a campus "
                    "sustainability problem or advance environmental innovation "
                    "at the college.",
                    lab_or_program="Green Innovation Grant",
                    opportunity_type="research",
                    paid="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["sustainability", "campus innovation",
                              "environment", "project grant"],
                ),
            ],
        },
    ],
}
