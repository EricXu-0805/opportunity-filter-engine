def _extract_skill_names(raw_skills: list) -> list[str]:
    result = []
    for s in raw_skills:
        if isinstance(s, dict):
            result.append(s.get("name", ""))
        elif isinstance(s, str):
            result.append(s)
        else:
            result.append(getattr(s, "name", str(s)))
    return [n for n in result if n]


def _extract_skill_levels(raw_skills: list) -> dict[str, str]:
    result = {}
    for s in raw_skills:
        if isinstance(s, dict):
            result[s.get("name", "")] = s.get("level", "beginner")
        elif isinstance(s, str):
            result[s] = "beginner"
        else:
            result[getattr(s, "name", str(s))] = getattr(s, "level", "beginner")
    return result


_EMAIL_GENERIC_KW = frozenset({
    "undergraduate", "research", "summer", "program", "internship",
    "opportunity", "assistant", "student", "uiuc", "illinois",
    "computer science", "artificial intelligence", "machine learning",
    "engineering", "science", "technology", "science & technology",
    "natural sciences", "social sciences & behavior", "department",
})


def _clean_research_interests(text: str) -> str:
    if not text:
        return ""
    import re
    text = re.sub(
        r"^(?:I am interested in|I'm interested in|my interest is in|interested in)\s*",
        "", text.strip(), flags=re.IGNORECASE,
    )
    return text.strip().rstrip(".")


def _infer_research_topic(opportunity: dict) -> str:
    desc = opportunity.get("description_raw") or opportunity.get("description_clean") or ""
    keywords = opportunity.get("keywords", [])
    specific = [kw for kw in keywords if kw.lower() not in _EMAIL_GENERIC_KW]

    if specific:
        if len(specific) <= 2:
            return " and ".join(specific[:2])
        return ", ".join(specific[:2]) + f", and {specific[2]}"
    if desc:
        noise = {"seeking", "looking for", "we are", "this position", "the lab",
                 "research opportunity with", "contact the professor"}
        for sentence in desc.split("."):
            s = sentence.strip()
            if len(s) < 20:
                continue
            if any(n in s.lower() for n in noise):
                continue
            if "$" in s:
                continue
            return s[:80]
    return ""


def _infer_research_area(opportunity: dict) -> str:
    keywords = opportunity.get("keywords", [])
    if keywords:
        specific = [kw for kw in keywords if kw.lower() not in _EMAIL_GENERIC_KW]
        if specific:
            return specific[0]
    dept = opportunity.get("department", "")
    if dept:
        return dept
    title = opportunity.get("title", "")
    for area in ["machine learning", "data science", "computer vision",
                 "robotics", "biology", "chemistry", "physics",
                 "neuroscience", "ecology", "engineering"]:
        if area in title.lower():
            return area
    return ""


def _match_skills_to_tasks(skills: list[str], opp: dict) -> list[str]:
    desc = (opp.get("description_raw") or opp.get("description_clean") or "").lower()
    required = [s.lower() for s in opp.get("eligibility", {}).get("skills_required", [])]
    matched = []
    for s in skills:
        sl = s.lower()
        if sl in desc or sl in required:
            matched.append(s)
    return matched


def _common_parts(profile: dict, opportunity: dict) -> dict:
    name = profile.get("name") or "Student"
    year = profile.get("year", "undergraduate")
    major = profile.get("major", "")
    school = profile.get("school", "UIUC")
    skills = _extract_skill_names(profile.get("hard_skills", []))
    skill_levels = _extract_skill_levels(profile.get("hard_skills", []))
    research_interests = _clean_research_interests(
        profile.get("research_interests_text", "")
    )
    linkedin_url = profile.get("linkedin_url", "")
    github_url = profile.get("github_url", "")

    pi_name = opportunity.get("pi_name") or ""
    lab = opportunity.get("lab_or_program", "")
    title = opportunity.get("title", "")
    opp_type = opportunity.get("opportunity_type", "")
    research_area = _infer_research_area(opportunity)
    research_topic = _infer_research_topic(opportunity)
    opp_desc = opportunity.get("description_raw") or opportunity.get("description_clean") or ""
    opp_skills_required = opportunity.get("eligibility", {}).get("skills_required", [])
    matching_skills = _match_skills_to_tasks(skills, opportunity)

    if pi_name and pi_name.lower() not in ("learn more", "none", "and robotics", "unknown"):
        recipient = f"Professor {pi_name}" if not pi_name.lower().startswith(("prof", "dr")) else pi_name
    elif opp_type == "summer_program":
        recipient = "Program Coordinator"
    else:
        recipient = "Professor"

    coursework = profile.get("coursework", [])

    return dict(
        name=name, year=year, major=major, school=school,
        skills=skills, skill_levels=skill_levels,
        research_interests=research_interests,
        linkedin_url=linkedin_url, github_url=github_url,
        pi_name=pi_name, lab=lab, title=title,
        research_area=research_area, research_topic=research_topic,
        opp_desc=opp_desc, opp_skills_required=opp_skills_required,
        matching_skills=matching_skills, recipient=recipient,
        coursework=coursework,
    )


