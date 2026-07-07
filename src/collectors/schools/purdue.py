"""Purdue University campus opportunity-graph config (US-News rollout).

Curated seed of Purdue's undergraduate-research landscape: the Office of
Undergraduate Research (OUR) hub, the College of Engineering SURF program, the
Center for Career Success, and Discovery Park research institutes. URLs verified
against purdue.edu (Jul 2026).

Emit buckets -> (source, school, audience), kept in lockstep with
school_audience.SOURCE_DEFAULTS:
    campus -> purdue_research_programs (purdue / campus)
    open   -> purdue_external_research (national / open)
    lab    -> purdue_labs              (purdue / unknown)
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
    "school_slug": "purdue",
    "organization": "Purdue University",
    "location": "West Lafayette, IN",
    "emit": {
        "campus": ("purdue_research_programs", "purdue", "campus"),
        "open": ("purdue_external_research", None, "open"),
        "lab": ("purdue_labs", "purdue", "unknown"),
    },
    "sources": [
        {
            "source_name": "purdue_our_hub",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": ["https://www.purdue.edu/undergrad-research/"],
            "crawl": RECURSIVE,
            "crawl_depth": 2,
            "programs": [
                program(
                    "our_hub",
                    "Office of Undergraduate Research (OUR) — Hub (Purdue)",
                    "https://www.purdue.edu/undergrad-research/",
                    "Purdue's central hub for undergraduate research: the fall/spring "
                    "Undergraduate Research Expo, research assistantships, scholarships, "
                    "and faculty-mentor matching across all colleges. Start here to find "
                    "a program by class year and field.",
                    lab_or_program="Office of Undergraduate Research",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["undergraduate research", "mentorship"],
                ),
            ],
        },
        {
            "source_name": "purdue_engineering_research",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": ["https://engineering.purdue.edu/Engr/Academics/Undergraduate/SURF"],
            "crawl": STATIC,
            "programs": [
                program(
                    "surf",
                    "Summer Undergraduate Research Fellowship (SURF) — Engineering (Purdue)",
                    "https://engineering.purdue.edu/Engr/Academics/Undergraduate/SURF",
                    "An 11-week full-time summer research program placing undergraduates "
                    "in College of Engineering labs alongside graduate-student mentors. "
                    "Pays a stipend (~$4,500) plus housing support; open to students from "
                    "Purdue and other institutions considering graduate study.",
                    organization="College of Engineering, Purdue University",
                    department="Engineering",
                    lab_or_program="SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="~$4,500 summer stipend + housing",
                    eligibility_majors=["Engineering", "Computer Science"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="unknown",
                    deadline_note="Annual summer cycle; applications typically due late winter.",
                    keywords=["summer research", "engineering", "stipend"],
                ),
            ],
        },
        {
            "source_name": "purdue_career",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": ["https://www.cco.purdue.edu/"],
            "crawl": STATIC,
            "programs": [
                program(
                    "career_success",
                    "Center for Career Success — Internships (Purdue)",
                    "https://www.cco.purdue.edu/",
                    "Purdue's Center for Career Success supports undergraduates with "
                    "internship and job search, career fairs, and the campus job board. "
                    "Open to all class years and majors.",
                    organization="Center for Career Success, Purdue University",
                    lab_or_program="Center for Career Success",
                    opportunity_type="internship",
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    keywords=["internship", "career"],
                ),
            ],
        },
        {
            "source_name": "purdue_institutes",
            "source_type": LAB,
            "emit": "lab",
            "seeds": ["https://www.purdue.edu/discoverypark/"],
            "crawl": RECURSIVE,
            "crawl_depth": 1,
            "programs": [
                program(
                    "discovery_park",
                    "Discovery Park District Institutes — Undergraduate Research (Purdue)",
                    "https://www.purdue.edu/discoverypark/",
                    "Purdue's interdisciplinary research institutes (Birck Nanotechnology "
                    "Center, Bindley Bioscience Center, and others) host undergraduate "
                    "researchers across nanotechnology, life sciences, and data science — "
                    "good cold-email targets for lab placements.",
                    department="Discovery Park",
                    lab_or_program="Discovery Park Institutes",
                    eligibility_majors=["Engineering", "Biology", "Data Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="unknown",
                    keywords=["nanotechnology", "bioscience", "join our lab"],
                ),
            ],
        },
        # --- Harvested program catalog (Jul 2026): every live-verified
        # undergraduate-research program, fellowship, and institute. ---
        {
            "source_name": "purdue_catalog_announcement_campus",
            "source_type": ANNOUNCEMENT,
            "emit": "campus",
            "seeds": [
                "https://www.purdue.edu/undergrad-research/ourconnect/",
                "https://www.purdue.edu/undergrad-research/seminar-series/index.php",
                "https://www.purdue.edu/undergrad-research/conferences/celebrate/index.php",
                "https://www.purdue.edu/undergrad-research/conferences/showcase/index.php",
                "https://www.purdue.edu/niso/scholarship/majorlist/index.html",
                "https://www.purdue.edu/undergrad-research/scholarships/ExtGrants.php",
                "https://www.purdue.edu/undergrad-research/conferences/fall/index.php",
                "https://www.purdue.edu/undergrad-research/conferences/spring/index.php",
                "https://www.purdue.edu/undergrad-research/conferences/summer/index.php",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "ourconnect",
                    "Purdue OURConnect \u2014 Undergraduate Research Opportunity Database",
                    "https://www.purdue.edu/undergrad-research/ourconnect/",
                    "Purdue's searchable database of undergraduate research opportunities and "
                    "programs across campus, run by the Office of Undergraduate Research. "
                    "Students browse faculty projects, programs, and openings by field and "
                    "eligibility. The primary tool for matching Purdue undergraduates to "
                    "mentored research.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="OURConnect",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling",
                    keywords=["opportunity database", "research listings", "OURConnect"],
                ),
                program(
                    "our_seminar_series",
                    "Purdue OUR Seminar Series",
                    "https://www.purdue.edu/undergrad-research/seminar-series/index.php",
                    "A seminar series run by Purdue's Office of Undergraduate Research covering "
                    "topics that help undergraduates start and advance in research. An "
                    "engagement/learning resource rather than a research placement. Open to all "
                    "Purdue undergraduates.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="OUR Seminar Series",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Ongoing during academic year",
                    keywords=["seminar", "professional development", "research skills"],
                ),
                program(
                    "celebrate_conference",
                    "Purdue Celebrate: Thinkers, Creators & Experimenters",
                    "https://www.purdue.edu/undergrad-research/conferences/celebrate/index.php",
                    "A hands-on spring symposium (West Lafayette) where undergraduates showcase "
                    "tangible research and creative projects \u2014 robots, models, programs, "
                    "performances \u2014 that attendees can interact with directly. A "
                    "presentation/engagement event rather than a research placement. Open to "
                    "individual or group projects, class work, and independent research; 2026 "
                    "event Apr 16 with a Mar 30 application deadline.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Celebrate: Thinkers, Creators & Experimenters",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="~Late March application; April event",
                    keywords=["symposium", "creative work", "hands-on showcase"],
                ),
                program(
                    "innovation_excellence_showcase",
                    "Purdue Innovation & Excellence Showcase (OUR)",
                    "https://www.purdue.edu/undergrad-research/conferences/showcase/index.php",
                    "A poster-presentation showcase for Purdue students at the Indianapolis "
                    "location to present scholarly and creative projects (including EPICS, VIP, "
                    "and Data Mine work). Distinct from the West Lafayette 'Celebrate' event. A "
                    "presentation venue rather than a research placement; 2026 event Apr 30.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Student Innovation & Excellence Showcase",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Spring; Indianapolis campus",
                    keywords=["showcase", "Indianapolis", "poster presentation"],
                ),
                program(
                    "niso_scholarship_list",
                    "Purdue NISO \u2014 Major Scholarships Coordinated (Full List)",
                    "https://www.purdue.edu/niso/scholarship/majorlist/index.html",
                    "NISO's index of the major national and international scholarships and "
                    "fellowships it coordinates for Purdue students, many research-oriented "
                    "(Goldwater, NSF GRFP, Fulbright, Udall, etc.). A resource/directory page "
                    "linking to individual scholarship advising pages. Open to eligible "
                    "undergraduates and recent grads.",
                    organization="Purdue University",
                    department="National & International Scholarships Office",
                    lab_or_program="NISO Scholarship List",
                    opportunity_type="fellowship",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Varies by scholarship",
                    keywords=["scholarship directory", "fellowships", "NISO"],
                ),
                program(
                    "our_ext_grants",
                    "Purdue OUR \u2014 Non-OUR (External) Grants & Funding List",
                    "https://www.purdue.edu/undergrad-research/scholarships/ExtGrants.php",
                    "A curated list maintained by Purdue's OUR of external and non-OUR grants, "
                    "scholarships, and funding sources undergraduates can use to support "
                    "research. Points students to college-, department-, and nationally "
                    "sponsored funding beyond OUR's own awards. A resource page rather than a "
                    "single application.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="External Grants List",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Varies by external source",
                    keywords=["external funding", "grants list", "scholarships"],
                ),
                program(
                    "fall_research_expo",
                    "Purdue Fall Undergraduate Research Expo",
                    "https://www.purdue.edu/undergrad-research/conferences/fall/index.php",
                    "A fall showcase where Purdue undergraduates present their research to the "
                    "campus community, organized by the Office of Undergraduate Research. A "
                    "dissemination/presentation venue rather than a research placement. Open to "
                    "undergraduates who have research to present.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Fall Research Expo",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Fall semester; registration required",
                    keywords=["expo", "poster presentation", "conference"],
                ),
                program(
                    "spring_research_conference",
                    "Purdue Undergraduate Research Conference (Spring)",
                    "https://www.purdue.edu/undergrad-research/conferences/spring/index.php",
                    "Purdue's spring undergraduate research conference where students across "
                    "disciplines present posters and talks on their work, run by the Office of "
                    "Undergraduate Research. A presentation venue rather than a research "
                    "placement. Open to undergraduates with research to share.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Spring Undergraduate Research Conference",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Spring semester; registration required",
                    keywords=["conference", "poster presentation", "spring"],
                ),
                program(
                    "summer_research_symposium",
                    "Purdue Summer Undergraduate Research Symposium",
                    "https://www.purdue.edu/undergrad-research/conferences/summer/index.php",
                    "A summer symposium where students in Purdue's summer research programs "
                    "(such as SURF) present their projects, coordinated by the Office of "
                    "Undergraduate Research. A capstone presentation venue for summer "
                    "researchers rather than a standalone placement. Open to summer research "
                    "participants.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Summer Research Symposium",
                    opportunity_type="summer_program",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="End of summer session",
                    keywords=["summer symposium", "presentation", "SURF"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_announcement_open",
            "source_type": ANNOUNCEMENT,
            "emit": "open",
            "seeds": [
                "https://www.nsf.gov/funding/initiatives/reu/students",
                "https://www.pathwaystoscience.org/undergrads.aspx",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "nsf_reu_sites",
                    "NSF Research Experiences for Undergraduates (REU) Sites",
                    "https://www.nsf.gov/funding/initiatives/reu/students",
                    "The National Science Foundation's REU program funds summer research "
                    "placements at host institutions nationwide across science, engineering, "
                    "and math fields. Undergraduates apply directly to individual REU Sites and "
                    "receive a stipend, and often housing and travel support, for full-time "
                    "mentored research. A national program many Purdue students apply to; U.S. "
                    "citizen/permanent-resident requirements typically apply.",
                    organization="National Science Foundation",
                    lab_or_program="Research Experiences for Undergraduates (REU)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend plus common housing/travel support",
                    eligibility_majors=["science", "engineering", "mathematics", "computer science"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Varies by site; most deadlines December\u2013February for summer",
                    keywords=["REU", "NSF", "summer research", "stipend", "national"],
                ),
                program(
                    "pathways_to_science",
                    "Pathways to Science (undergraduate opportunities database)",
                    "https://www.pathwaystoscience.org/undergrads.aspx",
                    "A searchable national database of summer research programs, REUs, and STEM "
                    "opportunities for undergraduates, maintained by the Institute for "
                    "Broadening Participation. Students filter by discipline, location, and "
                    "eligibility to find funded research placements. Free to use; a discovery "
                    "hub rather than a single program, widely used by Purdue and other students "
                    "to find external opportunities.",
                    organization="Institute for Broadening Participation",
                    lab_or_program="Pathways to Science",
                    opportunity_type="summer_program",
                    compensation="Varies by listed program",
                    eligibility_majors=["science", "engineering", "mathematics", "computer science"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    deadline_note="Varies by listed program",
                    keywords=["database", "summer research", "STEM", "REU", "opportunities"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_career_campus",
            "source_type": CAREER,
            "emit": "campus",
            "seeds": [
                "https://www.opp.purdue.edu/our-programs/undergrad-co-op",
                "https://www.opp.purdue.edu/our-programs/academic-internships",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "opp_undergrad_coop",
                    "Purdue Undergraduate Co-op (Office of Professional Practice)",
                    "https://www.opp.purdue.edu/our-programs/undergrad-co-op",
                    "A structured, multi-semester paid cooperative-education program run by "
                    "Purdue's Office of Professional Practice, alternating academic study with "
                    "full-time professional work at partner employers. Open to undergraduates "
                    "(primarily in engineering, technology, science, and related fields) who "
                    "want extended, career-relevant industry experience. Students earn a salary "
                    "during work terms and gain a Co-op designation on their transcript.",
                    organization="Purdue University",
                    department="Office of Professional Practice",
                    lab_or_program="Undergraduate Co-op Program",
                    opportunity_type="internship",
                    paid="yes",
                    compensation="Paid salary during work terms",
                    eligibility_majors=["engineering", "technology", "science", "computer science", "agriculture"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling application; apply before intended first work term",
                    keywords=["co-op", "cooperative education", "professional practice", "paid", "industry"],
                ),
                program(
                    "opp_academic_internships",
                    "Purdue Academic Internships (Office of Professional Practice)",
                    "https://www.opp.purdue.edu/our-programs/academic-internships",
                    "A for-credit internship program administered by Purdue's Office of "
                    "Professional Practice, letting undergraduates complete a professional work "
                    "experience tied to their academic program. Typically a single work term "
                    "(often summer) with a partner employer, with the internship recorded on "
                    "the transcript. Open to undergraduates seeking career-relevant experience; "
                    "often paid by the host employer.",
                    organization="Purdue University",
                    department="Office of Professional Practice",
                    lab_or_program="Academic Internships Program",
                    opportunity_type="internship",
                    compensation="Often paid by host employer; varies",
                    eligibility_majors=["engineering", "technology", "science", "computer science", "agriculture"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling; apply before intended work term",
                    keywords=["internship", "for credit", "professional practice", "industry"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_department_campus",
            "source_type": DEPARTMENT,
            "emit": "campus",
            "seeds": [
                "https://www.purdue.edu/niso/",
                "https://www.purdue.edu/science/Current_Students/research/index.html",
                "https://ag.purdue.edu/department/oap/cate/research/",
                "https://hhs.purdue.edu/undergraduate/research/",
                "https://polytechnic.purdue.edu/research",
                "https://www.cla.purdue.edu/research/undergraduate/index.html",
                "https://www.chem.purdue.edu/academic_programs/undergraduate/internships.html",
                "https://www.cs.purdue.edu/undergraduate/undergraduate-research.html",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "niso",
                    "Purdue National & International Scholarships Office (NISO)",
                    "https://www.purdue.edu/niso/",
                    "Purdue's office that advises students competing for prestigious national "
                    "and international scholarships and fellowships (Goldwater, Fulbright, NSF "
                    "GRFP, Rhodes, and more), many of which fund research. Provides application "
                    "coaching, essay review, and endorsement. Open to high-achieving "
                    "undergraduates and recent grads.",
                    organization="Purdue University",
                    department="National & International Scholarships Office",
                    lab_or_program="NISO",
                    opportunity_type="fellowship",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Varies by scholarship",
                    keywords=["NISO", "fellowships advising", "national scholarships"],
                ),
                program(
                    "cos_ugresearch",
                    "College of Science Undergraduate Research \u2014 Purdue University",
                    "https://www.purdue.edu/science/Current_Students/research/index.html",
                    "The College of Science's undergraduate research office, listing how "
                    "science majors (biology, chemistry, math, physics, statistics, computer "
                    "science, EAPS) can find faculty mentors, earn research credit, and access "
                    "funding and summer opportunities. A departmental gateway rather than a "
                    "single program.",
                    organization="Purdue University",
                    department="College of Science",
                    lab_or_program="College of Science Undergraduate Research",
                    compensation="Varies by lab/program",
                    eligibility_majors=["biology", "chemistry", "mathematics", "physics", "statistics", "computer science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; contact faculty directly",
                    keywords=["College of Science", "science research", "faculty mentor"],
                ),
                program(
                    "ag_cate_research",
                    "College of Agriculture Research Opportunities (CATE) \u2014 Purdue University",
                    "https://ag.purdue.edu/department/oap/cate/research/",
                    "The College of Agriculture's Center for Advancing the Teaching and "
                    "learning of STEM / Office of Academic Programs research page, aggregating "
                    "undergraduate research opportunities including SCARF and semester research "
                    "placements for Ag students. A departmental hub for finding mentors and "
                    "funded projects.",
                    organization="Purdue University",
                    department="College of Agriculture",
                    lab_or_program="CATE / Office of Academic Programs Research",
                    compensation="Varies; includes funded programs like SCARF",
                    eligibility_majors=["agriculture", "life sciences"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Program-specific deadlines",
                    keywords=["agriculture", "CATE", "research office", "undergraduate"],
                ),
                program(
                    "hhs_ugresearch",
                    "College of Health and Human Sciences Undergraduate Research \u2014 Purdue University",
                    "https://hhs.purdue.edu/undergraduate/research/",
                    "The College of Health and Human Sciences undergraduate research office, "
                    "guiding students in nutrition, psychology, speech/hearing, human "
                    "development, public health, and related fields toward faculty-mentored "
                    "research, credit, and funding. A departmental gateway to labs and programs "
                    "across HHS.",
                    organization="Purdue University",
                    department="College of Health and Human Sciences",
                    lab_or_program="HHS Undergraduate Research",
                    compensation="Varies by lab/program",
                    eligibility_majors=["health sciences", "nutrition", "psychology", "human development", "public health", "speech and hearing sciences"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; contact faculty/departments",
                    keywords=["HHS", "health sciences", "undergraduate research"],
                ),
                program(
                    "polytechnic_research",
                    "Purdue Polytechnic Institute Office of Research (Undergraduate Research) \u2014 Purdue University",
                    "https://polytechnic.purdue.edu/research",
                    "The Polytechnic Institute's research office, connecting undergraduates in "
                    "technology, construction, aviation, computer/information technology, and "
                    "engineering technology fields to faculty research, REUs, and funded "
                    "projects. A departmental hub rather than a single named program.",
                    organization="Purdue University",
                    department="Purdue Polytechnic Institute",
                    lab_or_program="Polytechnic Institute Office of Research",
                    compensation="Varies by program",
                    eligibility_majors=["technology", "engineering technology", "construction management", "aviation", "information technology"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Program-specific deadlines",
                    keywords=["polytechnic", "technology research", "research office"],
                ),
                program(
                    "cla_ugresearch",
                    "College of Liberal Arts Undergraduate Research \u2014 Purdue University",
                    "https://www.cla.purdue.edu/research/undergraduate/index.html",
                    "The College of Liberal Arts undergraduate research office, helping "
                    "humanities and social-science students find faculty mentors, research "
                    "grants, and presentation venues. Covers fields like history, "
                    "communication, political science, psychology, languages, and the arts. A "
                    "departmental gateway to CLA research.",
                    organization="Purdue University",
                    department="College of Liberal Arts",
                    lab_or_program="CLA Undergraduate Research",
                    compensation="Varies; some CLA research grants available",
                    eligibility_majors=["humanities", "social sciences", "communication", "political science", "history", "psychology"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; grant-specific deadlines",
                    keywords=["liberal arts", "humanities", "social science research"],
                ),
                program(
                    "chem_research_internships",
                    "Chemistry Undergraduate Research & Internships \u2014 Purdue University",
                    "https://www.chem.purdue.edu/academic_programs/undergraduate/internships.html",
                    "The Department of Chemistry's page on undergraduate research and "
                    "internships, guiding chemistry and biochemistry students to faculty "
                    "research placements, summer REUs, and industry internships, plus how to "
                    "earn research credit. A departmental gateway to chemistry research "
                    "opportunities.",
                    organization="Purdue University",
                    department="Department of Chemistry",
                    lab_or_program="Chemistry Undergraduate Research & Internships",
                    compensation="Varies by lab/internship",
                    eligibility_majors=["chemistry", "biochemistry"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; program-specific deadlines",
                    keywords=["chemistry", "research", "internships", "REU"],
                ),
                program(
                    "cs_ugresearch",
                    "Computer Science Undergraduate Research \u2014 Purdue University",
                    "https://www.cs.purdue.edu/undergraduate/undergraduate-research.html",
                    "The Department of Computer Science's undergraduate research page, "
                    "explaining how CS students find faculty mentors, join research groups, "
                    "earn research credit, and access programs like the Undergraduate Research "
                    "Experience. A departmental gateway to computing research across AI, "
                    "systems, theory, security, and more.",
                    organization="Purdue University",
                    department="Department of Computer Science",
                    lab_or_program="Computer Science Undergraduate Research",
                    compensation="Varies by lab/program",
                    eligibility_majors=["computer science", "data science"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; contact faculty/research groups",
                    keywords=["computer science", "undergraduate research", "AI", "systems"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_lab_lab",
            "source_type": LAB,
            "emit": "lab",
            "seeds": [
                "https://www.purdue.edu/computes/aida3/",
                "https://www.purdue.edu/discoverypark/drug-discovery/",
                "https://www.purdue.edu/research/embrio/",
                "https://www.purdue.edu/discoverypark/food/",
                "https://www.purdue.edu/discoverypark/institute-for-integrative-neuroscience/",
                "https://www.purdue.edu/discoverypark/pi4d/",
                "https://www.rcac.purdue.edu/anvil/reu",
                "https://www.math.purdue.edu/pxml",
                "https://www.purdue.edu/research/rche/",
                "https://www.cerias.purdue.edu/",
                "https://engineering.purdue.edu/CSME",
                "https://engineering.purdue.edu/Initiatives/IEI",
                "https://engineering.purdue.edu/JTRP",
                "https://www.rcac.purdue.edu/",
                "https://www.purdue.edu/discoverypark/WGHI/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "aida3_aviation_ai",
                    "Center on AI for Digital, Autonomous, and Augmented Aviation (AIDA3) \u2014 Purdue University",
                    "https://www.purdue.edu/computes/aida3/",
                    "AIDA3 is a Purdue center advancing artificial intelligence for aviation \u2014 "
                    "autonomous flight, digital aviation systems, and human-AI teaming. "
                    "Undergraduates engage through affiliated faculty research and "
                    "interdisciplinary projects. Compensation varies by project and funding.",
                    organization="Purdue University",
                    department="Purdue Computes",
                    lab_or_program="AIDA3",
                    compensation="Varies by project",
                    eligibility_majors=["Aeronautical Engineering", "Computer Science", "Electrical Engineering", "Aviation Technology", "Data Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["aviation", "artificial intelligence", "autonomous flight", "digital aviation"],
                ),
                program(
                    "pidd_drug_discovery",
                    "Purdue Institute for Drug Discovery (PIDD) \u2014 Purdue University",
                    "https://www.purdue.edu/discoverypark/drug-discovery/",
                    "The Purdue Institute for Drug Discovery unites chemists, biologists, and "
                    "pharmacy researchers to develop new therapeutics from target to lead "
                    "compound. Undergraduates participate through affiliated faculty labs and "
                    "summer research. Summer positions commonly carry a stipend; academic-year "
                    "roles vary.",
                    organization="Purdue University",
                    department="Discovery Park District",
                    lab_or_program="Purdue Institute for Drug Discovery",
                    compensation="Varies by lab; summer research often stipended",
                    eligibility_majors=["Chemistry", "Biochemistry", "Pharmacy", "Medicinal Chemistry", "Biology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty; summer programs close in spring",
                    keywords=["drug discovery", "medicinal chemistry", "therapeutics", "pharmacology"],
                ),
                program(
                    "embrio_institute",
                    "EMBRIO Institute (Emergent Mechanisms in Biology of Robustness, Integration & Organization) \u2014 Purdue Universit",
                    "https://www.purdue.edu/research/embrio/",
                    "EMBRIO is an NSF-funded Biology Integration Institute using AI and "
                    "mathematical modeling to understand how cells integrate signals across "
                    "scales. Undergraduates engage through affiliated faculty labs and "
                    "interdisciplinary summer research. Summer/REU roles typically carry a "
                    "stipend.",
                    organization="Purdue University",
                    department="NSF Biology Integration Institute",
                    lab_or_program="EMBRIO Institute",
                    compensation="Varies by lab; REU/summer roles stipended",
                    eligibility_majors=["Biology", "Biomedical Engineering", "Physics", "Mathematics", "Computer Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty; REU closes early spring",
                    keywords=["quantitative biology", "cell biology", "AI in biology", "biophysics", "NSF"],
                ),
                program(
                    "global_food_security",
                    "Purdue Center for Global Food Security \u2014 Purdue University",
                    "https://www.purdue.edu/discoverypark/food/",
                    "The Purdue Center for Global Food Security tackles hunger, agricultural "
                    "productivity, and food-system resilience through interdisciplinary "
                    "research. Undergraduates engage through affiliated faculty labs and "
                    "agriculture/development projects. Compensation varies by project and "
                    "funding.",
                    organization="Purdue University",
                    department="Discovery Park District",
                    lab_or_program="Center for Global Food Security",
                    compensation="Varies by project",
                    eligibility_majors=["Agricultural Economics", "Agronomy", "Food Science", "Environmental Science", "Nutrition Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["food security", "agriculture", "hunger", "food systems", "global development"],
                ),
                program(
                    "piin_neuroscience",
                    "Purdue Institute for Integrative Neuroscience (PIIN) \u2014 Purdue University",
                    "https://www.purdue.edu/discoverypark/institute-for-integrative-neuroscience/",
                    "The Purdue Institute for Integrative Neuroscience connects researchers "
                    "studying the brain from molecules to behavior, including neuroengineering "
                    "and neurological disease. Undergraduates engage through affiliated faculty "
                    "labs and summer research. Summer positions commonly carry a stipend; "
                    "academic-year roles vary.",
                    organization="Purdue University",
                    department="Discovery Park District",
                    lab_or_program="Purdue Institute for Integrative Neuroscience",
                    compensation="Varies by lab; summer research often stipended",
                    eligibility_majors=["Neuroscience", "Biology", "Psychology", "Biomedical Engineering", "Pharmacy"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty; summer programs close in spring",
                    keywords=["neuroscience", "brain", "neuroengineering", "behavior", "neurological disease"],
                ),
                program(
                    "pi4d_immunology",
                    "Purdue Institute of Inflammation, Immunology and Infectious Disease (PI4D) \u2014 Purdue University",
                    "https://www.purdue.edu/discoverypark/pi4d/",
                    "PI4D advances research on inflammation, immunology, and infectious "
                    "disease, spanning microbiology, vaccines, and immune engineering. "
                    "Undergraduates engage through affiliated faculty labs and summer research. "
                    "Summer positions commonly carry a stipend; academic-year roles vary.",
                    organization="Purdue University",
                    department="Discovery Park District",
                    lab_or_program="Purdue Institute of Inflammation, Immunology and Infectious ",
                    compensation="Varies by lab; summer research often stipended",
                    eligibility_majors=["Microbiology", "Biology", "Biochemistry", "Biomedical Engineering", "Immunology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty; summer programs close in spring",
                    keywords=["immunology", "inflammation", "infectious disease", "microbiology", "vaccines"],
                ),
                program(
                    "anvil_reu",
                    "Anvil / RCAC Advanced Computing REU \u2014 Purdue University",
                    "https://www.rcac.purdue.edu/anvil/reu",
                    "An NSF-funded REU hosted by Purdue's Rosen Center for Advanced Computing "
                    "around the Anvil supercomputer, offering an 11-week summer internship "
                    "(May\u2013August) in AI, high-performance computing, data analytics, and "
                    "software. Pays ~$680/week (~$7,500 total) plus furnished housing, "
                    "conference travel, and mentorship. Restricted to US citizens/permanent "
                    "residents.",
                    organization="Purdue University",
                    department="Rosen Center for Advanced Computing (RCAC)",
                    lab_or_program="Anvil Advanced Computing REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$680/week (~$7,500 total) plus housing; benefits exceed $14,000",
                    eligibility_majors=["computer science", "computer engineering", "data science", "mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Summer 2026 deadline Feb 16, 2026; runs May\u2013August",
                    keywords=["REU", "supercomputing", "Anvil", "HPC", "AI"],
                ),
                program(
                    "experimental_math_lab",
                    "Purdue Experimental Mathematics Lab (PXML) \u2014 Purdue University",
                    "https://www.math.purdue.edu/pxml",
                    "A Department of Mathematics lab where undergraduates join faculty- and "
                    "graduate-mentored teams on semester-long experimental and computational "
                    "math research projects, presenting results at a poster session. Open to "
                    "Purdue math and quantitative undergraduates; a good on-ramp to research "
                    "during the academic year.",
                    organization="Purdue University",
                    department="Department of Mathematics",
                    lab_or_program="Purdue Experimental Mathematics Lab (PXML)",
                    compensation="Varies; some credit/funded roles",
                    eligibility_majors=["mathematics", "statistics", "computer science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications each semester",
                    keywords=["experimental math", "PXML", "research lab", "mathematics"],
                ),
                program(
                    "rche_regenstrief",
                    "Regenstrief Center for Healthcare Engineering (RCHE) \u2014 Purdue University",
                    "https://www.purdue.edu/research/rche/",
                    "The Regenstrief Center for Healthcare Engineering applies systems "
                    "engineering and data analytics to improve healthcare delivery, patient "
                    "safety, and operations. Undergraduates join interdisciplinary project "
                    "teams and faculty research through RCHE. Roles range from volunteer to "
                    "stipended depending on the project and funding.",
                    organization="Purdue University",
                    department="College of Engineering",
                    lab_or_program="Regenstrief Center for Healthcare Engineering",
                    compensation="Varies by project",
                    eligibility_majors=["Industrial Engineering", "Biomedical Engineering", "Public Health", "Data Science", "Nursing"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty/project teams",
                    keywords=["healthcare engineering", "systems engineering", "health analytics", "patient safety"],
                ),
                program(
                    "cerias",
                    "CERIAS \u2014 Center for Education and Research in Information Assurance and Security \u2014 Purdue University",
                    "https://www.cerias.purdue.edu/",
                    "CERIAS is one of the world's leading multidisciplinary cybersecurity "
                    "research and education centers, spanning technical security, privacy, and "
                    "policy. Undergraduates can engage through affiliated faculty labs, "
                    "seminars, and research projects in information assurance. Compensation "
                    "varies by lab and funding.",
                    organization="Purdue University",
                    department="College of Science / Computer Science",
                    lab_or_program="CERIAS",
                    compensation="Varies by faculty lab",
                    eligibility_majors=["Computer Science", "Cybersecurity", "Electrical Engineering", "Information Technology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["cybersecurity", "information assurance", "privacy", "security research"],
                ),
                program(
                    "csme_microelectronics",
                    "Center for Secure Microelectronics Ecosystem (CSME) \u2014 Purdue University",
                    "https://engineering.purdue.edu/CSME",
                    "The Center for Secure Microelectronics Ecosystem advances trusted and "
                    "secure semiconductor design, packaging, and supply-chain assurance. "
                    "Undergraduates participate through affiliated faculty labs in the College "
                    "of Engineering. Compensation varies by lab and funding.",
                    organization="Purdue University",
                    department="College of Engineering",
                    lab_or_program="Center for Secure Microelectronics Ecosystem",
                    compensation="Varies by faculty lab",
                    eligibility_majors=["Electrical Engineering", "Computer Engineering", "Materials Science", "Computer Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["microelectronics", "semiconductors", "hardware security", "chip design"],
                ),
                program(
                    "iei_energy_innovation",
                    "Institute for Energy Innovation (IEI) \u2014 Purdue University",
                    "https://engineering.purdue.edu/Initiatives/IEI",
                    "The Institute for Energy Innovation coordinates Purdue research on "
                    "next-generation energy \u2014 nuclear, grid modernization, storage, and clean "
                    "fuels. Undergraduates engage through affiliated faculty labs and "
                    "energy-focused projects. Compensation varies by hosting lab and funding.",
                    organization="Purdue University",
                    department="College of Engineering",
                    lab_or_program="Institute for Energy Innovation",
                    compensation="Varies by project",
                    eligibility_majors=["Nuclear Engineering", "Electrical Engineering", "Mechanical Engineering", "Chemical Engineering", "Environmental Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["energy", "nuclear", "grid", "clean energy", "storage"],
                ),
                program(
                    "jtrp_transportation",
                    "Joint Transportation Research Program (JTRP) \u2014 Purdue University",
                    "https://engineering.purdue.edu/JTRP",
                    "The Joint Transportation Research Program is a long-running partnership "
                    "between Purdue and the Indiana Department of Transportation producing "
                    "applied research on roads, bridges, materials, and mobility. "
                    "Undergraduates engage through affiliated civil-engineering faculty on "
                    "funded projects. Compensation varies by project.",
                    organization="Purdue University",
                    department="Lyles School of Civil Engineering",
                    lab_or_program="Joint Transportation Research Program",
                    compensation="Varies by project",
                    eligibility_majors=["Civil Engineering", "Transportation Engineering", "Construction Management"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["transportation", "civil engineering", "infrastructure", "INDOT", "mobility"],
                ),
                program(
                    "rcac_computing",
                    "Rosen Center for Advanced Computing (RCAC) \u2014 Purdue University",
                    "https://www.rcac.purdue.edu/",
                    "The Rosen Center for Advanced Computing operates Purdue's research "
                    "supercomputers and cyberinfrastructure, supporting computational research "
                    "across all disciplines. Undergraduates can gain research and technical "
                    "experience through student positions and by supporting faculty "
                    "computational projects. Many student roles are paid hourly.",
                    organization="Purdue University",
                    department="Information Technology at Purdue (ITaP)",
                    lab_or_program="Rosen Center for Advanced Computing",
                    compensation="Student positions often paid hourly",
                    eligibility_majors=["Computer Science", "Data Science", "Computer Engineering", "Statistics"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Rolling; student positions posted through the year",
                    keywords=["supercomputing", "HPC", "cyberinfrastructure", "research computing"],
                ),
                program(
                    "wghi_womens_health",
                    "Women's Global Health Institute (WGHI) \u2014 Purdue University",
                    "https://www.purdue.edu/discoverypark/WGHI/",
                    "The Women's Global Health Institute drives interdisciplinary research on "
                    "disease prevention and health issues affecting women worldwide. "
                    "Undergraduates engage through affiliated faculty labs and health-focused "
                    "projects. Compensation varies by project and funding.",
                    organization="Purdue University",
                    department="Discovery Park District",
                    lab_or_program="Women's Global Health Institute",
                    compensation="Varies by project",
                    eligibility_majors=["Public Health", "Biology", "Nursing", "Biomedical Engineering", "Nutrition Science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Rolling via faculty",
                    keywords=["women's health", "global health", "disease prevention", "public health"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_lab_open",
            "source_type": LAB,
            "emit": "open",
            "seeds": [
                "https://iot4ag.us/reu-program/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "iot4ag_reu",
                    "IoT4Ag REU \u2014 NSF Engineering Research Center (hosted at Purdue)",
                    "https://iot4ag.us/reu-program/",
                    "The Research Experiences for Undergraduates program of IoT4Ag, an NSF "
                    "Engineering Research Center (led by Penn) spanning partner institutions "
                    "including Purdue, focused on Internet-of-Things technologies for "
                    "agriculture and food/energy/water security. Offers a paid summer of "
                    "mentored research at a member campus; typically restricted to US "
                    "citizens/permanent residents.",
                    organization="IoT4Ag NSF Engineering Research Center",
                    department="NSF Engineering Research Center (Purdue partner site)",
                    lab_or_program="IoT4Ag REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU summer stipend plus housing/travel",
                    eligibility_majors=["agricultural engineering", "electrical engineering", "computer science", "agronomy", "engineering"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="NSF REU cycle; applications typically due winter/spring",
                    keywords=["REU", "IoT", "agriculture", "engineering research center", "NSF"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_program_campus",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://www.purdue.edu/undergrad-research/students/courses.php",
                "https://www.purdue.edu/undergrad-research/faculty/cure/curepurdue.php",
                "https://www.purdue.edu/undergrad-research/students/PitchComp.php",
                "https://www.purdue.edu/undergrad-research/students/society.php",
                "https://www.purdue.edu/undergrad-research/students/ambassadors/index.php",
                "https://www.purdue.edu/gradschool/diversity/programs/summer-research-opportunities-program/",
                "https://www.purdue.edu/academics/ogsps/diversity/programs/summer-research-opportunities-program/",
                "https://www.purdue.edu/discoverypark/duri/",
                "https://www.purdue.edu/undergrad-research/students/OUR-Scholars.php",
                "https://ag.purdue.edu/department/biochem/research/reu-program-information.html",
                "https://polytechnic.purdue.edu/ppi-scmt-reu",
                "https://www.opp.purdue.edu/our-programs/GEARE",
                "https://datamine.purdue.edu/careers/",
                "https://www.purdue.edu/undergrad-research/scholarships/grants.php",
                "https://engineering.purdue.edu/Engr/Research/EURO/students/about-SURF",
                "https://datamine.purdue.edu/",
                "https://ag.purdue.edu/department/oap/cate/research/scarf.html",
                "https://pharmacy.purdue.edu/research/summer-research/",
                "https://vet.purdue.edu/veterinary-scholars/",
                "https://business.purdue.edu/centers/purce/programs.php",
                "https://education.purdue.edu/undergraduate-students/undergraduate-research/urt-program/",
                "https://www.physics.purdue.edu/research/reu/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "our_courses",
                    "Purdue OUR Online Research Course Series",
                    "https://www.purdue.edu/undergrad-research/students/courses.php",
                    "A series of online research-skills courses offered through Purdue's Office "
                    "of Undergraduate Research to help students learn how to find, conduct, and "
                    "communicate research. Prepares undergraduates to succeed in mentored "
                    "research placements. Open to Purdue undergraduates.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="OUR Research Courses",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="By semester enrollment",
                    keywords=["research courses", "research skills", "training"],
                ),
                program(
                    "cure_program",
                    "Purdue CURE \u2014 Course-based Undergraduate Research Experiences",
                    "https://www.purdue.edu/undergrad-research/faculty/cure/curepurdue.php",
                    "Course-based Undergraduate Research Experiences embed authentic research "
                    "into for-credit courses so students do original research as part of a "
                    "class rather than through an individual lab placement. Lowers the barrier "
                    "for early and first-generation students to try research. Students "
                    "participate by enrolling in designated CURE courses.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="CURE",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="By course enrollment",
                    keywords=["CURE", "course-based research", "for-credit research"],
                ),
                program(
                    "ur_pitch_competition",
                    "Purdue Undergraduate Research Pitch Competition",
                    "https://www.purdue.edu/undergrad-research/students/PitchComp.php",
                    "A competition where Purdue undergraduates pitch their research ideas or "
                    "projects for recognition and prizes, organized by the Office of "
                    "Undergraduate Research. Builds communication skills and can provide "
                    "funding/awards. Open to undergraduates engaged in or proposing research.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="UR Pitch Competition",
                    compensation="Prizes/awards",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Annual; see OUR",
                    keywords=["pitch competition", "research communication", "awards"],
                ),
                program(
                    "ur_society",
                    "Undergraduate Research Society of Purdue",
                    "https://www.purdue.edu/undergrad-research/students/society.php",
                    "A student organization connected to Purdue's OUR that builds community "
                    "among undergraduate researchers through peer support, events, and "
                    "networking. A community/engagement group rather than a research placement. "
                    "Open to any Purdue undergraduate interested in research.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="Undergraduate Research Society",
                    paid="no",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Open membership",
                    keywords=["student org", "research community", "networking"],
                ),
                program(
                    "our_ambassadors",
                    "Purdue OUR Ambassadors",
                    "https://www.purdue.edu/undergrad-research/students/ambassadors/index.php",
                    "A program in which experienced undergraduate researchers serve as "
                    "ambassadors to promote and support research participation across campus "
                    "for Purdue's Office of Undergraduate Research. A "
                    "peer-leadership/engagement role rather than a research placement itself. "
                    "Application-based for students already involved in research.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="OUR Ambassadors",
                    eligibility_majors=["All majors"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Application-based",
                    keywords=["ambassadors", "peer leadership", "outreach"],
                ),
                program(
                    "srop",
                    "Purdue Summer Research Opportunities Program (SROP)",
                    "https://www.purdue.edu/gradschool/diversity/programs/summer-research-opportunities-program/",
                    "A Big Ten Academic Alliance summer program hosted by Purdue's Graduate "
                    "School that gives undergraduates from underrepresented groups a paid, "
                    "mentored graduate-level research experience to prepare them for PhD study. "
                    "Includes stipend, housing, and GRE/graduate-school preparation. Open to "
                    "rising juniors/seniors nationally.",
                    organization="Purdue University",
                    department="Graduate School \u2014 Office of Graduate Diversity",
                    lab_or_program="SROP",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend + housing/travel",
                    eligibility_majors=["All majors", "STEM", "Social sciences", "Humanities"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Applications typically due winter for summer",
                    keywords=["SROP", "diversity", "summer research", "grad prep"],
                ),
                program(
                    "srop_x",
                    "Summer Research Opportunities Program (SROP) \u2014 Purdue University",
                    "https://www.purdue.edu/academics/ogsps/diversity/programs/summer-research-opportunities-program/",
                    "A CIC/Big Ten-style summer program hosted by Purdue's Graduate School "
                    "(OGSPS) for undergraduates from underrepresented backgrounds to conduct "
                    "faculty-mentored research and prepare for graduate study. Includes "
                    "stipend, housing, travel, and GRE/grad-school prep. Aimed at rising "
                    "juniors and seniors.",
                    organization="Purdue University",
                    department="Graduate School (OGSPS)",
                    lab_or_program="SROP (Summer Research Opportunities Program)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Stipend plus housing and travel",
                    eligibility_majors=["all"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Applications typically due in early spring",
                    keywords=["SROP", "diversity", "graduate prep", "summer research"],
                ),
                program(
                    "duri",
                    "Discovery Park Undergraduate Research Internship (DURI) \u2014 Purdue University",
                    "https://www.purdue.edu/discoverypark/duri/",
                    "A paid research internship placing undergraduates in interdisciplinary "
                    "labs across Purdue's Discovery Park District (health, sustainability, "
                    "security, AI, and more). Students work with faculty and graduate mentors "
                    "during the academic year or summer. Open to Purdue undergraduates across "
                    "disciplines.",
                    organization="Purdue University",
                    department="Discovery Park District",
                    lab_or_program="DURI (Discovery Park Undergraduate Research Internship)",
                    paid="stipend",
                    compensation="Paid research internship stipend",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications each semester/summer cycle",
                    keywords=["DURI", "Discovery Park", "interdisciplinary", "paid internship"],
                ),
                program(
                    "our_scholars",
                    "OUR Scholars Program \u2014 Office of Undergraduate Research, Purdue University",
                    "https://www.purdue.edu/undergrad-research/students/OUR-Scholars.php",
                    "A summer program from the Office of Undergraduate Research designed for "
                    "students new to research, providing a faculty-mentored project plus "
                    "cohort-based professional development. Includes a stipend and is well "
                    "suited to first- and second-year students exploring research for the first "
                    "time.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="OUR Scholars",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend",
                    eligibility_majors=["all"],
                    preferred_year=["freshman", "sophomore"],
                    international_friendly="yes",
                    deadline_note="Applications typically due in spring",
                    keywords=["OUR Scholars", "first research experience", "summer", "cohort"],
                ),
                program(
                    "biochem_reu",
                    "Biochemistry & Molecular Biology REU \u2014 Purdue University",
                    "https://ag.purdue.edu/department/biochem/research/reu-program-information.html",
                    "An NSF-funded Research Experiences for Undergraduates site in the "
                    "Department of Biochemistry, offering a paid summer of mentored research in "
                    "biochemistry and molecular biology with professional-development "
                    "activities. Aimed at undergraduates nationwide considering graduate study; "
                    "typically restricted to US citizens/permanent residents.",
                    organization="Purdue University",
                    department="Department of Biochemistry",
                    lab_or_program="Biochemistry & Molecular Biology REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU summer stipend plus housing/travel",
                    eligibility_majors=["biochemistry", "biology", "chemistry"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="NSF REU cycle; applications typically due February",
                    keywords=["REU", "biochemistry", "molecular biology", "NSF"],
                ),
                program(
                    "decarb_reu",
                    "Built Environment Decarbonization REU \u2014 Purdue Polytechnic Institute",
                    "https://polytechnic.purdue.edu/ppi-scmt-reu",
                    "An NSF-funded REU (Award 2447373) hosted by the Bowen School of "
                    "Construction Management Technology, offering a 10-week paid summer program "
                    "for a cohort of 8 students on built-environment decarbonization and "
                    "sustainability research. Aimed at undergraduates considering graduate "
                    "studies in construction management technology; typically US "
                    "citizens/permanent residents.",
                    organization="Purdue University",
                    department="Purdue Polytechnic Institute / Bowen School of Construction ",
                    lab_or_program="Built Environment Decarbonization REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Paid 10-week summer research stipend",
                    eligibility_majors=["construction management", "engineering technology", "civil engineering", "environmental science"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="NSF REU cycle; 10-week on-site summer program",
                    keywords=["REU", "decarbonization", "construction management", "sustainability", "NSF"],
                ),
                program(
                    "geare",
                    "Purdue GEARE Global Engineering Co-op/Internship",
                    "https://www.opp.purdue.edu/our-programs/GEARE",
                    "The Global Engineering Alliance for Research and Education (GEARE) is a "
                    "study-abroad plus international co-op/internship program for Purdue "
                    "engineering undergraduates. Participants combine coursework abroad with a "
                    "work or research placement at an international partner site to build "
                    "global engineering competency. Designed for engineering students; requires "
                    "advance planning and program application.",
                    organization="Purdue University",
                    department="Office of Professional Practice / College of Engineering",
                    lab_or_program="GEARE (Global Engineering Alliance for Research and Educatio",
                    opportunity_type="internship",
                    compensation="Varies by placement; some work terms paid",
                    eligibility_majors=["engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Apply well in advance; cohort-based",
                    keywords=["global engineering", "study abroad", "international co-op", "GEARE", "engineering"],
                ),
                program(
                    "data_mine_corporate",
                    "The Data Mine Corporate Partners (Purdue)",
                    "https://datamine.purdue.edu/careers/",
                    "The Data Mine is Purdue's large-scale experiential learning program in "
                    "which undergraduates work in teams on real data-science and analytics "
                    "projects, including Corporate Partners projects sponsored by companies and "
                    "organizations. Students across all majors gain hands-on research "
                    "experience with authentic datasets, often for academic credit and "
                    "sometimes stipends. This page also aggregates related internship and job "
                    "postings from Data Mine partners.",
                    organization="Purdue University",
                    department="The Data Mine",
                    lab_or_program="The Data Mine \u2014 Corporate Partners",
                    compensation="Academic credit; some projects/internships paid",
                    eligibility_majors=["all", "data science", "computer science", "statistics", "engineering"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Enrollment typically before fall semester; project applications vary",
                    keywords=["data science", "experiential learning", "corporate partners", "data mine", "analytics"],
                ),
                program(
                    "our_grants",
                    "Purdue OUR Grants (Research & Travel)",
                    "https://www.purdue.edu/undergrad-research/scholarships/grants.php",
                    "Research and travel grants administered by Purdue's Office of "
                    "Undergraduate Research to fund student research projects and conference "
                    "travel to present findings. Undergraduates apply with a faculty mentor's "
                    "support. Helps cover project supplies, stipends, or travel to disseminate "
                    "research.",
                    organization="Purdue University",
                    department="Office of Undergraduate Research",
                    lab_or_program="OUR Grants",
                    paid="stipend",
                    compensation="Research/travel grant",
                    eligibility_majors=["All majors"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    deadline_note="Multiple cycles per year",
                    keywords=["research grant", "travel grant", "funding"],
                ),
                program(
                    "surf_x",
                    "Purdue SURF \u2014 Summer Undergraduate Research Fellowship",
                    "https://engineering.purdue.edu/Engr/Research/EURO/students/about-SURF",
                    "Purdue's flagship Summer Undergraduate Research Fellowship, administered "
                    "by the Engineering Undergraduate Research Office (EURO), places "
                    "undergraduates in faculty labs for an intensive ~11-week paid summer "
                    "research experience culminating in a symposium. Open to undergraduates "
                    "(Purdue and external applicants) in engineering, science, and technology "
                    "fields. Provides a competitive stipend.",
                    organization="Purdue University",
                    department="College of Engineering (EURO)",
                    lab_or_program="SURF",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend (~11 weeks)",
                    eligibility_majors=["Engineering", "Science", "Technology", "STEM"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Applications due late winter/early spring for summer",
                    keywords=["SURF", "summer research", "paid fellowship", "engineering"],
                ),
                program(
                    "data_mine",
                    "Purdue The Data Mine",
                    "https://datamine.purdue.edu/",
                    "A large living-learning community and research program where "
                    "undergraduates from any major work in teams on real data-science projects, "
                    "many sponsored by industry and faculty partners (Data Mine Corporate "
                    "Partners). Combines coursework with hands-on applied research. Open to all "
                    "Purdue undergraduates; freshmen can join from day one.",
                    organization="Purdue University",
                    department="The Data Mine",
                    lab_or_program="The Data Mine",
                    compensation="Some sponsored projects offer stipends",
                    eligibility_majors=["All majors", "Data science", "STEM"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Enroll by semester; rolling",
                    keywords=["data science", "learning community", "applied research", "corporate partners"],
                ),
                program(
                    "scarf_agriculture",
                    "Summer College of Agriculture Research Fellowship (SCARF) \u2014 Purdue University",
                    "https://ag.purdue.edu/department/oap/cate/research/scarf.html",
                    "A paid 10.5-week summer research fellowship exposing College of "
                    "Agriculture undergraduates to faculty-mentored research across "
                    "agricultural and life sciences. Provides a $5,400 stipend plus "
                    "science-communication workshops, seminars, and industry tours. Requires "
                    "full-time Ag undergrad status and a 3.0+ GPA.",
                    organization="Purdue University",
                    department="College of Agriculture",
                    lab_or_program="SCARF (Summer College of Agriculture Research Fellowship)",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="$5,400 total stipend for 10.5 weeks",
                    eligibility_majors=["agriculture", "life sciences"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="yes",
                    deadline_note="Summer 2026 runs May 26\u2013July 30; application cycle currently closed",
                    keywords=["SCARF", "agriculture", "summer research", "stipend"],
                ),
                program(
                    "pharmacy_deans_summer",
                    "Dean's Summer Undergraduate Research Program \u2014 Purdue College of Pharmacy",
                    "https://pharmacy.purdue.edu/research/summer-research/",
                    "A summer research program in the College of Pharmacy giving undergraduates "
                    "hands-on experience in pharmaceutical sciences, medicinal chemistry, and "
                    "pharmacology labs under faculty mentorship. Includes a stipend and "
                    "culminates in a research presentation. Aimed at students considering "
                    "PharmD/PhD or research careers.",
                    organization="Purdue University",
                    department="College of Pharmacy",
                    lab_or_program="Dean's Summer Undergraduate Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend",
                    eligibility_majors=["pharmacy", "pharmaceutical sciences", "chemistry", "biology"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Applications typically due in spring",
                    keywords=["pharmacy", "summer research", "pharmaceutical sciences"],
                ),
                program(
                    "vet_scholars",
                    "Veterinary Scholars Summer Research Program \u2014 Purdue College of Veterinary Medicine",
                    "https://vet.purdue.edu/veterinary-scholars/",
                    "A summer biomedical research program in the College of Veterinary Medicine "
                    "placing undergraduates and vet students in faculty labs on animal-health "
                    "and comparative-medicine projects. Includes a stipend and participation in "
                    "the national Veterinary Scholars Symposium. Well suited to pre-vet and "
                    "biomedical undergraduates.",
                    organization="Purdue University",
                    department="College of Veterinary Medicine",
                    lab_or_program="Veterinary Scholars Summer Research Program",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="Summer stipend",
                    eligibility_majors=["veterinary medicine", "biology", "animal sciences", "biomedical sciences"],
                    preferred_year=["sophomore", "junior", "senior"],
                    deadline_note="Applications typically due in spring",
                    keywords=["veterinary", "biomedical research", "summer scholars"],
                ),
                program(
                    "purce_ugra",
                    "PURCE Undergraduate Research Assistantship (UGRA) \u2014 Daniels School of Business, Purdue University",
                    "https://business.purdue.edu/centers/purce/programs.php",
                    "The Purdue University Research Center in Economics (PURCE) runs an "
                    "Undergraduate Research Assistantship (UGRA) giving students direct "
                    "exposure to economic research \u2014 research design, quantitative data "
                    "analysis, and presentation \u2014 working ~10 hours/week with economics faculty "
                    "for pay. The page also lists the Economic Scholars Program and ECON 390.",
                    organization="Purdue University",
                    department="Daniels School of Business / PURCE",
                    lab_or_program="PURCE Undergraduate Research Assistantship (UGRA)",
                    paid="yes",
                    compensation="Paid ~10 hours/week; Economic Scholars up to $750",
                    eligibility_majors=["economics", "business"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Rolling; requires West Lafayette on-campus enrollment",
                    keywords=["economics", "PURCE", "research assistantship", "business"],
                ),
                program(
                    "education_urt",
                    "Undergraduate Research Training (URT) Program \u2014 Purdue College of Education",
                    "https://education.purdue.edu/undergraduate-students/undergraduate-research/urt-program/",
                    "A two-semester research apprenticeship in the College of Education where "
                    "undergraduates work ~6 hours/week with an education faculty member while "
                    "taking a graduate research-methods sequence (EDPS 53300/53400) for 6 "
                    "credits toward a minor. Open to sophomores\u2013seniors of any major with a "
                    "3.0+ GPA; includes a $1,500 academic-year stipend and conference "
                    "opportunities.",
                    organization="Purdue University",
                    department="College of Education",
                    lab_or_program="Undergraduate Research Training (URT) Program",
                    paid="stipend",
                    compensation="$1,500 stipend for the academic year",
                    eligibility_majors=["all", "education"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="yes",
                    deadline_note="Two-semester cohort; 12\u201315 students/year",
                    keywords=["education research", "URT", "apprenticeship", "learning sciences"],
                ),
                program(
                    "physics_reu",
                    "Physics & Astronomy REU \u2014 Purdue University",
                    "https://www.physics.purdue.edu/research/reu/",
                    "An NSF-funded Research Experiences for Undergraduates site in the "
                    "Department of Physics and Astronomy, placing students in a paid summer of "
                    "mentored research across condensed matter, high-energy, astrophysics, and "
                    "biophysics. Open to undergraduates nationally; typically restricted to US "
                    "citizens/permanent residents.",
                    organization="Purdue University",
                    department="Department of Physics and Astronomy",
                    lab_or_program="Physics & Astronomy REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU summer stipend plus housing/travel",
                    eligibility_majors=["physics", "astronomy", "astrophysics"],
                    preferred_year=["freshman", "sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="NSF REU cycle; applications typically due winter",
                    keywords=["REU", "physics", "astronomy", "NSF"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_program_campus_3",
            "source_type": PROGRAM,
            "emit": "campus",
            "seeds": [
                "https://engineering.purdue.edu/MSE/research/reu",
                "https://research.purdue.edu/scale/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "mse_reu",
                    "Materials Engineering REU \u2014 Purdue University",
                    "https://engineering.purdue.edu/MSE/research/reu",
                    "An NSF-funded Research Experiences for Undergraduates site in the School "
                    "of Materials Engineering, offering a paid summer of mentored research in "
                    "materials science and engineering with professional development and a "
                    "symposium. Open to undergraduates nationally; typically restricted to US "
                    "citizens/permanent residents.",
                    organization="Purdue University",
                    department="School of Materials Engineering",
                    lab_or_program="Materials Engineering REU",
                    opportunity_type="summer_program",
                    paid="stipend",
                    compensation="NSF REU summer stipend plus housing/travel",
                    eligibility_majors=["materials engineering", "materials science", "engineering"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="NSF REU cycle; applications typically due winter/spring",
                    keywords=["REU", "materials engineering", "NSF", "summer"],
                ),
                program(
                    "scale_microelectronics",
                    "SCALE \u2014 Scalable Asymmetric Lifecycle Engagement (Microelectronics Workforce), Purdue University",
                    "https://research.purdue.edu/scale/",
                    "A Purdue-led national microelectronics workforce program combining "
                    "government/defense-industrial-base internships with aligned research, "
                    "mentoring, and scholarships for undergraduate and graduate students. "
                    "Covers areas such as radiation-hardening, compound semiconductors, and "
                    "trusted AI. Restricted to US citizens due to defense focus. (Live site "
                    "redirects to scale4me.org.)",
                    organization="Purdue University",
                    department="SCALE (Microelectronics Workforce Program)",
                    lab_or_program="SCALE \u2014 Scalable Asymmetric Lifecycle Engagement",
                    opportunity_type="internship",
                    paid="stipend",
                    compensation="Internships, scholarships, and research stipends",
                    eligibility_majors=["electrical engineering", "computer engineering", "microelectronics", "materials engineering", "physics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Rolling; internship/scholarship cycles",
                    keywords=["SCALE", "microelectronics", "semiconductors", "defense", "workforce"],
                ),
            ],
        },
        {
            "source_name": "purdue_catalog_program_open",
            "source_type": PROGRAM,
            "emit": "open",
            "seeds": [
                "https://www.purdue.edu/niso/scholarship/majorlist/goldwater.html",
                "https://www.nasa.gov/learning-resources/internship-programs/",
                "https://orise.orau.gov/doescholars/",
            ],
            "crawl": STATIC,
            "programs": [
                program(
                    "goldwater",
                    "Barry M. Goldwater Scholarship \u2014 Purdue NISO Advising",
                    "https://www.purdue.edu/niso/scholarship/majorlist/goldwater.html",
                    "The Goldwater Scholarship is a prestigious national award for sophomores "
                    "and juniors pursuing research careers in the natural sciences, "
                    "mathematics, and engineering; Purdue's NISO coordinates campus nomination "
                    "and advising. A national program hosted/advised at Purdue rather than a "
                    "Purdue-run placement. Requires a strong research record and faculty "
                    "support.",
                    organization="Barry Goldwater Scholarship Foundation (advised by Purdue NISO)",
                    department="National & International Scholarships Office",
                    lab_or_program="Goldwater Scholarship",
                    opportunity_type="fellowship",
                    paid="stipend",
                    compensation="Up to $7,500/year scholarship",
                    eligibility_majors=["Natural sciences", "Mathematics", "Engineering", "STEM"],
                    preferred_year=["sophomore", "junior"],
                    international_friendly="no",
                    deadline_note="Campus deadline (fall/winter) precedes national deadline",
                    keywords=["Goldwater", "national scholarship", "STEM research", "fellowship"],
                ),
                program(
                    "nasa_internships",
                    "NASA Internship Programs",
                    "https://www.nasa.gov/learning-resources/internship-programs/",
                    "NASA offers paid internships for undergraduates across its centers, "
                    "placing students on real aerospace, science, and engineering projects with "
                    "NASA mentors. Applications are handled through NASA's centralized "
                    "internship portal, with sessions in fall, spring, and summer. A national "
                    "program; typically requires U.S. citizenship and a minimum GPA.",
                    organization="NASA",
                    lab_or_program="NASA Internship Programs",
                    opportunity_type="internship",
                    paid="stipend",
                    compensation="Paid stipend",
                    eligibility_majors=["engineering", "science", "computer science", "mathematics"],
                    preferred_year=["freshman", "sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Rolling per session; summer deadlines typically in early spring",
                    keywords=["NASA", "internship", "aerospace", "STEM", "paid"],
                ),
                program(
                    "doe_scholars",
                    "U.S. DOE Scholars Program (ORISE)",
                    "https://orise.orau.gov/doescholars/",
                    "The U.S. Department of Energy Scholars Program, administered by ORISE, "
                    "places undergraduates, recent graduates, and graduate students in paid "
                    "internships at DOE facilities and offices. Participants work on energy, "
                    "science, and policy projects with federal mentors and receive a stipend. A "
                    "national program; typically requires U.S. citizenship.",
                    organization="U.S. Department of Energy / ORISE",
                    lab_or_program="DOE Scholars Program",
                    opportunity_type="internship",
                    paid="stipend",
                    compensation="Paid stipend",
                    eligibility_majors=["engineering", "science", "computer science", "policy", "mathematics"],
                    preferred_year=["sophomore", "junior", "senior"],
                    international_friendly="no",
                    deadline_note="Annual application cycle; typically deadline in winter",
                    keywords=["DOE", "energy", "ORISE", "internship", "stipend"],
                ),
            ],
        },
    ],
}
