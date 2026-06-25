"""UC Berkeley campus-wide research/opportunity source registry.

This is the *source discovery layer* the campus collector (``ucb_campus``) runs
over. It turns "where do Berkeley undergraduates actually find research?" into
data: a list of typed sources, each with seed URLs, a crawl strategy, an update
cadence, and curated parse rules. URAP and the faculty directories are
deliberately NOT here — they keep their own dedicated collectors. This module
is the rest of the graph (announcements, programs, departments, labs, career
boards) so URAP becomes one node, not the backbone.

Design constraints that shaped the shape of this file:

  * **Stdlib only.** No ``requests``/``bs4`` import here. The registry must be
    importable (and the seed records emittable) with zero network deps, so the
    offline data-generation + test paths never touch the network. The live
    crawl lives in ``ucb_campus`` and lazy-imports its HTTP deps there.

  * **Curated seed records are the backbone.** Each source carries one or more
    ``programs`` — hand-verified opportunity specs (title, description,
    eligibility, compensation, application link). They show up unconditionally
    so the system has real Berkeley coverage even when a page is down or its
    markup drifts (same resilience model as ``uiuc_other``/``ucb_urap``). The
    live crawl only *refines* them (open/closed status, description excerpts)
    and *discovers* additional postings on top.

  * **Three emit buckets, audience-correct.** Every record's ``source`` field is
    one of three buckets chosen so the multi-school discovery-scope filter and
    the data-quality gate stay correct (see ``school_audience.SOURCE_DEFAULTS``):

        EMIT_CAMPUS   -> ucb_research_programs  (ucb / campus)
            Berkeley-enrollment-gated programs, dept pages, on-campus jobs.
        EMIT_OPEN     -> ucb_external_research  (national / open)
            External fellowships + REU-style listings hosted on Berkeley pages
            that welcome applicants from any school.
        EMIT_LAB      -> ucb_labs              (ucb / unknown)
            "Join our lab" / lab-recruiting pages — cold-email targets whose
            openness to outside collaborators is professor-specific.

    The fine-grained program/lab/department/career/announcement distinction the
    product cares about rides on each record's ``ucb_source_type`` field, not on
    ``source`` — so we get clean separation without exploding SOURCE_DEFAULTS.
"""

from __future__ import annotations

# --- Source-type taxonomy (the five high-value categories) -----------------

ANNOUNCEMENT = "announcement"   # campus-wide research bulletins / OURS feeds
PROGRAM = "program"             # named programs / fellowships / summer research
DEPARTMENT = "department"       # department- or college-level research pages
CAREER = "career"              # career-center / internship / RA job boards
LAB = "lab"                    # lab-level "join our lab" / recruiting pages

SOURCE_TYPES = frozenset({ANNOUNCEMENT, PROGRAM, DEPARTMENT, CAREER, LAB})

# --- Crawl strategies -------------------------------------------------------

STATIC = "static"          # fetch the seed page(s), parse in place
RECURSIVE = "recursive"    # BFS from the seed(s), depth-limited (1-3)
RSS = "rss"                # structured feed
SITEMAP = "sitemap"        # follow /sitemap.xml

CRAWL_STRATEGIES = frozenset({STATIC, RECURSIVE, RSS, SITEMAP})

# --- Update cadence ---------------------------------------------------------

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
SEASONAL = "seasonal"      # only meaningfully changes around its application cycle

# --- Emit buckets -> (source value used downstream) -------------------------

EMIT_CAMPUS = "ucb_research_programs"   # ucb / campus
EMIT_OPEN = "ucb_external_research"      # national / open
EMIT_LAB = "ucb_labs"                    # ucb / unknown

EMIT_BUCKETS = frozenset({EMIT_CAMPUS, EMIT_OPEN, EMIT_LAB})

# Keywords the recursive crawler prioritizes when deciding which links to
# follow and which discovered pages look like real opportunity postings.
PRIORITY_KEYWORDS = (
    "undergraduate research",
    "summer research",
    "join our lab",
    "join the lab",
    "research assistant",
    "research opportunit",      # opportunity / opportunities
    "internship",
    "fellowship",
    "reu",
    "apply",
    "recruiting",
    "open position",
    "now hiring",
)


def _prog(
    key: str,
    title: str,
    url: str,
    description: str,
    *,
    organization: str = "University of California, Berkeley",
    department: str = "",
    lab_or_program: str = "",
    opportunity_type: str = "research",
    paid: str = "unknown",
    compensation: str = "",
    eligibility_majors: list[str] | None = None,
    preferred_year: list[str] | None = None,
    international_friendly: str = "unknown",
    deadline_note: str = "",
    contact_email: str | None = None,
    keywords: list[str] | None = None,
) -> dict:
    """Build one curated opportunity spec. Kept terse so the registry below
    reads as data, not code."""
    return {
        "key": key,
        "title": title,
        "url": url,
        "description": description,
        "organization": organization,
        "department": department,
        "lab_or_program": lab_or_program,
        "opportunity_type": opportunity_type,
        "paid": paid,
        "compensation": compensation,
        "eligibility_majors": eligibility_majors or [],
        "preferred_year": preferred_year or ["sophomore", "junior", "senior"],
        "international_friendly": international_friendly,
        "deadline_note": deadline_note,
        "contact_email": contact_email,
        "keywords": keywords or [],
    }


# ===========================================================================
# THE REGISTRY
# ===========================================================================
# Each entry: a logical source with seed URLs + crawl policy + curated programs.
# `emit` decides the downstream `source` bucket (and thus school/audience).