def generate_cold_email(profile: dict, opportunity: dict) -> str:
    p = _common_parts(profile, opportunity)
    return _build_balanced(p)


def generate_variants(profile: dict, opportunity: dict) -> list[dict]:
    p = _common_parts(profile, opportunity)
    return [
        {"id": "balanced",  "label": "Balanced",       "text": _build_balanced(p)},
        {"id": "skills",    "label": "Skills Focus",   "text": _build_skills_focus(p)},
        {"id": "concise",   "label": "Concise",        "text": _build_concise(p)},
    ]


def _subject(p: dict, style: str = "") -> str:
    lab = p["lab"]
    area = p["research_area"]

    if style == "concise":
        ctx = lab or area or p["title"] or "research"
        return f"Subject: {p['major']} student — {ctx}"

    if lab and "Prof" in lab:
        return f"Subject: {p['year'].capitalize()} {p['major']} student interested in joining {lab}"
    if area:
        return f"Subject: Research inquiry — {p['year']} {p['major']} student, background in {area}"
    ctx = lab or p["title"] or "your research"
    return f"Subject: {p['year'].capitalize()} {p['major']} student — interest in {ctx}"


def _closing(p: dict) -> str:
    lines = [f"\n\nBest regards,\n{p['name']}"]
    if p.get("linkedin_url"):
        lines.append(f"LinkedIn: {p['linkedin_url']}")
    if p.get("github_url"):
        lines.append(f"GitHub: {p['github_url']}")
    return "\n".join(lines)


