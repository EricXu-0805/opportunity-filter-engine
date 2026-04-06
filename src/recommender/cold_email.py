"""
Template-based cold email generator for research opportunities.
No LLM needed — uses profile + opportunity fields to fill a professional template.
"""


def generate_cold_email(profile: dict, opportunity: dict) -> str:
    """Generate a cold email template for a research opportunity.

    Args:
        profile: Student profile dict with name, year, major, skills, projects, etc.
        opportunity: Opportunity dict with title, pi_name, lab_or_program, etc.

    Returns:
        A professional cold email string under 150 words.
    """
    # Extract profile fields
    name = profile.get("name") or "Student"
    year = profile.get("year", "undergraduate")
    major = profile.get("major", "")
    school = profile.get("school", "UIUC")
    skills = profile.get("hard_skills", [])
    projects = profile.get("projects", [])

    # Extract opportunity fields
    pi_name = opportunity.get("pi_name", "")
    lab = opportunity.get("lab_or_program", "")
    org = opportunity.get("organization", "")
    title = opportunity.get("title", "")
    dept = opportunity.get("department", "")
    research_area = _infer_research_area(opportunity)

    # Build recipient line
    recipient = pi_name or "Professor"
    if pi_name and not pi_name.lower().startswith(("prof", "dr")):
        recipient = f"Professor {pi_name}"

    # Build subject line
    subject_context = lab or research_area or dept or "research"
    subject = f"Subject: {year.capitalize()} {major} student — interest in {subject_context}"

    # Intro
    intro = f"Dear {recipient},\n\nI am a {year} studying {major} at {school}."

    # Why this lab
    why_parts = []
    if lab:
        why_parts.append(f"I am writing to express my interest in {lab}.")
    elif title:
        why_parts.append(f"I am writing regarding the {title} opportunity.")
    if research_area:
        why_parts.append(f"Your work in {research_area} aligns closely with my interests.")
    why_section = " ".join(why_parts) if why_parts else f"I am very interested in contributing to your research."

    # What you offer
    offer_parts = []
    if skills:
        top_skills = skills[:4]
        offer_parts.append(f"I have experience with {', '.join(top_skills)}.")
    if projects:
        proj = projects[0]
        proj_name = proj if isinstance(proj, str) else proj.get("name", "")
        proj_desc = "" if isinstance(proj, str) else proj.get("description", "")
        if proj_name and proj_desc:
            offer_parts.append(f"In my project {proj_name}, I {proj_desc.lower().rstrip('.')}.")
        elif proj_name:
            offer_parts.append(f"I have worked on {proj_name}.")
    offer_section = " ".join(offer_parts) if offer_parts else ""

    # Ask
    ask = "Would you be available for a brief meeting to discuss potential opportunities in your group?"

    # Assemble
    closing = f"Thank you for your time.\n\nBest regards,\n{name}"

    parts = [subject, "", intro, why_section]
    if offer_section:
        parts.append(offer_section)
    parts.extend([ask, "", closing])

    return "\n".join(parts)


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
