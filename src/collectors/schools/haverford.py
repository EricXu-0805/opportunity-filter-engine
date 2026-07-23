"""Haverford College campus opportunity-graph config.

Curated seed records of Haverford's undergraduate-research and funded-summer
landscape. As a small liberal-arts college with no graduate school, Haverford's
research pipeline runs through four college centers rather than large lab
institutes: the Marian E. Koshland Integrated Natural Sciences Center (KINSC)
for the sciences, the Center for Peace and Global Citizenship (CPGC) for
social-impact and global research/internships, the John B. Hurford '60 Center
for the Arts and Humanities (HCAH) for humanistic research and fellowships, and
the Office of the Provost for college-wide student-faculty research funding and
national fellowships (including Mellon Mays). Every center landing page was
rendered live (headless Chromium clearing the site's Cloudflare managed
challenge) and returned HTTP 200 on 2026-07-23; deeper program URLs are not
guessable, so each program is anchored to its administering center's verified
page.

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → haverford_research_programs (haverford / campus)
"""

from __future__ import annotations

from ..campus_graph import PROGRAM, STATIC, program

_B = "https://www.haverford.edu"
_KINSC = _B + "/kinsc"
_CPGC = _B + "/cpgc"
_HCAH = _B + "/hcah"
_PROVOST = _B + "/provost"
_PHILLY = _B + "/philly-program"