def _build_balanced(p: dict) -> str:
    subject = _subject(p)
    greeting = f"Dear {p['recipient']},"

    intro = f"My name is {p['name']}, and I am a {p['year']} studying {p['major']} at {p['school']}."
    intro += _p1_research_hook(p)

    skills_para = _p2_skills_applied(p)

    ask = (
        "\n\nI would love the chance to contribute to your lab"
        " and to learn more about your research."
        "\n\nWould you be open to a short meeting?"
        " I am happy to work around your availability."
    )
    closing = _closing(p)
    body = f"{greeting}\n\n{intro}{skills_para}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _build_skills_focus(p: dict) -> str:
    subject = _subject(p)
    greeting = f"Dear {p['recipient']},"

    intro = f"My name is {p['name']}, and I am a {p['year']} {p['major']} major at {p['school']}."
    intro += _p1_research_hook(p)

    skills_para = ""
    skills = p["skills"]
    matching = p["matching_skills"]
    levels = p["skill_levels"]

    if skills:
        expert_skills = [s for s in skills if levels.get(s) == "expert"]
        experienced_skills = [s for s in skills if levels.get(s) == "experienced"]

        if expert_skills:
            skills_para += f"\n\nI have strong proficiency in {', '.join(expert_skills[:3])}"
            if experienced_skills:
                skills_para += f" and working experience with {', '.join(experienced_skills[:3])}"
            skills_para += "."
        elif experienced_skills:
            skills_para += f"\n\nI have hands-on experience with {', '.join(experienced_skills[:4])}."
        else:
            skills_para += f"\n\nI have experience with {', '.join(skills[:4])}."

        if matching:
            skills_para += (
                f" In particular, my background in {', '.join(matching)}"
                f" is directly applicable to this position."
            )

        required = p["opp_skills_required"]
        if required:
            have = [s for s in required if s.lower() in {sk.lower() for sk in skills}]
            if have:
                skills_para += f" I already work with {', '.join(have)} which this role requires."

    coursework = p.get("coursework", [])
    if coursework:
        skills_para += f" Relevant coursework includes {', '.join(coursework[:3])}."

    ask = (
        "\n\nI would welcome the opportunity to discuss how my skills"
        " could support your current projects."
        "\n\nWould you have 15 minutes for a brief conversation?"
    )
    closing = _closing(p)
    body = f"{greeting}\n\n{intro}{skills_para}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _build_concise(p: dict) -> str:
    subject = _subject(p, style="concise")
    greeting = f"Dear {p['recipient']},"

    core = f"I am a {p['year']} {p['major']} student at {p['school']}"
    if p["research_area"]:
        core += f", interested in {p['research_area']}"
    core += "."

    skills = p["skills"]
    matching = p["matching_skills"]
    if matching:
        core += f" I have experience with {', '.join(matching[:3])}, which are relevant to your work."
    elif skills:
        core += f" I have experience with {', '.join(skills[:3])}."

    ask = " Would you be open to a brief conversation about potential opportunities in your lab?"

    closing = _closing(p)
    body = f"{greeting}\n\n{core}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _p1_research_hook(p: dict) -> str:
    research_topic = p["research_topic"]
    research_area = p["research_area"]
    lab = p["lab"]
    interests = p["research_interests"]

    is_short_topic = research_topic and len(research_topic) < 50 and " " in research_topic

    if interests and is_short_topic and lab:
        return (
            f" I am writing because your work on {research_topic}"
            f" in the {lab} strongly resonates with my interest in"
            f" {interests[:80].rstrip('.')}."
        )
    if interests and is_short_topic:
        return (
            f" I am writing because your research on {research_topic}"
            f" closely aligns with my interest in {interests[:80].rstrip('.')}."
        )
    if interests and research_area and lab:
        lab_ref = lab if lab[0].isupper() and ("Prof" in lab or "'s" in lab) else f"the {lab}"
        return (
            f" I came across {lab_ref} and your work in {research_area},"
            f" which aligns closely with my interest in {interests[:80].rstrip('.')}."
        )
    if interests and research_area:
        return (
            f" I am reaching out because your work in {research_area}"
            f" aligns with my interest in {interests[:80].rstrip('.')}."
        )
    if interests and lab:
        lab_ref = lab if lab[0].isupper() and ("Prof" in lab or "'s" in lab) else f"the {lab}"
        return (
            f" I came across {lab_ref} and am very interested in"
            f" contributing, as my background in {interests[:60].rstrip('.')} is closely related."
        )
    if is_short_topic and lab:
        lab_ref = lab if lab[0].isupper() and ("Prof" in lab or "'s" in lab) else f"the {lab}"
        return (
            f" I came across {lab_ref} and your work on {research_topic},"
            f" and would like to learn more about opportunities to contribute."
        )
    if is_short_topic:
        return (
            f" I came across your research on {research_topic}"
            f" and would like to learn more about opportunities"
            f" to contribute."
        )
    if lab:
        lab_ref = lab if lab[0].isupper() and ("Prof" in lab or "'s" in lab) else f"the {lab}"
        return (
            f" I came across {lab_ref} and am very interested"
            f" in contributing to your research."
        )
    return ""


def _p2_skills_applied(p: dict) -> str:
    skills = p["skills"]
    if not skills:
        return ""

    matching = p["matching_skills"]

    task_keywords = {
        "Python":     "data processing, analysis, and scripting",
        "MATLAB":     "data cleaning, visualization, and numerical computation",
        "R":          "statistical analysis and data visualization",
        "PyTorch":    "building and training deep learning models",
        "TensorFlow": "building and training deep learning models",
        "Java":       "software development and object-oriented design",
        "C++":        "systems programming and performance-critical applications",
        "C":          "low-level systems programming",
        "JavaScript": "web development and interactive applications",
        "SQL":        "database querying and data management",
        "React":      "building interactive user interfaces",
        "OpenCV":     "image processing and computer vision tasks",
        "pandas":     "data wrangling and analysis",
        "Git":        "version control and collaborative development",
        "Linux":      "system administration and command-line tooling",
        "Docker":     "containerization and reproducible environments",
        "LaTeX":      "technical writing and documentation",
    }

    top = (matching or skills)[:3]
    applications = []
    for s in top:
        app = task_keywords.get(s)
        if app:
            applications.append(f"{s} for {app}")
        else:
            applications.append(s)

    if len(applications) == 1:
        skill_str = applications[0]
    elif len(applications) == 2:
        skill_str = f"{applications[0]} and {applications[1]}"
    else:
        skill_str = f"{', '.join(applications[:-1])}, and {applications[-1]}"

    para = f"\n\nI have experience with {skill_str}."

    if matching and len(matching) >= 2:
        para += (
            f" In particular, my background in {', '.join(matching[:3])}"
            f" directly applies to this role."
        )

    coursework = p.get("coursework", [])
    if coursework:
        para += f" Relevant coursework includes {', '.join(coursework[:3])}."

    return para
