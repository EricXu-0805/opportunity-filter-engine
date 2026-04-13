def generate_cold_email(profile: dict, opportunity: dict) -> str:
    name = profile.get("name") or "Student"
    year = profile.get("year", "undergraduate")
    major = profile.get("major", "")
    school = profile.get("school", "UIUC")
    skills = profile.get("hard_skills", [])
    research_interests = profile.get("research_interests_text", "")

    pi_name = opportunity.get("pi_name", "")
    lab = opportunity.get("lab_or_program", "")
    title = opportunity.get("title", "")
    dept = opportunity.get("department", "")
    research_area = _infer_research_area(opportunity)
    opp_desc = opportunity.get("description", "")

    recipient = pi_name or "Professor"
    if pi_name and not pi_name.lower().startswith(("prof", "dr")):
        recipient = f"Professor {pi_name}"

    subject_context = lab or research_area or title or "research"
    subject = f"{year.capitalize()} {major} student — interest in {subject_context}"

    # P1: Personal intro + what caught your attention about THEIR work
    greeting = f"Dear {recipient},"
    intro = f"My name is {name}, and I am a {year} studying {major} at {school}."

    interest_hook = ""
    if research_area and research_interests:
        interest_hook = (
            f" I am very interested in {research_interests[:100].rstrip('.')}."
            f" I really enjoyed learning about your work on {research_area}"
            f" and would love to contribute."
        )
    elif research_area:
        interest_hook = (
            f" I am very interested in {research_area}."
            f" I really enjoyed learning about your research in this area."
        )
    elif lab or title:
        interest_hook = f" I came across {lab or title} and it aligns closely with what I want to explore."

    # P2: Your specific skills and how they match
    skills_para = ""
    if skills:
        top = skills[:4]
        skill_str = " and ".join([", ".join(top[:-1]), top[-1]]) if len(top) > 1 else top[0]
        skills_para = (
            f"\n\nI have experience with {skill_str}."
        )
        if opp_desc:
            desc_lower = opp_desc.lower()
            matching = [s for s in skills if s.lower() in desc_lower]
            if matching:
                skills_para += f" In particular, my background in {', '.join(matching)} seems directly relevant to this position."
        skills_para += " I am a fast learner and eager to pick up new tools as needed."

    # P3-P4: Express desire + ask for meeting
    ask = (
        "\n\nI would love the chance to contribute to your lab"
        " and to learn more about your research."
        "\n\nWould you be open to a short meeting?"
        " I am happy to work around your availability."
    )

    closing = f"\n\nBest regards,\n{name}"

    body = f"{greeting}\n\n{intro}{interest_hook}{skills_para}{ask}{closing}"

    return f"{subject}\n\n{body}"


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
