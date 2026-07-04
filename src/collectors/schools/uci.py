"""UC Irvine campus opportunity-graph config (second UC-system rollout school).

Curated seed records of UCI's undergraduate-research landscape: the campus-wide
Undergraduate Research Opportunities Program (UROP) and its funding/journal/
symposium, the Graduate Division pipeline programs open to undergrads (SURF,
UC LEADS), the diversity research programs (MARC U-STAR, CAMP/LSAMP), the
school-run undergraduate-research pages (Biological Sciences, Samueli
Engineering, Physical Sciences, Social Ecology), the career division, and
research institutes with undergraduate involvement (Beckman Laser, Calit2).
URLs verified HTTP-200 (Jul 2026). Grad-only bridge programs (Competitive Edge)
and the scholarship-advising office are left out (not undergrad research).

Emit buckets → (source, school, audience), in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus → uci_research_programs (uci / campus)
    open   → uci_external_research (national / open)
    lab    → uci_labs              (uci / unknown)
"""

from __future__ import annotations

from ..campus_graph import (
    ANNOUNCEMENT,
    CAREER,
    DEPARTMENT,
    LAB,
    PROGRAM,
    STATIC,
    program,
)

SCHOOL: dict = {
    "school_slug": "uci",
    "organization": "University of California, Irvine",
    "location": "Irvine, CA",
    "emit": {
        "campus": ("uci_research_programs", "uci", "campus"),
        "open": ("uci_external_research", None, "open"),
        "lab": ("uci_labs", "uci", "unknown"),
    },
    "sources": [
        {
            "source_name": "uci_urop_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": ["https://urop.uci.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "urop_hub",
                    "Undergraduate Research Opportunities Program (UROP) — UC Irvine",
                    "https://urop.uci.edu/",
                    "UROP is UC Irvine's campus-wide front door to undergraduate "
                    "research in every major: fellowships and funding, mentor "
                    "matching, the Undergraduate Research Journal, and the annual "
                    "Undergraduate Research Symposium. Start here to find a research "
                    "opportunity by field and class year.",
                    lab_or_program="UROP",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship", "fellowship"],
                ),
                program(
                    "urop_opportunities",
                    "UROP Fellowships & Research Funding (UC Irvine)",
                    "https://urop.uci.edu/urop-opportunities/",
                    "UROP's funding and recognition awards for UC Irvine undergraduate "
                    "researchers — fellowships and grants that support faculty-mentored "
                    "projects across all disciplines.",
                    lab_or_program="UROP",
                    paid="yes",
                    international_friendly="yes",
                    keywords=["research fellowship", "funding"],
                ),
                program(
                    "urop_symposium",
                    "UCI Undergraduate Research Symposium",
                    "https://urop.uci.edu/symposium/",
                    "The annual campus symposium where UC Irvine undergraduates present "
                    "their research and creative work; both presenter and attendee "
                    "tracks. A route into the research community for early-stage students.",
                    lab_or_program="UROP",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["research symposium", "presentation"],
                ),
                program(
                    "urop_research_discovery",
                    "Research Discovery Program (UROP, UC Irvine)",
                    "https://urop.uci.edu/research-discovery-program/",
                    "A UROP program that introduces early-stage undergraduates to "
                    "research and connects them with faculty mentors and opportunities.",
                    lab_or_program="UROP",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
            ],
        },
        {
            "source_name": "uci_pipeline_programs",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": ["https://grad.uci.edu/prospective-students/graduate-preparation-programs/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "surf",
                    "Summer Undergraduate Research Fellowship (SURF) — UC Irvine",
                    "https://grad.uci.edu/prospective-students/graduate-preparation-programs/summer-undergraduate-research-fellowship/",
                    "An 8-week intensive summer program of faculty-mentored research "
                    "for PhD/MFA-bound undergraduates across nearly all fields; ~$6,000 "
                    "stipend plus parking. Run by the UCI Graduate Division.",
                    lab_or_program="Graduate Division",
                    opportunity_type="summer_program",
                    paid="yes",
                    compensation="~$6,000 summer stipend",
                    preferred_year=["junior", "senior"],
                    keywords=["summer research", "graduate preparation"],
                ),
                program(
                    "uc_leads",
                    "UC LEADS — Leadership Excellence through Advanced Degrees (UC Irvine)",
                    "https://grad.uci.edu/prospective-students/graduate-preparation-programs/uc-leads/",
                    "A two-year UC systemwide research-scholars program preparing "
                    "undergraduates from underrepresented backgrounds in STEM for "
                    "doctoral study; includes a mentored research stipend.",
                    lab_or_program="Graduate Division",
                    paid="yes",
                    preferred_year=["sophomore", "junior"],
                    keywords=["STEM research", "doctoral preparation"],
                ),
                program(
                    "marc_ustar",
                    "MARC U-STAR — Maximizing Access to Research Careers (UC Irvine)",
                    "https://marc.bio.uci.edu/",
                    "An NIH-funded program training underrepresented juniors and seniors "
                    "for biomedical-science PhD careers through mentored research and a "
                    "stipend. Housed in Biological Sciences.",
                    lab_or_program="MARC U-STAR",
                    paid="yes",
                    preferred_year=["junior", "senior"],
                    keywords=["biomedical research", "NIH"],
                ),
                program(
                    "camp_lsamp",
                    "CAMP — California Alliance for Minority Participation (UC Irvine)",
                    "https://camp.uci.edu/",
                    "UC Irvine's NSF LSAMP-funded alliance advancing inclusive excellence "
                    "and research participation in science, technology, engineering, and "
                    "mathematics.",
                    lab_or_program="CAMP / LSAMP",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    keywords=["STEM research", "LSAMP"],
                ),
            ],
        },
        {
            "source_name": "uci_school_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://undergraduate.bio.uci.edu/research/",
                "https://engineering.uci.edu/research/undergraduate",
                "https://ps.uci.edu/research",
                "https://socialecology.uci.edu/pages/research-social-ecology",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "biosci_ugresearch",
                    "Biological Sciences — Undergraduate Research (UC Irvine)",
                    "https://undergraduate.bio.uci.edu/research/",
                    "The Charlie Dunlop School of Biological Sciences undergraduate "
                    "research hub: BIO 199 independent research for credit and the "
                    "Undergraduate Excellence in Research program that recognizes "
                    "sustained faculty-mentored work.",
                    department="Biological Sciences",
                    international_friendly="yes",
                    keywords=["biology research", "BIO 199"],
                ),
                program(
                    "engineering_ugresearch",
                    "Samueli School of Engineering — Undergraduate Research (UC Irvine)",
                    "https://engineering.uci.edu/research/undergraduate",
                    "The Henry Samueli School of Engineering's undergraduate-research "
                    "information and opportunities page — how to find a faculty lab and "
                    "join engineering research as an undergraduate.",
                    department="Engineering",
                    keywords=["engineering research"],
                ),
                program(
                    "physsci_research",
                    "School of Physical Sciences — Research (UC Irvine)",
                    "https://ps.uci.edu/research",
                    "The School of Physical Sciences research portal spanning Chemistry, "
                    "Physics & Astronomy, Mathematics, and Earth System Science, with "
                    "the centers and facilities that host undergraduate researchers.",
                    department="Physical Sciences",
                    keywords=["physical sciences research"],
                ),
                program(
                    "socialecology_research",
                    "School of Social Ecology — Research (UC Irvine)",
                    "https://socialecology.uci.edu/pages/research-social-ecology",
                    "The School of Social Ecology research page: research hubs and "
                    "student-research resources across Psychological Science, "
                    "Criminology/Law & Society, and Urban Planning & Public Policy.",
                    department="Social Ecology",
                    keywords=["social science research"],
                ),
            ],
        },
        {
            "source_name": "uci_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://career.uci.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_pathways",
                    "UCI Division of Career Pathways",
                    "https://career.uci.edu/",
                    "UC Irvine's career division: internship and research-internship "
                    "listings (including summer research fellowships surfaced through "
                    "the center), advising, and the campus Handshake job board.",
                    lab_or_program="Division of Career Pathways",
                    opportunity_type="internship",
                    keywords=["internships", "career"],
                ),
            ],
        },
        {
            "source_name": "uci_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.bli.uci.edu/",
                "https://www.calit2.uci.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "beckman_laser",
                    "Beckman Laser Institute & Medical Clinic (UC Irvine)",
                    "https://www.bli.uci.edu/",
                    "A biophotonics and laser-medicine research institute ('benchtop to "
                    "bedside') at UC Irvine that hosts student researchers in optics, "
                    "imaging, and translational medicine.",
                    lab_or_program="Beckman Laser Institute",
                    keywords=["biophotonics", "optics", "imaging"],
                ),
                program(
                    "calit2",
                    "Calit2 — California Institute for Telecommunications & IT (UC Irvine)",
                    "https://www.calit2.uci.edu/",
                    "An interdisciplinary technology research institute at UC Irvine "
                    "(home of the Qualcomm Institute) spanning connected devices, "
                    "health tech, and digital media, with undergraduate research roles.",
                    lab_or_program="Calit2 / Qualcomm Institute",
                    keywords=["information technology", "interdisciplinary research"],
                ),
            ],
        },
    ],
}
