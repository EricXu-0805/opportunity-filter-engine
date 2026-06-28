"""University of Wisconsin-Madison (Madison) campus opportunity-graph config (US-News Top-50 rollout).

Curated, offline-safe seed records of UW-Madison's undergraduate-research landscape on
the generic ``campus_graph`` engine: the central undergraduate-research office +
its signature scholarships/fellowships/summer programs, a department research
program, the career center, and research-institute cold-email targets.

The OPEN-bucket program(s) — Cellular and Molecular Biology of Stress Summer Research Program (IBS-SRP / NSF REU) — explicitly recruit students from other institutions, so they are national/open rather than campus-gated. Everything else is UW-Madison-enrollment-gated.

URLs verified HTTP-200 against the official .edu domains (Jun 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> wisc_research_programs (wisc / campus)
    open   -> wisc_external_research (national / open)
    lab    -> wisc_labs              (wisc / unknown)
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
    "school_slug": "wisc",
    "organization": "University of Wisconsin-Madison",
    "location": "Madison, WI",
    "emit": {
        "campus": ("wisc_research_programs", "wisc", "campus"),
        "open": ("wisc_external_research", None, "open"),
        "lab": ("wisc_labs", "wisc", "unknown"),
    },
    "sources": [
        {
            "source_name": "wisc_announcement",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://research.wisc.edu/information-for-undergraduate-students/",
                "https://wiscience.wisc.edu/resources/undergrad-resources/guide-to-undergraduate-research/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "ovcr_undergrad_hub",
                    "Information for Undergraduate Students (Office of Research hub)",
                    "https://research.wisc.edu/information-for-undergraduate-students/",
                    "Central gateway from UW-Madison's Office of Research listing the campus's undergraduate research programs and funding, including Undergraduate Research Scholars, Wisconsin Idea Fellowships, the Summer Research Opportunity Program, Hilldale/Holstrom fellowships, and the Undergraduate Symposium.",
                    organization="UW-Madison Office of the Vice Chancellor for Research",
                    lab_or_program="Office of the Vice Chancellor for Research undergraduate research hub",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["undergraduate research", "fellowships", "research office", "funding", "mentorship"],
                ),
                program(
                    "wiscience_guide",
                    "WISCIENCE Guide to Undergraduate Research",
                    "https://wiscience.wisc.edu/resources/undergrad-resources/guide-to-undergraduate-research/",
                    "A step-by-step guide from WISCIENCE walking students through getting into research (identifying interests, finding researchers on campus, writing outreach emails, interviewing) and succeeding once in a research group (mentor relationships, group culture, presenting findings).",
                    organization="UW-Madison WISCIENCE",
                    lab_or_program="WISCIENCE Guide to Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["finding a mentor", "research position", "cold email", "getting started", "WISCIENCE"],
                ),
            ],
        },
        {
            "source_name": "wisc_program",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://urs.ls.wisc.edu/",
                "https://awards.advising.wisc.edu/all-scholarships/hilldale-undergraduatefaculty-research-fellowship/",
                "https://awards.advising.wisc.edu/all-scholarships/sophomore-research-fellowship/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "urs_scholars",
                    "Undergraduate Research Scholars (URS) Program",
                    "https://urs.ls.wisc.edu/",
                    "URS pairs first- and second-year undergraduates (and first-year transfer students) with a UW-Madison faculty or staff mentor for a year-long research or creative-practice project, earning 1-3 credits via Inter L&S 250 plus a weekly peer-led seminar.",
                    organization="UW-Madison College of Letters & Science",
                    department="College of Letters & Science",
                    lab_or_program="Undergraduate Research Scholars Program",
                    opportunity_type="research",
                    paid="no",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    keywords=["research for credit", "faculty mentor", "first-year", "creative practice", "seminar"],
                ),
                program(
                    "hilldale_fellowship",
                    "Hilldale Undergraduate/Faculty Research Fellowship",
                    "https://awards.advising.wisc.edu/all-scholarships/hilldale-undergraduatefaculty-research-fellowship/",
                    "Campus-wide fellowship funding an independent research project under the mentorship of a UW-Madison faculty or research/instructional academic staff member; the student receives a $4,000 stipend and the advisor receives $1,000 for research costs. Applicants need at least junior standing at the time of application.",
                    organization="UW-Madison Undergraduate Academic Awards",
                    lab_or_program="Hilldale Undergraduate/Faculty Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$4,000 student stipend (plus $1,000 to the faculty advisor)",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    deadline_note="Applications open Dec 15, 2025; deadline Feb 15, 2026 at 11:59 p.m.",
                    keywords=["fellowship", "independent research", "faculty mentor", "stipend", "any discipline"],
                ),
                program(
                    "sophomore_research_fellowship",
                    "Sophomore Research Fellowship",
                    "https://awards.advising.wisc.edu/all-scholarships/sophomore-research-fellowship/",
                    "Fellowship supporting a student's own research project in collaboration with UW-Madison faculty or research/instructional academic staff; the student receives a $3,000 unrestricted stipend and the advisor may request up to $500 for research costs. Open to sophomores, freshmen with 24+ credits by May, and first-year transfer students with a minimum 2.3 GPA.",
                    organization="UW-Madison Undergraduate Academic Awards",
                    lab_or_program="Sophomore Research Fellowship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="$3,000 student stipend (plus up to $500 to the advisor)",
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="unknown",
                    deadline_note="Applications open Dec 15, 2025; deadline Feb 22, 2026 at 11:59 p.m. ~15 awards available.",
                    keywords=["sophomore", "fellowship", "independent research", "stipend", "early-career"],
                ),
            ],
        },
        {
            "source_name": "wisc_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://wiscience.wisc.edu/IBS-SRP",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "ibs_srp_cmbs_reu",
                    "Cellular and Molecular Biology of Stress Summer Research Program (IBS-SRP / NSF REU)",
                    "https://wiscience.wisc.edu/IBS-SRP",
                    "An NSF REU summer research program (part of the Integrated Biological Sciences Summer Research Program) primarily for students from other institutions; UW-Madison students are excluded by funding rules. Participants receive a $7,000 stipend plus housing, partial meal plan, health insurance, and round-trip travel. Requires at least 2 completed semesters with at least 1 semester remaining after the program.",
                    organization="UW-Madison WISCIENCE",
                    lab_or_program="Integrated Biological Sciences Summer Research Program (IBS-SRP), Cellular and Molecular Biology of Stress REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$7,000 stipend plus housing, partial meal plan, health insurance, and round-trip travel",
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    keywords=["REU", "summer research", "molecular biology", "biosciences", "graduate prep"],
                ),
            ],
        },
        {
            "source_name": "wisc_department",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://undergradresearch.chem.wisc.edu/overview/",
                "https://engineering.wisc.edu/research/undergraduate/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "chem_undergrad_research",
                    "Department of Chemistry Undergraduate Research",
                    "https://undergradresearch.chem.wisc.edu/overview/",
                    "The Chemistry Department's undergraduate research portal explaining how to get involved (course credit, scholarships, paid positions, internships, volunteer work) and a three-step process to identify interests, find faculty, and apply to a research group. Notes over 70% of chemistry majors participate in undergraduate research.",
                    organization="UW-Madison Department of Chemistry",
                    department="Department of Chemistry",
                    lab_or_program="Chemistry Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    eligibility_majors=["Chemistry"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["chemistry", "research group", "lab", "join a group", "departmental research"],
                ),
                program(
                    "engineering_undergrad_research",
                    "College of Engineering Undergraduate Research",
                    "https://engineering.wisc.edu/research/undergraduate/",
                    "The College of Engineering's undergraduate research page describing how to find research positions (contacting professors, department offices, Handshake, the student jobs site, engineering research centers, the Wisconsin Discovery Portal) and noting students may earn college credit or an hourly wage, including engineering honors-in-research options.",
                    organization="UW-Madison College of Engineering",
                    department="College of Engineering",
                    lab_or_program="College of Engineering Undergraduate Research",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["engineering", "research position", "honors in research", "hourly wage", "research centers"],
                ),
            ],
        },
        {
            "source_name": "wisc_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://successworks.wisc.edu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "successworks_handshake",
                    "SuccessWorks (College of L&S Career Center) — Handshake",
                    "https://successworks.wisc.edu/",
                    "SuccessWorks is the career development center for UW-Madison's College of Letters & Science, serving 18,000+ students with career and internship advising, resume/cover-letter feedback, and mock interviews, and hosts Handshake as its jobs/internships board connecting students to 200,000+ employers.",
                    organization="UW-Madison College of Letters & Science (SuccessWorks)",
                    lab_or_program="SuccessWorks career center (Handshake host)",
                    opportunity_type="internship",
                    paid="unknown",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["career center", "Handshake", "internships", "jobs", "advising"],
                ),
            ],
        },
        {
            "source_name": "wisc_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://wid.wisc.edu/employment/",
            ],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "wid_institute",
                    "Wisconsin Institute for Discovery (WID) — Employment / Openings",
                    "https://wid.wisc.edu/employment/",
                    "The Wisconsin Institute for Discovery is an interdisciplinary research institute at UW-Madison; its employment page lists openings at WID and other Vice Chancellor for Research units and directs prospective researchers to contact individual labs about openings, making it a cold-email target for joining a lab.",
                    organization="Wisconsin Institute for Discovery (UW-Madison)",
                    lab_or_program="Wisconsin Institute for Discovery (WID)",
                    opportunity_type="research",
                    paid="unknown",
                    preferred_year=["junior", "senior"],
                    international_friendly="unknown",
                    keywords=["interdisciplinary", "research institute", "lab openings", "cold email", "data science"],
                ),
            ],
        },
    ],
}
