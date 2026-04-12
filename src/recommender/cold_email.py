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
    research_area = _infer_research_area(opportunity)

    recipient = pi_name or "Professor"
    if pi_name and not pi_name.lower().startswith(("prof", "dr")):
        recipient = f"Professor {pi_name}"

    subject_context = lab or research_area or title or "research"
    subject = f"Subject: {year.capitalize()} {major} student interested in {subject_context}"

    greeting = f"Dear {recipient},"
    intro = f"I'm a {year} {major} student at {school}."

    hook = ""
    if research_area and research_interests:
        hook = (
            f" I came across your work in {research_area} and it caught my attention"
            f" because I've been exploring {research_interests[:120].rstrip('.')}."
        )
    elif research_area:
        hook = f" I found your work in {research_area} and it resonates with what I want to pursue."
    elif lab or title:
        target = lab or title
        hook = f" I came across {target} and would love to learn more about getting involved."

    background = ""
    if skills:
        skill_str = ", ".join(skills[:4])
        if len(skills) > 4:
            skill_str += f", and {len(skills) - 4} more"
        background = f" I've been working with {skill_str} through coursework and personal projects."

    ask = (
        "\n\nWould you have 15 minutes in the coming weeks to chat about"
        " potential opportunities in your group? I'd be happy to send my resume"
        " and share more about my background."
    )

    closing = f"\n\nThank you for your time,\n{name}"

    body = f"{greeting}\n\n{intro}{hook}{background}{ask}{closing}"

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