UCB_SOURCES: list[dict] = [
    # ---- 1. CAMPUS RESEARCH ANNOUNCEMENT SOURCES --------------------------
    {
        "source_name": "ucb_ours_hub",
        "source_type": ANNOUNCEMENT,
        "emit": EMIT_CAMPUS,
        "seeds": [
            "https://research.berkeley.edu/our/",
            "https://research.berkeley.edu/undergraduate-research/",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 2,
        "update": WEEKLY,
        "programs": [
            _prog(
                "ours_hub",
                "Office of Undergraduate Research & Scholarships (OURS) — Research Hub",
                "https://research.berkeley.edu/our/",
                "Central hub for UC Berkeley undergraduate research. OURS lists "
                "campus research programs (URAP, SURF, Haas Scholars, SPUR), "
                "scholarship-connected research awards, info sessions, and "
                "deadlines. Start here to find a program that matches your year "
                "and field, then follow through to the specific application.",
                lab_or_program="OURS",
                preferred_year=["freshman", "sophomore", "junior", "senior"],
                international_friendly="yes",
                contact_email="ours@berkeley.edu",
                keywords=["undergraduate research", "research", "mentorship"],
            ),
            _prog(
                "ours_discovery",
                "OURS Research Discovery & Info Sessions",
                "https://research.berkeley.edu/our/events",
                "Recurring OURS info sessions and workshops that walk "
                "undergraduates through finding a faculty mentor, writing a "
                "research proposal, and applying to URAP/SURF. Useful entry "
                "point for first-time researchers with no prior lab experience.",
                lab_or_program="OURS",
                opportunity_type="research",
                preferred_year=["freshman", "sophomore", "junior", "senior"],
                international_friendly="yes",
                contact_email="ours@berkeley.edu",
                keywords=["undergraduate research", "info session", "mentorship"],
            ),
        ],
    },
    {
        "source_name": "ucb_research_news",
        "source_type": ANNOUNCEMENT,
        "emit": EMIT_CAMPUS,
        "seeds": ["https://research.berkeley.edu/news/"],
        "crawl": RECURSIVE,
        "crawl_depth": 1,
        "update": WEEKLY,
        "programs": [
            _prog(
                "vcr_research_news",
                "Berkeley Research — Undergraduate Opportunity Announcements",
                "https://research.berkeley.edu/news/",
                "Announcement stream from the Vice Chancellor for Research office. "
                "Periodically posts campus-wide undergraduate research calls, new "
                "funded programs, and cross-departmental opportunities that do not "
                "live on any single department page.",
                lab_or_program="Berkeley Research (VCR)",
                preferred_year=["freshman", "sophomore", "junior", "senior"],
                international_friendly="yes",
                keywords=["undergraduate research", "announcement"],
            ),
        ],
    },

    # ---- 2. SUMMER RESEARCH PROGRAMS --------------------------------------
    {
        "source_name": "ucb_summer_programs",
        "source_type": PROGRAM,
        "emit": EMIT_CAMPUS,
        "seeds": [
            "https://research.berkeley.edu/our/undergraduate-research-programs/",
        ],
        "crawl": STATIC,
        "update": SEASONAL,
        "programs": [
            _prog(
                "surf",
                "SURF — Summer Undergraduate Research Fellowship (UC Berkeley)",
                "https://research.berkeley.edu/our/surf/",
                "SURF funds Berkeley undergraduates to do full-time faculty-mentored "
                "research over the summer (roughly 8-10 weeks). Tracks include SURF "
                "L&S, SURF Rose Hills (STEM), and SMART. Students propose a project "
                "with a faculty mentor and receive a summer stipend. Application "
                "opens in the fall/winter for the following summer.",
                lab_or_program="SURF",
                opportunity_type="summer_program",
                paid="stipend",
                compensation="Summer stipend (varies by track; typically $4,000-$6,000+)",
                preferred_year=["sophomore", "junior", "senior"],
                international_friendly="yes",
                deadline_note="Annual cycle — applications typically due late winter (Feb).",
                contact_email="surf@berkeley.edu",
                keywords=["summer research", "fellowship", "stipend", "undergraduate research"],
            ),
            _prog(
                "rose_hills",
                "SURF Rose Hills — Summer STEM Research Fellowship",
                "https://research.berkeley.edu/our/surf/rose-hills/",
                "The Rose Hills track of SURF supports California-resident STEM "
                "undergraduates conducting summer research in science, math, and "
                "engineering with a Berkeley faculty mentor. Comes with a summer "
                "stipend and a research-skills cohort.",
                lab_or_program="SURF Rose Hills",
                opportunity_type="summer_program",
                paid="stipend",
                compensation="Summer stipend",
                eligibility_majors=["Engineering", "Computer Science", "Biology",
                                    "Chemistry", "Physics", "Mathematics", "Statistics"],
                preferred_year=["sophomore", "junior", "senior"],
                deadline_note="Annual cycle — typically due February.",
                contact_email="surf@berkeley.edu",
                keywords=["summer research", "stem", "fellowship", "stipend"],
            ),
            _prog(
                "spur",
                "SPUR — Sponsored Projects for Undergraduate Research (Rausser CNR)",
                "https://nature.berkeley.edu/research/sponsored-projects-undergraduate-research-spur",
                "SPUR matches undergraduates with faculty-led research projects in "
                "the Rausser College of Natural Resources across environmental "
                "science, ecology, microbial biology, nutrition, and resource "
                "economics. Semester and summer cohorts; some tracks are paid or "
                "for academic credit.",
                organization="Rausser College of Natural Resources, UC Berkeley",
                department="Rausser College of Natural Resources",
                lab_or_program="SPUR",
                opportunity_type="summer_program",
                paid="unknown",
                eligibility_majors=["Environmental Science", "Molecular Environmental Biology",
                                    "Nutritional Science", "Microbial Biology",
                                    "Environmental Economics & Policy", "Forestry"],
                preferred_year=["freshman", "sophomore", "junior", "senior"],
                deadline_note="Semester + summer cohorts; deadlines posted per cycle.",
                keywords=["summer research", "environmental science", "ecology", "undergraduate research"],
            ),
            _prog(
                "amgen_scholars",
                "Amgen Scholars Program at UC Berkeley (Summer Research)",
                "https://research.berkeley.edu/amgen-scholars/",
                "A 10-week summer research program in science and biotechnology for "
                "undergraduates from across the country, hosted at UC Berkeley. "
                "Includes a stipend, housing, travel, and a national symposium. "
                "Open to U.S. undergraduates (not limited to Berkeley students).",
                opportunity_type="summer_program",
                paid="yes",
                compensation="Stipend + housing + travel",
                eligibility_majors=["Biology", "Chemistry", "Bioengineering",
                                    "Chemical Engineering", "Molecular & Cell Biology"],
                preferred_year=["sophomore", "junior"],
                international_friendly="no",
                deadline_note="Summer program — national application, typically due February.",
                keywords=["summer research", "biotechnology", "stipend", "reu"],
            ),
        ],
    },
    {
        "source_name": "ucb_eecs_summer",
        "source_type": PROGRAM,
        "emit": EMIT_OPEN,
        "seeds": [
            "https://eecs.berkeley.edu/resources/undergrads/research/sure",
            "https://www2.eecs.berkeley.edu/Research/Areas/",
        ],
        "crawl": STATIC,
        "update": SEASONAL,
        "programs": [
            _prog(
                "eecs_sure",
                "SUPERB / SURE — EECS Summer Undergraduate Research (UC Berkeley)",
                "https://eecs.berkeley.edu/resources/undergrads/research/sure",
                "EECS summer research experiences (SUPERB-ITS and related SURE "
                "tracks) place undergraduates in Berkeley EECS labs for an "
                "intensive summer of mentored research in AI, systems, circuits, "
                "and theory. Stipend + housing for admitted scholars; designed for "
                "students considering graduate study, including those from other "
                "institutions.",
                organization="EECS, UC Berkeley",
                department="Electrical Engineering and Computer Sciences",
                lab_or_program="SUPERB / SURE",
                opportunity_type="summer_program",
                paid="stipend",
                compensation="Summer stipend + housing",
                eligibility_majors=["Computer Science", "Electrical Engineering",
                                    "Computer Engineering", "EECS"],
                preferred_year=["sophomore", "junior"],
                international_friendly="no",
                deadline_note="Summer REU-style cycle — typically due winter/early spring.",
                keywords=["summer research", "reu", "machine learning", "systems", "circuits"],
            ),
        ],
    },
    {
        "source_name": "ucb_external_fellowships",
        "source_type": PROGRAM,
        "emit": EMIT_OPEN,
        "seeds": [
            "https://research.berkeley.edu/our/scholarships-and-honors/",
        ],
        "crawl": STATIC,
        "update": MONTHLY,
        "programs": [
            _prog(
                "haas_scholars",
                "Haas Scholars Program — Year-Long Research (UC Berkeley)",
                "https://research.berkeley.edu/haas-scholars/",
                "Twenty Haas Scholars are selected each year to pursue a self-designed "
                "research or creative project across any discipline during their "
                "senior year, with a faculty mentor and a substantial research grant. "
                "Highly selective; open to all majors with financial need.",
                lab_or_program="Haas Scholars",
                opportunity_type="research",
                paid="stipend",
                compensation="Research grant (~$13,800)",
                preferred_year=["junior"],
                deadline_note="Annual cycle — applications due in the spring of junior year.",
                keywords=["fellowship", "thesis", "research grant", "undergraduate research"],
            ),
            _prog(
                "mcnair",
                "McNair Scholars Program (UC Berkeley)",
                "https://research.berkeley.edu/mcnair/",
                "Federally funded program preparing first-generation, low-income, and "
                "underrepresented undergraduates for PhD study through mentored "
                "research, a summer research institute, and graduate-school advising.",
                lab_or_program="McNair Scholars",
                opportunity_type="research",
                paid="stipend",
                compensation="Summer research stipend",
                preferred_year=["sophomore", "junior"],
                international_friendly="no",
                deadline_note="Annual cohort — spring application.",
                keywords=["research", "phd preparation", "summer research", "mentorship"],
            ),
        ],
    },

    # ---- 3. DEPARTMENT / PROGRAM-LEVEL RESEARCH PAGES ----------------------
    {
        "source_name": "ucb_department_research",
        "source_type": DEPARTMENT,
        "emit": EMIT_CAMPUS,
        "seeds": [
            "https://eecs.berkeley.edu/resources/undergrads/research",
            "https://www2.eecs.berkeley.edu/Research/",
            "https://statistics.berkeley.edu/undergraduate/research",
            "https://mcb.berkeley.edu/undergrad/research",
            "https://physics.berkeley.edu/academics/undergraduate/research-opportunities",
            "https://bioeng.berkeley.edu/academics/undergraduate/research/",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 1,
        "update": MONTHLY,
        "programs": [
            _prog(
                "eecs_research_page",
                "EECS Undergraduate Research Opportunities (UC Berkeley)",
                "https://eecs.berkeley.edu/resources/undergrads/research",
                "The EECS department's guide to undergraduate research: how to find a "
                "faculty mentor, the URAP and SUPERB pathways, unit-bearing 199 "
                "research, and lab openings in AI, systems, theory, circuits, and HCI.",
                organization="EECS, UC Berkeley",
                department="Electrical Engineering and Computer Sciences",
                eligibility_majors=["Computer Science", "Electrical Engineering",
                                    "Computer Engineering", "EECS"],
                preferred_year=["sophomore", "junior", "senior"],
                contact_email="ugadvising@eecs.berkeley.edu",
                keywords=["undergraduate research", "machine learning", "systems", "circuits"],
            ),
            _prog(
                "stat_research_page",
                "Statistics Undergraduate Research (UC Berkeley)",
                "https://statistics.berkeley.edu/undergraduate/research",
                "Department of Statistics page on undergraduate research routes: "
                "faculty-mentored projects, the Stat 199 independent research units, "
                "and data-science research collaborations.",
                organization="Department of Statistics, UC Berkeley",
                department="Statistics",
                eligibility_majors=["Statistics", "Data Science", "Applied Mathematics"],
                preferred_year=["junior", "senior"],
                keywords=["undergraduate research", "statistics", "data science"],
            ),
            _prog(
                "mcb_research_page",
                "Molecular & Cell Biology Undergraduate Research (UC Berkeley)",
                "https://mcb.berkeley.edu/undergrad/research",
                "MCB's hub for undergraduate research: how to join a wet-lab, the "
                "MCB 199 research units, the MCB honors thesis track, and listings "
                "of labs actively recruiting undergraduate researchers.",
                organization="Molecular & Cell Biology, UC Berkeley",
                department="Molecular & Cell Biology",
                eligibility_majors=["Molecular & Cell Biology", "Biology", "Bioengineering"],
                preferred_year=["sophomore", "junior", "senior"],
                keywords=["undergraduate research", "molecular biology", "cell biology", "wet lab"],
            ),
            _prog(
                "physics_research_page",
                "Physics Undergraduate Research Opportunities (UC Berkeley)",
                "https://physics.berkeley.edu/academics/undergraduate/research-opportunities",
                "Department of Physics guide to undergraduate research: the Physics "
                "199 units, the senior thesis, summer research, and a list of "
                "research groups (astrophysics, condensed matter, AMO, particle "
                "physics) open to undergraduate involvement.",
                organization="Department of Physics, UC Berkeley",
                department="Physics",
                eligibility_majors=["Physics", "Astrophysics", "Engineering Physics"],
                preferred_year=["sophomore", "junior", "senior"],
                keywords=["undergraduate research", "astrophysics", "condensed matter", "physics"],
            ),
            _prog(
                "bioe_research_page",
                "Bioengineering Undergraduate Research (UC Berkeley)",
                "https://bioeng.berkeley.edu/academics/undergraduate/research/",
                "Department of Bioengineering page on undergraduate research: lab "
                "rotations, the BioE 196 research units, design teams, and faculty "
                "labs recruiting undergraduates in synthetic biology, imaging, and "
                "biomechanics.",
                organization="Department of Bioengineering, UC Berkeley",
                department="Bioengineering",
                eligibility_majors=["Bioengineering", "Biomedical Engineering"],
                preferred_year=["sophomore", "junior", "senior"],
                keywords=["undergraduate research", "bioengineering", "synthetic biology", "imaging"],
            ),
            _prog(
                "cs_research_page",
                "Computer Science Research for Undergraduates (UC Berkeley)",
                "https://www2.eecs.berkeley.edu/Research/Areas/",
                "Berkeley EECS research-areas index — the entry point to faculty "
                "groups across AI, security, databases, programming languages, "
                "graphics, and theory. Each area links to labs that take "
                "undergraduate researchers.",
                organization="EECS, UC Berkeley",
                department="Electrical Engineering and Computer Sciences",
                eligibility_majors=["Computer Science", "EECS", "Data Science"],
                preferred_year=["sophomore", "junior", "senior"],
                keywords=["undergraduate research", "artificial intelligence", "security", "databases"],
            ),
        ],
    },

    # ---- 4. CAREER / INTERNSHIP HUBS (campus-controlled) -------------------
    {
        "source_name": "ucb_career_hubs",
        "source_type": CAREER,
        "emit": EMIT_CAMPUS,
        "seeds": [
            "https://career.berkeley.edu/",
            "https://career.berkeley.edu/explore-careers/",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 1,
        "update": WEEKLY,
        "programs": [
            _prog(
                "career_engagement",
                "Berkeley Career Engagement — Research & Internship Postings",
                "https://career.berkeley.edu/",
                "The campus career center's hub for finding internships, research "
                "assistantships, and on-campus jobs. Routes students to Handshake "
                "postings, career fairs, and industry/research advising. Open to all "
                "Berkeley undergraduates regardless of major or class year.",
                organization="UC Berkeley Career Engagement",
                lab_or_program="Career Engagement",
                opportunity_type="internship",
                paid="unknown",
                preferred_year=["freshman", "sophomore", "junior", "senior"],
                international_friendly="yes",
                contact_email="career@berkeley.edu",
                keywords=["internship", "career", "research assistant"],
            ),
            _prog(
                "work_study_research",
                "Work-Study Undergraduate Research Assistant Jobs (UC Berkeley)",
                "https://workstudy.berkeley.edu/",
                "Paid undergraduate research assistant positions funded through "
                "Federal/Berkeley Work-Study. Faculty and research units post RA "
                "roles (lab assistant, data collection, literature review) that pay "
                "an hourly wage to eligible students. Listed on the campus job board.",
                organization="UC Berkeley Work-Study",
                lab_or_program="Work-Study",
                opportunity_type="research",
                paid="yes",
                compensation="Hourly wage (Work-Study funded)",
                preferred_year=["freshman", "sophomore", "junior", "senior"],
                contact_email="workstudy@berkeley.edu",
                keywords=["research assistant", "paid", "work-study", "on-campus"],
            ),
        ],
    },
    {
        "source_name": "ucb_engineering_internships",
        "source_type": CAREER,
        "emit": EMIT_CAMPUS,
        "seeds": ["https://engineering.berkeley.edu/students/undergraduate-guide/academic-opportunities/research/"],
        "crawl": STATIC,
        "update": MONTHLY,
        "programs": [
            _prog(
                "coe_research_internships",
                "College of Engineering — Undergraduate Research & Internships (UC Berkeley)",
                "https://engineering.berkeley.edu/students/undergraduate-guide/academic-opportunities/research/",
                "Berkeley Engineering's hub for undergraduate research and internship "
                "pathways: faculty research (ENGIN 199), the Engineering Student "
                "Services research advising, design teams, and partner-lab internship "
                "placements. Open to engineering undergraduates across all majors.",
                organization="College of Engineering, UC Berkeley",
                department="College of Engineering",
                opportunity_type="research",
                eligibility_majors=["Engineering", "Mechanical Engineering",
                                    "Civil Engineering", "Bioengineering",
                                    "Materials Science", "Nuclear Engineering",
                                    "Industrial Engineering", "EECS"],
                preferred_year=["sophomore", "junior", "senior"],
                keywords=["undergraduate research", "internship", "engineering"],
            ),
        ],
    },

    # ---- 5. LAB / "JOIN OUR LAB" RECRUITING PAGES --------------------------
    {
        "source_name": "ucb_lab_recruiting",
        "source_type": LAB,
        "emit": EMIT_LAB,
        "seeds": [
            "https://bair.berkeley.edu/",
            "https://bids.berkeley.edu/",
            "https://rdi.berkeley.edu/",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 2,
        "update": MONTHLY,
        "programs": [
            _prog(
                "bair_lab",
                "Berkeley AI Research (BAIR) — Undergraduate Researchers",
                "https://bair.berkeley.edu/",
                "Berkeley AI Research brings together faculty and students across "
                "machine learning, computer vision, NLP, robotics, and AI theory. "
                "Individual BAIR labs recruit undergraduate researchers directly — "
                "the lab pages list current projects and how to reach out. Strong "
                "cold-email target for AI/ML-interested undergraduates.",
                department="Electrical Engineering and Computer Sciences",
                lab_or_program="Berkeley AI Research (BAIR)",
                opportunity_type="research",
                eligibility_majors=["Computer Science", "EECS", "Statistics",
                                    "Data Science", "Mathematics"],
                preferred_year=["junior", "senior"],
                keywords=["machine learning", "computer vision", "robotics",
                          "natural language processing", "join our lab"],
            ),
            _prog(
                "bids_lab",
                "Berkeley Institute for Data Science (BIDS) — Research Affiliates",
                "https://bids.berkeley.edu/",
                "BIDS is Berkeley's hub for data-intensive research across domains. "
                "It runs undergraduate-facing data-science research collaborations "
                "and connects students with projects in reproducible science, "
                "machine learning, and computational research.",
                department="Berkeley Institute for Data Science",
                lab_or_program="BIDS",
                opportunity_type="research",
                eligibility_majors=["Data Science", "Statistics", "Computer Science"],
                preferred_year=["junior", "senior"],
                keywords=["data science", "machine learning", "research", "join our lab"],
            ),
            _prog(
                "rdi_lab",
                "Berkeley RDI — Decentralization & AI Research (Undergraduate Roles)",
                "https://rdi.berkeley.edu/",
                "The Berkeley Center for Responsible, Decentralized Intelligence "
                "(RDI) runs research and courses at the intersection of AI, "
                "blockchain, and security, and periodically recruits undergraduate "
                "researchers and course assistants for its projects.",
                department="Electrical Engineering and Computer Sciences",
                lab_or_program="Berkeley RDI",
                opportunity_type="research",
                eligibility_majors=["Computer Science", "EECS", "Data Science"],
                preferred_year=["junior", "senior"],
                keywords=["artificial intelligence", "security", "blockchain", "join our lab"],
            ),
        ],
    },

    # ---- DEPARTMENT RESEARCH PAGES (breadth across colleges) --------------
    {
        "source_name": "ucb_more_departments",
        "source_type": DEPARTMENT,
        "emit": EMIT_CAMPUS,
        "seeds": [
            "https://chemistry.berkeley.edu/research",
            "https://www.ce.berkeley.edu/research",
            "https://me.berkeley.edu/research/",
            "https://mse.berkeley.edu/research/",
            "https://astro.berkeley.edu/research/",
            "https://ib.berkeley.edu/undergrad/research.php",
            "https://psychology.berkeley.edu/students/undergraduate-program/research-opportunities",
            "https://www.econ.berkeley.edu/undergrad/research",
            "https://data.berkeley.edu/research",
            "https://math.berkeley.edu/programs/undergraduate",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 1,
        "update": MONTHLY,
        "programs": [
            _prog("chem_dept", "Chemistry Undergraduate Research (UC Berkeley)",
                  "https://chemistry.berkeley.edu/research",
                  "College of Chemistry research page covering undergraduate routes into "
                  "synthetic, physical, and chemical-biology labs, the Chem 199 research "
                  "units, and faculty groups recruiting undergraduate researchers.",
                  organization="College of Chemistry, UC Berkeley", department="Chemistry",
                  eligibility_majors=["Chemistry", "Chemical Biology", "Biochemistry"],
                  keywords=["undergraduate research", "organic chemistry", "catalysis", "spectroscopy"]),
            _prog("cbe_dept", "Chemical & Biomolecular Engineering Research (UC Berkeley)",
                  "https://cbe.berkeley.edu/research/",
                  "Department of Chemical & Biomolecular Engineering research overview: "
                  "energy, catalysis, biomolecular, and materials labs that take "
                  "undergraduate researchers through ChemE 199 and summer projects.",
                  organization="College of Chemistry, UC Berkeley", department="Chemical & Biomolecular Engineering",
                  eligibility_majors=["Chemical Engineering", "Chemical & Biomolecular Engineering"],
                  keywords=["undergraduate research", "catalysis", "energy systems", "materials science"]),
            _prog("cee_dept", "Civil & Environmental Engineering Research (UC Berkeley)",
                  "https://www.ce.berkeley.edu/research",
                  "CEE research page spanning structures, transportation, environmental "
                  "engineering, and geosystems; lists faculty labs and the CE 199 "
                  "undergraduate research pathway.",
                  organization="College of Engineering, UC Berkeley", department="Civil & Environmental Engineering",
                  eligibility_majors=["Civil Engineering", "Environmental Engineering"],
                  keywords=["undergraduate research", "structural engineering", "transportation", "water treatment"]),
            _prog("me_dept", "Mechanical Engineering Research (UC Berkeley)",
                  "https://me.berkeley.edu/research/",
                  "Department of Mechanical Engineering research areas — controls, "
                  "manufacturing, fluids, biomechanics, energy — with faculty labs "
                  "open to undergraduate researchers via ME 196/199.",
                  organization="College of Engineering, UC Berkeley", department="Mechanical Engineering",
                  eligibility_majors=["Mechanical Engineering"],
                  keywords=["undergraduate research", "robotics", "manufacturing", "fluid dynamics"]),
            _prog("mse_dept", "Materials Science & Engineering Research (UC Berkeley)",
                  "https://mse.berkeley.edu/research/",
                  "MSE research overview — electronic materials, nanomaterials, "
                  "biomaterials, and structural materials — and how undergraduates "
                  "join a materials lab.",
                  organization="College of Engineering, UC Berkeley", department="Materials Science & Engineering",
                  eligibility_majors=["Materials Science", "Materials Science & Engineering"],
                  keywords=["undergraduate research", "nanotechnology", "materials science", "biomaterials"]),
            _prog("astro_dept", "Astronomy Undergraduate Research (UC Berkeley)",
                  "https://astro.berkeley.edu/research/",
                  "Department of Astronomy research page: observational and theoretical "
                  "astrophysics groups, the Berkeley astronomy labs, and summer/academic-"
                  "year research for undergraduates.",
                  organization="Department of Astronomy, UC Berkeley", department="Astronomy",
                  eligibility_majors=["Astrophysics", "Physics", "Astronomy"],
                  keywords=["undergraduate research", "astrophysics", "cosmology", "observational astronomy"]),
            _prog("ib_dept", "Integrative Biology Undergraduate Research (UC Berkeley)",
                  "https://ib.berkeley.edu/undergrad/research.php",
                  "Integrative Biology guide to undergraduate research: field and lab "
                  "projects in ecology, evolution, physiology, and organismal biology, "
                  "plus the IB 199 research units and honors thesis.",
                  organization="Department of Integrative Biology, UC Berkeley", department="Integrative Biology",
                  eligibility_majors=["Integrative Biology", "Biology"],
                  keywords=["undergraduate research", "ecology", "evolutionary biology", "physiology"]),
            _prog("psych_dept", "Psychology Research Opportunities (UC Berkeley)",
                  "https://psychology.berkeley.edu/students/undergraduate-program/research-opportunities",
                  "Department of Psychology page listing labs recruiting undergraduate "
                  "research assistants across cognitive, clinical, developmental, and "
                  "social psychology, plus the Psych 199 research units.",
                  organization="Department of Psychology, UC Berkeley", department="Psychology",
                  eligibility_majors=["Psychology", "Cognitive Science", "Neuroscience"],
                  keywords=["undergraduate research", "cognitive psychology", "clinical psychology", "perception"]),
            _prog("econ_dept", "Economics Undergraduate Research (UC Berkeley)",
                  "https://www.econ.berkeley.edu/undergrad/research",
                  "Department of Economics research page: research-assistant openings "
                  "with faculty, the Econ honors thesis, and data-intensive policy "
                  "research labs (CEGA, O-Lab, Opportunity Lab) hiring undergraduates.",
                  organization="Department of Economics, UC Berkeley", department="Economics",
                  eligibility_majors=["Economics", "Data Science", "Statistics"],
                  keywords=["undergraduate research", "econometrics", "economics", "causal inference"]),
            _prog("cdss_research", "Data Science Research (CDSS, UC Berkeley)",
                  "https://data.berkeley.edu/research",
                  "Computing, Data Science & Society research hub. Connects undergraduates "
                  "to data-science research teams, the Data Science Discovery program, "
                  "and domain labs applying data methods across campus.",
                  organization="Computing, Data Science & Society, UC Berkeley", department="Data Science",
                  eligibility_majors=["Data Science", "Statistics", "Computer Science"],
                  keywords=["undergraduate research", "data science", "machine learning", "statistics"]),
            _prog("math_dept", "Mathematics Undergraduate Research (UC Berkeley)",
                  "https://math.berkeley.edu/programs/undergraduate",
                  "Department of Mathematics undergraduate page covering directed reading, "
                  "the Math 199 research units, and summer research / REU pathways in pure "
                  "and applied mathematics.",
                  organization="Department of Mathematics, UC Berkeley", department="Mathematics",
                  eligibility_majors=["Mathematics", "Applied Mathematics"],
                  keywords=["undergraduate research", "mathematics", "applied mathematics", "probability"]),
            _prog("ne_dept", "Nuclear Engineering Research (UC Berkeley)",
                  "https://www.nuc.berkeley.edu/research/",
                  "Department of Nuclear Engineering research areas — reactor physics, "
                  "nuclear materials, fusion, and nonproliferation — with undergraduate "
                  "research via NE 199 and summer projects.",
                  organization="College of Engineering, UC Berkeley", department="Nuclear Engineering",
                  eligibility_majors=["Nuclear Engineering"],
                  keywords=["undergraduate research", "nuclear reactors", "fusion", "radiation detection"]),
            _prog("ieor_dept", "IEOR Undergraduate Research (UC Berkeley)",
                  "https://ieor.berkeley.edu/academics/undergraduate/",
                  "Industrial Engineering & Operations Research page on undergraduate "
                  "research in optimization, supply chain, machine learning, and "
                  "financial engineering.",
                  organization="College of Engineering, UC Berkeley", department="Industrial Engineering & Operations Research",
                  eligibility_majors=["Industrial Engineering", "Operations Research", "Data Science"],
                  keywords=["undergraduate research", "operations research", "optimization", "supply chain"]),
            _prog("espm_dept", "ESPM Environmental Research (UC Berkeley)",
                  "https://ourenvironment.berkeley.edu/research",
                  "Department of Environmental Science, Policy & Management research hub: "
                  "ecology, conservation, environmental policy, and forestry labs that "
                  "recruit undergraduate researchers.",
                  organization="Rausser College of Natural Resources, UC Berkeley", department="Environmental Science, Policy & Management",
                  eligibility_majors=["Environmental Science", "Conservation & Resource Studies", "Forestry"],
                  keywords=["undergraduate research", "conservation biology", "ecology", "environmental policy"]),
            _prog("pmb_dept", "Plant & Microbial Biology Research (UC Berkeley)",
                  "https://plantandmicrobiology.berkeley.edu/research",
                  "Department of Plant & Microbial Biology research page: genetics, "
                  "plant-microbe interactions, and microbial ecology labs open to "
                  "undergraduate researchers.",
                  organization="Rausser College of Natural Resources, UC Berkeley", department="Plant & Microbial Biology",
                  eligibility_majors=["Microbial Biology", "Genetics & Plant Biology", "Molecular Environmental Biology"],
                  keywords=["undergraduate research", "plant biology", "microbiology", "genetics"]),
            _prog("nst_dept", "Nutritional Sciences & Toxicology Research (UC Berkeley)",
                  "https://nst.berkeley.edu/research",
                  "Department of Nutritional Sciences & Toxicology research overview: "
                  "metabolism, toxicology, and physiology labs recruiting undergraduate "
                  "researchers.",
                  organization="Rausser College of Natural Resources, UC Berkeley", department="Nutritional Sciences & Toxicology",
                  eligibility_majors=["Nutritional Science", "Molecular & Cell Biology"],
                  keywords=["undergraduate research", "nutrition", "metabolism", "toxicology"]),
            _prog("neuro_dept", "Neuroscience Undergraduate Research (UC Berkeley)",
                  "https://neuroscience.berkeley.edu/undergraduate-research/",
                  "Helen Wills Neuroscience Institute page connecting undergraduates to "
                  "systems, cognitive, and molecular neuroscience labs across campus.",
                  organization="Helen Wills Neuroscience Institute, UC Berkeley", department="Neuroscience",
                  eligibility_majors=["Neuroscience", "Molecular & Cell Biology", "Cognitive Science"],
                  keywords=["undergraduate research", "neuroscience", "cognitive neuroscience", "neural engineering"]),
        ],
    },

    # ---- SIGNATURE / STRUCTURED PROGRAMS ----------------------------------
    {
        "source_name": "ucb_signature_programs",
        "source_type": PROGRAM,
        "emit": EMIT_CAMPUS,
        "seeds": ["https://research.berkeley.edu/our/undergraduate-research-programs/"],
        "crawl": STATIC,
        "update": SEASONAL,
        "programs": [
            _prog("busp", "Biology Scholars Program (BSP) Research (UC Berkeley)",
                  "https://bsp.berkeley.edu/",
                  "The Biology Scholars Program supports undergraduates — especially "
                  "first-generation and underrepresented students — in the biological "
                  "sciences, including placement into faculty research labs and summer "
                  "research funding.",
                  lab_or_program="Biology Scholars Program",
                  eligibility_majors=["Biology", "Molecular & Cell Biology", "Integrative Biology"],
                  preferred_year=["freshman", "sophomore", "junior"],
                  international_friendly="yes",
                  keywords=["undergraduate research", "biology", "mentorship"]),
            _prog("cal_nerds", "Cal NERDS — STEM Research Scholars (UC Berkeley)",
                  "https://calnerds.berkeley.edu/",
                  "Cal NERDS develops underrepresented STEM undergraduates through "
                  "research placements, paid research scholarships, tech training, and "
                  "graduate-school preparation.",
                  lab_or_program="Cal NERDS",
                  preferred_year=["freshman", "sophomore", "junior", "senior"],
                  paid="stipend", compensation="Research scholarship/stipend",
                  international_friendly="yes",
                  keywords=["undergraduate research", "stem", "mentorship", "stipend"]),
            _prog("berkeley_connect", "Berkeley Connect — Mentored Research Pathways",
                  "https://berkeleyconnect.berkeley.edu/",
                  "Berkeley Connect pairs students with graduate-student mentors within a "
                  "department and runs small-group activities that often lead into "
                  "faculty research; offered across ~40 departments.",
                  lab_or_program="Berkeley Connect",
                  preferred_year=["freshman", "sophomore", "junior", "senior"],
                  international_friendly="yes",
                  keywords=["mentorship", "undergraduate research"]),
            _prog("data_discovery", "Data Science Discovery Research Program (UC Berkeley)",
                  "https://data.berkeley.edu/research/discovery-research-program",
                  "The Discovery program places teams of undergraduates onto real "
                  "data-science research and industry projects each semester, mentored "
                  "by domain researchers — a structured, low-barrier entry into "
                  "data-intensive research.",
                  organization="Computing, Data Science & Society, UC Berkeley",
                  lab_or_program="Data Science Discovery",
                  eligibility_majors=["Data Science", "Statistics", "Computer Science", "Economics"],
                  preferred_year=["sophomore", "junior", "senior"],
                  international_friendly="yes",
                  deadline_note="Semester cohorts — apply at the start of each term.",
                  keywords=["data science", "undergraduate research", "machine learning"]),
            _prog("calteach", "CalTeach Research & STEM Education (UC Berkeley)",
                  "https://calteach.berkeley.edu/",
                  "CalTeach combines STEM coursework with research and education "
                  "internships for students interested in science research and teaching.",
                  lab_or_program="CalTeach",
                  eligibility_majors=["Biology", "Chemistry", "Physics", "Mathematics", "Engineering"],
                  preferred_year=["freshman", "sophomore", "junior"],
                  international_friendly="yes",
                  keywords=["stem", "undergraduate research", "education"]),
            _prog("transfer_research", "Transfer Student Research Pathways (OURS)",
                  "https://research.berkeley.edu/our/transfer-students/",
                  "OURS guidance and programs designed for transfer students to enter "
                  "research quickly — accelerated mentor-matching, transfer-specific "
                  "research seminars, and funding.",
                  lab_or_program="OURS Transfer",
                  preferred_year=["junior", "senior"],
                  international_friendly="yes",
                  keywords=["undergraduate research", "transfer students", "mentorship"]),
            _prog("stronach", "Stronach Baccalaureate Prize — Year-Long Project",
                  "https://research.berkeley.edu/our/stronach/",
                  "A competitive award funding a year-long independent research or "
                  "creative project for graduating seniors, with a faculty sponsor.",
                  lab_or_program="Stronach Prize",
                  preferred_year=["senior"],
                  paid="stipend", compensation="Project award",
                  deadline_note="Annual — spring of senior year.",
                  keywords=["research grant", "thesis", "undergraduate research"]),
            _prog("summer_sessions_research", "Berkeley Summer Sessions Research & Internships",
                  "https://summer.berkeley.edu/",
                  "Summer Sessions hosts research-credit options (199 units), lab courses, "
                  "and internship-for-credit pathways for students staying on campus over "
                  "the summer.",
                  lab_or_program="Summer Sessions",
                  opportunity_type="summer_program",
                  preferred_year=["freshman", "sophomore", "junior", "senior"],
                  international_friendly="yes",
                  keywords=["summer research", "undergraduate research"]),
        ],
    },

    # ---- RESEARCH CENTERS / INSTITUTES (lab recruiting) -------------------
    {
        "source_name": "ucb_research_centers",
        "source_type": LAB,
        "emit": EMIT_LAB,
        "seeds": [
            "https://sky.cs.berkeley.edu/",
            "https://simons.berkeley.edu/",
            "https://citris-uc.org/",
            "https://www.ssl.berkeley.edu/",
            "https://bsac.berkeley.edu/",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 1,
        "update": MONTHLY,
        "programs": [
            _prog("sky_lab", "Sky Computing Lab — Systems Research (UC Berkeley)",
                  "https://sky.cs.berkeley.edu/",
                  "The Sky Computing Lab (successor to RISELab/AMPLab) does systems "
                  "research on cloud, ML infrastructure, and distributed computing. "
                  "Member groups take undergraduate researchers — reach out to "
                  "individual project leads.",
                  department="Electrical Engineering and Computer Sciences", lab_or_program="Sky Computing Lab",
                  eligibility_majors=["Computer Science", "EECS", "Data Science"],
                  preferred_year=["junior", "senior"],
                  keywords=["systems", "high performance computing", "machine learning", "join our lab"]),
            _prog("simons_inst", "Simons Institute for the Theory of Computing (UC Berkeley)",
                  "https://simons.berkeley.edu/",
                  "The Simons Institute runs semester research programs in theoretical "
                  "computer science. Undergraduates with strong theory backgrounds can "
                  "engage through affiliated faculty and events.",
                  department="Electrical Engineering and Computer Sciences", lab_or_program="Simons Institute",
                  eligibility_majors=["Computer Science", "Mathematics", "EECS"],
                  preferred_year=["junior", "senior"],
                  keywords=["algorithms", "theory", "optimization", "join our lab"]),
            _prog("citris", "CITRIS & the Banatao Institute — Tech for Society Labs",
                  "https://citris-uc.org/",
                  "CITRIS runs interdisciplinary technology research (health, energy, "
                  "robotics, civic tech) and offers undergraduate research and "
                  "innovation programs, including the CITRIS Workforce Innovation roles.",
                  department="CITRIS", lab_or_program="CITRIS",
                  eligibility_majors=["Computer Science", "EECS", "Bioengineering", "Data Science"],
                  preferred_year=["sophomore", "junior", "senior"],
                  keywords=["robotics", "internet of things", "biomedical", "join our lab"]),
            _prog("ssl_lab", "Space Sciences Laboratory — Undergraduate Research (UC Berkeley)",
                  "https://www.ssl.berkeley.edu/",
                  "The Space Sciences Laboratory builds instruments and analyzes data for "
                  "NASA missions in space physics and astrophysics, and hosts "
                  "undergraduate researchers on instrument and data-analysis projects.",
                  department="Space Sciences Laboratory", lab_or_program="Space Sciences Laboratory",
                  eligibility_majors=["Physics", "Astrophysics", "Engineering", "EECS"],
                  preferred_year=["junior", "senior"],
                  keywords=["astrophysics", "signal processing", "remote sensing", "join our lab"]),
            _prog("bsac_lab", "Berkeley Sensor & Actuator Center (BSAC) — MEMS Labs",
                  "https://bsac.berkeley.edu/",
                  "BSAC is an industry-university MEMS and microsystems research center. "
                  "Member labs recruit undergraduate researchers for microfabrication and "
                  "sensor projects.",
                  department="Electrical Engineering and Computer Sciences", lab_or_program="BSAC",
                  eligibility_majors=["Electrical Engineering", "EECS", "Materials Science", "Mechanical Engineering"],
                  preferred_year=["junior", "senior"],
                  keywords=["mems", "microfabrication", "sensors", "join our lab"]),
        ],
    },

    # ---- EXTERNAL / REU-STYLE LISTINGS HOSTED BY BERKELEY -----------------
    {
        "source_name": "ucb_external_reu",
        "source_type": PROGRAM,
        "emit": EMIT_OPEN,
        "seeds": [
            "https://education.lbl.gov/internships/",
            "https://math.berkeley.edu/programs/undergraduate/reu",
        ],
        "crawl": STATIC,
        "update": SEASONAL,
        "programs": [
            _prog("lbl_suli", "Berkeley Lab SULI — DOE Undergraduate Internship",
                  "https://education.lbl.gov/internships/",
                  "Lawrence Berkeley National Laboratory's Science Undergraduate "
                  "Laboratory Internship (SULI, DOE-funded) places undergraduates from "
                  "across the U.S. into Berkeley Lab research for a paid 10-16 week term, "
                  "mentored by lab scientists. Strong REU-style pipeline alongside campus.",
                  organization="Lawrence Berkeley National Laboratory",
                  lab_or_program="Berkeley Lab SULI",
                  opportunity_type="summer_program", paid="yes",
                  compensation="Weekly stipend + possible travel/housing",
                  eligibility_majors=["Physics", "Chemistry", "Engineering", "Computer Science", "Biology"],
                  preferred_year=["sophomore", "junior", "senior"],
                  international_friendly="no",
                  deadline_note="DOE cycles — typically due Jan (summer) and earlier for other terms.",
                  keywords=["summer research", "reu", "national laboratory", "stipend"]),
            _prog("lbl_experiences", "Berkeley Lab Undergraduate Research Experiences",
                  "https://education.lbl.gov/internships/programs/",
                  "Beyond SULI, Berkeley Lab hosts additional undergraduate research "
                  "experiences (CCI, BLUR, and program-specific internships) across "
                  "computing, energy, biosciences, and physics.",
                  organization="Lawrence Berkeley National Laboratory",
                  lab_or_program="Berkeley Lab",
                  opportunity_type="summer_program", paid="yes",
                  compensation="Stipend",
                  preferred_year=["sophomore", "junior", "senior"],
                  international_friendly="no",
                  deadline_note="Varies by program; mostly spring deadlines for summer.",
                  keywords=["summer research", "reu", "national laboratory", "computing"]),
            _prog("math_reu", "Berkeley Mathematics REU / Summer Research",
                  "https://math.berkeley.edu/programs/undergraduate/reu",
                  "Berkeley Math's pointers to summer REU and research opportunities in "
                  "pure and applied mathematics, including the department's own summer "
                  "research and national REU programs.",
                  organization="Department of Mathematics, UC Berkeley",
                  lab_or_program="Math REU",
                  opportunity_type="summer_program",
                  eligibility_majors=["Mathematics", "Applied Mathematics", "Statistics"],
                  preferred_year=["sophomore", "junior"],
                  international_friendly="no",
                  deadline_note="REU cycle — most deadlines Feb-March for summer.",
                  keywords=["summer research", "reu", "mathematics"]),
            _prog("physics_reu", "Berkeley Physics Summer Research / REU pointers",
                  "https://physics.berkeley.edu/academics/undergraduate/summer-research",
                  "Berkeley Physics' compiled summer research and REU options for "
                  "physics undergraduates, on campus and at partner institutions.",
                  organization="Department of Physics, UC Berkeley",
                  lab_or_program="Physics REU",
                  opportunity_type="summer_program",
                  eligibility_majors=["Physics", "Astrophysics", "Engineering Physics"],
                  preferred_year=["sophomore", "junior"],
                  international_friendly="no",
                  deadline_note="REU cycle — most deadlines Feb-March for summer.",
                  keywords=["summer research", "reu", "physics", "astrophysics"]),
        ],
    },

    # ---- NEWSLETTER / BULLETIN INGESTION (lightweight) --------------------
    {
        "source_name": "ucb_newsletters",
        "source_type": ANNOUNCEMENT,
        "emit": EMIT_CAMPUS,
        "seeds": [
            "https://research.berkeley.edu/our/newsletter/",
            "https://engineering.berkeley.edu/news/",
            "https://data.berkeley.edu/news",
        ],
        "crawl": RECURSIVE,
        "crawl_depth": 1,
        "update": WEEKLY,
        "programs": [
            _prog("ours_newsletter", "OURS Undergraduate Research Newsletter (UC Berkeley)",
                  "https://research.berkeley.edu/our/newsletter/",
                  "The OURS newsletter aggregates fresh undergraduate research calls, "
                  "deadlines, info sessions, and newly funded programs each cycle. "
                  "A bulletin-style feed of campus-wide opportunities that often "
                  "predate dedicated program pages.",
                  lab_or_program="OURS Newsletter",
                  preferred_year=["freshman", "sophomore", "junior", "senior"],
                  international_friendly="yes",
                  keywords=["undergraduate research", "newsletter", "announcement"]),
            _prog("coe_news", "Berkeley Engineering News — Student Research Bulletin",
                  "https://engineering.berkeley.edu/news/",
                  "Berkeley Engineering news stream that periodically announces "
                  "undergraduate research programs, design-team recruiting, and "
                  "internship calls across engineering departments.",
                  organization="College of Engineering, UC Berkeley",
                  lab_or_program="Berkeley Engineering News",
                  eligibility_majors=["Engineering"],
                  preferred_year=["freshman", "sophomore", "junior", "senior"],
                  international_friendly="yes",
                  keywords=["announcement", "undergraduate research", "engineering"]),
            _prog("cdss_news", "CDSS / Data Science News — Research Bulletin",
                  "https://data.berkeley.edu/news",
                  "Computing, Data Science & Society news feed that surfaces data-science "
                  "research program calls, Discovery cohort openings, and undergraduate "
                  "research announcements.",
                  organization="Computing, Data Science & Society, UC Berkeley",
                  lab_or_program="CDSS News",
                  eligibility_majors=["Data Science", "Statistics", "Computer Science"],
                  preferred_year=["freshman", "sophomore", "junior", "senior"],
                  international_friendly="yes",
                  keywords=["announcement", "data science", "undergraduate research"]),
        ],
    },
]


# --- Registry helpers -------------------------------------------------------

def all_source_names() -> list[str]:
    return [s["source_name"] for s in UCB_SOURCES]


def sources_by_type(source_type: str) -> list[dict]:
    return [s for s in UCB_SOURCES if s["source_type"] == source_type]


def iter_programs():
    """Yield (source, program) for every curated program in the registry."""
    for source in UCB_SOURCES:
        for program in source.get("programs", []):
            yield source, program


def total_seed_count() -> int:
    return sum(len(s.get("programs", [])) for s in UCB_SOURCES)


def validate_registry() -> list[str]:
    """Return a list of structural problems (empty = healthy). Cheap enough to
    run as a test and at the top of the collector so a malformed entry fails
    loudly instead of silently dropping a source."""
    errors: list[str] = []
    seen_source_names: set[str] = set()
    seen_keys: set[str] = set()
    for s in UCB_SOURCES:
        name = s.get("source_name", "")
        if not name:
            errors.append("source with no source_name")
        if name in seen_source_names:
            errors.append(f"duplicate source_name: {name}")
        seen_source_names.add(name)
        if s.get("source_type") not in SOURCE_TYPES:
            errors.append(f"{name}: bad source_type {s.get('source_type')!r}")
        if s.get("emit") not in EMIT_BUCKETS:
            errors.append(f"{name}: bad emit bucket {s.get('emit')!r}")
        if s.get("crawl") not in CRAWL_STRATEGIES:
            errors.append(f"{name}: bad crawl strategy {s.get('crawl')!r}")
        if not s.get("seeds"):
            errors.append(f"{name}: no seed URLs")
        for p in s.get("programs", []):
            k = p.get("key")
            if not k:
                errors.append(f"{name}: program with no key")
            if k in seen_keys:
                errors.append(f"duplicate program key: {k}")
            seen_keys.add(k)
            if not p.get("title") or not p.get("url"):
                errors.append(f"{name}/{k}: missing title or url")
            if p.get("opportunity_type") not in {"research", "summer_program", "internship", "fellowship"}:
                errors.append(f"{name}/{k}: bad opportunity_type {p.get('opportunity_type')!r}")
    return errors
