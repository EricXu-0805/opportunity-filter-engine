"""
Resume gap analyzer — identifies missing skills, suggests coursework,
and provides a preparation timeline for a given opportunity.
"""


# Mapping from skills to relevant UIUC courses
SKILL_COURSES = {
    "Python": ["CS 101", "CS 124"],
    "Java": ["CS 124", "CS 128"],
    "C++": ["CS 128", "ECE 220"],
    "C": ["ECE 220", "CS 241"],
    "R": ["STAT 385", "STAT 107"],
    "MATLAB": ["ECE 210", "MATH 285"],
    "SQL": ["CS 411", "IS 457"],
    "PyTorch": ["CS 444", "CS 446"],
    "TensorFlow": ["CS 444", "CS 446"],
    "pandas": ["STAT 107", "IS 457"],
    "JavaScript": ["CS 409"],
    "React": ["CS 409"],
    "Git": ["CS 128"],
    "Linux": ["CS 241", "ECE 391"],
    "Docker": ["CS 341"],
    "OpenCV": ["CS 444", "ECE 420"],
    "machine learning": ["CS 446", "ECE 449"],
    "data analysis": ["STAT 107", "STAT 200"],
    "data science": ["STAT 107", "CS 307"],
    "computer vision": ["CS 444", "ECE 420"],
    "robotics": ["ECE 470", "CS 446"],
    "natural language processing": ["CS 447"],
    "embedded systems": ["ECE 391", "ECE 385"],
}

# How long it typically takes to become productive with a skill
SKILL_TIMELINE = {
    "Python": "2-4 weeks self-study",
    "Java": "3-5 weeks self-study",
    "C++": "4-8 weeks self-study",
    "C": "4-6 weeks self-study",
    "R": "2-3 weeks self-study",
    "MATLAB": "2-3 weeks self-study",
    "SQL": "1-2 weeks self-study",
    "PyTorch": "3-5 weeks (after Python)",
    "TensorFlow": "3-5 weeks (after Python)",
    "pandas": "1-2 weeks (after Python)",
    "JavaScript": "3-4 weeks self-study",
    "React": "3-5 weeks (after JavaScript)",
    "Git": "1 week self-study",
    "Linux": "2-3 weeks self-study",
    "Docker": "1-2 weeks self-study",
    "OpenCV": "2-3 weeks (after Python)",
    "LaTeX": "1 week self-study",
    "Excel": "1-2 weeks self-study",
    "GIS": "3-4 weeks self-study",
    "SPSS": "2-3 weeks self-study",
    "SAS": "3-4 weeks self-study",
    "Stata": "2-3 weeks self-study",
    "AWS": "3-4 weeks self-study",
    "CAD": "4-6 weeks self-study",
}


from src.matcher.ranker import _canonicalize_skill, _parse_skills


def _skill_name(s) -> str:
    if isinstance(s, dict):
        return s.get("name", "")
    if isinstance(s, str):
        return s
    return getattr(s, "name", str(s))


def analyze_gaps(profile: dict, opportunity: dict) -> dict:
    student_skill_map = _parse_skills(profile.get("hard_skills", []))
    student_skills = set(student_skill_map.keys())
    elig = opportunity.get("eligibility", {})

    required = elig.get("skills_required", []) or []
    preferred = elig.get("skills_preferred", []) or []

    # Missing skills
    missing_required = [s for s in required if _canonicalize_skill(s) not in student_skills and s.lower() not in student_skills]
    missing_preferred = [s for s in preferred if _canonicalize_skill(s) not in student_skills and s.lower() not in student_skills]
    missing_skills = missing_required + missing_preferred

    # Suggested coursework
    suggested_coursework = []
    student_courses = {c.strip().upper() for c in profile.get("coursework", [])}
    seen_courses = set()
    for skill in missing_skills:
        courses = SKILL_COURSES.get(skill, [])
        for c in courses:
            if c.upper() not in student_courses and c not in seen_courses:
                suggested_coursework.append(c)
                seen_courses.add(c)

    # Resume tips
    resume_tips = _generate_resume_tips(profile, opportunity, missing_required, missing_preferred)

    # Preparation timeline
    preparation_timeline = []
    for skill in missing_skills:
        time_est = SKILL_TIMELINE.get(skill, "2-4 weeks self-study")
        preparation_timeline.append({
            "skill": skill,
            "estimated_time": time_est,
            "priority": "high" if skill in missing_required else "medium",
        })

    return {
        "missing_skills": missing_skills,
        "suggested_coursework": suggested_coursework,
        "resume_tips": resume_tips,
        "preparation_timeline": preparation_timeline,
    }


def _generate_resume_tips(profile: dict, opportunity: dict,
                          missing_req: list, missing_pref: list) -> list[str]:
    """Generate actionable resume tips based on the gap analysis."""
    tips = []
    elig = opportunity.get("eligibility", {})
    opp_type = opportunity.get("opportunity_type", "")

    # Skill gap tips
    if missing_req:
        tips.append(
            f"Prioritize learning {', '.join(missing_req)} — these are listed as required."
        )
    if missing_pref:
        tips.append(
            f"Consider picking up {', '.join(missing_pref)} to strengthen your application."
        )

    all_student_skills = set(_parse_skills(profile.get("hard_skills", [])).keys())
    required = elig.get("skills_required", []) or []
    matched = [s for s in required if _canonicalize_skill(s) in all_student_skills or s.lower() in all_student_skills]
    if matched:
        tips.append(
            f"Highlight your experience with {', '.join(matched)} prominently on your resume."
        )

    # Experience level tips
    exp = profile.get("experience_level", "none")
    if exp in ("none", "beginner"):
        tips.append("Include relevant coursework and class projects to compensate for limited research experience.")
        if opp_type == "research":
            tips.append("Mention any independent study, hackathon, or personal project that shows research aptitude.")

    # Projects
    projects = profile.get("projects", [])
    if projects:
        tips.append("Feature your project work — PIs value students who build things independently.")
    else:
        tips.append("Consider adding a personal or class project to demonstrate practical skills.")

    # Resume readiness
    if not profile.get("resume_ready", False):
        tips.append("Prepare a polished resume before applying — visit your career center for a review.")

    # Application effort
    app = opportunity.get("application", {})
    if app.get("requires_cover_letter") == "yes":
        tips.append("This opportunity requires a cover letter — tailor it to the specific research area.")
    if app.get("requires_recommendation") == "yes":
        tips.append("Line up a recommendation letter — ask a professor who knows your work well.")

    return tips
