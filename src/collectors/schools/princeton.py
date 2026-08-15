"""Princeton University campus opportunity-graph config (US-News #1).

First school on the generic ``campus_graph`` engine. Curated seed records of
Princeton's undergraduate-research landscape: the Office of Undergraduate
Research (OUR) hub + its programs (OURSIP, ReMatch+, senior-thesis funding,
UFAC), department summer-research programs (MolBio SURP, PNI), career
development, and a couple of research institutes. URLs verified against
undergraduateresearch.princeton.edu (Jun 2026).

Emit buckets → (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → princeton_research_programs (princeton / campus)
    open   → princeton_external_research (national / open)
    lab    → princeton_labs              (princeton / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    DEPARTMENT,
    LAB,
    PROGRAM,
    RECURSIVE,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "princeton",
    "organization": "Princeton University",
    "location": "Princeton, NJ",
    "emit": {
        "campus": ("princeton_research_programs", "princeton", "campus"),
        "open": ("princeton_external_research", None, "open"),
        "lab": ("princeton_labs", "princeton", "unknown"),
    },
    "sources": [
        # ---- Announcements / OUR hub --------------------------------------
        {
            "source_name": "princeton_our_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://undergraduateresearch.princeton.edu/",
                "https://undergraduateresearch.princeton.edu/programs",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "our_hub",
                    "Office of Undergraduate Research (OUR) — Hub (Princeton)",
                    "https://undergraduateresearch.princeton.edu/",
                    "Princeton's Office of Undergraduate Research is the front door to "
                    "term-time research workshops, the ReMatch faculty/grad-mentor "
                    "matching program, summer research (ReMatch+, OURSIP), the Summer "
                    "Research Colloquium, and senior-thesis funding. Start here to find "
                    "a program by class year and field.",
                    lab_or_program="Office of Undergraduate Research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
                program(
                    "our_funding",
                    "OUR Funding — Undergraduate Research Grants (Princeton)",
                    "https://undergraduateresearch.princeton.edu/funding",
                    "Central listing of Princeton undergraduate research funding "
                    "managed through SAFE (Student Activities Funding Engine): summer "
                    "research grants, senior-thesis funding cycles (summer/fall/winter), "
                    "and conference travel. Open to all Princeton undergraduates.",
                    lab_or_program="OUR Funding (SAFE)",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["funding", "research grant", "senior thesis"],
                ),
            ],
        },
        # ---- Signature programs -------------------------------------------
        {
            "source_name": "princeton_our_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://undergraduateresearch.princeton.edu/programs"],
            "crawl": STATIC,
            "programs": [
                program(
                    "oursip",
                    "OURSIP — OUR Student-Initiated Internship Program (Princeton)",
                    "https://undergraduateresearch.princeton.edu/programs/summer-programs/oursip",
                    "OURSIP gives Princeton freshmen and sophomores (occasionally "
                    "juniors) a summer grant to carry out a faculty-mentored research "
                    "internship they've arranged themselves. 2026 on-campus program "
                    "runs ~9 weeks, May 31–Aug 2. Apply via SAFE.",
                    lab_or_program="OURSIP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer research grant",
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Annual summer cycle — applications typically due late winter.",
                    keywords=["summer research", "internship", "research grant"],
                ),
                program(
                    "rematch_plus",
                    "ReMatch+ — Graduate-Mentored Summer Research (Princeton)",
                    "https://undergraduateresearch.princeton.edu/programs/rematch",
                    "ReMatch+ is the summer culmination of the year-long ReMatch "
                    "program: freshmen and sophomores carry out paid graduate-mentored "
                    "research projects over the summer. Pairs students with grad-student "
                    "and postdoc mentors across disciplines.",
                    lab_or_program="ReMatch+",
                    opportunity_type="summer_program",
                    paid="yes",
                    compensation="Paid summer research",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="Year-long ReMatch in fall/winter; ReMatch+ over the summer.",
                    keywords=["summer research", "mentorship", "paid"],
                ),
                program(
                    "senior_thesis_funding",
                    "Senior Thesis Research Funding (Princeton OUR)",
                    "https://undergraduateresearch.princeton.edu/funding",
                    "Three funding cycles (summer, fall, winter) support A.B. seniors' "
                    "senior-thesis research. Juniors funding summer thesis research "
                    "apply through the senior-thesis funding activity in SAFE.",
                    lab_or_program="Senior Thesis Funding",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Thesis research grant",
                    preferred_year=["junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Three cycles per year (summer/fall/winter).",
                    keywords=["senior thesis", "research grant"],
                ),
                program(
                    "ufac",
                    "UFAC — Undergraduate Fund for Academic Conferences (Princeton)",
                    "https://undergraduateresearch.princeton.edu/funding",
                    "UFAC funds Princeton undergraduates of any class year or department "
                    "to present their research at a conference in their field.",
                    lab_or_program="UFAC",
                    opportunity_type="research",
                    paid="stipend",
                    compensation="Conference travel funding",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["conference", "funding"],
                ),
            ],
        },
        # ---- Department research programs ---------------------------------
        {
            "source_name": "princeton_department_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://molbio.princeton.edu/undergraduate/research/summer-research",
                "https://pni.princeton.edu/study/undergraduate-program/funding",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            # Both department subdomains sit behind the same Cloudflare
            # challenge as the career site. Recursive crawl + render means each
            # discovered page also goes through Chromium, which is why _fetch
            # caps the per-URL render budget at 60s.
            "render": True,
            "programs": [
                program(
                    "molbio_surp",
                    "SURP — Summer Undergraduate Research (Molecular Biology, Princeton)",
                    "https://molbio.princeton.edu/undergraduate/research/summer-research",
                    "The Department of Molecular Biology's Summer Undergraduate Research "
                    "Program places students in molecular/cell biology, genomics, and "
                    "biophysics labs for a funded summer of mentored bench research.",
                    organization="Department of Molecular Biology, Princeton University",
                    department="Molecular Biology",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend",
                    eligibility_majors=["Molecular Biology", "Biology", "Biochemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    keywords=["summer research", "molecular biology", "genomics", "biophysics"],
                ),
                program(
                    "pni_undergrad",
                    "Princeton Neuroscience Institute — Undergraduate Research",
                    "https://pni.princeton.edu/study/undergraduate-program/funding",
                    "The Princeton Neuroscience Institute supports undergraduate research "
                    "in systems, cognitive, computational, and molecular neuroscience, "
                    "including summer funding and term-time lab placements.",
                    organization="Princeton Neuroscience Institute",
                    department="Neuroscience",
                    eligibility_majors=["Neuroscience", "Psychology", "Molecular Biology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["neuroscience", "cognitive neuroscience", "computational"],
                ),
            ],
        },
        # ---- Career / internship hub --------------------------------------
        {
            "source_name": "princeton_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://careerdevelopment.princeton.edu/"],
            "crawl": STATIC,
            # Cloudflare cf-mitigated: challenge on a plain GET. Headless
            # clears it: measured 2026-08-15, returns "Center for Career
            # Development".
            "render": True,
            "programs": [
                program(
                    "career_development",
                    "Princeton Center for Career Development — Internships & Research",
                    "https://careerdevelopment.princeton.edu/",
                    "Princeton's Center for Career Development connects undergraduates to "
                    "internships, research assistantships, funded summer experiences "
                    "(including the Princeton Internship Network), and advising. Open to "
                    "all class years and majors.",
                    organization="Princeton Center for Career Development",
                    lab_or_program="Center for Career Development",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career", "research assistant"],
                ),
            ],
        },
        # ---- Research institutes / labs (cold-email targets) --------------
        {
            "source_name": "princeton_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://environment.princeton.edu/",
                "https://www.pppl.gov/education",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "hmei",
                    "High Meadows Environmental Institute — Undergraduate Research (Princeton)",
                    "https://environment.princeton.edu/",
                    "The High Meadows Environmental Institute runs funded undergraduate "
                    "summer internships and research across environmental science, "
                    "energy, climate, and policy, including the long-running PEI/HMEI "
                    "internship program.",
                    department="High Meadows Environmental Institute",
                    lab_or_program="HMEI",
                    eligibility_majors=["Environmental Studies", "Ecology", "Geosciences", "Engineering"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    keywords=["environment", "climate", "sustainability", "summer research"],
                ),
                program(
                    "pppl",
                    "Princeton Plasma Physics Laboratory — Undergraduate Programs",
                    "https://www.pppl.gov/education",
                    "PPPL (a DOE national lab managed by Princeton) hosts undergraduate "
                    "research in plasma physics, fusion energy, and related engineering "
                    "through internships and lab placements.",
                    department="Princeton Plasma Physics Laboratory",
                    lab_or_program="PPPL",
                    eligibility_majors=["Physics", "Engineering", "Astrophysics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    keywords=["plasma physics", "fusion", "energy", "join our lab"],
                ),
            ],
        },
    ],
}
