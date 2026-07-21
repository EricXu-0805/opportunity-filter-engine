"""Amherst College campus opportunity-graph config.

Curated seed records of Amherst College's undergraduate-research landscape,
centered on the college-wide Student-Faculty Research hub and its named
summer-research fellowships. Amherst is an undergraduate-only liberal arts
college, so nearly all research is student-faculty collaboration funded
through these programs. All URLs curl-verified live (HTTP 200) on 2026-07-21.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → amherst_research_programs (amherst / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_SFR = "https://www.amherst.edu/academiclife/student-faculty-research"

SCHOOL: dict = {
    "school_slug": "amherst",
    "organization": "Amherst College",
    "location": "Amherst, MA",
    "emit": {
        "campus": ("amherst_research_programs", "amherst", "campus"),
    },
    "sources": [
        {
            "source_name": "amherst_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [
                _SFR,
                _SFR + "/funding-for-student-research",
                _SFR + "/surf-program",
            ],
            "programs": [
                program(
                    "amherst_student_faculty_research",
                    "Student-Faculty Research (Amherst College)",
                    _SFR,
                    "Amherst College's college-wide hub for student-faculty "
                    "research. As an undergraduate-only liberal arts college, "
                    "Amherst centers hands-on collaborative research with "
                    "faculty across the sciences, social sciences, humanities, "
                    "and arts, funded through a family of named summer and "
                    "term-time fellowships and research awards.",
                    lab_or_program="Student-Faculty Research",
                    opportunity_type="research",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["undergraduate research", "student-faculty research",
                              "any major", "mentored research"],
                ),
                program(
                    "amherst_surf",
                    "Summer Science Undergraduate Research Fellowships (SURF) "
                    "(Amherst College)",
                    _SFR + "/surf-program",
                    "SURF is an 8-week on-campus summer program (typically "
                    "starting in early June) whose mission is to give students "
                    "their first immersive research experience. SURF fellows "
                    "work closely with a STEM faculty mentor on a research "
                    "project that culminates in a poster presentation at the "
                    "start of the fall session.",
                    lab_or_program="Summer Science Undergraduate Research Fellowships",
                    opportunity_type="summer_program",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["summer research", "STEM", "faculty mentor",
                              "laboratory research"],
                ),
                program(
                    "amherst_call_summer",
                    "Gregory S. Call Summer Research Awards (Amherst College)",
                    _SFR + "/gregory-s-call-summer-resarch-awards",
                    "The Gregory S. Call Summer Student Research Program "
                    "supports rising seniors conducting thesis work over an "
                    "eight-week summer term, with housing and meals provided "
                    "for students performing their thesis research on campus. "
                    "The program funds independent, faculty-advised research "
                    "across the disciplines.",
                    lab_or_program="Gregory S. Call Academic Internship Program",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["junior", "senior"],
                    keywords=["summer research", "senior thesis",
                              "faculty-advised research", "research award"],
                ),
                program(
                    "amherst_call_termtime",
                    "Gregory S. Call Fall and Spring Research Awards "
                    "(Amherst College)",
                    _SFR + "/funding-for-student-research",
                    "Support for student term-time research and conference "
                    "travel of up to $1,000 from the Gregory S. Call Student "
                    "Research Program and related funds, supporting research "
                    "across disciplines during the academic year.",
                    lab_or_program="Gregory S. Call Academic Internship Program",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["term-time research", "conference travel",
                              "research funding", "any major"],
                ),
                program(
                    "amherst_call_interns",
                    "Gregory S. Call Academic Interns (Amherst College)",
                    _SFR + "/academicinterns",
                    "The Gregory S. Call Academic Intern program places "
                    "students as paid research assistants working directly "
                    "with Amherst faculty on their scholarly projects — for "
                    "example analyzing data from field experiments — building "
                    "research skills through sustained faculty collaboration.",
                    lab_or_program="Gregory S. Call Academic Internship Program",
                    opportunity_type="research",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research assistant", "faculty collaboration",
                              "academic internship", "mentored research"],
                ),
                program(
                    "amherst_schupf",
                    "Schupf Fellows Program (Amherst College)",
                    _SFR + "/schupf",
                    "Schupf Fellows engage in intensive summer research in the "
                    "arts, humanities, and social sciences. A cohort of about "
                    "twenty rising Amherst sophomores and juniors is funded "
                    "each year through a competitive selection process to "
                    "carry out eight weeks of summer research with a faculty "
                    "member.",
                    lab_or_program="Schupf Fellows Program",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["sophomore", "junior"],
                    keywords=["arts and humanities", "social sciences",
                              "summer research", "faculty-mentored research"],
                ),
                program(
                    "amherst_post_bacc",
                    "Post-Baccalaureate Summer Research Fellowship "
                    "(Amherst College)",
                    _SFR + "/post-baccalaureate-fellowship",
                    "Faculty nominate graduating seniors who have completed a "
                    "project (honors thesis, seminar paper, or essay) of "
                    "exceptionally high quality with potential for publication. "
                    "Fellows receive a $5,000 stipend for eight weeks of summer "
                    "work with a faculty advisor to develop the project toward "
                    "publication.",
                    lab_or_program="Post-Baccalaureate Summer Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["senior"],
                    deadline_note="By faculty nomination of graduating seniors.",
                    keywords=["post-baccalaureate", "senior thesis",
                              "publication", "faculty-advised research"],
                ),
                program(
                    "amherst_summer_bridge_institute",
                    "Summer Bridge Research Institute (Amherst College)",
                    _SFR + "/summer-bridge-institute",
                    "The Summer Bridge Research Institute introduces "
                    "participants to research traditions, approaches, and "
                    "procedures in the humanities and social sciences, helping "
                    "students develop research skills that provide building "
                    "blocks for further coursework and research-intensive "
                    "careers.",
                    lab_or_program="Summer Bridge Research Institute",
                    opportunity_type="summer_program",
                    paid="stipend",
                    international_friendly="yes",
                    preferred_year=["freshman", "sophomore"],
                    keywords=["humanities", "social sciences", "research skills",
                              "summer program"],
                ),
                program(
                    "amherst_varmus_scholars",
                    "Harold Varmus 1961 International Scholars (Amherst College)",
                    _SFR + "/varmus-international-scholars",
                    "The Harold Varmus 1961 International Scholars Fund supports "
                    "Amherst students pursuing independent scholarly work — "
                    "approved by a faculty sponsor, in any field — outside the "
                    "United States for eight weeks to six months. Scholars "
                    "receive a $10,000 fellowship covering transportation, "
                    "living, and research expenses, and may work in research "
                    "laboratories abroad, including in underserved or "
                    "developing regions. Preference is given to rising seniors.",
                    lab_or_program="Harold Varmus International Scholars Fund",
                    opportunity_type="fellowship",
                    paid="stipend",
                    international_friendly="unknown",
                    preferred_year=["junior", "senior"],
                    keywords=["international research", "study abroad",
                              "independent scholarship", "fieldwork"],
                ),
            ],
        },
    ],
}
