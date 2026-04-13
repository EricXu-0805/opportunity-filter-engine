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


def _common_parts(profile: dict, opportunity: dict) -> dict:
    name = profile.get("name") or "Student"
    year = profile.get("year", "undergraduate")
    major = profile.get("major", "")
    school = profile.get("school", "UIUC")
    skills = _extract_skill_names(profile.get("hard_skills", []))
    research_interests = profile.get("research_interests_text", "")

    pi_name = opportunity.get("pi_name", "")
    lab = opportunity.get("lab_or_program", "")
    title = opportunity.get("title", "")
    research_area = _infer_research_area(opportunity)
    opp_desc = opportunity.get("description", "")

    recipient = pi_name or "Professor"
    if pi_name and not pi_name.lower().startswith(("prof", "dr")):
        recipient = f"Professor {pi_name}"

    return dict(
        name=name, year=year, major=major, school=school,
        skills=skills, research_interests=research_interests,
        pi_name=pi_name, lab=lab, title=title,
        research_area=research_area, opp_desc=opp_desc,
        recipient=recipient,
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
    ctx = p["lab"] or p["research_area"] or p["title"] or "research"
    if style == "concise":
        return f"{p['major']} student — {ctx}"
    return f"{p['year'].capitalize()} {p['major']} student — interest in {ctx}"


def _build_balanced(p: dict) -> str:
    subject = _subject(p)
    greeting = f"Dear {p['recipient']},"
    intro = f"My name is {p['name']}, and I am a {p['year']} studying {p['major']} at {p['school']}."

    interest_hook = _interest_hook(p)
    skills_para = _skills_paragraph(p, top_n=4)

    ask = (
        "\n\nI would love the chance to contribute to your lab"
        " and to learn more about your research."
        "\n\nWould you be open to a short meeting?"
        " I am happy to work around your availability."
    )
    closing = f"\n\nBest regards,\n{p['name']}"
    body = f"{greeting}\n\n{intro}{interest_hook}{skills_para}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _build_skills_focus(p: dict) -> str:
    subject = _subject(p)
    greeting = f"Dear {p['recipient']},"
    intro = f"My name is {p['name']}, and I am a {p['year']} {p['major']} major at {p['school']}."

    skills_para = ""
    skills = p["skills"]
    if skills:
        all_str = ", ".join(skills[:6])
        skills_para = f"\n\nI have hands-on experience with {all_str}."
        if p["opp_desc"]:
            desc_lower = p["opp_desc"].lower()
            matching = [s for s in skills if s.lower() in desc_lower]
            if matching:
                skills_para += (
                    f" My background in {', '.join(matching)} is directly"
                    f" applicable to your work."
                )
        skills_para += (
            " I am confident I can contribute technically from day one"
            " and am always eager to expand my toolkit."
        )

    interest_brief = ""
    if p["research_area"]:
        interest_brief = f"\n\nYour research in {p['research_area']} is a strong match for the direction I want to take."

    ask = (
        "\n\nI would welcome the opportunity to discuss how my skills"
        " could support your current projects."
        "\n\nWould you have 15 minutes for a brief conversation?"
    )
    closing = f"\n\nBest regards,\n{p['name']}"
    body = f"{greeting}\n\n{intro}{skills_para}{interest_brief}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _build_concise(p: dict) -> str:
    subject = _subject(p, style="concise")
    greeting = f"Dear {p['recipient']},"

    core = f"I am a {p['year']} {p['major']} student at {p['school']}"
    if p["research_area"]:
        core += f", interested in {p['research_area']}"
    core += "."

    skills = p["skills"]
    if skills:
        core += f" I have experience with {', '.join(skills[:3])}."

    ask = " Would you be open to a brief conversation about potential opportunities in your lab?"

    closing = f"\n\nBest,\n{p['name']}"
    body = f"{greeting}\n\n{core}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _interest_hook(p: dict) -> str:
    if p["research_area"] and p["research_interests"]:
        return (
            f" I am very interested in {p['research_interests'][:100].rstrip('.')}."
            f" I really enjoyed learning about your work on {p['research_area']}"
            f" and would love to contribute."
        )
    if p["research_area"]:
        return (
            f" I am very interested in {p['research_area']}."
            f" I really enjoyed learning about your research in this area."
        )
    if p["lab"] or p["title"]:
        ctx = p["lab"] or p["title"]
        return f" I came across {ctx} and it aligns closely with what I want to explore."
    return ""


def _skills_paragraph(p: dict, top_n: int = 4) -> str:
    skills = p["skills"]
    if not skills:
        return ""
    top = skills[:top_n]
    skill_str = " and ".join([", ".join(top[:-1]), top[-1]]) if len(top) > 1 else top[0]
    para = f"\n\nI have experience with {skill_str}."
    if p["opp_desc"]:
        desc_lower = p["opp_desc"].lower()
        matching = [s for s in skills if s.lower() in desc_lower]
        if matching:
            para += f" In particular, my background in {', '.join(matching)} seems directly relevant to this position."
    para += " I am a fast learner and eager to pick up new tools as needed."
    return para


def _infer_research_area(opportunity: dict) -> str:
    """Try to infer a research area string from opportunity fields."""
    keywords = opportunity.get("keywords", [])
    if keywords:
        # Filter out generic keywords
        generic = {"undergraduate", "research", "summer", "program", "internship", "opportunity"}
        specific = [kw for kw in keywords if kw.lower() not in generic]
        if specific:
            return specific[0]

    dept = opportunity.get("department", "")
    if dept:
        return dept

    # Try to get something from title
    title = opportunity.get("title", "")
    for area in ["machine learning", "data science", "computer vision",
                 "robotics", "biology", "chemistry", "physics",
                 "neuroscience", "ecology", "engineering"]:
        if area in title.lower():
            return area

    return ""