SCHOOL: dict = {
    "school_slug": "haverford",
    "organization": "Haverford College",
    "location": "Haverford, PA",
    "emit": {
        "campus": ("haverford_research_programs", "haverford", "campus"),
    },
    "sources": [
        {
            "source_name": "haverford_ugr_hub",
            "source_type": PROGRAM,
            "emit": "campus",
            "crawl": STATIC,
            "seeds": [_KINSC, _CPGC, _HCAH, _PROVOST, _PHILLY],
            "programs": [
                program(
                    "haverford_kinsc_summer_research",
                    "KINSC Summer Research (Marian E. Koshland Integrated Natural Sciences Center)",
                    _KINSC,
                    "The Koshland Integrated Natural Sciences Center (KINSC) "
                    "coordinates Haverford's summer research in biology, "
                    "chemistry, physics & astronomy, computer science, "
                    "mathematics & statistics, psychology, and biochemistry. "
                    "Students spend eight to ten weeks working full-time on a "
                    "faculty member's research project with a summer stipend and "
                    "on-campus housing, joining a cohort that presents its work "
                    "at an end-of-summer symposium.",
                    lab_or_program="Koshland Integrated Natural Sciences Center",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Summer research applications are typically due "
                                  "in late winter / early spring.",
                    keywords=["summer research", "natural sciences",
                              "faculty mentor", "research stipend"],
                ),
                program(
                    "haverford_kinsc_interdisciplinary",
                    "KINSC Interdisciplinary Research (Haverford College)",
                    _KINSC,
                    "Beyond the summer program, the KINSC supports "
                    "year-round student-faculty collaboration across the "
                    "sciences, including cross-departmental work in "
                    "biochemistry & biophysics, scientific computing, and "
                    "environmental studies. Undergraduates take substantive "
                    "roles as research partners, often continuing a project "
                    "toward a senior thesis in one of the college's science "
                    "departments.",
                    lab_or_program="Koshland Integrated Natural Sciences Center",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["interdisciplinary research", "biochemistry",
                              "scientific computing", "senior thesis"],
                ),
                program(
                    "haverford_cpgc_summer_internships",
                    "CPGC Summer Internships & Funding (Center for Peace and Global Citizenship)",
                    _CPGC,
                    "The Center for Peace and Global Citizenship funds Haverford "
                    "students to spend the summer on internships and "
                    "field-research placements — in the US and abroad — with "
                    "NGOs, community organizations, research institutes, and "
                    "government agencies working on peace, justice, human "
                    "rights, public health, and development. Awards include a "
                    "stipend so students can pursue unpaid public-interest work.",
                    lab_or_program="Center for Peace and Global Citizenship",
                    opportunity_type="internship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Summer funding applications are generally due "
                                  "in the late-winter / spring cycle.",
                    keywords=["summer internship", "global citizenship",
                              "social justice", "public interest"],
                ),
                program(
                    "haverford_cpgc_engaged_research",
                    "CPGC Community-Engaged & Global Research (Haverford College)",
                    _CPGC,
                    "The CPGC also supports faculty-mentored, community-engaged "
                    "and international research projects that pair scholarly "
                    "inquiry with real-world social impact. Students design or "
                    "join projects in the social sciences and humanities — from "
                    "human-rights fieldwork to participatory community research "
                    "— with funding, mentorship, and a framework for ethical "
                    "engaged scholarship.",
                    lab_or_program="Center for Peace and Global Citizenship",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["engaged research", "human rights",
                              "community-based research", "fieldwork"],
                ),
                program(
                    "haverford_hcah_student_fellowships",
                    "HCAH Student Research Fellowships (Hurford Center for the Arts and Humanities)",
                    _HCAH,
                    "The John B. Hurford '60 Center for the Arts and Humanities "
                    "(HCAH) funds student research fellowships, summer study "
                    "grants, and creative projects across the humanities and "
                    "arts. Fellows pursue mentored scholarly or artistic work — "
                    "archival research, curatorial projects, digital humanities, "
                    "and independent creative work — and join a vibrant "
                    "interdisciplinary community of students and faculty.",
                    lab_or_program="Hurford Center for the Arts and Humanities",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["humanities research", "arts", "creative projects",
                              "mentored research"],
                ),
                program(
                    "haverford_hcah_summer_scholars",
                    "HCAH Summer Humanities Research (Haverford College)",
                    _HCAH,
                    "Through the HCAH, Haverford students spend the summer on "
                    "faculty-mentored humanities research in fields such as "
                    "English, history, philosophy, religion, classics, "
                    "comparative literature, and languages, supported by a "
                    "summer stipend. Projects often seed senior theses and "
                    "public humanities programming on campus.",
                    lab_or_program="Hurford Center for the Arts and Humanities",
                    opportunity_type="summer_program",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "humanities", "faculty mentor",
                              "senior thesis"],
                ),
                program(
                    "haverford_provost_student_faculty_research",
                    "Student-Faculty Research Funding (Office of the Provost)",
                    _PROVOST,
                    "The Office of the Provost administers college-wide "
                    "student-faculty research funding, supporting "
                    "undergraduates who collaborate with Haverford faculty on "
                    "original research across every division. With small classes "
                    "and no graduate students, Haverford undergraduates take on "
                    "substantive research roles during the academic year and the "
                    "funded summer term.",
                    lab_or_program="Office of the Provost",
                    opportunity_type="research",
                    paid="stipend",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["faculty-mentored research", "undergraduate research",
                              "any division", "research funding"],
                ),
                program(
                    "haverford_mellon_mays",
                    "Mellon Mays Undergraduate Fellowship (Haverford College)",
                    _PROVOST,
                    "The Mellon Mays Undergraduate Fellowship (MMUF) prepares "
                    "students from underrepresented groups for PhD study and "
                    "academic careers in the humanities and select social and "
                    "natural sciences. Haverford fellows receive multi-year "
                    "faculty mentorship, funded summer research, a research "
                    "stipend, and conference support aimed at broadening the "
                    "range of perspectives in the academy.",
                    lab_or_program="Mellon Mays Undergraduate Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    keywords=["Mellon Mays", "PhD pathway", "mentored research",
                              "humanities research"],
                ),
                program(
                    "haverford_tri_co_philly",
                    "Tri-Co Philadelphia Program (Haverford College)",
                    _PHILLY,
                    "The Tri-College Philadelphia Program lets Haverford, Bryn "
                    "Mawr, and Swarthmore students engage Philadelphia as a site "
                    "of learning and research — combining coursework, "
                    "community-based projects, and internships with local "
                    "organizations, arts institutions, and research partners in "
                    "the city.",
                    lab_or_program="Tri-Co Philly Program",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["Philadelphia", "community-based learning",
                              "Tri-College", "urban research"],
                ),
            ],
        },
    ],
}
